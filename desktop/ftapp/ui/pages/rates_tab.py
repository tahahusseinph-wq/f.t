"""تبويب أسعار الصرف في الإعدادات: سعر كل عملة بالليرة السورية، تعديل سريع، وتاريخ التغيّر."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget)

from ftapp.services import catalog_service, currency_service
from ftapp.services.errors import ServiceError
from ftapp.ui.context import ctx
from ftapp.ui.widgets.charts import SalesChart
from ftapp.ui.widgets.common import Card, Toast, button, confirm, error, muted
from ftapp.ui.widgets.forms import money_spin


class RatesTab(QWidget):
    """كل العملات المفعّلة (ليرة سورية، دولار، يورو، ليرة تركية) وسعر الوحدة منها بالعملة الأساسية."""

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        card = Card("أسعار الصرف", icon_name="money")
        self.base_label = QLabel()
        self.base_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        card.add(self.base_label)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(10)
        card.body.addLayout(self.grid)
        self.reprice = QCheckBox("تحديث أسعار المنتجات (التكلفة والبيع) بنفس نسبة تغيّر سعر الدولار")
        self.reprice.setToolTip("مفيد إذا كانت بضاعتك مسعّرة على الدولار: يرفع أو يخفض أسعار الليرة تلقائياً")
        card.add(self.reprice)
        row = QHBoxLayout()
        row.addWidget(button("حفظ أسعار الصرف", "check", "primary", on_click=self._save))
        row.addWidget(button("إعادة تحميل", "refresh", on_click=self.refresh))
        row.addStretch(1)
        card.body.addLayout(row)
        card.add(muted("كل المبالغ محفوظة بالليرة السورية. سعر الصرف يُستخدم عند البيع بعملة أخرى، "
                       "وفي صرف العملات بنقطة البيع (لحساب الربح أو الخسارة)، وفي سطر «ما يعادل» على الفاتورة."))
        lay.addWidget(card)

        hist = Card("تاريخ سعر الصرف", icon_name="chart")
        self.chart = SalesChart()
        self.chart.setMinimumHeight(240)
        hist.add(self.chart, 1)
        lay.addWidget(hist, 1)
        self.spins: dict[str, QDoubleSpinBox] = {}
        self.old: dict[str, float] = {}

    def refresh(self) -> None:
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.spins.clear()
        with ctx.session() as (s, _):
            base = currency_service.base(s)
            self.base_symbol = base.symbol
            self.base_label.setText(f"العملة الأساسية: {base.name} ({base.symbol}) — كل الأسعار أدناه بـ{base.name}")
            rows = [(c.code, c.name, c.symbol, currency_service.nice(currency_service.unit_value(c)),
                     (currency_service.rate_history(s, c.code) or [None])[-1])
                    for c in currency_service.list_currencies(s) if not c.is_base]
        for i, (code, name, symbol, unit, last) in enumerate(rows):
            title = QLabel(f"1 {name} ({symbol})")
            title.setStyleSheet("font-weight: bold;")
            spin = money_spin(10**9, 2, self.base_symbol)
            spin.setValue(unit)
            spin.setMinimumWidth(200)
            self.spins[code] = spin
            self.old[code] = unit
            when = muted(f"آخر تعديل: {last.changed_at:%Y-%m-%d %H:%M}" if last else "", wrap=False)
            chart_btn = button("", "chart", on_click=lambda _=False, c=code: self._chart(c), tooltip="عرض التاريخ")
            self.grid.addWidget(title, i, 0)
            self.grid.addWidget(QLabel("="), i, 1, Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(spin, i, 2)
            self.grid.addWidget(when, i, 3)
            self.grid.addWidget(chart_btn, i, 4)
        self.grid.setColumnStretch(3, 1)
        if rows:
            self._chart("USD" if "USD" in self.spins else rows[0][0])

    def _chart(self, code: str) -> None:
        with ctx.session() as (s, _):
            hist = currency_service.rate_history(s, code)
            points = [(h.changed_at.strftime("%m-%d"), currency_service.nice(1 / h.rate)) for h in hist if h.rate]
        if points:
            self.chart.set_data([p[0] for p in points], [p[1] for p in points])

    def _save(self) -> None:
        values = {code: spin.value() for code, spin in self.spins.items()}
        changed = [c for c, v in values.items() if abs(v - self.old.get(c, 0)) > 1e-9]
        if not changed:
            Toast.show_message(self, "لم يتغير أي سعر", "info")
            return
        percent = None
        if self.reprice.isChecked() and "USD" in changed and self.old.get("USD"):
            percent = round((values["USD"] / self.old["USD"] - 1) * 100, 4)
            if not confirm(self, f"سيتم تعديل أسعار كل المنتجات بنسبة {percent:+.2f}% (مثل تغيّر الدولار). متابعة؟"):
                return
        try:
            with ctx.session() as (s, u):
                currency_service.set_unit_values(s, u, values)
                count = catalog_service.bulk_price_apply(s, u, catalog_service.BulkPriceFilter(), percent) if percent else 0
        except ServiceError as exc:
            error(self, str(exc))
            return
        msg = "تم حفظ أسعار الصرف"
        if count:
            msg += f" وتحديث أسعار {count} منتج"
        Toast.show_message(self, msg, "success")
        ctx.signals.products_changed.emit()
        self.refresh()
