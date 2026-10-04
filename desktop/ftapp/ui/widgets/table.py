"""جدول بيانات عام مع بحث وترتيب وتلوين وتصدير."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QMenu, QTableView, QWidget

from ftapp.core.utils import fmt_money, fmt_qty
from ftapp.ui.theme import tokens


@dataclass
class Column:
    title: str
    key: str | Callable[[Any], Any]
    kind: str = "text"            # text, money, qty, percent, date, datetime, bool
    width: int | None = None
    stretch: bool = False
    color: Callable[[Any], str | None] | None = None   # لون النص
    bg: Callable[[Any], str | None] | None = None      # لون الخلفية
    bold: bool = False
    symbol: str = ""
    extra: dict = field(default_factory=dict)

    def raw(self, row: Any) -> Any:
        if callable(self.key):
            return self.key(row)
        if isinstance(row, dict):
            return row.get(self.key)
        return getattr(row, self.key, None)

    def display(self, row: Any) -> str:
        v = self.raw(row)
        if v is None or v == "":
            return "" if self.kind == "text" else "—"
        if self.kind == "money":
            return fmt_money(float(v), self.symbol)
        if self.kind == "qty":
            return fmt_qty(float(v))
        if self.kind == "percent":
            return f"{float(v):.1f}%"
        if self.kind == "date":
            return v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v)
        if self.kind == "datetime":
            return v.strftime("%Y-%m-%d %H:%M") if hasattr(v, "strftime") else str(v)
        if self.kind == "bool":
            return "✓" if v else "—"
        return str(v)


class RowsModel(QAbstractTableModel):
    def __init__(self, columns: list[Column]) -> None:
        super().__init__()
        self.columns = columns
        self.rows: list[Any] = []

    def set_rows(self, rows: list[Any]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section].title
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return col.display(row)
        if role == Qt.ItemDataRole.UserRole:  # قيمة الترتيب
            v = col.raw(row)
            return v if isinstance(v, (int, float)) else (str(v) if v is not None else "")
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col.kind in ("money", "qty", "percent", "date", "datetime", "bool"):
                return int(Qt.AlignmentFlag.AlignCenter)
            # AlignLeft يُعكس تلقائياً في واجهة RTL فيصبح بداية السطر (يمين)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and col.color:
            c = col.color(row)
            return QBrush(QColor(c)) if c else None
        if role == Qt.ItemDataRole.BackgroundRole and col.bg:
            c = col.bg(row)
            return QBrush(QColor(c)) if c else None
        if role == Qt.ItemDataRole.FontRole and col.bold:
            f = QFont()
            f.setBold(True)
            return f
        return None


class _Proxy(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(-1)


class DataTable(QTableView):
    activated_row = Signal(object)      # نقر مزدوج
    selection_changed_rows = Signal(list)

    def __init__(self, columns: list[Column], parent: QWidget | None = None, multi: bool = False) -> None:
        super().__init__(parent)
        self.columns = columns
        self.model_ = RowsModel(columns)
        self.proxy = _Proxy()
        self.proxy.setSourceModel(self.model_)
        self.setModel(self.proxy)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection if multi
                              else QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(36)
        self.setShowGrid(False)
        self.setWordWrap(False)
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        for i, c in enumerate(columns):
            if c.stretch:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            elif c.width:
                self.setColumnWidth(i, c.width)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.doubleClicked.connect(self._on_double)
        self.selectionModel().selectionChanged.connect(lambda *_: self.selection_changed_rows.emit(self.selected_rows()))
        self._menu_actions: list[tuple[str, Callable[[Any], None]]] = []
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def set_rows(self, rows: list[Any]) -> None:
        self.model_.set_rows(rows)

    def rows(self) -> list[Any]:
        return self.model_.rows

    def filter(self, text: str) -> None:
        self.proxy.setFilterFixedString(text)

    def _source_row(self, proxy_index: QModelIndex) -> Any:
        return self.model_.rows[self.proxy.mapToSource(proxy_index).row()]

    def current_row(self) -> Any | None:
        idx = self.currentIndex()
        if not idx.isValid():
            sel = self.selectionModel().selectedRows()
            if not sel:
                return None
            idx = sel[0]
        return self._source_row(idx)

    def selected_rows(self) -> list[Any]:
        return [self._source_row(i) for i in self.selectionModel().selectedRows()]

    def visible_rows(self) -> list[Any]:
        return [self._source_row(self.proxy.index(r, 0)) for r in range(self.proxy.rowCount())]

    def _on_double(self, index: QModelIndex) -> None:
        self.activated_row.emit(self._source_row(index))

    def add_menu_action(self, text: str, fn: Callable[[Any], None]) -> None:
        self._menu_actions.append((text, fn))

    def _menu(self, pos) -> None:
        if not self._menu_actions:
            return
        idx = self.indexAt(pos)
        if not idx.isValid():
            return
        row = self._source_row(idx)
        menu = QMenu(self)
        for text, fn in self._menu_actions:
            menu.addAction(text, lambda f=fn, r=row: f(r))
        menu.exec(self.viewport().mapToGlobal(pos))

    def export_data(self) -> tuple[list[str], list[list[Any]], list[str]]:
        headers = [c.title for c in self.columns]
        rows = []
        for row in self.visible_rows():
            out = []
            for c in self.columns:
                v = c.raw(row)
                if c.kind in ("money", "qty", "percent") and v not in (None, ""):
                    out.append(float(v))
                elif c.kind in ("date", "datetime") and hasattr(v, "strftime"):
                    out.append(c.display(row))
                elif c.kind == "bool":
                    out.append("نعم" if v else "لا")
                else:
                    out.append("" if v is None else str(v))
            rows.append(out)
        kinds = [c.kind if c.kind in ("money", "qty", "percent") else "text" for c in self.columns]
        return headers, rows, kinds


def status_colors(status: str) -> str | None:
    t = tokens()
    return {"out": t["danger"], "low": t["warning"], "ok": t["success"]}.get(status)
