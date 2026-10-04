"""أرشيف الفواتير: المبيعات، المرتجعات، عروض الأسعار."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ftapp.core.utils import fmt_qty
from ftapp.models import Invoice
from ftapp.services import auth_service, currency_service, sales_service
from ftapp.ui.context import ctx
from ftapp.ui.dialogs.invoice_preview import InvoicePreviewDialog
from ftapp.ui.pages.base import Page
from ftapp.ui.pages.inventory_page import export_table
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.common import Toast, button, confirm, error, fill_combo, muted, run_safely
from ftapp.ui.widgets.forms import date_edit
from ftapp.ui.widgets.table import Column, DataTable


class ReturnDialog(QDialog):
    def __init__(self, parent, invoice_id: int) -> None:
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.setWindowTitle("مرتجع")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(720, 480)
        lay = QVBoxLayout(self)
        with ctx.session() as (s, _):
            inv = s.get(Invoice, invoice_id)
            self.has_customer = bool(inv.customer_id)
            t = QLabel(f"مرتجع من الفاتورة {inv.number}")
            t.setObjectName("pageTitle")
            lay.addWidget(t)
            self.table = QTableWidget(len(inv.items), 4)
            self.table.setHorizontalHeaderLabels(["الصنف", "المباع", "المرتجع سابقاً", "الكمية المرتجعة الآن"])
            self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            self.table.verticalHeader().setVisible(False)
            for r, it in enumerate(inv.items):
                name = QTableWidgetItem(it.product_name)
                name.setData(Qt.ItemDataRole.UserRole, it.id)
                self.table.setItem(r, 0, name)
                self.table.setItem(r, 1, QTableWidgetItem(fmt_qty(it.quantity)))
                self.table.setItem(r, 2, QTableWidgetItem(fmt_qty(it.returned_qty)))
                sp = QDoubleSpinBox()
                sp.setRange(0, it.quantity - it.returned_qty)
                sp.setDecimals(3)
                self.table.setCellWidget(r, 3, sp)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.r_cash = QRadioButton("إرجاع المبلغ نقداً")
        self.r_balance = QRadioButton("خصم من دين الزبون")
        self.r_cash.setChecked(True)
        self.r_balance.setEnabled(self.has_customer)
        row.addWidget(self.r_cash)
        row.addWidget(self.r_balance)
        row.addStretch(1)
        lay.addLayout(row)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("سبب الإرجاع")
        lay.addWidget(self.notes)
        b = QHBoxLayout()
        b.addStretch(1)
        b.addWidget(button("إلغاء", on_click=self.reject))
        b.addWidget(button("تنفيذ المرتجع", "return", "primary", on_click=self._do))
        lay.addLayout(b)
        self.return_id: int | None = None

    def _do(self) -> None:
        items = [(self.table.item(r, 0).data(Qt.ItemDataRole.UserRole), self.table.cellWidget(r, 3).value())
                 for r in range(self.table.rowCount()) if self.table.cellWidget(r, 3).value() > 0]

        def do():
            with ctx.session() as (s, u):
                ret = sales_service.create_return(s, u, self.invoice_id, items,
                                                  "cash" if self.r_cash.isChecked() else "balance", self.notes.text())
                return ret.id
        rid = run_safely(self, do)
        if rid:
            self.return_id = rid
            self.accept()


class InvoicesPage(Page):
    title = "الفواتير"
    subtitle = "المبيعات والمرتجعات وعروض الأسعار"

    def __init__(self) -> None:
        super().__init__()
        bar = QHBoxLayout()
        self.kind = QComboBox()
        for text, k in (("فواتير البيع", "sale"), ("المرتجعات", "return"), ("عروض الأسعار", "quotation")):
            self.kind.addItem(text, k)
        self.date_from = date_edit(date.today() - timedelta(days=30))
        self.date_to = date_edit()
        self.seller = QComboBox()
        self.search = QLineEdit()
        self.search.setObjectName("searchBox")
        self.search.setPlaceholderText("رقم الفاتورة أو اسم/هاتف الزبون")
        self.search.returnPressed.connect(self.refresh_now)
        for w in (self.kind, QLabel("من"), self.date_from, QLabel("إلى"), self.date_to, self.seller):
            bar.addWidget(w)
        bar.addWidget(self.search, 1)
        bar.addWidget(button("عرض", "search", "soft", on_click=self.refresh_now))
        bar.addWidget(button("تصدير", "excel", on_click=lambda: export_table(self, self.table, "الفواتير")))
        self.kind.currentIndexChanged.connect(self.refresh_now)
        self.root.addLayout(bar)
        t = tokens()
        self.table = DataTable([
            Column("الرقم", "number", bold=True), Column("التاريخ", "date", "datetime"),
            Column("الزبون", "customer", stretch=True), Column("البائع", "seller"),
            Column("الأصناف", "items", "qty"), Column("الإجمالي", "total", bold=True),
            Column("المدفوع", "paid"), Column("المتبقي", "remaining",
                                             color=lambda r: t["danger"] if r["remaining_v"] > 0 else None),
            Column("الدفع", "method"), Column("الحالة", "status",
                                            color=lambda r: t["danger"] if r["status"] == "ملغاة" else None),
        ])
        self.table.activated_row.connect(lambda r: self._open(r["id"]))
        self.table.add_menu_action("عرض / طباعة", lambda r: self._open(r["id"]))
        if ctx.can("sales.return"):
            self.table.add_menu_action("مرتجع", self._return)
        if ctx.can("sales.cancel"):
            self.table.add_menu_action("إلغاء الفاتورة", self._cancel)
        self.table.add_menu_action("تحويل عرض السعر إلى فاتورة", self._convert)
        self.root.addWidget(self.table, 1)
        self.summary = muted("")
        self.root.addWidget(self.summary)
        ctx.signals.sales_changed.connect(self.mark_dirty)
        with ctx.session() as (s, _):
            users = [(u.display_name, u.id) for u in auth_service.list_users(s)]
        if ctx.can("sales.view_all"):
            fill_combo(self.seller, users, placeholder="كل البائعين")
        else:
            fill_combo(self.seller, [(ctx.display_name, ctx.user_id)])
            self.seller.setEnabled(False)
        self.seller.currentIndexChanged.connect(self.refresh_now)

    def refresh(self) -> None:
        with ctx.session() as (s, _):
            invs = sales_service.list_invoices(s, self.kind.currentData(), self.date_from.date().toPython(),
                                               self.date_to.date().toPython(), self.seller.currentData(),
                                               search=self.search.text(), limit=3000)
            rows = []
            total = paid = 0.0
            for inv in invs:
                f = lambda v, c=inv.currency_code: currency_service.format_amount(s, v, c)  # noqa: E731
                rows.append({"id": inv.id, "number": inv.number, "date": inv.created_at,
                             "customer": inv.customer_name or "زبون نقدي", "seller": inv.user.display_name if inv.user else "",
                             "items": len(inv.items), "total": f(inv.total), "paid": f(inv.paid),
                             "remaining": f(inv.remaining) if inv.kind == "sale" else "—",
                             "remaining_v": inv.remaining if inv.kind == "sale" else 0,
                             "method": sales_service.PAYMENT_METHODS.get(inv.payment_method, ""),
                             "status": sales_service.STATUSES.get(inv.status, inv.status), "kind": inv.kind,
                             "raw_status": inv.status})
                if inv.status != "cancelled":
                    total += inv.total
                    paid += inv.paid
            ftotal = currency_service.format_amount(s, total)
            fpaid = currency_service.format_amount(s, paid)
        self.table.set_rows(rows)
        self.summary.setText(f"{len(rows)} مستند • الإجمالي {ftotal} • المحصّل {fpaid}")

    def _open(self, invoice_id: int) -> None:
        InvoicePreviewDialog(self, invoice_id).exec()

    def _return(self, row) -> None:
        if row["kind"] != "sale":
            error(self, "المرتجع يكون من فاتورة بيع فقط")
            return
        dlg = ReturnDialog(self, row["id"])
        if dlg.exec() and dlg.return_id:
            Toast.show_message(self, "تم تسجيل المرتجع وإعادة البضاعة للمخزون", "success")
            InvoicePreviewDialog(self, dlg.return_id).exec()
            self.refresh_now()

    def _cancel(self, row) -> None:
        from PySide6.QtWidgets import QInputDialog
        reason, ok = QInputDialog.getText(self, "إلغاء الفاتورة", f"سبب إلغاء {row['number']}:")
        if not ok or not confirm(self, "إلغاء الفاتورة سيعيد البضاعة للمخزون ويلغي الدين. متابعة؟", danger=True):
            return

        def do():
            with ctx.session() as (s, u):
                sales_service.cancel_invoice(s, u, row["id"], reason)
        if run_safely(self, do, "تم إلغاء الفاتورة"):
            self.refresh_now()

    def _convert(self, row) -> None:
        if row["kind"] != "quotation" or row["raw_status"] != "open":
            error(self, "اختر عرض سعر مفتوحاً")
            return

        def do():
            with ctx.session() as (s, u):
                return sales_service.convert_quotation(s, u, row["id"]).id
        new_id = run_safely(self, do, "تم تحويل عرض السعر إلى فاتورة")
        if new_id:
            self.refresh_now()
            self._open(new_id)

    def open_item(self, payload) -> None:
        if isinstance(payload, dict) and payload.get("invoice_id"):
            self._open(payload["invoice_id"])
