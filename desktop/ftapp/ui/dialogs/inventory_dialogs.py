"""نوافذ المخزون: تعديل كمية، نقل بين المستودعات، مستودع، جرد."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QRadioButton, QVBoxLayout,
                               QWidget)

from ftapp.core.utils import fmt_qty
from ftapp.models import Product, Warehouse
from ftapp.services import catalog_service, inventory_service
from ftapp.ui.context import ctx
from ftapp.ui.widgets.common import Toast, button, error, fill_combo, muted
from ftapp.ui.widgets.forms import FormDialog, date_edit, qty_spin
from ftapp.ui.widgets.table import Column, DataTable


class StockAdjustDialog(FormDialog):
    def __init__(self, parent, product_id: int) -> None:
        super().__init__(parent, "تعديل كمية المخزون", 480)
        self.product_id = product_id
        with ctx.session() as (s, _):
            p = s.get(Product, product_id)
            self.pname, self.unit, self.track = p.name, p.unit, p.track_expiry
            self.levels = {lvl.warehouse_id: lvl.quantity for lvl in p.stock_levels}
            whs = [(w.name, w.id) for w in inventory_service.list_warehouses(s)]
        self.form.addRow(muted(self.pname))
        self.wh = QComboBox()
        fill_combo(self.wh, whs)
        self.wh.currentIndexChanged.connect(self._update_current)
        self.row("المستودع", self.wh)
        self.current = QLabel()
        self.row("الكمية الحالية", self.current)
        modes = QHBoxLayout()
        self.m_add = QRadioButton("إضافة")
        self.m_remove = QRadioButton("إخراج")
        self.m_damage = QRadioButton("تالف")
        self.m_set = QRadioButton("تعيين كمية")
        self.m_add.setChecked(True)
        for m in (self.m_add, self.m_remove, self.m_damage, self.m_set):
            modes.addWidget(m)
            m.toggled.connect(self._update_preview)
        w = QWidget()
        w.setLayout(modes)
        self.row("العملية", w)
        self.qty = qty_spin()
        self.qty.valueChanged.connect(self._update_preview)
        self.row(f"الكمية ({self.unit})", self.qty)
        self.expiry = date_edit()
        self.expiry_label = QLabel("تاريخ الصلاحية")
        self.form.addRow(self.expiry_label, self.expiry)
        self.reason = self.line("السبب / البيان", "", "مثال: بضاعة واردة، كسر، تصحيح جرد")
        self.preview = muted("")
        self.row("", self.preview)
        self.on_save = self._do
        self.finish_layout()
        self._update_current()
        self.qty.setFocus()

    def _update_current(self) -> None:
        self.current.setText(f"{fmt_qty(self.levels.get(self.wh.currentData(), 0))} {self.unit}")
        self._update_preview()

    def _update_preview(self) -> None:
        cur = self.levels.get(self.wh.currentData(), 0)
        q = self.qty.value()
        new = q if self.m_set.isChecked() else (cur + q if self.m_add.isChecked() else cur - q)
        self.preview.setText(f"الكمية بعد العملية: {fmt_qty(new)} {self.unit}")
        show_exp = self.track and self.m_add.isChecked()
        self.expiry.setVisible(show_exp)
        self.expiry_label.setVisible(show_exp)

    def _do(self):
        q = self.qty.value()
        wh = self.wh.currentData()
        reason = self.reason.text().strip()
        with ctx.session() as (s, u):
            if self.m_set.isChecked():
                inventory_service.set_quantity(s, u, self.product_id, wh, q, reason or "تعيين كمية")
            else:
                if q <= 0:
                    from ftapp.services.errors import ValidationError
                    raise ValidationError("أدخل كمية أكبر من صفر")
                if self.m_add.isChecked():
                    inventory_service.adjust(s, u, self.product_id, wh, q, "in", reason or "إدخال",
                                             expiry=self.expiry.date().toPython() if self.track else None)
                else:
                    kind = "damage" if self.m_damage.isChecked() else "out"
                    inventory_service.adjust(s, u, self.product_id, wh, -q, kind, reason or ("تالف" if kind == "damage" else "إخراج"))
        return True


class WarehouseDialog(FormDialog):
    def __init__(self, parent, warehouse_id: int | None = None) -> None:
        super().__init__(parent, "مستودع")
        self.warehouse_id = warehouse_id
        with ctx.session() as (s, _):
            w = s.get(Warehouse, warehouse_id) if warehouse_id else None
        self.name = self.line("الاسم *", w.name if w else "")
        self.location = self.line("الموقع", w.location if w else "")
        from PySide6.QtWidgets import QCheckBox
        self.default = QCheckBox("المستودع الافتراضي للبيع والإدخال")
        self.default.setChecked(bool(w and w.is_default))
        self.row("", self.default)
        self.on_save = self._do
        self.finish_layout()

    def _do(self):
        with ctx.session() as (s, _):
            return inventory_service.save_warehouse(s, self.name.text(), self.location.text(), self.default.isChecked(),
                                                    self.warehouse_id).id


class ProductPicker(QWidget):
    """حقل اختيار منتج بالبحث أو الباركود."""

    def __init__(self, on_pick, placeholder: str = "اكتب الاسم أو امسح الباركود ثم Enter") -> None:
        super().__init__()
        self.on_pick = on_pick
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setObjectName("searchBox")
        self.edit.setPlaceholderText(placeholder)
        self.edit.returnPressed.connect(self._go)
        lay.addWidget(self.edit, 1)

    def _go(self) -> None:
        text = self.edit.text().strip()
        if not text:
            return
        with ctx.session() as (s, _):
            p = catalog_service.find_by_code(s, text)
            if p is None:
                items, _ = catalog_service.search_products(s, text, limit=30)
                if len(items) == 1:
                    p = items[0]
                elif items:
                    from ftapp.ui.dialogs.pickers import choose_product
                    pid = choose_product(self, [(f"{x.name} — {x.code} (المتوفر {fmt_qty(x.quantity)})", x.id) for x in items])
                    p = s.get(Product, pid) if pid else None
            if p is None:
                Toast.show_message(self, "لم يتم العثور على المنتج", "warning")
                return
            self.on_pick(p.id, p.name, p.code)
        self.edit.clear()


class TransferDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("نقل بضاعة بين المستودعات")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(760, 560)
        self.items: dict[int, dict] = {}
        lay = QVBoxLayout(self)
        t = QLabel("نقل بضاعة")
        t.setObjectName("pageTitle")
        lay.addWidget(t)
        with ctx.session() as (s, _):
            whs = [(w.name, w.id) for w in inventory_service.list_warehouses(s)]
        row = QHBoxLayout()
        self.src = QComboBox()
        fill_combo(self.src, whs)
        self.dst = QComboBox()
        fill_combo(self.dst, whs)
        if len(whs) > 1:
            self.dst.setCurrentIndex(1)
        row.addWidget(QLabel("من"))
        row.addWidget(self.src, 1)
        row.addWidget(QLabel("إلى"))
        row.addWidget(self.dst, 1)
        lay.addLayout(row)
        self.picker = ProductPicker(self._add)
        lay.addWidget(self.picker)
        self.table = DataTable([Column("المنتج", "name", stretch=True), Column("الكود", "code"),
                                Column("المتوفر بالمصدر", "available", "qty"), Column("الكمية المنقولة", "qty", "qty", bold=True)])
        self.table.activated_row.connect(self._edit_qty)
        lay.addWidget(self.table, 1)
        lay.addWidget(muted("نقر مزدوج على السطر لتعديل الكمية."))
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("ملاحظات")
        lay.addWidget(self.notes)
        b = QHBoxLayout()
        b.addStretch(1)
        b.addWidget(button("إلغاء", on_click=self.reject))
        b.addWidget(button("تنفيذ النقل", "transfer", "primary", on_click=self._do))
        lay.addLayout(b)

    def _add(self, pid: int, name: str, code: str) -> None:
        from PySide6.QtWidgets import QInputDialog
        with ctx.session() as (s, _):
            avail = inventory_service.quantity_in(s, pid, self.src.currentData())
        q, ok = QInputDialog.getDouble(self, "الكمية", f"كمية «{name}» المنقولة (المتوفر {fmt_qty(avail)})", 1, 0, 1e9, 3)
        if ok and q > 0:
            self.items[pid] = {"id": pid, "name": name, "code": code, "available": avail, "qty": q}
            self.table.set_rows(list(self.items.values()))

    def _edit_qty(self, row: dict) -> None:
        self._add(row["id"], row["name"], row["code"])

    def _do(self) -> None:
        try:
            with ctx.session() as (s, u):
                inventory_service.create_transfer(s, u, self.src.currentData(), self.dst.currentData(),
                                                  [(i["id"], i["qty"]) for i in self.items.values()], self.notes.text())
        except Exception as exc:
            error(self, str(exc))
            return
        Toast.show_message(self.parent(), "تم نقل البضاعة", "success")
        self.accept()
