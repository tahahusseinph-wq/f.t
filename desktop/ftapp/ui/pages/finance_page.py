"""المالية: المصاريف، الصندوق والورديات (لكل عملة)، صرف العملات، الرواتب والسلف، العمولات."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget)

from ftapp.core.utils import fmt_money
from ftapp.services import cash_service, currency_service, finance_service, payroll_service
from ftapp.ui import icons
from ftapp.ui.context import ctx
from ftapp.ui.pages.base import Page
from ftapp.ui.pages.inventory_page import export_table
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.common import Toast, button, confirm, muted, run_safely
from ftapp.ui.widgets.forms import FormDialog, date_edit, money_spin
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
        self.form.addRow(muted("الرواتب والسلف تُسجّل من تبويب «الرواتب والسلف» لتُحسب على الموظف."))
        self.on_save = self._do
        self.finish_layout()

    def _do(self):
        with ctx.session() as (s, u):
            return finance_service.add_expense(s, u, self.amount.value(), self.cat.currentData(), self.desc.text(),
                                               self.date.date().toPython(), self.cash.isChecked()).id


class OpenShiftDialog(FormDialog):
    """فتح الوردية: الرصيد الافتتاحي في الصندوق لكل عملة مفعّلة."""

    def __init__(self, parent) -> None:
        super().__init__(parent, "فتح وردية — رصيد الصندوق الافتتاحي", 460, "فتح الوردية")
        with ctx.session() as (s, _):
            curs = [(c.code, c.name, c.symbol, c.decimals) for c in currency_service.list_currencies(s)]
        self.spins = {}
        for code, name, symbol, dec in curs:
            sp = money_spin(1e13, dec, symbol)
            self.spins[code] = sp
            self.row(name, sp)
        self.form.addRow(muted("أدخل المبلغ الموجود فعلياً في الدرج من كل عملة (اتركه 0 إن لم يوجد)."))
        self.on_save = self._do
        self.finish_layout()

    def _do(self):
        with ctx.session() as (s, u):
            return finance_service.open_shift(s, u, balances={c: sp.value() for c, sp in self.spins.items()}).id


class CloseShiftDialog(FormDialog):
    """إغلاق الوردية: المتوقع والمعدود فعلياً لكل عملة، والفرق الإجمالي بالعملة الأساسية."""

    def __init__(self, parent) -> None:
        super().__init__(parent, "إغلاق الوردية ومطابقة الصندوق", 680, "إغلاق الوردية")
        self.rows: dict[str, tuple] = {}
        info = []
        with ctx.session() as (s, u):
            shift = finance_service.current_shift(s, u)
            self.summary = finance_service.shift_summary(s, shift) if shift else None
            if shift:
                f = lambda v: currency_service.format_amount(s, v)  # noqa: E731
                curs = {c.code: c for c in currency_service.list_currencies(s)}
                self.rates = {code: c.rate for code, c in curs.items()}
                self.base_symbol = currency_service.base(s).symbol
                info = [(code, curs[code].name, curs[code].symbol, curs[code].decimals, b)
                        for code, b in self.summary["by_currency"].items() if code in curs]
                texts = {k: f(self.summary[k]) for k in ("sales_total", "credit_sales", "shamcash")}
        if self.summary is None:
            self.form.addRow(muted("لا توجد وردية مفتوحة"))
            self.save_btn.setEnabled(False)
        else:
            self.form.addRow("المبيعات (الإجمالي)", QLabel(texts["sales_total"]))
            self.form.addRow("مبيعات آجلة", QLabel(texts["credit_sales"]))
            self.form.addRow("مقبوض عبر شام كاش (خارج الصندوق)", QLabel(texts["shamcash"]))
            self.form.addRow("عدد الفواتير", QLabel(str(self.summary["invoices"])))
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            for col, h in enumerate(("العملة", "افتتاحي", "داخل", "خارج", "المتوقع", "المعدود فعلياً", "الفرق")):
                lbl = QLabel(h)
                lbl.setStyleSheet("font-weight: bold;")
                grid.addWidget(lbl, 0, col)
            for r, (code, name, symbol, dec, b) in enumerate(info, start=1):
                def fm(v, sy=symbol, d=dec):
                    return fmt_money(v, sy, d)
                grid.addWidget(QLabel(name), r, 0)
                grid.addWidget(QLabel(fm(b["opening"])), r, 1)
                grid.addWidget(QLabel(fm(b["in"])), r, 2)
                grid.addWidget(QLabel(fm(b["out"])), r, 3)
                exp = QLabel(fm(b["expected"]))
                exp.setStyleSheet("font-weight: bold;")
                grid.addWidget(exp, r, 4)
                sp = money_spin(1e13, dec)
                sp.setMinimum(-1e13)
                sp.setValue(b["expected"])
                sp.valueChanged.connect(self._diff)
                grid.addWidget(sp, r, 5)
                d = QLabel()
                grid.addWidget(d, r, 6)
                self.rows[code] = (sp, d, b["expected"], dec)
            box = QWidget()
            box.setLayout(grid)
            self.form.addRow(box)
            self.total_diff = QLabel()
            self.total_diff.setObjectName("bigTotal")
            self.row("الفرق الإجمالي", self.total_diff)
            self.notes = self.line("ملاحظات")
            self._diff()
        self.on_save = self._do
        self.finish_layout()

    def _diff(self) -> None:
        t = tokens()
        total = 0.0
        for code, (sp, lbl, expected, dec) in self.rows.items():
            d = sp.value() - expected
            total += d / (self.rates.get(code) or 1)
            ok = abs(d) < 10 ** -dec / 2
            lbl.setText("✓" if ok else (f"+{d:,.{dec}f}" if d > 0 else f"{d:,.{dec}f}"))
            lbl.setStyleSheet(f"color: {t['success'] if ok else t['danger']}; font-weight: bold;")
        ok = abs(total) < 0.5
        if ok:
            text = "مطابق ✓"
        elif total > 0:
            text = f"زيادة {total:,.0f} {self.base_symbol}"
        else:
            text = f"عجز {-total:,.0f} {self.base_symbol}"
        self.total_diff.setText(text)
        self.total_diff.setStyleSheet(f"color: {t['success'] if ok else t['danger']};")

    def _do(self):
        with ctx.session() as (s, u):
            return finance_service.close_shift(s, u, notes=self.notes.text(),
                                               actual_balances={c: r[0].value() for c, r in self.rows.items()}).id


class EmployeeDialog(FormDialog):
    def __init__(self, parent, employee_id: int | None = None) -> None:
        super().__init__(parent, "موظف")
        with ctx.session() as (s, _):
            e = payroll_service.get_employee(s, employee_id) if employee_id else None
            sym = currency_service.base(s).symbol
            vals = (e.name, e.phone, e.pay_period, e.salary, e.notes, e.is_active) if e else ("", "", "monthly", 0, "", True)
        self.employee_id = employee_id
        self.name = self.line("الاسم *", vals[0])
        self.phone = self.line("الهاتف", vals[1])
        self.period = self.combo("طريقة المحاسبة", [(v, k) for k, v in payroll_service.PERIODS.items()], vals[2])
        self.salary = money_spin(suffix=sym)
        self.salary.setValue(vals[3])
        self.row("الراتب لكل فترة", self.salary, "يومي = أجرة اليوم، أسبوعي = راتب الأسبوع، شهري = راتب الشهر")
        self.notes = self.line("ملاحظات", vals[4])
        self.active = QCheckBox("على رأس العمل")
        self.active.setChecked(vals[5])
        self.row("", self.active)
        self.on_save = self._do
        self.finish_layout()

    def _do(self):
        with ctx.session() as (s, _):
            return payroll_service.save_employee(s, self.name.text(), self.period.currentData(), self.salary.value(),
                                                 self.phone.text(), self.notes.text(), self.active.isChecked(),
                                                 self.employee_id).id


class SalaryDialog(FormDialog):
    """دفع راتب يومي/أسبوعي/شهري مع خصم السلف المستحقة."""

    def __init__(self, parent, employee_id: int) -> None:
        super().__init__(parent, "دفع راتب", 480, "دفع الراتب")
        with ctx.session() as (s, _):
            e = payroll_service.get_employee(s, employee_id)
            self.owed = payroll_service.outstanding_advances(s, e.id)
            last = payroll_service.last_paid_to(s, e.id)
            sym = currency_service.base(s).symbol
            name, period, salary = e.name, e.pay_period, e.salary
        self.employee_id = employee_id
        self.sym = sym
        start, end = payroll_service.period_range(period, date.today())
        if last and period != "monthly":  # الفترة التالية لآخر راتب مدفوع
            start = last + timedelta(days=1)
            end = start + timedelta(days=0 if period == "daily" else 6)
        self.form.addRow("الموظف", QLabel(f"<b>{name}</b> — راتب {payroll_service.PERIODS[period]}"))
        self.d_from = date_edit(start)
        self.d_to = date_edit(end)
        self.row("من", self.d_from)
        self.row("إلى", self.d_to)
        self.amount = money_spin(suffix=sym)
        self.amount.setValue(salary)
        self.amount.valueChanged.connect(self._net)
        self.row("الراتب الإجمالي", self.amount)
        self.deduct = money_spin(suffix=sym)
        self.deduct.setMaximum(max(0.0, self.owed))
        self.deduct.setValue(min(self.owed, salary))
        self.deduct.valueChanged.connect(self._net)
        self.row("خصم من السلف", self.deduct, f"السلف المستحقة على الموظف: {self.owed:,.0f} {sym}")
        self.net = QLabel()
        self.net.setObjectName("bigTotal")
        self.row("الصافي المدفوع", self.net)
        self.cash = QCheckBox("مدفوع من صندوق الوردية الحالية")
        self.cash.setChecked(True)
        self.row("", self.cash)
        self.notes = self.line("ملاحظات")
        self._net()
        self.on_save = self._do
        self.finish_layout()

    def _net(self) -> None:
        self.net.setText(f"{max(0.0, self.amount.value() - self.deduct.value()):,.0f} {self.sym}")

    def _do(self):
        with ctx.session() as (s, u):
            return payroll_service.pay_salary(s, u, self.employee_id, self.amount.value(), self.deduct.value(),
                                              self.d_from.date().toPython(), self.d_to.date().toPython(),
                                              from_cash=self.cash.isChecked(), notes=self.notes.text()).id


class AdvanceDialog(FormDialog):
    def __init__(self, parent, employee_id: int) -> None:
        super().__init__(parent, "سلفة لموظف", 440, "تسجيل السلفة")
        with ctx.session() as (s, _):
            e = payroll_service.get_employee(s, employee_id)
            owed = payroll_service.outstanding_advances(s, e.id)
            sym = currency_service.base(s).symbol
            name = e.name
        self.employee_id = employee_id
        self.form.addRow("الموظف", QLabel(f"<b>{name}</b> — سلف سابقة غير مخصومة: {owed:,.0f} {sym}"))
        self.amount = money_spin(suffix=sym)
        self.row("مبلغ السلفة *", self.amount)
        self.date = date_edit()
        self.row("التاريخ", self.date)
        self.cash = QCheckBox("مدفوعة من صندوق الوردية الحالية")
        self.cash.setChecked(True)
        self.row("", self.cash)
        self.notes = self.line("ملاحظات")
        self.form.addRow(muted("تُخصم السلفة تلقائياً عند دفع الراتب القادم (ويمكن تعديل قيمة الخصم)."))
        self.on_save = self._do
        self.finish_layout()

    def _do(self):
        with ctx.session() as (s, u):
            return payroll_service.give_advance(s, u, self.employee_id, self.amount.value(), self.date.date().toPython(),
                                                self.cash.isChecked(), self.notes.text()).id


class FinancePage(Page):
    title = "المالية"
    subtitle = "المصاريف، الصندوق، صرف العملات، الرواتب والسلف، والعمولات"

    def __init__(self) -> None:
        super().__init__()
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        self.can_exp = ctx.can("expenses.manage")
        if self.can_exp:
            self._build_expenses()
            self._build_payroll()
        self._build_shifts()
        if ctx.can("sales.create"):
            self._build_exchanges()
        if ctx.can("reports.view"):
            self._build_commissions()
        self.tabs.currentChanged.connect(lambda *_: self.refresh_now())
        ctx.signals.sales_changed.connect(self.mark_dirty)

    def _tab(self, title, icon_name) -> QVBoxLayout:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.tabs.addTab(w, icons.icon(icon_name), title)
        return lay

    # ---------------- المصاريف ----------------
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

    # ---------------- الرواتب والسلف ----------------
    def _build_payroll(self) -> None:
        lay = self._tab("الرواتب والسلف", "users")
        bar = QHBoxLayout()
        bar.addWidget(button("موظف جديد", "plus", on_click=lambda: self._employee(None)))
        bar.addWidget(button("تعديل", "edit", on_click=lambda: self._employee((self.emps.current_row() or {}).get("id"))))
        bar.addWidget(button("دفع راتب", "wallet", "primary", on_click=self._salary))
        bar.addWidget(button("سلفة", "minus", on_click=self._advance))
        bar.addWidget(button("حذف", "trash", on_click=self._del_employee))
        bar.addStretch(1)
        lay.addLayout(bar)
        t = tokens()
        self.emps = DataTable([Column("الموظف", "name", stretch=True, bold=True), Column("المحاسبة", "period"),
                               Column("الراتب", "salary", "money"), Column("آخر راتب حتى", "last", "date"),
                               Column("سلف مستحقة", "advances", "money", bold=True,
                                      color=lambda r: t["danger"] if r["advances"] > 0 else None),
                               Column("الحالة", "status")])
        self.emps.activated_row.connect(lambda r: self._employee(r["id"]))
        self.emps.selection_changed_rows.connect(lambda *_: self._load_tx())
        lay.addWidget(self.emps, 2)
        hb = QHBoxLayout()
        hb.addWidget(QLabel("سجل الرواتب والسلف"))
        hb.addStretch(1)
        hb.addWidget(button("حذف الحركة", "trash", on_click=self._del_tx))
        hb.addWidget(button("تصدير", "excel", on_click=lambda: export_table(self, self.txs, "الرواتب والسلف")))
        lay.addLayout(hb)
        self.txs = DataTable([Column("التاريخ", "date", "date"), Column("الموظف", "emp", bold=True),
                              Column("النوع", "kind"), Column("الفترة", "period", stretch=True),
                              Column("المبلغ", "amount", "money"), Column("خصم سلف", "deducted", "money"),
                              Column("المدفوع", "net", "money", bold=True), Column("ملاحظات", "notes")])
        lay.addWidget(self.txs, 2)

    def _selected_employee(self) -> int | None:
        r = self.emps.current_row()
        if not r:
            Toast.show_message(self, "اختر موظفاً من القائمة أولاً", "warning")
            return None
        return r["id"]

    def _employee(self, employee_id) -> None:
        if employee_id is False:
            return
        if EmployeeDialog(self, employee_id).exec():
            self.refresh_now()

    def _salary(self) -> None:
        eid = self._selected_employee()
        if eid and SalaryDialog(self, eid).exec():
            Toast.show_message(self, "تم دفع الراتب وتسجيله ضمن المصاريف", "success")
            self.refresh_now()

    def _advance(self) -> None:
        eid = self._selected_employee()
        if eid and AdvanceDialog(self, eid).exec():
            Toast.show_message(self, "تم تسجيل السلفة", "success")
            self.refresh_now()

    def _del_employee(self) -> None:
        r = self.emps.current_row()
        if r and confirm(self, f"حذف الموظف «{r['name']}»؟ (إذا كان له سجل رواتب سيتم إيقافه فقط)", danger=True):
            def do():
                with ctx.session() as (s, _):
                    payroll_service.delete_employee(s, r["id"])
            run_safely(self, do)
            self.refresh_now()

    def _del_tx(self) -> None:
        r = self.txs.current_row()
        if r and confirm(self, "حذف هذه الحركة؟ سيُحذف المصروف المرتبط بها أيضاً.", danger=True):
            def do():
                with ctx.session() as (s, u):
                    payroll_service.delete_transaction(s, u, r["id"])
            run_safely(self, do)
            self.refresh_now()

    def _load_tx(self) -> None:
        r = self.emps.current_row()
        with ctx.session() as (s, _):
            rows = [{"id": t.id, "date": t.pay_date, "emp": t.employee.name,
                     "kind": payroll_service.KINDS.get(t.kind, t.kind),
                     "period": f"{t.period_from:%Y-%m-%d} → {t.period_to:%Y-%m-%d}" if t.period_from and t.period_to else "",
                     "amount": t.amount, "deducted": t.deducted or None, "net": t.net, "notes": t.notes}
                    for t in payroll_service.list_transactions(s, r["id"] if r else None)[:500]]
        self.txs.set_rows(rows)

    # ---------------- الورديات ----------------
    def _build_shifts(self) -> None:
        lay = self._tab("الصندوق والورديات", "clock")
        bar = QHBoxLayout()
        bar.addWidget(button("فتح وردية", "clock", on_click=self._open_shift))
        bar.addWidget(button("إغلاق ورديتي", "lock", "primary", on_click=self._close_shift))
        bar.addStretch(1)
        lay.addLayout(bar)
        t = tokens()
        self.shifts = DataTable([
            Column("البائع", "user", bold=True), Column("الفتح", "opened", "datetime"), Column("الإغلاق", "closed", "datetime"),
            Column("الصندوق الافتتاحي", "opening_text", stretch=True), Column("المتوقع", "expected_text", stretch=True),
            Column("الفعلي", "actual_text", stretch=True),
            Column("الفرق", "diff", "money", bold=True,
                   color=lambda r: t["danger"] if r["diff"] and r["diff"] < 0 else (t["success"] if r["diff"] else None)),
            Column("الحالة", "status"), Column("ملاحظات", "notes")])
        lay.addWidget(self.shifts, 1)
        lay.addWidget(muted("الفرق محسوب بالعملة الأساسية بعد تحويل كل العملات بسعر الصرف الحالي."))

    def _open_shift(self) -> None:
        if OpenShiftDialog(self).exec():
            Toast.show_message(self, "تم فتح الوردية", "success")
            self.refresh_now()

    def _close_shift(self) -> None:
        if CloseShiftDialog(self).exec():
            Toast.show_message(self, "تم إغلاق الوردية", "success")
            self.refresh_now()

    @staticmethod
    def _balances_text(curs: dict, balances: dict | None) -> str:
        parts = []
        for code, amount in (balances or {}).items():
            c = curs.get(code)
            if c and amount:
                parts.append(fmt_money(amount, c.symbol, c.decimals))
        return " • ".join(parts) or "—"

    # ---------------- صرف العملات ----------------
    def _build_exchanges(self) -> None:
        lay = self._tab("صرف العملات", "money")
        bar = QHBoxLayout()
        bar.addWidget(button("عملية صرف جديدة", "plus", "primary", on_click=self._new_exchange))
        bar.addWidget(button("حذف", "trash", on_click=self._del_exchange))
        self.xc_from = date_edit(date.today().replace(day=1))
        self.xc_to = date_edit()
        for w in (QLabel("من"), self.xc_from, QLabel("إلى"), self.xc_to):
            bar.addWidget(w)
        bar.addWidget(button("عرض", "search", "soft", on_click=self.refresh_now))
        bar.addStretch(1)
        bar.addWidget(button("تصدير", "excel", on_click=lambda: export_table(self, self.xc, "صرف العملات")))
        lay.addLayout(bar)
        t = tokens()
        self.xc = DataTable([Column("التاريخ", "date", "datetime"), Column("العملية", "op", bold=True),
                             Column("المبلغ", "amount_text"), Column("السعر المطبق", "rate_used", "qty"),
                             Column("السعر المعتمد", "rate_official", "qty"), Column("المقابل", "counter_text"),
                             Column("ربح / خسارة", "profit", "money", bold=True,
                                    color=lambda r: t["danger"] if r["profit"] < 0 else (t["success"] if r["profit"] > 0 else None)),
                             Column("الزبون", "customer"), Column("البائع", "user")])
        lay.addWidget(self.xc, 1)
        self.xc_summary = QLabel()
        self.xc_summary.setStyleSheet("font-weight: bold;")
        lay.addWidget(self.xc_summary)

    def _new_exchange(self) -> None:
        from ftapp.ui.pages.pos_page import ExchangeDialog
        if ExchangeDialog(self).exec():
            self.refresh_now()

    def _del_exchange(self) -> None:
        r = self.xc.current_row()
        if r and confirm(self, "حذف عملية الصرف؟ ستُلغى حركتها من الصندوق.", danger=True):
            with ctx.session() as (s, u):
                cash_service.delete_exchange(s, u, r["id"])
            self.refresh_now()

    # ---------------- العمولات ----------------
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

    def refresh(self) -> None:
        title = self.tabs.tabText(self.tabs.currentIndex())
        with ctx.session() as (s, u):
            if title == "المصاريف":
                exps = finance_service.list_expenses(s, self.ex_from.date().toPython(), self.ex_to.date().toPython())
                self.expenses.set_rows([{"id": e.id, "date": e.expense_date, "cat": e.category.name if e.category else "",
                                         "desc": e.description, "amount": e.amount, "cash": e.paid_from_cash} for e in exps])
                self.ex_summary.setText(f"الإجمالي: {currency_service.format_amount(s, sum(e.amount for e in exps))}")
            elif title == "الرواتب والسلف":
                self.emps.set_rows([{"id": r["employee"].id, "name": r["employee"].name, "period": r["period"],
                                     "salary": r["salary"], "last": r["last_paid"], "advances": r["advances"],
                                     "status": "على رأس العمل" if r["employee"].is_active else "موقوف"}
                                    for r in payroll_service.summary(s)])
            elif title == "الصندوق والورديات":
                curs = {c.code: c for c in currency_service.list_currencies(s)}
                base = currency_service.base(s).code
                uid = None if ctx.can("reports.view") else ctx.user_id
                rows = []
                for sh in finance_service.list_shifts(s, uid):
                    opening = sh.opening_balances or ({base: sh.opening_cash} if sh.opening_cash else {})
                    if sh.status == "closed":
                        expected = sh.expected_balances or {base: sh.expected_cash}
                        actual = sh.actual_balances or {base: sh.actual_cash}
                    else:
                        expected = {c: b["expected"] for c, b in finance_service.shift_summary(s, sh)["by_currency"].items()}
                        actual = None
                    rows.append({"user": sh.user.display_name, "opened": sh.opened_at, "closed": sh.closed_at,
                                 "opening_text": self._balances_text(curs, opening),
                                 "expected_text": self._balances_text(curs, expected),
                                 "actual_text": self._balances_text(curs, actual) if actual is not None else "",
                                 "diff": sh.difference if sh.status == "closed" else None,
                                 "status": "مغلقة" if sh.status == "closed" else "مفتوحة", "notes": sh.notes})
                self.shifts.set_rows(rows)
            elif title == "صرف العملات":
                curs = {c.code: c for c in currency_service.list_currencies(s)}
                exs = cash_service.list_exchanges(s, self.xc_from.date().toPython(), self.xc_to.date().toPython())
                rows = []
                for e in exs:
                    c, b = curs.get(e.currency_code), curs.get(e.counter_code)
                    rows.append({"id": e.id, "date": e.created_at,
                                 "op": f"{'بيع' if e.direction == 'sell' else 'شراء'} {c.name if c else e.currency_code}",
                                 "amount_text": fmt_money(e.amount, c.symbol if c else "", c.decimals if c else 2),
                                 "rate_used": e.rate_used, "rate_official": e.rate_official,
                                 "counter_text": fmt_money(e.counter_amount, b.symbol if b else "", b.decimals if b else 0),
                                 "profit": e.profit, "customer": e.customer_name,
                                 "user": e.user.display_name if e.user else ""})
                self.xc.set_rows(rows)
                net = sum(e.profit for e in exs)
                gains = sum(e.profit for e in exs if e.profit > 0)
                losses = -sum(e.profit for e in exs if e.profit < 0)
                f = lambda v: currency_service.format_amount(s, v)  # noqa: E731
                self.xc_summary.setText(f"عدد العمليات: {len(exs)} • أرباح: {f(gains)} • خسائر: {f(losses)} • "
                                        f"الصافي: {f(net)} {'(ربح)' if net > 0 else '(خسارة)' if net < 0 else ''}")
            elif title == "عمولات البائعين":
                self.comm.set_rows([{**c, "user": c["user"].display_name}
                                    for c in finance_service.commissions(s, self.cm_from.date().toPython(),
                                                                         self.cm_to.date().toPython())])
        if title == "الرواتب والسلف":
            self._load_tx()

    def open_item(self, payload) -> None:
        if isinstance(payload, dict) and payload.get("tab"):
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == payload["tab"]:
                    self.tabs.setCurrentIndex(i)
