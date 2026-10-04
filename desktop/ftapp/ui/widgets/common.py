"""عناصر واجهة مشتركة: بطاقات، أزرار، رسائل، تنبيهات منبثقة."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ftapp.ui import icons
from ftapp.ui.i18n import tr
from ftapp.ui.theme import tokens


def rgba(hex_color: str, alpha: float) -> str:
    """لون شفاف لأنماط Qt (التي تقرأ #AARRGGBB وليس #RRGGBBAA)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {int(alpha * 255)})"


def button(text: str, icon_name: str | None = None, variant: str | None = None,
           on_click: Callable | None = None, tooltip: str = "") -> QPushButton:
    btn = QPushButton(tr(text))
    if icon_name:
        color = "#FFFFFF" if variant in ("primary", "danger") else (tokens()["primary"] if variant == "soft" else None)
        btn.setIcon(icons.icon(icon_name, color))
        btn.setIconSize(QSize(17, 17))
    if variant:
        btn.setProperty("variant", variant)
    if on_click:
        btn.clicked.connect(lambda *_: on_click())
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def icon_button(icon_name: str, tooltip: str, on_click: Callable | None = None, color: str | None = None) -> QPushButton:
    btn = QPushButton()
    btn.setProperty("variant", "ghost")
    btn.setIcon(icons.icon(icon_name, color))
    btn.setIconSize(QSize(19, 19))
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        btn.clicked.connect(lambda *_: on_click())
    return btn


class Card(QFrame):
    def __init__(self, title: str = "", parent: QWidget | None = None, icon_name: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 2)
        from PySide6.QtGui import QColor
        shadow.setColor(QColor(13, 27, 42, 18))
        self.setGraphicsEffect(shadow)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        if title:
            if icon_name:
                ic = QLabel()
                ic.setPixmap(icons.pixmap(icon_name, tokens()["primary"], 18))
                self.header.addWidget(ic)
            self.title_label = QLabel(tr(title))
            self.title_label.setObjectName("cardTitle")
            self.header.addWidget(self.title_label)
            self.header.addStretch(1)
            self.body.addLayout(self.header)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget


class KpiCard(Card):
    def __init__(self, label: str, icon_name: str, color: str | None = None) -> None:
        super().__init__()
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout()
        row.setSpacing(12)
        badge = QLabel()
        badge.setFixedSize(44, 44)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c = color or tokens()["primary"]
        badge.setStyleSheet(f"background: {rgba(c, 0.13)}; border-radius: 12px;")
        badge.setPixmap(icons.pixmap(icon_name, c, 22))
        row.addWidget(badge)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.label = QLabel(tr(label))
        self.label.setObjectName("kpiLabel")
        self.value = QLabel("—")
        self.value.setObjectName("kpiValue")
        self.delta = QLabel("")
        self.delta.setObjectName("kpiDelta")
        col.addWidget(self.label)
        col.addWidget(self.value)
        col.addWidget(self.delta)
        row.addLayout(col, 1)
        self.body.addLayout(row)

    def set(self, value: str, delta: str = "", delta_color: str | None = None) -> None:
        self.value.setText(value)
        self.delta.setText(delta)
        self.delta.setVisible(bool(delta))
        if delta_color:
            self.delta.setStyleSheet(f"color: {delta_color};")


def badge(text: str, kind: str = "info") -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName({"danger": "badgeDanger", "warning": "badgeWarning", "success": "badgeSuccess"}.get(kind, "badgeInfo"))
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {tokens()['border']};")
    return line


def muted(text: str, wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    lbl.setWordWrap(wrap)
    return lbl


def empty_state(text: str, icon_name: str = "box") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    ic = QLabel()
    ic.setPixmap(icons.pixmap(icon_name, tokens()["border"], 56))
    ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl = muted(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(ic)
    lay.addWidget(lbl)
    return w


def logo_label(size: int = 64) -> QLabel:
    from ftapp.core.paths import logo_path

    lbl = QLabel()
    pm = QPixmap(str(logo_path()))
    if not pm.isNull():
        lbl.setPixmap(pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    lbl.setFixedSize(size, size)
    return lbl


def fill_combo(combo: QComboBox, items: list[tuple[str, object]], selected: object = None,
               placeholder: str | None = None) -> None:
    combo.blockSignals(True)
    combo.clear()
    if placeholder is not None:
        combo.addItem(placeholder, None)
    for text, data in items:
        combo.addItem(text, data)
    if selected is not None:
        idx = combo.findData(selected)
        if idx >= 0:
            combo.setCurrentIndex(idx)
    combo.blockSignals(False)


# ---------------- الرسائل ----------------

def _box(parent: QWidget | None, icon: QMessageBox.Icon, title: str, text: str) -> QMessageBox:
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    return box


def error(parent: QWidget | None, text: str, title: str = "خطأ") -> None:
    _box(parent, QMessageBox.Icon.Warning, title, text).exec()


def info(parent: QWidget | None, text: str, title: str = "تم") -> None:
    _box(parent, QMessageBox.Icon.Information, title, text).exec()


def confirm(parent: QWidget | None, text: str, title: str = "تأكيد", danger: bool = False,
            yes: str = "نعم", no: str = "إلغاء") -> bool:
    box = _box(parent, QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question, title, text)
    y = box.addButton(yes, QMessageBox.ButtonRole.YesRole)
    box.addButton(no, QMessageBox.ButtonRole.NoRole)
    if danger:
        y.setProperty("variant", "danger")
    box.exec()
    return box.clickedButton() is y


def run_safely(parent: QWidget | None, fn: Callable, success: str | None = None) -> object | None:
    """ينفذ عملية ويعرض رسالة الخطأ المنطقي بالعربية بدل تعطل الواجهة."""
    import logging

    from ftapp.services.errors import ServiceError

    try:
        result = fn()
    except ServiceError as exc:
        error(parent, str(exc))
        return None
    except Exception as exc:  # pragma: no cover - أخطاء غير متوقعة
        logging.getLogger(__name__).exception("UI action failed")
        error(parent, f"حدث خطأ غير متوقع:\n{exc}")
        return None
    if success:
        Toast.show_message(parent, success, "success")
    return result if result is not None else True


class Toast(QLabel):
    """إشعار صغير يظهر أعلى النافذة ويختفي تلقائياً."""

    _active: list["Toast"] = []

    def __init__(self, parent: QWidget, text: str, kind: str = "info") -> None:
        super().__init__(text, parent)
        t = tokens()
        color = {"success": t["success"], "danger": t["danger"], "warning": t["warning"]}.get(kind, t["primary"])
        self.setStyleSheet(f"background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};"
                           f"border-right: 5px solid {color}; border-radius: 10px; padding: 10px 16px;")
        self.setWordWrap(True)
        self.setMaximumWidth(420)
        self.adjustSize()
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self._anim = QPropertyAnimation(effect, b"opacity", self)
        self._anim.setDuration(250)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    @classmethod
    def show_message(cls, parent: QWidget | None, text: str, kind: str = "info", msec: int = 3500) -> None:
        if parent is None:
            return
        window = parent.window()
        toast = cls(window, text, kind)
        offset = 16 + sum(t.height() + 8 for t in cls._active if t.isVisible())
        toast.move(24, 70 + offset)
        toast.show()
        toast.raise_()
        toast._anim.start()
        cls._active.append(toast)

        def done() -> None:
            if toast in cls._active:
                cls._active.remove(toast)
            toast.deleteLater()
        QTimer.singleShot(msec, done)
