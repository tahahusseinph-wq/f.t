"""المشتريات والموردون، مع قراءة فاتورة المورد من صورة."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ftapp.core.utils import money
from ftapp.models import Product, Supplier
from ftapp.services import catalog_service, currency_service, gemini_service, inventory_service, purchase_service
from ftapp.ui import icons
from ftapp.ui.context import ctx
from ftapp.ui.dialogs.inventory_dialogs import ProductPicker
from ftapp.ui.dialogs.pickers import choose_product
from ftapp.ui.pages.base import Page
from ftapp.ui.widgets.common import Toast, button, confirm, error, fill_combo, run_safely
from ftapp.ui.widgets.forms import FormDialog, date_edit, money_spin
from ftapp.ui.widgets.table import Column, DataTable
from ftapp.ui.widgets.worker import run_async


class SupplierDialog(FormDialog):
    def __init__(self, parent, supplier_id: int | None = None) -> None:
        super().__init__(parent, "مورد")
        self.supplier_id = supplier_id
        with ctx.session() as (s, _):
            sp = s.get(Supplier, supplier_id) if supplier_id else None
        self.name = self.line("الاسم *", sp.name if sp else "")
        self.phone = self.line("الهاتف", sp.phone if sp else "")
        self.address = self.line("العنوان", sp.address if sp else "")
        self.notes = self.line("ملاحظات", sp.notes if sp else "")
        self.on_save = self._do
        self.finish_layout()

    def _do(self):
        with ctx.session() as (s, _):
            return catalog_service.save_supplier(s, self.name.text(), self.phone.text(), self.address.text(),
                                                 self.notes.text(), self.supplier_id).id


class PurchaseDialog(QDialog):
    COLS = ["المنتج", "الكود", "الكمية", "سعر الشراء", "الدفعة", "الصلاحية", "الإجمالي"]

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("فاتورة شراء جديدة")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1020, 680)
        lay = QVBoxLayout(self)
        t = QLabel("فاتورة شراء")
        t.setObjectName("pageTitle")
        lay.addWidget(t)
        with ctx.session() as (s, _):
            sups = [(x.name, x.id) for x in catalog_service.list_suppliers(s)]
            whs = [(w.name, w.id) for w in inventory_service.list_warehouses(s)]
            self.symbol = currency_service.base(s).symbol
        head = QHBoxLayout()
        self.supplier = QComboBox()
        fill_combo(self.supplier, sups, placeholder="— بدون مورد —")
        self.wh = QComboBox()
        fill_combo(self.wh, whs)
        self.ref = QLineEdit()
        self.ref.setPlaceholderText("رقم فاتورة المورد")
        for w in (QLabel("المورد"), self.supplier, QLabel("المستودع"), self.wh, self.ref):
            head.addWidget(w)
        if ctx.can("ai.use"):
            head.addWidget(button("قراءة فاتورة من صورة", "camera", "soft", on_click=self._ocr))
        lay.addLayout(head)
        self.picker = ProductPicker(self._add_product, "ابحث عن منتج أو امسح الباركود لإضافته")
        lay.addWidget(self.picker)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(button("حذف السطر", "trash", on_click=lambda: (self.table.removeRow(self.table.currentRow()), self._total())))
        self.update_cost = QCheckBox("تحديث سعر التكلفة للمنتجات")
        self.update_cost.setChecked(True)
        row.addWidget(self.update_cost)
        row.addStretch(1)
        self.total_label = QLabel()
        self.total_label.setObjectName("bigTotal")
        row.addWidget(self.total_label)
        lay.addLayout(row)
        pay = QHBoxLayout()
        self.paid = money_spin(suffix=self.symbol)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("ملاحظات")
        pay.addWidget(QLabel("المدفوع للمورد"))
        pay.addWidget(self.paid)
        pay.addWidget(button("دفع كامل", on_click=lambda: self.paid.setValue(self._total())))
        pay.addWidget(self.notes, 1)
        lay.addLayout(pay)
        b = QHBoxLayout()
        b.addStretch(1)
        b.addWidget(button("إلغاء", on_click=self.reject))
        b.addWidget(button("حفظ الفاتورة وإدخال البضاعة", "check", "primary", on_click=self._save))
        lay.addLayout(b)
        self._total()

    def _add_row(self, pid: int, name: str, code: str, qty: float = 1, cost: float = 0, track: bool = False) -> None:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == pid:
                sp = self.table.cellWidget(r, 2)
                sp.setValue(sp.value() + qty)
                return
        r = self.table.rowCount()
        self.table.insertRow(r)
        it = QTableWidgetItem(name)
        it.setData(Qt.ItemDataRole.UserRole, pid)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(r, 0, it)
        self.table.setItem(r, 1, QTableWidgetItem(code))
        q = QDoubleSpinBox()
        q.setRange(0, 1e9)
        q.setDecimals(3)
        q.setValue(qty)
        c = money_spin()
        c.setValue(cost)
        for w in (q, c):
            w.valueChanged.connect(self._total)
        self.table.setCellWidget(r, 2, q)
        self.table.setCellWidget(r, 3, c)
        self.table.setItem(r, 4, QTableWidgetItem(""))
        exp = date_edit()
        exp.setEnabled(track)
        self.table.setCellWidget(r, 5, exp)
        self.table.setItem(r, 6, QTableWidgetItem(""))
        self._total()

    def _add_product(self, pid: int, name: str, code: str) -> None:
        with ctx.session() as (s, _):
            p = s.get(Product, pid)
            self._add_row(pid, name, code, 1, p.cost_price, p.track_expiry)

    def _total(self) -> float:
        total = 0.0
        for r in range(self.table.rowCount()):
            q, c = self.table.cellWidget(r, 2), self.table.cellWidget(r, 3)
            if q and c:
                line = q.value() * c.value()
                total += line
                item = self.table.item(r, 6)
                if item:
                    item.setText(f"{line:,.2f}")
        self.total_label.setText(f"الإجمالي: {total:,.2f} {self.symbol}")
        return money(total)

    def _ocr(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "صورة فاتورة المورد", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        data = Path(path).read_bytes()
        mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        Toast.show_message(self, "⏳ جارِ قراءة الفاتورة بالذكاء الاصطناعي...")
        run_async(lambda: gemini_service.parse_supplier_invoice(None, data, mime), self._apply_ocr,
                  lambda m: error(self, m))

    def _apply_ocr(self, inv) -> None:
        missing = []
        with ctx.session() as (s, _):
            if inv.supplier_name:
                i = next((k for k in range(self.supplier.count()) if inv.supplier_name in self.supplier.itemText(k)), -1)
                if i >= 0:
                    self.supplier.setCurrentIndex(i)
            if inv.invoice_number:
                self.ref.setText(inv.invoice_number)
            for line in inv.items:
                p = catalog_service.find_by_code(s, line.code) if line.code else None
                if p is None:
                    items, _ = catalog_service.search_products(s, line.name, limit=10)
                    if len(items) == 1:
                        p = items[0]
                    elif items:
                        pid = choose_product(self, [(f"{x.name} — {x.code}", x.id) for x in items],
                                             f"اختر المنتج المطابق لـ «{line.name}»")
                        p = s.get(Product, pid) if pid else None
                if p is None:
                    missing.append(line.name)
                    continue
                self._add_row(p.id, p.name, p.code, line.quantity or 1, line.unit_price or p.cost_price, p.track_expiry)
        msg = f"تمت قراءة {len(inv.items)} سطر."
        if missing:
            msg += "\nمنتجات غير موجودة (أضفها أولاً من صفحة المنتجات):\n• " + "\n• ".join(missing)
        from ftapp.ui.widgets.common import info
        info(self, msg, "نتيجة القراءة")

    def _save(self) -> None:
        lines = []
        for r in range(self.table.rowCount()):
            pid = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            exp_w = self.table.cellWidget(r, 5)
            lines.append(purchase_service.PurchaseLine(
                pid, self.table.cellWidget(r, 2).value(), self.table.cellWidget(r, 3).value(),
                (self.table.item(r, 4).text() if self.table.item(r, 4) else "").strip(),
                exp_w.date().toPython() if exp_w.isEnabled() else None))

        def do():
            with ctx.session() as (s, u):
                return purchase_service.create_purchase(s, u, self.supplier.currentData(), self.wh.currentData(), lines,
                                                        self.paid.value(), self.notes.text(), self.ref.text(),
                                                        self.update_cost.isChecked()).number
        number = run_safely(self, do)
        if number:
            Toast.show_message(self.parent(), f"تم حفظ فاتورة الشراء {number} وإدخال البضاعة", "success")
            self.accept()


class PurchasesPage(Page):
    title = "المشتريات"
    subtitle = "فواتير الشراء والموردون"

    def __init__(self) -> None:
        super().__init__()
        self.actions.addWidget(button("فاتورة شراء", "plus", "primary", on_click=self._new))
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        w = QWidget()
        lay = QVBoxLayout(w)
        self.purchases = DataTable([
            Column("الرقم", "number", bold=True), Column("التاريخ", "date", "datetime"),
            Column("المورد", "supplier", stretch=True), Column("رقم المورد", "ref"), Column("الأصناف", "items", "qty"),
            Column("الإجمالي", "total", "money", bold=True), Column("المدفوع", "paid", "money"),
            Column("المتبقي", "remaining", "money"),
        ])
        self.purchases.activated_row.connect(self._show)
        lay.addWidget(self.purchases, 1)
        self.tabs.addTab(w, icons.icon("receipt"), "فواتير الشراء")
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        bar = QHBoxLayout()
        bar.addWidget(button("مورد جديد", "plus", on_click=lambda: self._sup(None)))
        bar.addWidget(button("تعديل", "edit", on_click=lambda: self._sup((self.suppliers.current_row() or {}).get("id"))))
        bar.addWidget(button("تسجيل دفعة للمورد", "money", "soft", on_click=self._pay))
        bar.addWidget(button("حذف", "trash", on_click=self._del_sup))
        bar.addStretch(1)
        l2.addLayout(bar)
        self.suppliers = DataTable([Column("المورد", "name", stretch=True, bold=True), Column("الهاتف", "phone"),
                                    Column("العنوان", "address"), Column("المستحق له", "balance", "money", bold=True)])
        self.suppliers.activated_row.connect(lambda r: self._sup(r["id"]))
        l2.addWidget(self.suppliers, 1)
        self.tabs.addTab(w2, icons.icon("truck"), "الموردون")
        ctx.signals.products_changed.connect(self.mark_dirty)

    def refresh(self) -> None:
        with ctx.session() as (s, _):
            self.purchases.set_rows([{"id": p.id, "number": p.number, "date": p.created_at,
                                      "supplier": p.supplier.name if p.supplier else "—", "ref": p.supplier_ref,
                                      "items": len(p.items), "total": p.total, "paid": p.paid,
                                      "remaining": money(p.total - p.paid),
                                      "lines": [(i.product.name, i.quantity, i.unit_cost) for i in p.items]}
                                     for p in purchase_service.list_purchases(s)])
            self.suppliers.set_rows([{"id": x.id, "name": x.name, "phone": x.phone, "address": x.address,
                                      "balance": x.balance} for x in catalog_service.list_suppliers(s)])

    def _new(self) -> None:
        if PurchaseDialog(self).exec():
            self.refresh_now()

    def _show(self, row) -> None:
        from ftapp.ui.widgets.common import info
        info(self, "\n".join(f"• {n} × {q:g} بسعر {c:,.2f}" for n, q, c in row["lines"]), f"فاتورة {row['number']}")

    def _sup(self, sid) -> None:
        if sid is False:
            return
        if SupplierDialog(self, sid).exec():
            self.refresh_now()

    def _pay(self) -> None:
        r = self.suppliers.current_row()
        if not r:
            return
        from PySide6.QtWidgets import QInputDialog
        amount, ok = QInputDialog.getDouble(self, "دفعة للمورد", f"المبلغ المدفوع لـ {r['name']}", r["balance"], 0, 1e12, 2)
        if ok and amount > 0:
            def do():
                with ctx.session() as (s, u):
                    purchase_service.pay_supplier(s, u, r["id"], amount)
            run_safely(self, do, "تم تسجيل الدفعة")
            self.refresh_now()

    def _del_sup(self) -> None:
        r = self.suppliers.current_row()
        if r and confirm(self, f"حذف المورد «{r['name']}»؟", danger=True):
            with ctx.session() as (s, _):
                catalog_service.delete_supplier(s, r["id"])
            self.refresh_now()
