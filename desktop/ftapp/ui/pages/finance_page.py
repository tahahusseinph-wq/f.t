"""المالية: المصاريف، الصندوق والورديات، العمولات، العملات وأسعار الصرف."""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from ftapp.models import Currency
from ftapp.services import currency_service, finance_service, settings_service
from ftapp.ui import icons
from ftapp.ui.context import ctx
from ftapp.ui.pages.base import Page
from ftapp.ui.pages.inventory_page import export_table
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.charts import SalesChart
from ftapp.ui.widgets.common import Card, Toast, button, confirm, fill_combo, muted, run_safely
from ftapp.ui.widgets.forms import FormDialog, date_edit, int_spin, money_spin
from ftapp.ui.widgets.table import Column, DataTable


class ExpenseDialog(FormDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent, "مصروف جديد")
        with ctx.session() as (s, _):
            cats = [(c.name, c.id) for c in finance_service.list_expense_categories(s)]
            sym = currency_service.base(s).symbol
        self.amount = money_spin(suffix=sym)
        self.row("المبلغ *", self.amount)
        self.cat = self.combo("التصنيف", cats)
        self.desc = self.line("البيان")
        self.date = date_edit()
        self.row("التاريخ", self.date)
        self.cash = QCheckBox("مدفوع من صندوق الوردية الحالية")
        self.cash.setChecked(True)
        self.row("", self.cash)
        self.on_save = self._do
        self.finish_layout()

    def _do(self):
        with ctx.session() as (s, u):
            return finance_service.add_expense(s, u, self.amount.value(), self.cat.currentData(), self.desc.text(),
                                               self.date.date().toPython(), self.cash.isChecked()).id


class CloseShiftDialog(FormDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent, "إغلاق الوردية ومطابقة الصندوق", 480, "إغلاق الوردية")
        with ctx.session() as (s, u):
            shift = finance_service.current_shift(s, u)
            if shift is None:
                self.summary = None
            else:
                self.summary = finance_service.shift_summary(s, shift)
                f = lambda v: currency_service.format_amount(s, v)  # noqa: E731
                sym = currency_service.base(s).symbol
        if self.summary is None:
            self.form.addRow(muted("لا توجد وردية مفتوحة"))
            self.save_btn.setEnabled(False)
        else:
            sm = self.summary
            for label, key in (("الرصيد الافتتاحي", "opening"), ("مبيعات نقدية", "sales_cash"),
                               ("مبيعات آجلة", "credit_sales"), ("دفعات زبائن", "payments"), ("مرتجعات نقدية", "refunds"),
                               ("مصاريف من الصندوق", "expenses")):
                self.form.addRow(label, QLabel(f(sm[key])))
            exp = QLabel(f(sm["expected"]))
            exp.setObjectName("bigTotal")
            self.form.addRow("المتوقع في الصندوق", exp)
            self.actual = money_spin(suffix=sym)
            self.actual.setValue(sm["expected"])
            self.actual.valueChanged.connect(self._diff)
            self.row("المبلغ الفعلي المعدود", self.actual)
            self.diff = QLabel()
            self.row("الفرق", self.diff)
            self.notes = self.line("ملاحظات")
            self._diff()
        self.on_save = self._do
        self.finish_layout()

    def _diff(self) -> None:
        d = self.actual.value() - self.summary["expected"]
        t = tokens()
        self.diff.setText("مطابق ✓" if abs(d) < 0.005 else (f"زيادة {d:,.2f}" if d > 0 else f"عجز {-d:,.2f}"))
        self.diff.setStyleSheet(f"color: {t['success'] if abs(d) < 0.005 else t['danger']}; font-weight: bold;")

    def _do(self):
        with ctx.session() as (s, u):
            return finance_service.close_shift(s, u, self.actual.value(), self.notes.text()).id


class CurrencyDialog(FormDialog):
    def __init__(self, parent, code: str | None = None) -> None:
        super().__init__(parent, "عملة / سعر صرف")
        with ctx.session() as (s, _):
            c = s.get(Currency, code) if code else None
            base = currency_service.base(s).code
        self.code = self.line("الرمز *", c.code if c else "", "مثال: SYP")
        self.code.setEnabled(c is None)
        self.name = self.line("الاسم", c.name if c else "")
        self.symbol = self.line("الرمز المختصر", c.symbol if c else "")
        self.rate = money_spin(10**12, 4)
        self.rate.setValue(c.rate if c else 1)
        self.rate.setEnabled(not (c and c.is_base))
        self.row(f"كم تساوي 1 {base}؟", self.rate)
        self.decimals = int_spin(0, 4)
        self.decimals.setValue(c.decimals if c else 2)
        self.row("الخانات العشرية", self.decimals)
        self.on_save = self._do
        self.finish_layout()

    def _do(self):
        with ctx.session() as (s, u):
            return currency_service.save_currency(s, u, self.code.text(), self.name.text(), self.symbol.text(),
                                                  self.rate.value(), self.decimals.value()).code


