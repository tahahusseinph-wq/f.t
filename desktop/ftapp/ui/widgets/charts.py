"""رسوم بيانية (QtCharts) بألوان الهوية."""
from __future__ import annotations

from PySide6.QtCharts import (QAreaSeries, QBarCategoryAxis, QBarSeries, QBarSet, QCategoryAxis, QChart, QChartView,
                              QHorizontalBarSeries, QLineSeries, QPieSeries, QValueAxis)
from PySide6.QtCore import QMargins, QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen

from ftapp.ui.theme import FONT_FAMILY, tokens

PALETTE = ["#1565C0", "#6BB8E6", "#26A69A", "#FFA726", "#AB47BC", "#EF5350", "#8D6E63", "#5C6BC0", "#9CCC65",
           "#78909C"]


def _base_chart() -> QChart:
    t = tokens()
    chart = QChart()
    chart.setBackgroundBrush(QBrush(QColor(t["surface"])))
    chart.setBackgroundRoundness(0)
    chart.setMargins(QMargins(4, 4, 4, 4))
    chart.legend().setLabelColor(QColor(t["muted"]))
    chart.legend().setFont(QFont(FONT_FAMILY, 8))
    chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
    chart.setAnimationDuration(500)
    return chart


def _axis_style(axis) -> None:
    t = tokens()
    axis.setLabelsColor(QColor(t["muted"]))
    axis.setLabelsFont(QFont(FONT_FAMILY, 8))
    axis.setGridLineColor(QColor(t["border"]))
    axis.setLinePenColor(QColor(t["border"]))


class ChartView(QChartView):
    def __init__(self, parent=None) -> None:
        super().__init__(_base_chart(), parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setMinimumHeight(240)
        self.setStyleSheet("background: transparent;")

    def _reset(self) -> QChart:
        chart = _base_chart()
        self.setChart(chart)
        return chart


class SalesChart(ChartView):
    """منحنى المبيعات مع الأرباح."""

    def set_data(self, labels: list[str], sales: list[float], profit: list[float] | None = None) -> None:
        t = tokens()
        chart = self._reset()
        upper = QLineSeries()
        upper.setName("المبيعات")
        for i, v in enumerate(sales):
            upper.append(QPointF(i, v))
        lower = QLineSeries()
        for i in range(len(sales)):
            lower.append(QPointF(i, 0))
        area = QAreaSeries(upper, lower)
        # QAreaSeries لا يمتلك السلسلتين: نحتفظ بمرجع لهما وإلا يحذفهما بايثون ويتعطل البرنامج
        self._keep = (upper, lower)
        area.setName("المبيعات")
        grad = QLinearGradient(QPointF(0, 0), QPointF(0, 1))
        grad.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
        c = QColor(t["primary"])
        c1 = QColor(c)
        c1.setAlpha(110)
        c2 = QColor(c)
        c2.setAlpha(8)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        area.setBrush(QBrush(grad))
        area.setPen(QPen(c, 2.4))
        chart.addSeries(area)
        series = [area]
        if profit is not None:
            pl = QLineSeries()
            pl.setName("الربح")
            for i, v in enumerate(profit):
                pl.append(QPointF(i, v))
            pl.setPen(QPen(QColor("#26A69A"), 2, Qt.PenStyle.DashLine))
            chart.addSeries(pl)
            series.append(pl)
        ax = QCategoryAxis()
        ax.setLabelsPosition(QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue)
        n = max(len(sales) - 1, 1)
        ax.setRange(0, n)
        step = max(1, len(labels) // 8)
        for i, lbl in enumerate(labels):
            if i % step == 0:
                ax.append(lbl, i)
        ay = QValueAxis()
        values = [*sales, *(profit or [])]
        ay.setRange(min(0, min(values or [0])), max(values or [1]) * 1.15 or 1)
        ay.setLabelFormat("%.0f")
        ay.setTickCount(5)
        for a in (ax, ay):
            _axis_style(a)
        chart.addAxis(ax, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(ay, Qt.AlignmentFlag.AlignLeft)
        for s_ in series:
            s_.attachAxis(ax)
            s_.attachAxis(ay)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignTop)


class DonutChart(ChartView):
    def set_data(self, items: list[tuple[str, float, str | None]]) -> None:
        t = tokens()
        chart = self._reset()
        pie = QPieSeries()
        pie.setHoleSize(0.55)
        total = sum(v for _, v, _ in items) or 1
        for i, (name, value, color) in enumerate(items):
            if value <= 0:
                continue
            sl = pie.append(f"{name} {value / total * 100:.0f}%", value)
            sl.setBrush(QColor(color or PALETTE[i % len(PALETTE)]))
            sl.setBorderColor(QColor(t["surface"]))
            sl.setBorderWidth(2)
        if not pie.count():
            sl = pie.append("لا توجد بيانات", 1)
            sl.setBrush(QColor(t["border"]))
        chart.addSeries(pie)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignRight)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)


class HBarChart(ChartView):
    def set_data(self, labels: list[str], values: list[float], color: str | None = None) -> None:
        chart = self._reset()
        bar = QBarSet("")
        bar.setColor(QColor(color or tokens()["primary"]))
        bar.setBorderColor(QColor(color or tokens()["primary"]))
        for v in reversed(values):
            bar.append(v)
        series = QHorizontalBarSeries()
        series.append(bar)
        series.setBarWidth(0.6)
        chart.addSeries(series)
        ay = QBarCategoryAxis()
        ay.append([(l[:22] + "…") if len(l) > 23 else l for l in reversed(labels)] or [""])
        ax = QValueAxis()
        ax.setRange(0, max(values or [1]) * 1.1)
        ax.setLabelFormat("%.0f")
        ax.setTickCount(4)
        for a in (ax, ay):
            _axis_style(a)
        chart.addAxis(ay, Qt.AlignmentFlag.AlignLeft)
        chart.addAxis(ax, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(ay)
        series.attachAxis(ax)
        chart.legend().setVisible(False)


class BarChart(ChartView):
    def set_data(self, labels: list[str], sets: list[tuple[str, list[float], str]]) -> None:
        chart = self._reset()
        series = QBarSeries()
        for name, values, color in sets:
            s = QBarSet(name)
            s.setColor(QColor(color))
            s.setBorderColor(QColor(color))
            s.append(values)
            series.append(s)
        chart.addSeries(series)
        ax = QBarCategoryAxis()
        ax.append(labels or [""])
        ay = QValueAxis()
        ay.setRange(0, max([v for _, vals, _ in sets for v in vals] or [1]) * 1.15)
        ay.setLabelFormat("%.0f")
        for a in (ax, ay):
            _axis_style(a)
        chart.addAxis(ax, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(ay, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(ax)
        series.attachAxis(ay)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignTop)
