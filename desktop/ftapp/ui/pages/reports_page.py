"""التقارير: الملخص، نسبة المبيع لكل منتج، الأقسام، الأرباح، ساعات الذروة، سجل النشاطات."""
from __future__ import annotations

import html
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ftapp.services import audit, currency_service, pdf_service, report_service, settings_service
from ftapp.ui import icons
from ftapp.ui.context import ctx
from ftapp.ui.dialogs.catalog_dialogs import open_path
from ftapp.ui.pages.base import Page
from ftapp.ui.pages.inventory_page import export_table
from ftapp.ui.theme import tokens
from ftapp.ui.widgets.charts import BarChart, DonutChart
from ftapp.ui.widgets.common import Card, KpiCard, button, muted
from ftapp.ui.widgets.forms import date_edit
from ftapp.ui.widgets.table import Column, DataTable

DAYS = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


class ReportsPage(Page):
    title = "التقارير"
    subtitle = "تحليل المبيعات والأرباح ونسبة مبيع كل منتج"

    def __init__(self) -> None:
        super().__init__()
        self.preset = QComboBox()
        for key, label in (("month", "هذا الشهر"), ("last_month", "الشهر الماضي"), ("30days", "آخر 30 يوم"),
                           ("week", "آخر 7 أيام"), ("today", "اليوم"), ("year", "هذه السنة"), ("custom", "فترة مخصصة")):
            self.preset.addItem(label, key)
        self.d_from = date_edit(date.today().replace(day=1))
        self.d_to = date_edit()
        self.preset.currentIndexChanged.connect(self._preset)
        for w in (self.preset, QLabel("من"), self.d_from, QLabel("إلى"), self.d_to):
            self.actions.addWidget(w)
        self.actions.addWidget(button("عرض", "refresh", "primary", on_click=self.refresh_now))
        self.actions.addWidget(button("PDF", "pdf", on_click=self._pdf))
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        self._build_summary()
        self._build_products()
        self._build_categories()
        self._build_heatmap()
        if ctx.can("users.manage"):
            self._build_audit()
        self.tabs.currentChanged.connect(lambda *_: self.refresh_now())
        self._preset()

    def _preset(self) -> None:
        key = self.preset.currentData()
        custom = key == "custom"
        self.d_from.setEnabled(custom)
        self.d_to.setEnabled(custom)
        if not custom:
            p = report_service.period(key)
            from PySide6.QtCore import QDate
            self.d_from.setDate(QDate(p.start.year, p.start.month, p.start.day))
            self.d_to.setDate(QDate(p.end.year, p.end.month, p.end.day))
            self.refresh_now()

    def _period(self) -> report_service.Period:
        return report_service.Period(self.d_from.date().toPython(), self.d_to.date().toPython(), self.preset.currentText())

    def _tab(self, title, icon_name) -> QVBoxLayout:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.tabs.addTab(w, icons.icon(icon_name), title)
        return lay

    def _build_summary(self) -> None:
        lay = self._tab("الملخص", "chart")
        grid = QGridLayout()
        t = tokens()
        self.kp = {
            "sales": KpiCard("صافي المبيعات", "money", t["primary"]),
            "gross_profit": KpiCard("الربح الإجمالي", "chart", t["success"]),
            "expenses": KpiCard("المصاريف", "minus", "#8D6E63"),
            "net_profit": KpiCard("صافي الربح", "star", "#00897B"),
            "invoices": KpiCard("الفواتير", "receipt", "#7E57C2"),
            "returns": KpiCard("المرتجعات", "return", t["danger"]),
            "avg_invoice": KpiCard("متوسط الفاتورة", "tag", "#F57C00"),
            "credit": KpiCard("مبيعات آجلة", "wallet", "#5C6BC0"),
        }
        for i, card in enumerate(self.kp.values()):
            grid.addWidget(card, i // 4, i % 4)
        lay.addLayout(grid)
        card = Card("المبيعات والأرباح حسب الفترة", icon_name="bar")
        self.bar = BarChart()
        self.bar.setMinimumHeight(320)
        card.add(self.bar, 1)
        lay.addWidget(card, 1)

    def _build_products(self) -> None:
        lay = self._tab("نسبة المبيع لكل منتج", "percent")
        bar = QHBoxLayout()
        bar.addWidget(muted("نسبة المبيع = حصة المنتج من إجمالي المبيعات. الهامش = الربح ÷ المبيعات."))
        bar.addStretch(1)
        bar.addWidget(button("تصدير", "excel", on_click=lambda: export_table(self, self.products, "نسبة المبيع")))
        lay.addLayout(bar)
        t = tokens()
        cols = [Column("#", "rank", "qty", width=40), Column("المنتج", "name", stretch=True, bold=True),
                Column("الكمية المباعة", "quantity", "qty"), Column("المبيعات", "revenue", "money", bold=True),
                Column("نسبة المبيع", "share", "percent", color=lambda r: t["primary"])]
        if ctx.can("products.view_cost"):
            cols += [Column("الربح", "profit", "money"),
                     Column("هامش الربح", "margin", "percent",
                            color=lambda r: t["danger"] if r["margin"] < 0 else (t["success"] if r["margin"] > 20 else None))]
        self.products = DataTable(cols)
        lay.addWidget(self.products, 1)

    def _build_categories(self) -> None:
        lay = self._tab("حسب القسم", "layers")
        row = QHBoxLayout()
        self.cats = DataTable([Column("القسم", "name", stretch=True, bold=True), Column("الكمية", "quantity", "qty"),
                               Column("المبيعات", "revenue", "money"), Column("الحصة", "share", "percent"),
                               Column("الربح", "profit", "money")])
        row.addWidget(self.cats, 3)
        self.cat_chart = DonutChart()
        row.addWidget(self.cat_chart, 2)
        lay.addLayout(row, 1)

    def _build_heatmap(self) -> None:
        lay = self._tab("أوقات الذروة", "clock")
        lay.addWidget(muted("مبيعات كل ساعة في كل يوم من الأسبوع خلال الفترة. اللون الأغمق = مبيعات أكثر."))
        self.heat = QTableWidget(7, 24)
        self.heat.setVerticalHeaderLabels(DAYS)
        self.heat.setHorizontalHeaderLabels([f"{h}" for h in range(24)])
        self.heat.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.heat.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.heat.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.heat, 1)

    def _build_audit(self) -> None:
        lay = self._tab("سجل النشاطات", "list")
        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(button("تصدير", "excel", on_click=lambda: export_table(self, self.audit, "سجل النشاطات")))
        lay.addLayout(bar)
        self.audit = DataTable([Column("الوقت", "time", "datetime"), Column("المستخدم", "user"),
                                Column("العملية", "action", bold=True), Column("المصدر", "source"),
                                Column("التفاصيل", "details", stretch=True)])
        lay.addWidget(self.audit, 1)

    def refresh(self) -> None:
        p = self._period()
        title = self.tabs.tabText(self.tabs.currentIndex())
        with ctx.session() as (s, _):
            cur = currency_service.display(s)
            conv = lambda v: currency_service.convert(v, cur)  # noqa: E731
            if title == "الملخص":
                k = report_service.kpis(s, p)
                for key, card in self.kp.items():
                    v = k[key]
                    card.set(f"{v:,}" if key == "invoices" else currency_service.format_amount(s, v))
                series = report_service.sales_series(s, p)
                sets = [("المبيعات", [conv(r["sales"]) for r in series], tokens()["primary"])]
                if ctx.can("products.view_cost"):
                    sets.append(("الربح", [conv(r["profit"]) for r in series], "#26A69A"))
                self.bar.set_data([r["label"] for r in series], sets)
            elif title == "نسبة المبيع لكل منتج":
                rows = report_service.product_sales(s, p)
                for i, r in enumerate(rows, 1):
                    r["rank"] = i
                self.products.set_rows(rows)
            elif title == "حسب القسم":
                cats = report_service.sales_by_category(s, p)
                self.cats.set_rows(cats)
                self.cat_chart.set_data([(c["name"], c["revenue"], c["color"]) for c in cats])
            elif title == "أوقات الذروة":
                grid = report_service.hourly_heatmap(s, p)
                top = max(max(r) for r in grid) or 1
                base = QColor(tokens()["primary"])
                for d in range(7):
                    for h in range(24):
                        v = grid[d][h]
                        it = QTableWidgetItem(f"{conv(v):,.0f}" if v else "")
                        c = QColor(base)
                        c.setAlpha(int(15 + 220 * v / top) if v else 0)
                        it.setBackground(c)
                        it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        if v / top > 0.55:
                            it.setForeground(QColor("white"))
                        self.heat.setItem(d, h, it)
            elif title == "سجل النشاطات":
                self.audit.set_rows([{"time": a.created_at, "user": a.username,
                                      "action": audit.ACTION_LABELS.get(a.action, a.action), "source": a.source,
                                      "details": ", ".join(f"{k}: {v}" for k, v in (a.details or {}).items())}
                                     for a in audit.recent(s, 2000)])

    def _pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "حفظ التقرير PDF", f"تقرير_{date.today()}.pdf", "PDF (*.pdf)")
        if not path:
            return
        p = self._period()
        with ctx.session() as (s, _):
            k = report_service.kpis(s, p)
            f = lambda v: currency_service.format_amount(s, v)  # noqa: E731
            company = settings_service.get(s, "company")["name"]
            prods = report_service.product_sales(s, p)[:40]
            cats = report_service.sales_by_category(s, p)
        e = html.escape
        rows_k = "".join(f"<tr><td>{e(lbl)}</td><td align='left'><b>{val}</b></td></tr>" for lbl, val in [
            ("صافي المبيعات", f(k["sales"])), ("عدد الفواتير", k["invoices"]), ("الربح الإجمالي", f(k["gross_profit"])),
            ("المصاريف", f(k["expenses"])), ("صافي الربح", f(k["net_profit"])), ("المرتجعات", f(k["returns"])),
            ("هامش الربح", f"{k['margin_percent']}%")])
        rows_p = "".join(f"<tr><td>{i}</td><td>{e(r['name'])}</td><td align='center'>{r['quantity']:g}</td>"
                         f"<td align='center'>{f(r['revenue'])}</td><td align='center'>{r['share']}%</td></tr>"
                         for i, r in enumerate(prods, 1))
        rows_c = "".join(f"<tr><td>{e(c['name'])}</td><td align='center'>{f(c['revenue'])}</td>"
                         f"<td align='center'>{c['share']}%</td></tr>" for c in cats)
        th = "style='background-color:#1565C0; color:white;'"
        doc = f"""<html><body dir='rtl' style='font-family:Cairo; font-size:9pt'>
        <table width='100%'><tr><td><h2 style='color:#1565C0'>{e(company)}</h2>
        <p>تقرير المبيعات: {p.start} إلى {p.end}</p></td><td align='left'><img src='logo' width='70' height='70'></td></tr></table>
        <h3>الملخص</h3><table width='60%' cellpadding='4'>{rows_k}</table>
        <h3>نسبة المبيع لكل منتج</h3><table width='100%' cellpadding='4'>
        <tr><th {th}>#</th><th {th}>المنتج</th><th {th}>الكمية</th><th {th}>المبيعات</th><th {th}>النسبة</th></tr>{rows_p}</table>
        <h3>حسب القسم</h3><table width='70%' cellpadding='4'><tr><th {th}>القسم</th><th {th}>المبيعات</th><th {th}>الحصة</th></tr>{rows_c}</table>
        </body></html>"""
        open_path(pdf_service.html_to_pdf(doc, Path(path)))
