"""الزبائن والديون وكشوف الحساب."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QSplitter, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

from ftapp.models import Customer
from ftapp.services import catalog_service, currency_service, excel_service, sales_service
from ftapp.ui.context import ctx
from ftapp.ui.dialogs.catalog_dialogs import open_path
from ftapp.ui.pages.base import Page
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.common import Card, Toast, button, confirm, muted, run_safely
from ftapp.ui.widgets.forms import FormDialog, money_spin
from ftapp.ui.widgets.table import Column, DataTable


class CustomerDialog(FormDialog):
    def __init__(self, parent, customer_id: int | None = None) -> None:
        super().__init__(parent, "تعديل زبون" if customer_id else "زبون جديد")
        self.customer_id = customer_id
        with ctx.session() as (s, _):
            c = s.get(Customer, customer_id) if customer_id else None
            tiers = [(t.name, t.id) for t in catalog_service.list_tiers(s)]
            sym = currency_service.base(s).symbol
        self.name = self.line("الاسم *", c.name if c else "")
        self.phone = self.line("الهاتف", c.phone if c else "", "09xxxxxxxx")
        self.phone.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.address = self.line("العنوان", c.address if c else "")
        self.tier = self.combo("شريحة السعر", tiers, c.tier_id if c else None)
        self.limit = money_spin(suffix=sym)
        self.limit.setValue(c.credit_limit if c else 0)
        self.limit.setSpecialValueText("بدون حد")
        self.row("حد الدين", self.limit, "يظهر تنبيه عند تجاوز الزبون لهذا الحد")
        self.notes = self.line("ملاحظات", c.notes if c else "")
        self.on_save = self._do
        self.finish_layout()

    def _do(self):
        with ctx.session() as (s, _):
            return sales_service.save_customer(s, self.name.text(), self.phone.text(), self.address.text(),
                                               self.tier.currentData(), self.limit.value(), self.notes.text(),
                                               self.customer_id).id


class CustomersPage(Page):
    title = "الزبائن"
    subtitle = "بيانات الزبائن، الديون، الدفعات وكشوف الحساب"

    def __init__(self) -> None:
        super().__init__()
        self.actions.addWidget(button("زبون جديد", "plus", "primary", on_click=lambda: self._edit(None)))
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("searchBox")
        self.search.setPlaceholderText("بحث بالاسم أو الهاتف")
        self.search.textChanged.connect(self.refresh_now)
        self.debtors = QCheckBox("المدينون فقط")
        self.debtors.toggled.connect(self.refresh_now)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.debtors)
        ll.addLayout(bar)
        t = tokens()
        self.table = DataTable([
            Column("الزبون", "name", stretch=True, bold=True), Column("الهاتف", "phone"), Column("الشريحة", "tier"),
            Column("الدين", "balance_f", color=lambda r: t["danger"] if r["balance"] > 0 else None, bold=True),
        ])
        self.table.activated_row.connect(lambda r: self._edit(r["id"]))
        self.table.selection_changed_rows.connect(lambda rows: self._statement(rows[0] if rows else None))
        self.table.add_menu_action("تعديل", lambda r: self._edit(r["id"]))
        self.table.add_menu_action("حذف", self._delete)
        ll.addWidget(self.table, 1)
        self.summary = muted("")
        ll.addWidget(self.summary)
        splitter.addWidget(left)

        self.card = Card("كشف الحساب", icon_name="receipt")
        row = QHBoxLayout()
        row.addWidget(button("تسجيل دفعة", "money", "primary", on_click=self._payment))
        row.addWidget(button("تصدير الكشف", "excel", on_click=self._export))
        row.addStretch(1)
        self.card.body.addLayout(row)
        self.statement = DataTable([
            Column("التاريخ", "date", "datetime"), Column("البيان", "desc", stretch=True),
            Column("مدين", "debit", "money"), Column("دائن", "credit", "money"),
            Column("الرصيد", "balance", "money", bold=True),
        ])
        self.card.add(self.statement, 1)
        splitter.addWidget(self.card)
        splitter.setSizes([600, 600])
        self.root.addWidget(splitter, 1)
        self.current_id: int | None = None
        ctx.signals.sales_changed.connect(self.mark_dirty)

    def refresh(self) -> None:
        with ctx.session() as (s, _):
            rows = [{"id": c.id, "name": c.name, "phone": c.phone, "tier": c.tier.name if c.tier else "",
                     "balance": c.balance, "balance_f": currency_service.format_amount(s, c.balance)}
                    for c in sales_service.list_customers(s, self.search.text(), self.debtors.isChecked())]
            total = currency_service.format_amount(s, sum(r["balance"] for r in rows if r["balance"] > 0))
        self.table.set_rows(rows)
        self.summary.setText(f"{len(rows)} زبون • إجمالي الديون {total}")
        if self.current_id:
            self._statement({"id": self.current_id, "name": ""})

    def _statement(self, row) -> None:
        if not row:
            return
        self.current_id = row["id"]
        with ctx.session() as (s, _):
            c = s.get(Customer, row["id"])
            if c is None:
                return
            self.card.title_label.setText(f"كشف حساب: {c.name}")
            self.statement.set_rows(sales_service.customer_statement(s, c.id))

    def _edit(self, cid) -> None:
        if CustomerDialog(self, cid).exec():
            self.refresh_now()

    def _delete(self, row) -> None:
        if confirm(self, f"حذف الزبون «{row['name']}»؟", danger=True):
            def do():
                with ctx.session() as (s, _):
                    sales_service.delete_customer(s, row["id"])
            run_safely(self, do, "تم الحذف")
            self.refresh_now()

    def _payment(self) -> None:
        if not self.current_id:
            Toast.show_message(self, "اختر زبوناً أولاً", "warning")
            return
        with ctx.session() as (s, _):
            c = s.get(Customer, self.current_id)
            name, bal = c.name, c.balance
        amount, ok = QInputDialog.getDouble(self, "تسجيل دفعة", f"المبلغ المستلم من {name} (الدين {bal:,.2f})",
                                            max(bal, 0), 0, 1e12, 2)
        if ok and amount > 0:
            def do():
                with ctx.session() as (s, u):
                    sales_service.receive_payment(s, u, self.current_id, amount)
            run_safely(self, do, "تم تسجيل الدفعة")
            self.refresh_now()

    def _export(self) -> None:
        if not self.current_id:
            return
        path, _ = QFileDialog.getSaveFileName(self, "تصدير", "كشف_حساب.xlsx", "Excel (*.xlsx)")
        if path:
            headers, rows, kinds = self.statement.export_data()
            with ctx.session() as (s, _):
                excel_service.export_table(path, self.card.title_label.text(), headers, rows, s, kinds)
            open_path(Path(path))

    def open_item(self, payload) -> None:
        if isinstance(payload, dict) and payload.get("customer_id"):
            self._statement({"id": payload["customer_id"], "name": ""})