class FinancePage(Page):
    title = "المالية"
    subtitle = "المصاريف، الصندوق، العمولات، والعملات"

    def __init__(self) -> None:
        super().__init__()
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        self.can_exp = ctx.can("expenses.manage")
        if self.can_exp:
            self._build_expenses()
        self._build_shifts()
        if ctx.can("reports.view"):
            self._build_commissions()
        if ctx.can("settings.manage"):
            self._build_currencies()
        self.tabs.currentChanged.connect(lambda *_: self.refresh_now())
        ctx.signals.sales_changed.connect(self.mark_dirty)

    def _tab(self, title, icon_name) -> QVBoxLayout:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.tabs.addTab(w, icons.icon(icon_name), title)
        return lay

    def _build_expenses(self) -> None:
        lay = self._tab("المصاريف", "minus")
        bar = QHBoxLayout()
        bar.addWidget(button("مصروف جديد", "plus", "primary", on_click=self._add_expense))
        bar.addWidget(button("حذف", "trash", on_click=self._del_expense))
        self.ex_from = date_edit(date.today().replace(day=1))
        self.ex_to = date_edit()
        for w in (QLabel("من"), self.ex_from, QLabel("إلى"), self.ex_to):
            bar.addWidget(w)
        bar.addWidget(button("عرض", "search", "soft", on_click=self.refresh_now))
        bar.addStretch(1)
        bar.addWidget(button("تصدير", "excel", on_click=lambda: export_table(self, self.expenses, "المصاريف")))
        lay.addLayout(bar)
        self.expenses = DataTable([Column("التاريخ", "date", "date"), Column("التصنيف", "cat"),
                                   Column("البيان", "desc", stretch=True), Column("المبلغ", "amount", "money", bold=True),
                                   Column("من الصندوق", "cash", "bool")])
        lay.addWidget(self.expenses, 1)
        self.ex_summary = muted("")
        lay.addWidget(self.ex_summary)

    def _add_expense(self) -> None:
        if ExpenseDialog(self).exec():
            self.refresh_now()

    def _del_expense(self) -> None:
        r = self.expenses.current_row()
        if r and confirm(self, "حذف المصروف المحدد؟", danger=True):
            with ctx.session() as (s, _):
                finance_service.delete_expense(s, r["id"])
            self.refresh_now()

    def _build_shifts(self) -> None:
        lay = self._tab("الصندوق والورديات", "clock")
        bar = QHBoxLayout()
        bar.addWidget(button("إغلاق ورديتي", "lock", "primary", on_click=self._close_shift))
        bar.addStretch(1)
        lay.addLayout(bar)
        t = tokens()
        self.shifts = DataTable([
            Column("البائع", "user", bold=True), Column("الفتح", "opened", "datetime"), Column("الإغلاق", "closed", "datetime"),
            Column("افتتاحي", "opening", "money"), Column("المتوقع", "expected", "money"), Column("الفعلي", "actual", "money"),
            Column("الفرق", "diff", "money", bold=True,
                   color=lambda r: t["danger"] if r["diff"] and r["diff"] < 0 else (t["success"] if r["diff"] else None)),
            Column("الحالة", "status"), Column("ملاحظات", "notes", stretch=True)])
        lay.addWidget(self.shifts, 1)

    def _close_shift(self) -> None:
        if CloseShiftDialog(self).exec():
            Toast.show_message(self, "تم إغلاق الوردية", "success")
            self.refresh_now()

    def _build_commissions(self) -> None:
        lay = self._tab("عمولات البائعين", "percent")
        bar = QHBoxLayout()
        self.cm_from = date_edit(date.today().replace(day=1))
        self.cm_to = date_edit()
        for w in (QLabel("من"), self.cm_from, QLabel("إلى"), self.cm_to):
            bar.addWidget(w)
        bar.addWidget(button("احسب", "refresh", "soft", on_click=self.refresh_now))
        bar.addStretch(1)
        bar.addWidget(button("تصدير", "excel", on_click=lambda: export_table(self, self.comm, "العمولات")))
        lay.addLayout(bar)
        self.comm = DataTable([Column("البائع", "user", stretch=True, bold=True), Column("الفواتير", "invoices", "qty"),
                               Column("المبيعات", "sales", "money"), Column("المرتجعات", "returns", "money"),
                               Column("الصافي", "net", "money"), Column("النسبة", "rate", "percent"),
                               Column("العمولة", "commission", "money", bold=True)])
        lay.addWidget(self.comm, 1)
        lay.addWidget(muted("نسبة العمولة لكل بائع تُحدد من صفحة المستخدمين."))

    def _build_currencies(self) -> None:
        lay = self._tab("العملات وأسعار الصرف", "money")
        bar = QHBoxLayout()
        bar.addWidget(button("عملة جديدة", "plus", on_click=lambda: self._cur(None)))
        bar.addWidget(button("تعديل سعر الصرف", "edit", "primary",
                             on_click=lambda: self._cur((self.currencies.current_row() or {}).get("code"))))
        bar.addWidget(button("حذف", "trash", on_click=self._del_cur))
        bar.addStretch(1)
        bar.addWidget(QLabel("عملة العرض الافتراضية"))
        self.display_cur = QComboBox()
        self.display_cur.activated.connect(self._set_display)
        bar.addWidget(self.display_cur)
        lay.addLayout(bar)
        self.currencies = DataTable([Column("الرمز", "code", bold=True), Column("الاسم", "name", stretch=True),
                                     Column("الرمز المختصر", "symbol"), Column("سعر الصرف", "rate", "qty", bold=True),
                                     Column("أساسية", "base", "bool")])
        self.currencies.activated_row.connect(lambda r: self._cur(r["code"]))
        self.currencies.selection_changed_rows.connect(self._rate_chart)
        lay.addWidget(self.currencies, 1)
        card = Card("تاريخ سعر الصرف", icon_name="chart")
        self.rate_chart = SalesChart()
        self.rate_chart.setMinimumHeight(220)
        card.add(self.rate_chart)
        lay.addWidget(card)
        lay.addWidget(muted("كل الأسعار مخزنة بالعملة الأساسية؛ تغيير سعر الصرف يحدّث الأسعار المعروضة بالعملة الأخرى فوراً. "
                            "لتعديل أسعار البضاعة نفسها استخدم «تحديث الأسعار الجماعي» من صفحة المنتجات."))

    def _cur(self, code) -> None:
        if code is False:
            return
        if CurrencyDialog(self, code).exec():
            self.refresh_now()

    def _del_cur(self) -> None:
        r = self.currencies.current_row()
        if r and confirm(self, f"حذف العملة {r['code']}؟", danger=True):
            def do():
                with ctx.session() as (s, _):
                    currency_service.delete_currency(s, r["code"])
            run_safely(self, do)
            self.refresh_now()

    def _set_display(self) -> None:
        with ctx.session() as (s, _):
            settings_service.set(s, "display_currency", self.display_cur.currentData())
        Toast.show_message(self, "تم تغيير عملة العرض", "success")

    def _rate_chart(self, rows) -> None:
        if not rows:
            return
        with ctx.session() as (s, _):
            hist = currency_service.rate_history(s, rows[0]["code"])
        if hist:
            self.rate_chart.set_data([h.changed_at.strftime("%m-%d") for h in hist], [h.rate for h in hist])

    def refresh(self) -> None:
        title = self.tabs.tabText(self.tabs.currentIndex())
        with ctx.session() as (s, u):
            if title == "المصاريف":
                exps = finance_service.list_expenses(s, self.ex_from.date().toPython(), self.ex_to.date().toPython())
                self.expenses.set_rows([{"id": e.id, "date": e.expense_date, "cat": e.category.name if e.category else "",
                                         "desc": e.description, "amount": e.amount, "cash": e.paid_from_cash} for e in exps])
                self.ex_summary.setText(f"الإجمالي: {currency_service.format_amount(s, sum(e.amount for e in exps))}")
            elif title == "الصندوق والورديات":
                uid = None if ctx.can("reports.view") else ctx.user_id
                self.shifts.set_rows([{"user": sh.user.display_name, "opened": sh.opened_at, "closed": sh.closed_at,
                                       "opening": sh.opening_cash,
                                       "expected": sh.expected_cash if sh.status == "closed" else finance_service.shift_summary(s, sh)["expected"],
                                       "actual": sh.actual_cash if sh.status == "closed" else None,
                                       "diff": sh.difference if sh.status == "closed" else None,
                                       "status": "مغلقة" if sh.status == "closed" else "مفتوحة", "notes": sh.notes}
                                      for sh in finance_service.list_shifts(s, uid)])
            elif title == "عمولات البائعين":
                self.comm.set_rows([{**c, "user": c["user"].display_name}
                                    for c in finance_service.commissions(s, self.cm_from.date().toPython(),
                                                                         self.cm_to.date().toPython())])
            elif title == "العملات وأسعار الصرف":
                curs = currency_service.list_currencies(s)
                self.currencies.set_rows([{"code": c.code, "name": c.name, "symbol": c.symbol, "rate": c.rate,
                                           "base": c.is_base} for c in curs])
                fill_combo(self.display_cur, [(f"{c.name} ({c.symbol})", c.code) for c in curs],
                           currency_service.display(s).code)
