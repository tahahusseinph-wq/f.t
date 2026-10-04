"""لوحة التحكم: مؤشرات، رسوم المبيعات، الأكثر مبيعاً، التنبيهات الهامة."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ftapp.services import currency_service, notification_service, report_service
from ftapp.ui import icons
from ftapp.ui.context import ctx
from ftapp.ui.pages.base import Page
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.charts import DonutChart, HBarChart, SalesChart
from ftapp.ui.widgets.common import Card, KpiCard, button, muted

PERIODS = [("today", "اليوم"), ("week", "7 أيام"), ("month", "هذا الشهر"), ("30days", "30 يوم"), ("year", "السنة")]


class DashboardPage(Page):
    title = "لوحة التحكم"
    subtitle = "نظرة سريعة على المبيعات والمخزون"

    def __init__(self) -> None:
        super().__init__()
        self.period = "month"
        group = QButtonGroup(self)
        for key, label in PERIODS:
            b = QPushButton(label)
            b.setProperty("variant", "chip")
            b.setCheckable(True)
            b.setChecked(key == self.period)
            b.clicked.connect(lambda _=False, k=key: self._set_period(k))
            group.addButton(b)
            self.actions.addWidget(b)
        self.actions.addWidget(button("تحديث", "refresh", on_click=self.refresh_now))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QVBoxLayout(body)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setSpacing(14)

        t = tokens()
        kpis = QGridLayout()
        kpis.setSpacing(14)
        self.k_sales = KpiCard("صافي المبيعات", "money", t["primary"])
        self.k_profit = KpiCard("صافي الربح", "chart", t["success"])
        self.k_invoices = KpiCard("عدد الفواتير", "receipt", "#7E57C2")
        self.k_stock = KpiCard("قيمة المخزون", "warehouse", "#00897B")
        self.k_avg = KpiCard("متوسط الفاتورة", "tag", "#F57C00")
        self.k_credit = KpiCard("مبيعات آجلة", "wallet", t["danger"])
        self.k_expenses = KpiCard("المصاريف", "minus", "#8D6E63")
        self.k_products = KpiCard("المنتجات الفعالة", "box", "#5C6BC0")
        cards = [self.k_sales, self.k_profit, self.k_invoices, self.k_stock, self.k_avg, self.k_credit,
                 self.k_expenses, self.k_products]
        if not ctx.can("products.view_cost"):
            cards = [c for c in cards if c not in (self.k_profit, self.k_stock, self.k_expenses)]
            for c in (self.k_profit, self.k_stock, self.k_expenses):
                c.hide()
        for i, card in enumerate(cards):
            kpis.addWidget(card, i // 4, i % 4)
        grid.addLayout(kpis)

        row1 = QHBoxLayout()
        row1.setSpacing(14)
        sales_card = Card("المبيعات والأرباح", icon_name="chart")
        self.sales_chart = SalesChart()
        self.sales_chart.setMinimumHeight(300)
        sales_card.add(self.sales_chart, 1)
        row1.addWidget(sales_card, 3)
        alerts_card = Card("التنبيهات الهامة", icon_name="alert")
        alerts_card.header.addWidget(button("عرض الكل", variant="ghost",
                                            on_click=lambda: ctx.signals.navigate.emit("notifications", None)))
        self.alerts = QListWidget()
        self.alerts.setStyleSheet("QListWidget { border: none; }")
        self.alerts.itemActivated.connect(self._open_alert)
        self.alerts.itemClicked.connect(self._open_alert)
        alerts_card.add(self.alerts, 1)
        alerts_card.setMinimumWidth(360)
        row1.addWidget(alerts_card, 2)
        grid.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(14)
        top_card = Card("الأكثر مبيعاً", icon_name="star")
        self.top_chart = HBarChart()
        self.top_chart.setMinimumHeight(300)
        top_card.add(self.top_chart, 1)
        row2.addWidget(top_card, 3)
        cat_card = Card("المبيعات حسب القسم", icon_name="layers")
        self.cat_chart = DonutChart()
        self.cat_chart.setMinimumHeight(300)
        cat_card.add(self.cat_chart, 1)
        row2.addWidget(cat_card, 2)
        grid.addLayout(row2)

        slow_card = Card("بضاعة راكدة واقتراحات الطلب", icon_name="clock")
        self.slow_label = muted("")
        slow_card.add(self.slow_label)
        grid.addWidget(slow_card)

        scroll.setWidget(body)
        self.root.addWidget(scroll, 1)

        for sig in (ctx.signals.sales_changed, ctx.signals.stock_changed, ctx.signals.notifications_changed):
            sig.connect(self._schedule)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.mark_dirty)

    def _schedule(self) -> None:
        self._debounce.start(800)

    def _set_period(self, key: str) -> None:
        self.period = key
        self.refresh_now()

    def refresh(self) -> None:
        t = tokens()
        with ctx.session() as (s, _):
            p = report_service.period(self.period)
            k = report_service.kpis(s, p)
            prev = self._previous(p)
            kp = report_service.kpis(s, prev) if prev else None
            fmt = lambda v: currency_service.format_amount(s, v)  # noqa: E731
            series_p = report_service.period("30days") if self.period == "today" else p
            series = report_service.sales_series(s, series_p)
            top = report_service.top_products(s, p, 8)
            cats = report_service.sales_by_category(s, p)
            alerts = [(n.severity, n.title, n.body, n.entity, n.entity_id)
                      for n in notification_service.important_alerts(s, 40)]
            slow = report_service.slow_movers(s)
            reorder = report_service.reorder_suggestions(s)
            cur = currency_service.display(s)
            conv = lambda v: currency_service.convert(v, cur)  # noqa: E731
            slow_value = fmt(sum(x["value"] for x in slow))

        def delta(key: str) -> tuple[str, str | None]:
            if not kp or not kp.get(key):
                return "", None
            change = (k[key] - kp[key]) / abs(kp[key]) * 100
            arrow = "▲" if change >= 0 else "▼"
            return f"{arrow} {abs(change):.0f}% عن الفترة السابقة", t["success"] if change >= 0 else t["danger"]

        self.k_sales.set(fmt(k["sales"]), *delta("sales"))
        self.k_profit.set(fmt(k["net_profit"]), f"هامش الربح {k['margin_percent']}%")
        self.k_invoices.set(f"{k['invoices']:,}", *delta("invoices"))
        self.k_stock.set(fmt(k["stock_cost"]), f"بسعر البيع {fmt(k['stock_value'])}")
        self.k_avg.set(fmt(k["avg_invoice"]))
        self.k_credit.set(fmt(k["credit"]), f"المرتجعات {fmt(k['returns'])}" if k["returns"] else "")
        self.k_expenses.set(fmt(k["expenses"]))
        self.k_products.set(f"{k['products']:,}", f"{k['stock_units']:,.0f} قطعة في المستودع")

        show_profit = ctx.can("products.view_cost")
        self.sales_chart.set_data([r["label"] for r in series], [conv(r["sales"]) for r in series],
                                  [conv(r["profit"]) for r in series] if show_profit else None)
        self.top_chart.set_data([r["name"] for r in top], [conv(r["revenue"]) for r in top])
        self.cat_chart.set_data([(c["name"], c["revenue"], c["color"]) for c in cats[:8]])

        self.alerts.clear()
        if not alerts:
            item = QListWidgetItem(icons.icon("check", t["success"]), "لا توجد تنبيهات، كل شيء على ما يرام 👌")
            self.alerts.addItem(item)
        for sev, title, body, entity, eid in alerts:
            color = {"danger": t["danger"], "warning": t["warning"]}.get(sev, t["primary"])
            item = QListWidgetItem(icons.icon("alert" if sev != "info" else "info", color), f"{title}\n{body}")
            item.setData(Qt.ItemDataRole.UserRole, (entity, eid))
            self.alerts.addItem(item)

        parts = []
        if slow:
            parts.append(f"• {len(slow)} منتج لم يُبع منذ فترة طويلة، قيمتها {slow_value}. أبرزها: "
                         + "، ".join(x["product"].name for x in slow[:4]))
        if reorder:
            urgent = [r for r in reorder if r["days_left"] is not None and r["days_left"] <= 7]
            parts.append(f"• {len(reorder)} منتج يحتاج إعادة طلب" + (f"، منها {len(urgent)} ستنفد خلال أسبوع" if urgent else "")
                         + " — راجع المخزون ← اقتراحات الطلب.")
        self.slow_label.setText("\n".join(parts) or "لا توجد ملاحظات حالياً.")

    @staticmethod
    def _previous(p: report_service.Period) -> report_service.Period | None:
        from datetime import timedelta

        length = p.days
        end = p.start - timedelta(days=1)
        return report_service.Period(end - timedelta(days=length - 1), end)

    def _open_alert(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        entity, eid = data
        if entity == "product" and eid:
            ctx.signals.navigate.emit("products", {"product_id": eid})
        elif entity == "customer" and eid:
            ctx.signals.navigate.emit("customers", {"customer_id": eid})
