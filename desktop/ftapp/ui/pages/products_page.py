"""صفحة المنتجات: البحث، الفلترة حسب القسم، والإجراءات."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLineEdit, QMenu, QSplitter, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ftapp.services import catalog_service, currency_service, excel_service
from ftapp.ui import icons
from ftapp.ui.context import ctx
from ftapp.ui.dialogs.catalog_dialogs import (BulkPriceDialog, ExportDialog, ImportDialog, LabelsDialog,
                                              PromotionDialog, VariantsDialog)
from ftapp.ui.dialogs.product_dialog import ProductDialog
from ftapp.ui.pages.base import Page
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.common import Card, Toast, button, confirm, muted, run_safely
from ftapp.ui.widgets.table import Column, DataTable, status_colors

STATUS_LABEL = {"ok": "متوفر", "low": "منخفض", "out": "نافد"}


class ProductsPage(Page):
    title = "المنتجات"
    subtitle = "إدارة البضاعة، الأصناف، الأسعار والكميات"

    def __init__(self) -> None:
        super().__init__()
        self.category_id: int | None = None
        can_edit = ctx.can("products.edit")
        if can_edit:
            self.actions.addWidget(button("منتج جديد", "plus", "primary", on_click=self._new, tooltip="Ctrl+N"))
        more = button("المزيد", "list")
        menu = QMenu(more)
        if can_edit:
            menu.addAction(icons.icon("upload"), "استيراد من Excel", lambda: self._dialog(ImportDialog(self)))
        menu.addAction(icons.icon("excel"), "تصدير جرد البضاعة (مجلد Excel)", lambda: ExportDialog(self).exec())
        menu.addAction(icons.icon("download"), "تصدير الجدول الحالي", self._export_table)
        if can_edit:
            menu.addSeparator()
            menu.addAction(icons.icon("percent"), "تحديث الأسعار الجماعي", lambda: self._dialog(BulkPriceDialog(self, self._selected_ids())))
            menu.addAction(icons.icon("tag"), "عرض/خصم على المنتج المحدد", self._promo)
            menu.addAction(icons.icon("barcode"), "طباعة ملصقات للمحدد", self._labels)
            menu.addAction(icons.icon("grid"), "إنشاء متغيرات (ألوان/مقاسات)", self._variants)
        more.setMenu(menu)
        self.actions.addWidget(more)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        # شجرة الأقسام
        tree_card = Card("الأقسام", icon_name="layers")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet("QTreeWidget { border: none; }")
        self.tree.itemSelectionChanged.connect(self._tree_changed)
        tree_card.add(self.tree, 1)
        tree_card.setMinimumWidth(190)
        tree_card.setMaximumWidth(250)
        splitter.addWidget(tree_card)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("searchBox")
        self.search.setPlaceholderText("ابحث بالاسم أو الكود أو الباركود أو الماركة...")
        self.search.addAction(icons.icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 3)
        self.stock = QComboBox()
        for text, key in (("كل الكميات", "all"), ("منخفض المخزون", "low"), ("نافد", "out"), ("متوفر", "available")):
            self.stock.addItem(text, key)
        self.brand = QComboBox()
        self.status = QComboBox()
        for text, val in (("الفعالة", True), ("الموقوفة", False), ("الكل", None)):
            self.status.addItem(text, val)
        for w in (self.stock, self.brand, self.status):
            filters.addWidget(w, 1)
            w.currentIndexChanged.connect(self.refresh_now)
        rl.addLayout(filters)

        sym = ""
        with ctx.session() as (s, _):
            sym = currency_service.base(s).symbol
        from ftapp.core.utils import fmt_qty
        cols = [
            Column("الكود", "code", width=140),
            Column("اسم المنتج", "name", stretch=True, bold=True),
            Column("القسم", "category", width=105),
            Column("الماركة", "brand", width=85),
            Column("الكمية", lambda r: f"{fmt_qty(r['qty'])} {r['unit']}", width=85,
                   color=lambda r: status_colors(r["status"]), bold=True),
            Column("سعر البيع", "price", "money", width=95, symbol=sym),
        ]
        if ctx.can("products.view_cost"):
            cols += [Column("التكلفة", "cost", "money", width=90, symbol=sym),
                     Column("الربح %", "margin", "percent", width=65)]
        cols += [Column("الحالة", lambda r: STATUS_LABEL[r["status"]] if r["active"] else "موقوف", width=65,
                        color=lambda r: status_colors(r["status"]) if r["active"] else tokens()["muted"])]
        self.table = DataTable(cols, multi=True)
        self.table.activated_row.connect(lambda r: self._edit(r["id"]))
        self.table.add_menu_action("فتح / تعديل", lambda r: self._edit(r["id"]))
        if ctx.can("inventory.adjust"):
            self.table.add_menu_action("تعديل الكمية", self._adjust)
        if can_edit:
            self.table.add_menu_action("نسخ كمنتج جديد", self._duplicate)
            self.table.add_menu_action("طباعة ملصق", lambda r: LabelsDialog(self, [r["id"]]).exec())
        if ctx.can("products.delete"):
            self.table.add_menu_action("حذف", self._delete)
        rl.addWidget(self.table, 1)
        self.summary = muted("")
        rl.addWidget(self.summary)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        self.root.addWidget(splitter, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh_now)
        self.search.textChanged.connect(lambda: self._timer.start(250))
        ctx.signals.products_changed.connect(self.mark_dirty)
        ctx.signals.stock_changed.connect(self.mark_dirty)
        self._load_tree()

    def _dialog(self, dlg) -> None:
        if dlg.exec():
            self.mark_dirty()
            self._load_tree()

    def _load_tree(self) -> None:
        self.tree.clear()
        all_item = QTreeWidgetItem(["كل الأقسام"])
        all_item.setIcon(0, icons.icon("grid"))
        all_item.setData(0, Qt.ItemDataRole.UserRole, None)
        self.tree.addTopLevelItem(all_item)
        with ctx.session() as (s, _):
            nodes: dict[int, QTreeWidgetItem] = {}
            for c, _depth in catalog_service.category_tree(s):
                it = QTreeWidgetItem([c.name])
                it.setIcon(0, icons.icon("layers", c.color))
                it.setData(0, Qt.ItemDataRole.UserRole, c.id)
                parent = nodes.get(c.parent_id)
                (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
                nodes[c.id] = it
            brands = catalog_service.brands(s)
        self.tree.expandAll()
        self.tree.setCurrentItem(all_item)
        self.brand.blockSignals(True)
        current = self.brand.currentData()
        self.brand.clear()
        self.brand.addItem("كل الماركات", None)
        for b in brands:
            self.brand.addItem(b, b)
        i = self.brand.findData(current)
        self.brand.setCurrentIndex(max(i, 0))
        self.brand.blockSignals(False)

    def _tree_changed(self) -> None:
        item = self.tree.currentItem()
        self.category_id = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self.refresh_now()

    def refresh(self) -> None:
        with ctx.session() as (s, _):
            items, total = catalog_service.search_products(
                s, self.search.text(), category_id=self.category_id, brand=self.brand.currentData(),
                active=self.status.currentData(), stock_filter=self.stock.currentData() or "all", limit=2000)
            rows = []
            qty_sum = value = 0.0
            for p in items:
                status = catalog_service.stock_status(s, p)
                rows.append({"id": p.id, "code": p.code, "name": p.name,
                             "category": p.category.name if p.category else "", "brand": p.brand,
                             "qty": p.quantity, "unit": p.unit, "price": p.sale_price, "cost": p.cost_price,
                             "margin": catalog_service.actual_margin_percent(p), "status": status,
                             "active": p.is_active})
                qty_sum += p.quantity
                value += p.quantity * p.sale_price
            fmt_value = currency_service.format_amount(s, value)
        self.table.set_rows(rows)
        low = sum(1 for r in rows if r["status"] != "ok")
        extra = f" (يعرض أول {len(rows)})" if total > len(rows) else ""
        self.summary.setText(f"{total} منتج{extra} • إجمالي الكمية {qty_sum:,.0f} • القيمة بسعر البيع {fmt_value}"
                             + (f" • {low} منخفض/نافد" if low else ""))

    def _selected_ids(self) -> list[int]:
        return [r["id"] for r in self.table.selected_rows()]

    def _new(self) -> None:
        if ProductDialog(self, None, {"category_id": self.category_id}).exec():
            self._load_tree()
            self.mark_dirty()

    def _edit(self, product_id: int) -> None:
        if ProductDialog(self, product_id).exec():
            self._load_tree()
            self.mark_dirty()

    def _adjust(self, row: dict) -> None:
        from ftapp.ui.dialogs.inventory_dialogs import StockAdjustDialog
        if StockAdjustDialog(self, row["id"]).exec():
            self.mark_dirty()

    def _duplicate(self, row: dict) -> None:
        with ctx.session() as (s, _):
            p = catalog_service.get_product(s, row["id"])
            preset = {"name": f"{p.name} (نسخة)", "category_id": p.category_id}
        ProductDialog(self, None, preset).exec()

    def _delete(self, row: dict) -> None:
        if not confirm(self, f"حذف المنتج «{row['name']}»؟\nإذا كان له مبيعات سابقة سيتم إيقافه بدل حذفه.", danger=True):
            return

        def do():
            with ctx.session() as (s, u):
                return catalog_service.delete_product(s, u, row["id"])
        res = run_safely(self, do)
        if res:
            Toast.show_message(self, "تم الحذف" if res == "deleted" else "تم إيقاف المنتج (له مبيعات سابقة)", "success")
            self.mark_dirty()

    def _labels(self) -> None:
        ids = self._selected_ids()
        if not ids:
            Toast.show_message(self, "حدد منتجاً أو أكثر من الجدول", "warning")
            return
        LabelsDialog(self, ids).exec()

    def _variants(self) -> None:
        row = self.table.current_row()
        if not row:
            Toast.show_message(self, "حدد المنتج الأساسي أولاً", "warning")
            return
        self._dialog(VariantsDialog(self, row["id"]))

    def _promo(self) -> None:
        row = self.table.current_row()
        self._dialog(PromotionDialog(self, None, row["id"] if row else None))

    def _export_table(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "تصدير", "المنتجات.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        headers, rows, kinds = self.table.export_data()
        with ctx.session() as (s, _):
            excel_service.export_table(path, "قائمة المنتجات", headers, rows, s, kinds)
        from ftapp.ui.dialogs.catalog_dialogs import open_path
        from pathlib import Path
        open_path(Path(path))

    def open_item(self, payload) -> None:
        if not isinstance(payload, dict):
            return
        if payload.get("new"):
            self._new()
        elif payload.get("product_id"):
            self._edit(payload["product_id"])
