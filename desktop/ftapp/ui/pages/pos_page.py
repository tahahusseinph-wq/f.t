"""نقطة البيع: سلة، زبون، شرائح أسعار، عروض، دفع نقدي/آجل، وفاتورة فورية."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from sqlalchemy import select

from ftapp.core.utils import fmt_money, fmt_qty
from ftapp.models import Currency, Customer, Product
from ftapp.services import (cash_service, catalog_service, currency_service, finance_service, sales_service)
from ftapp.services.errors import ServiceError
from ftapp.ui import icons
from ftapp.ui.context import ctx
from ftapp.ui.pages.base import Page
from ftapp.ui.theme import compact, tokens
from ftapp.ui.widgets.common import Card, Toast, button, confirm, error, fill_combo, muted
from ftapp.ui.widgets.forms import FormDialog, money_spin


class CustomerQuickDialog(FormDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent, "زبون جديد")
        with ctx.session() as (s, _):
            tiers = [(t.name, t.id) for t in catalog_service.list_tiers(s)]
        self.name = self.line("الاسم *")
        self.phone = self.line("الهاتف")
        self.phone.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.address = self.line("العنوان")
        self.tier = self.combo("شريحة السعر", tiers)
        self.on_save = self._do
        self.finish_layout()

    def _do(self):
        with ctx.session() as (s, _):
            return sales_service.save_customer(s, self.name.text(), self.phone.text(), self.address.text().strip(), tier_id=self.tier.currentData()).id


class ExchangeDialog(FormDialog):
    """صرف عملات للزبون: بيع أو شراء دولار/يورو/ليرة تركية مقابل الليرة السورية.
    يحدد من أين ينقص الصندوق وإلى أين يزيد، ويحسب الربح أو الخسارة مقارنة بسعر الصرف المعتمد."""

    def __init__(self, parent) -> None:
        super().__init__(parent, "صرف عملات", 500, "تنفيذ عملية الصرف")
        with ctx.session() as (s, _):
            base = currency_service.base(s)
            self.base = (base.code, base.name, base.symbol, base.decimals)
            self.curs = {c.code: (c.name, c.symbol, c.decimals, currency_service.nice(currency_service.unit_value(c)))
                         for c in currency_service.list_currencies(s) if not c.is_base}
        self.direction = self.combo("نوع العملية", [("بيع عملة للزبون (أعطيه دولار وآخذ ليرة)", "sell"),
                                                    ("شراء عملة من الزبون (آخذ دولار وأعطيه ليرة)", "buy")])
        self.currency = self.combo("العملة", [(f"{v[0]} ({v[1]})", k) for k, v in self.curs.items()],
                                   "USD" if "USD" in self.curs else None)
        self.amount = money_spin(1e12, 2)
        self.row("المبلغ", self.amount)
        self.rate = money_spin(1e9, 2, self.base[2])
        self.official = muted("")
        self.row("سعر الصرف المطبق", self.rate)
        self.form.addRow("", self.official)
        self.customer = self.line("اسم الزبون (اختياري)")
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setStyleSheet("font-size: 11pt;")
        self.form.addRow(self.result)
        self.profit = QLabel()
        self.profit.setObjectName("bigTotal")
        self.form.addRow(self.profit)
        self.direction.currentIndexChanged.connect(self._update)
        self.currency.currentIndexChanged.connect(self._currency_changed)
        self.amount.valueChanged.connect(self._update)
        self.rate.valueChanged.connect(self._update)
        self._currency_changed()
        self.on_save = self._do
        self.finish_layout()

    def _currency_changed(self) -> None:
        code = self.currency.currentData()
        if code in self.curs:
            name, symbol, dec, unit = self.curs[code]
            self.amount.setSuffix(f" {symbol}")
            self.rate.setValue(unit)
            self.official.setText(f"السعر المعتمد في الإعدادات: 1 {symbol} = {unit:,.2f} {self.base[2]}")
        self._update()

    def _update(self) -> None:
        code = self.currency.currentData()
        if code not in self.curs:
            return
        name, symbol, dec, official = self.curs[code]
        amount, rate = self.amount.value(), self.rate.value()
        counter = round(amount * rate, self.base[3])
        sell = self.direction.currentData() == "sell"
        b = self.base[2]
        if sell:
            self.result.setText(f"الزبون يدفع: <b>{counter:,.{self.base[3]}f} {b}</b><br>"
                                f"وتعطيه: <b>{amount:,.2f} {symbol}</b><br>"
                                f"الصندوق: {name} ينقص {amount:,.2f} • {self.base[1]} تزيد {counter:,.{self.base[3]}f}")
            profit = amount * (rate - official)
        else:
            self.result.setText(f"الزبون يعطيك: <b>{amount:,.2f} {symbol}</b><br>"
                                f"وتدفع له: <b>{counter:,.{self.base[3]}f} {b}</b><br>"
                                f"الصندوق: {name} يزيد {amount:,.2f} • {self.base[1]} تنقص {counter:,.{self.base[3]}f}")
            profit = amount * (official - rate)
        t = tokens()
        if abs(profit) < 0.5:
            self.profit.setText("بسعر الصرف المعتمد (بدون ربح أو خسارة)")
            self.profit.setStyleSheet("")
        else:
            word = "ربح" if profit > 0 else "خسارة"
            self.profit.setText(f"{word}: {abs(profit):,.0f} {b}")
            self.profit.setStyleSheet(f"color: {t['success'] if profit > 0 else t['danger']};")

    def _do(self):
        with ctx.session() as (s, u):
            ex = cash_service.create_exchange(s, u, self.direction.currentData(), self.currency.currentData(),
                                              self.amount.value(), self.rate.value(), self.customer.text())
            return ex.id


class POSPage(Page):
    title = "نقطة البيع"
    subtitle = "كل عملية بيع تُصدر فاتورة فوراً • F2 للبحث • F9 لإتمام البيع وإصدار الفاتورة • Delete لحذف سطر"
    COLS = ["المنتج", "الكمية", "السعر", "الخصم", "الإجمالي", ""]

    def __init__(self) -> None:
        super().__init__()
        self.cart: list[dict] = []
        self.can_discount = ctx.can("sales.discount")
        self.shift_label = QLabel()
        self.actions.addWidget(self.shift_label)
        self.shift_btn = button("فتح وردية", "clock", on_click=self._toggle_shift)
        self.actions.addWidget(self.shift_btn)
        self.exchange_btn = button("صرف عملات", "money", on_click=self._exchange,
                                   tooltip="بيع أو شراء دولار/يورو/ليرة تركية للزبون مع حساب الربح أو الخسارة")
        self.actions.addWidget(self.exchange_btn)

        body = QHBoxLayout()
        body.setSpacing(14)
        # ===== العمود الرئيسي: البحث والسلة =====
        left = QVBoxLayout()
        left.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("searchBox")
        self.search.setMinimumHeight(46)
        self.search.setStyleSheet("font-size: 12pt;")
        self.search.setPlaceholderText("امسح الباركود أو اكتب الكود/الاسم ثم Enter  (F2)")
        self.search.addAction(icons.icon("barcode"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.returnPressed.connect(self._search_enter)
        self.search.textChanged.connect(lambda: self._suggest_timer.start(200))
        left.addWidget(self.search)
        self.suggest = QListWidget()
        self.suggest.setMaximumHeight(170)
        self.suggest.hide()
        self.suggest.itemActivated.connect(self._pick_suggestion)
        self.suggest.itemClicked.connect(self._pick_suggestion)
        left.addWidget(self.suggest)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i, w in (((1, 90), (2, 100), (3, 80), (4, 100), (5, 40)) if compact() else ((1, 110), (2, 120), (3, 100), (4, 130), (5, 44))):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, w)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40 if compact() else 48)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        left.addWidget(self.table, 1)
        self.empty_hint = muted("السلة فارغة — ابدأ بمسح باركود أو البحث عن منتج")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.empty_hint)
        lw = QWidget()
        lw.setLayout(left)
        body.addWidget(lw, 3)

        # ===== لوحة الدفع =====
        panel = Card("بيع جديد — الزبون والفاتورة", icon_name="wallet")
        panel.setMinimumWidth(300 if compact() else 380)
        panel.setMaximumWidth(440)
        # --- الزبون: من القائمة أو إدخال تفاصيل زبون جديد ---
        mrow = QHBoxLayout()
        self.cust_mode = QButtonGroup(self)
        self.m_existing = QRadioButton("زبون من القائمة")
        self.m_details = QRadioButton("تفاصيل زبون جديد")
        self.m_existing.setChecked(True)
        for i, rb in enumerate((self.m_existing, self.m_details)):
            self.cust_mode.addButton(rb, i)
            mrow.addWidget(rb)
        mrow.addStretch(1)
        self.m_existing.toggled.connect(self._cust_mode_changed)
        panel.body.addLayout(mrow)
        self.existing_box = QWidget()
        ex = QVBoxLayout(self.existing_box)
        ex.setContentsMargins(0, 0, 0, 0)
        crow = QHBoxLayout()
        self.customer = QComboBox()
        self.customer.setEditable(True)
        self.customer.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.customer.currentIndexChanged.connect(self._customer_changed)
        crow.addWidget(self.customer, 1)
        crow.addWidget(button("", "plus", on_click=self._new_customer, tooltip="زبون جديد"))
        ex.addLayout(crow)
        self.customer_info = muted("")
        self.customer_info.setWordWrap(True)
        ex.addWidget(self.customer_info)
        panel.add(self.existing_box)
        self.details_box = QWidget()
        dg = QGridLayout(self.details_box)
        dg.setContentsMargins(0, 0, 0, 0)
        self.c_name = QLineEdit()
        self.c_name.setPlaceholderText("اسم الزبون أو الجهة")
        self.c_phone = QLineEdit()
        self.c_phone.setPlaceholderText("09xxxxxxxx")
        self.c_phone.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.c_address = QLineEdit()
        self.c_address.setPlaceholderText("المدينة، الشارع ...")
        self.c_save = QCheckBox("حفظ الزبون في قائمة الزبائن")
        self.c_save.setChecked(True)
        for r, (label, w) in enumerate((("الاسم", self.c_name), ("الهاتف", self.c_phone), ("العنوان", self.c_address))):
            dg.addWidget(QLabel(label), r, 0)
            dg.addWidget(w, r, 1)
        dg.addWidget(self.c_save, 3, 0, 1, 2)
        self.details_box.hide()
        panel.add(self.details_box)
        grid = QGridLayout()
        self.tier = QComboBox()
        self.tier.currentIndexChanged.connect(self._recalc)
        self.currency = QComboBox()
        self.currency.currentIndexChanged.connect(self._recalc)
        grid.addWidget(QLabel("شريحة السعر"), 0, 0)
        grid.addWidget(self.tier, 0, 1)
        self.rate_btn = button("", "edit", on_click=self._edit_rate, tooltip="تعديل سعر صرف العملة")
        self.rate_btn.setEnabled(ctx.can("settings.manage"))
        cur_row = QHBoxLayout()
        cur_row.addWidget(self.currency, 1)
        cur_row.addWidget(self.rate_btn)
        grid.addWidget(QLabel("العملة"), 1, 0)
        grid.addLayout(cur_row, 1, 1)
        self.l_rate = muted("")
        grid.addWidget(self.l_rate, 2, 0, 1, 2)
        panel.body.addLayout(grid)
        panel.add(self._sep())

        totals = QGridLayout()
        totals.setVerticalSpacing(6)
        self.l_sub = QLabel()
        self.discount = money_spin()
        self.discount.setEnabled(self.can_discount)
        self.discount.valueChanged.connect(self._recalc)
        totals.addWidget(QLabel("المجموع"), 0, 0)
        totals.addWidget(self.l_sub, 0, 1, Qt.AlignmentFlag.AlignLeft)
        totals.addWidget(QLabel("خصم على الفاتورة"), 1, 0)
        totals.addWidget(self.discount, 1, 1)
        panel.body.addLayout(totals)
        self.l_total = QLabel()
        self.l_total.setObjectName("bigTotal")
        self.l_total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel.add(self.l_total)
        self.l_alt = muted("")
        self.l_alt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel.add(self.l_alt)
        panel.add(self._sep())

        pm = QGridLayout()
        pm.setHorizontalSpacing(10)
        self.pay_group = QButtonGroup(self)
        self.p_cash = QRadioButton("نقدي")
        self.p_sham = QRadioButton("شام كاش")
        self.p_credit = QRadioButton("آجل (دين)")
        self.p_partial = QRadioButton("دفع جزئي")
        self.p_cash.setChecked(True)
        for i, rb in enumerate((self.p_cash, self.p_sham, self.p_credit, self.p_partial)):
            self.pay_group.addButton(rb, i)
            pm.addWidget(rb, i // 2, i % 2)
            rb.toggled.connect(self._pay_mode)
        panel.body.addLayout(pm)
        prow = QGridLayout()
        self.paid = money_spin()
        self.paid.valueChanged.connect(self._update_change)
        self.l_change = QLabel()
        self.l_change.setStyleSheet("font-weight: bold;")
        prow.addWidget(QLabel("المبلغ المستلم"), 0, 0)
        prow.addWidget(self.paid, 0, 1)
        prow.addWidget(self.l_change, 1, 0, 1, 2)
        panel.body.addLayout(prow)
        self.sham_ref = QLineEdit()
        self.sham_ref.setPlaceholderText("رقم عملية شام كاش (اختياري)")
        self.sham_ref.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.sham_ref.hide()
        panel.add(self.sham_ref)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("ملاحظات على الفاتورة")
        panel.add(self.notes)
        panel.body.addStretch(1)
        self.pay_btn = button("إتمام البيع وإصدار الفاتورة  (F9)", "check", "primary", on_click=self._checkout)
        self.pay_btn.setMinimumHeight(52)
        self.pay_btn.setStyleSheet("font-size: 13pt;")
        panel.add(self.pay_btn)
        brow = QHBoxLayout()
        brow.addWidget(button("عرض سعر", "receipt", on_click=self._quotation))
        brow.addWidget(button("تفريغ السلة", "trash", on_click=self._clear))
        panel.body.addLayout(brow)
        body.addWidget(panel, 2)
        self.root.addLayout(body, 1)

        self._suggest_timer = QTimer(self)
        self._suggest_timer.setSingleShot(True)
        self._suggest_timer.timeout.connect(self._update_suggestions)
        QShortcut(QKeySequence("F9"), self, activated=self._checkout)
        QShortcut(QKeySequence("F2"), self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))
        QShortcut(QKeySequence("Delete"), self.table, activated=self._remove_selected)
        ctx.signals.products_changed.connect(self._recalc)
        self._load_refs()

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"color: {tokens()['border']};")
        return f

    # ---------------- المراجع ----------------
    def _load_refs(self) -> None:
        with ctx.session() as (s, u):
            customers = [(f"{c.name}  {c.phone}".strip(), c.id) for c in sales_service.list_customers(s)]
            tiers = [(t.name, t.id) for t in catalog_service.list_tiers(s)]
            curs = [(f"{c.name} ({c.symbol})", c.code) for c in currency_service.list_currencies(s)]
            display = currency_service.display(s).code
        fill_combo(self.customer, customers, self.customer.currentData(), placeholder="زبون نقدي")
        fill_combo(self.tier, tiers, self.tier.currentData())
        fill_combo(self.currency, curs, self.currency.currentData() or display)
        self._update_shift()

    def refresh(self) -> None:
        self._load_refs()
        self._recalc()
        self.search.setFocus()

    def _update_shift(self) -> None:
        with ctx.session() as (s, u):
            shift = finance_service.current_shift(s, u)
            text = f"وردية مفتوحة منذ {shift.opened_at:%H:%M}" if shift else "لا توجد وردية مفتوحة"
        self.shift_label.setText(text)
        self.shift_label.setObjectName("badgeSuccess" if shift else "badgeWarning")
        self.shift_label.style().unpolish(self.shift_label)
        self.shift_label.style().polish(self.shift_label)
        self.shift_btn.setText("إغلاق الوردية" if shift else "فتح وردية")
        self._shift_open = shift is not None

    def _toggle_shift(self) -> None:
        from ftapp.ui.pages.finance_page import CloseShiftDialog
        from ftapp.ui.pages.finance_page import OpenShiftDialog
        if self._shift_open:
            CloseShiftDialog(self).exec()
        else:
            OpenShiftDialog(self).exec()
        self._update_shift()

    def _exchange(self) -> None:
        if not self._shift_open and not confirm(self, "لا توجد وردية مفتوحة. تنفيذ الصرف بدون وردية؟\n"
                                                    "(لن تُحتسب العملية ضمن صندوق أي وردية)"):
            return
        if ExchangeDialog(self).exec():
            Toast.show_message(self, "تم تنفيذ عملية الصرف وتحديث الصندوق", "success")

    # ---------------- البحث ----------------
    def _update_suggestions(self) -> None:
        text = self.search.text().strip()
        self.suggest.clear()
        if len(text) < 2:
            self.suggest.hide()
            return
        with ctx.session() as (s, _):
            items, _ = catalog_service.search_products(s, text, limit=12)
            for p in items:
                price, _promo = catalog_service.final_price(s, p, self.tier.currentData())
                it = QListWidgetItem(f"{p.name}  —  {p.code}  •  {currency_service.format_amount(s, price)}  •  المتوفر {fmt_qty(p.quantity)}")
                it.setData(Qt.ItemDataRole.UserRole, p.id)
                if p.quantity <= 0:
                    it.setForeground(Qt.GlobalColor.red)
                self.suggest.addItem(it)
        self.suggest.setVisible(self.suggest.count() > 0)

    def _pick_suggestion(self, item: QListWidgetItem) -> None:
        self.add_product(item.data(Qt.ItemDataRole.UserRole))

    def _search_enter(self) -> None:
        text = self.search.text().strip()
        if not text:
            return
        qty = 1.0
        if "*" in text:  # صيغة 3*CODE لإضافة كمية
            left, _, right = text.partition("*")
            try:
                qty, text = float(left), right.strip()
            except ValueError:
                pass
        with ctx.session() as (s, _):
            p = catalog_service.find_by_code(s, text)
            pid = p.id if p else None
        if pid is None and self.suggest.count():
            pid = self.suggest.item(0).data(Qt.ItemDataRole.UserRole)
        if pid is None:
            Toast.show_message(self, f"لا يوجد منتج بالكود «{text}»", "warning")
            self.search.selectAll()
            return
        self.add_product(pid, qty)

    def add_product(self, pid: int, qty: float = 1.0) -> None:
        for line in self.cart:
            if line["pid"] == pid:
                line["qty"] += qty
                break
        else:
            with ctx.session() as (s, _):
                p = s.get(Product, pid)
                if not p.is_active:
                    Toast.show_message(self, "هذا المنتج موقوف عن البيع", "warning")
                    return
                self.cart.append({"pid": p.id, "name": p.name, "code": p.code, "unit": p.unit, "qty": qty,
                                  "price": None, "discount": 0.0})
        self.search.clear()
        self.suggest.hide()
        self._recalc()
        self.search.setFocus()

    # ---------------- الحساب ----------------
    def _cur(self, s) -> Currency:
        return s.get(Currency, self.currency.currentData()) or currency_service.display(s)

    def _request(self, s, customer_id: int | None = None) -> sales_service.SaleRequest:
        """customer_id: زبون حُفظ للتو من «تفاصيل زبون جديد» (عند الإتمام فقط)."""
        cur = self._cur(s)
        name = phone = address = ""
        if self.m_details.isChecked():
            name, phone, address = self.c_name.text().strip(), self.c_phone.text().strip(), self.c_address.text().strip()
        else:
            customer_id = self.customer.currentData()
        lines = [sales_service.CartLine(l["pid"], l["qty"],
                                        currency_service.to_base(l["price"], cur) if l["price"] is not None else None,
                                        currency_service.to_base(l["discount"], cur)) for l in self.cart]
        method = ("cash" if self.p_cash.isChecked() else "shamcash" if self.p_sham.isChecked()
                  else "credit" if self.p_credit.isChecked() else "partial")
        full = method in sales_service.PAID_IN_FULL
        return sales_service.SaleRequest(
            lines=lines, customer_id=customer_id, customer_name=name, customer_phone=phone,
            customer_address=address, tier_id=self.tier.currentData(),
            discount=currency_service.to_base(self.discount.value(), cur), payment_method=method,
            paid=None if full else currency_service.to_base(self.paid.value(), cur),
            currency_code=cur.code, notes=self._notes(method))

    def _notes(self, method: str) -> str:
        notes = self.notes.text().strip()
        ref = self.sham_ref.text().strip()
        if method == "shamcash" and ref:
            notes = f"{notes}\nرقم عملية شام كاش: {ref}".strip()
        return notes

    def _recalc(self) -> None:
        self.empty_hint.setVisible(not self.cart)
        with ctx.session() as (s, _):
            cur = self._cur(s)
            conv = lambda v: currency_service.convert(v, cur)  # noqa: E731
            try:
                calc = sales_service.compute_totals(s, self._request(s))
                self.l_sub.setStyleSheet("")
            except ServiceError as exc:
                Toast.show_message(self, str(exc), "warning")
                return
            stock = {p.id: p.quantity for p in [s.get(Product, l["pid"]) for l in self.cart]}
            base = currency_service.base(s)
            rate_text = f"سعر الصرف: {currency_service.rate_label(s, cur)}" if cur.code != base.code else ""
        self.table.setRowCount(len(self.cart))
        t = tokens()
        for r, (line, c) in enumerate(zip(self.cart, calc["lines"])):
            name = QTableWidgetItem(f"{line['name']}\n{line['code']}" + (f"  🏷 {c['promotion'].name}" if c["promotion"] else ""))
            if stock.get(line["pid"], 0) < line["qty"]:
                name.setForeground(Qt.GlobalColor.red)
                name.setToolTip(f"المتوفر {fmt_qty(stock.get(line['pid'], 0))} فقط")
            self.table.setItem(r, 0, name)
            q = QDoubleSpinBox()
            q.setRange(0.001, 1e9)
            q.setDecimals(3 if line["unit"] in ("متر", "كيلو", "لتر") else 0)
            q.setValue(line["qty"])
            q.setAlignment(Qt.AlignmentFlag.AlignCenter)
            q.valueChanged.connect(lambda v, i=r: self._set(i, "qty", v))
            self.table.setCellWidget(r, 1, q)
            price = money_spin(decimals=cur.decimals)
            price.setValue(conv(c["unit_price"]))
            price.setEnabled(self.can_discount)
            price.editingFinished.connect(lambda i=r, w=price: self._set(i, "price", w.value()))
            self.table.setCellWidget(r, 2, price)
            disc = money_spin(decimals=cur.decimals)
            disc.setValue(conv(c["discount"]))
            disc.setEnabled(self.can_discount)
            disc.editingFinished.connect(lambda i=r, w=disc: self._set(i, "discount", w.value()))
            self.table.setCellWidget(r, 3, disc)
            tot = QTableWidgetItem(fmt_money(conv(c["line_total"]), cur.symbol, cur.decimals))
            tot.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 4, tot)
            rm = QPushButton()
            rm.setProperty("variant", "ghost")
            rm.setIcon(icons.icon("x", t["danger"]))
            rm.clicked.connect(lambda _=False, i=r: self._remove(i))
            self.table.setCellWidget(r, 5, rm)
        f = lambda v: fmt_money(conv(v), cur.symbol, cur.decimals)  # noqa: E731
        self.l_sub.setText(f(calc["subtotal"]))
        self.total_base = calc["total"]
        self.total_display = conv(calc["total"])
        self.l_total.setText(f(calc["total"]))
        self.l_alt.setText(fmt_money(calc["total"], base.symbol, base.decimals) if cur.code != base.code else "")
        self.l_rate.setText(rate_text)
        self.rate_btn.setVisible(cur.code != base.code)
        self.pay_btn.setEnabled(bool(self.cart))
        self._update_change()

    def _set(self, i: int, key: str, value: float) -> None:
        if i >= len(self.cart):
            return
        self.cart[i][key] = value
        QTimer.singleShot(0, self._recalc)

    def _remove(self, i: int) -> None:
        if i < len(self.cart):
            self.cart.pop(i)
            self._recalc()

    def _remove_selected(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self._remove(r)

    def _pay_mode(self) -> None:
        if self.p_credit.isChecked() or self.p_sham.isChecked():
            self.paid.setValue(0)
        self.paid.setEnabled(not (self.p_credit.isChecked() or self.p_sham.isChecked()))
        self.sham_ref.setVisible(self.p_sham.isChecked())
        self._update_change()

    def _update_change(self) -> None:
        total = getattr(self, "total_display", 0)
        paid = self.paid.value()
        with ctx.session() as (s, _):
            cur = self._cur(s)
        if self.p_cash.isChecked():
            change = paid - total
            if paid and change >= 0:
                self.l_change.setText(f"الباقي للزبون: {fmt_money(change, cur.symbol, cur.decimals)}")
                self.l_change.setStyleSheet(f"color: {tokens()['success']}; font-weight: bold;")
            elif paid:
                self.l_change.setText(f"المبلغ أقل من الإجمالي بـ {fmt_money(-change, cur.symbol, cur.decimals)}")
                self.l_change.setStyleSheet(f"color: {tokens()['danger']}; font-weight: bold;")
            else:
                self.l_change.setText("")
        elif self.p_sham.isChecked():
            self.l_change.setText("يُسدَّد كامل المبلغ عبر شام كاش (لا يدخل صندوق النقد)")
            self.l_change.setStyleSheet(f"color: {tokens()['primary']}; font-weight: bold;")
        else:
            rest = max(0.0, total - (paid if self.p_partial.isChecked() else 0))
            self.l_change.setText(f"يُسجل ديناً على الزبون: {fmt_money(rest, cur.symbol, cur.decimals)}")
            self.l_change.setStyleSheet(f"color: {tokens()['warning']}; font-weight: bold;")

    def _edit_rate(self) -> None:
        """تعديل سعر صرف العملة المختارة مباشرة من شاشة البيع (يُحفظ في سجل أسعار الصرف)."""
        with ctx.session() as (s, _):
            cur = self._cur(s)
            base = currency_service.base(s)
            if cur.is_base:
                return
            code, name, symbol, rate = cur.code, cur.name, cur.symbol, cur.rate
            base_code = base.code
        unit = currency_service.nice(1 / rate)
        value, ok = QInputDialog.getDouble(self, "سعر الصرف", f"كم تساوي 1 {name} ({symbol}) بالعملة الأساسية ({base_code})؟",
                                           unit, 0.0001, 1e12, 2)
        if not ok or abs(value - unit) < 1e-9:
            return
        try:
            with ctx.session() as (s, u):
                currency_service.set_unit_values(s, u, {code: value})
        except ServiceError as exc:
            error(self, str(exc))
            return
        Toast.show_message(self, f"تم تعديل سعر الصرف: 1 {symbol} = {value:,.2f} {base_code}", "success")
        self._recalc()

    def _customer_changed(self) -> None:
        cid = self.customer.currentData()
        if cid:
            with ctx.session() as (s, _):
                c = s.get(Customer, cid)
                info = f"الهاتف: {c.phone or '—'}"
                if c.address:
                    info += f" • العنوان: {c.address}"
                if c.balance:
                    info += f" • الرصيد المستحق: {currency_service.format_amount(s, c.balance)}"
                tier = c.tier_id
            self.customer_info.setText(info)
            if tier:
                self.tier.setCurrentIndex(max(0, self.tier.findData(tier)))
        else:
            self.customer_info.setText("")
            self.tier.setCurrentIndex(0)
        self._recalc()

    def _cust_mode_changed(self) -> None:
        existing = self.m_existing.isChecked()
        self.existing_box.setVisible(existing)
        self.details_box.setVisible(not existing)
        if existing:
            self._customer_changed()
        else:
            self.tier.setCurrentIndex(0)
            self.c_name.setFocus()
            self._recalc()

    def _save_typed_customer(self, s) -> int | None:
        """يحفظ تفاصيل الزبون المكتوبة (أو يجد زبوناً مسجلاً بنفس الهاتف) ويعيد رقمه."""
        name, phone = self.c_name.text().strip(), self.c_phone.text().strip()
        if phone:
            found = s.scalar(select(Customer).where(Customer.phone == phone))
            if found:
                if not found.address and self.c_address.text().strip():
                    found.address = self.c_address.text().strip()
                return found.id
        return sales_service.save_customer(s, name, phone, self.c_address.text().strip(),
                                           tier_id=self.tier.currentData()).id

    def _new_customer(self) -> None:
        dlg = CustomerQuickDialog(self)
        if dlg.exec():
            self._load_refs()
            self.customer.setCurrentIndex(max(0, self.customer.findData(dlg.result_value)))

    # ---------------- الإتمام ----------------
    def _checkout(self) -> None:
        if not self.cart:
            return
        if not self._shift_open and not confirm(self, "لا توجد وردية مفتوحة. المتابعة بدون وردية؟\n"
                                                    "(لن تُحتسب الفاتورة ضمن صندوق أي وردية)"):
            return
        if self.p_cash.isChecked() and self.paid.value() and self.paid.value() < self.total_display - 0.001:
            error(self, "المبلغ المستلم أقل من الإجمالي. اختر «دفع جزئي» أو صحّح المبلغ.")
            return
        typed = self.m_details.isChecked()
        has_details = typed and any(w.text().strip() for w in (self.c_name, self.c_phone, self.c_address))
        if has_details and not self.c_name.text().strip():
            error(self, "أدخل اسم الزبون أو امسح تفاصيله للبيع كزبون نقدي")
            self.c_name.setFocus()
            return
        on_credit = self.p_credit.isChecked() or self.p_partial.isChecked()
        if typed and on_credit and not (has_details and self.c_save.isChecked()):
            error(self, "البيع الآجل أو الجزئي يحتاج زبوناً مسجلاً: أدخل الاسم وفعّل «حفظ الزبون في قائمة الزبائن».")
            return
        try:
            with ctx.session() as (s, u):
                cid = None
                if has_details and self.c_save.isChecked():
                    cid = self._save_typed_customer(s)
                inv = sales_service.create_sale(s, u, self._request(s, cid))
                inv_id, number = inv.id, inv.number
        except ServiceError as exc:
            error(self, str(exc))
            return
        self._clear(ask=False)
        self._load_refs()
        Toast.show_message(self, f"تم البيع — فاتورة {number}", "success")
        from ftapp.ui.dialogs.invoice_preview import InvoicePreviewDialog
        InvoicePreviewDialog(self, inv_id).exec()
        self.search.setFocus()

    def _quotation(self) -> None:
        if not self.cart:
            return
        try:
            with ctx.session() as (s, u):
                q = sales_service.create_quotation(s, u, self._request(s))
                qid = q.id
        except ServiceError as exc:
            error(self, str(exc))
            return
        self._clear(ask=False)
        from ftapp.ui.dialogs.invoice_preview import InvoicePreviewDialog
        InvoicePreviewDialog(self, qid).exec()

    def _clear(self, ask: bool = True) -> None:
        if ask and self.cart and not confirm(self, "تفريغ السلة؟"):
            return
        self.cart.clear()
        self.discount.setValue(0)
        self.paid.setValue(0)
        self.notes.clear()
        self.sham_ref.clear()
        self.p_cash.setChecked(True)
        self.customer.setCurrentIndex(0)
        for w in (self.c_name, self.c_phone, self.c_address):
            w.clear()
        self.m_existing.setChecked(True)
        self._recalc()

    def open_item(self, payload) -> None:
        if isinstance(payload, dict) and payload.get("product_id"):
            self.add_product(payload["product_id"])
