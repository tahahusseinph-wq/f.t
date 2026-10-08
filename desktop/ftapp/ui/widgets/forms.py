"""أساس النوافذ الحوارية والنماذج."""
from __future__ import annotations

from datetime import date
from typing import Callable

from PySide6.QtCore import QDate, QObject, QEvent, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ftapp.ui.i18n import direction
from ftapp.ui.widgets.common import button, run_safely


def money_spin(maximum: float = 1e12, decimals: int = 2, suffix: str = "") -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(0, maximum)
    sb.setDecimals(decimals)
    sb.setGroupSeparatorShown(True)
    sb.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    sb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if suffix:
        sb.setSuffix(f" {suffix}")
    return sb


def qty_spin(maximum: float = 1e9, decimals: int = 3, minimum: float = 0) -> QDoubleSpinBox:
    sb = money_spin(maximum, decimals)
    sb.setMinimum(minimum)
    return sb


def int_spin(minimum: int = 0, maximum: int = 10**9) -> QSpinBox:
    sb = QSpinBox()
    sb.setRange(minimum, maximum)
    sb.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    sb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return sb


def date_edit(value: date | None = None) -> QDateEdit:
    de = QDateEdit()
    de.setCalendarPopup(True)
    de.setDisplayFormat("yyyy-MM-dd")
    d = value or date.today()
    de.setDate(QDate(d.year, d.month, d.day))
    return de


def qdate_to_date(de: QDateEdit) -> date:
    return de.date().toPython()


def fit_to_screen(dlg: QWidget) -> None:
    """يصغّر النافذة ويوسّطها حتى لا تخرج عن حدود الشاشة (لابتوبات الشاشة الصغيرة)."""
    screen = dlg.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return
    g = screen.availableGeometry()
    max_w, max_h = g.width() - 30, g.height() - 50
    mn = dlg.minimumSize()
    if mn.width() > max_w or mn.height() > max_h:
        dlg.setMinimumSize(min(mn.width(), max_w), min(mn.height(), max_h))
    w, h = min(dlg.width(), max_w), min(dlg.height(), max_h)
    if (w, h) != (dlg.width(), dlg.height()):
        dlg.resize(w, h)
    x = min(max(dlg.x(), g.left()), g.right() - w)
    y = min(max(dlg.y(), g.top()), g.bottom() - h - 30)
    dlg.move(max(g.left(), x), max(g.top(), y))


class DialogFitter(QObject):
    """مرشّح عام: كل نافذة حوارية تُضبط على حجم الشاشة لحظة ظهورها."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Show and isinstance(obj, QDialog):
            QTimer.singleShot(0, lambda o=obj: _safe_fit(o))
        return False


def _safe_fit(dlg: QDialog) -> None:
    try:
        if dlg.isVisible():
            fit_to_screen(dlg)
    except RuntimeError:  # حُذفت النافذة قبل التنفيذ
        pass


class FormDialog(QDialog):
    """نافذة نموذج: عنوان، حقول قابلة للتمرير، رسالة خطأ، وزرا حفظ/إلغاء ثابتان بالأسفل."""

    def __init__(self, parent: QWidget | None, title: str, width: int = 460, save_text: str = "حفظ") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(direction())
        self.setMinimumWidth(width)
        self._width = width
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        outer.addWidget(heading)
        # المحتوى داخل منطقة تمرير: إذا كانت الحقول أطول من الشاشة ينزل المستخدم بالعجلة
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        body = QWidget()
        body.setObjectName("formBody")
        body.setStyleSheet("#formBody { background: transparent; }")
        self.root = QVBoxLayout(body)
        self.root.setContentsMargins(6, 2, 6, 2)
        self.root.setSpacing(12)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(10)
        self.root.addLayout(self.form)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)
        self.error_label = QLabel()
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        outer.addWidget(self.error_label)
        self._outer = outer
        self.buttons = QHBoxLayout()
        self.buttons.addStretch(1)
        self.cancel_btn = button("إلغاء", on_click=self.reject)
        self.save_btn = button(save_text, "check", "primary", on_click=self._save)
        self.save_btn.setDefault(True)
        self.buttons.addWidget(self.cancel_btn)
        self.buttons.addWidget(self.save_btn)
        self.on_save: Callable[[], object] | None = None
        self.result_value: object = None

    def finish_layout(self) -> None:
        self.root.addStretch(1)
        self._outer.addLayout(self.buttons)
        # الارتفاع: حجم المحتوى الكامل ما دام يتسع في الشاشة، وإلا يظهر شريط التمرير
        body = self.scroll.widget()
        body.adjustSize()
        screen = QGuiApplication.primaryScreen()
        avail_h = screen.availableGeometry().height() - 60 if screen else 700
        want_h = body.sizeHint().height() + 150
        self.scroll.setMinimumHeight(min(body.sizeHint().height() + 4, 160))
        self.resize(max(self._width, body.sizeHint().width() + 60), min(want_h, avail_h))

    def row(self, label: str, widget: QWidget, hint: str = "") -> QWidget:
        if hint:
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            lay.addWidget(widget)
            h = QLabel(hint)
            h.setObjectName("hint")
            h.setWordWrap(True)
            lay.addWidget(h)
            self.form.addRow(label, box)
        else:
            self.form.addRow(label, widget)
        return widget

    def line(self, label: str, value: str = "", placeholder: str = "", hint: str = "") -> QLineEdit:
        le = QLineEdit(value)
        le.setPlaceholderText(placeholder)
        return self.row(label, le, hint)  # type: ignore[return-value]

    def combo(self, label: str, items: list[tuple[str, object]], selected: object = None) -> QComboBox:
        cb = QComboBox()
        for text, data in items:
            cb.addItem(text, data)
        if selected is not None:
            i = cb.findData(selected)
            if i >= 0:
                cb.setCurrentIndex(i)
        return self.row(label, cb)  # type: ignore[return-value]

    def show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))

    def _save(self) -> None:
        from ftapp.services.errors import ServiceError

        if self.on_save is None:
            self.accept()
            return
        try:
            self.result_value = self.on_save()
        except ServiceError as exc:
            self.show_error(str(exc))
            return
        except Exception as exc:  # pragma: no cover
            import logging
            logging.getLogger(__name__).exception("form save failed")
            self.show_error(f"خطأ غير متوقع: {exc}")
            return
        self.accept()


__all__ = ["FormDialog", "DialogFitter", "fit_to_screen", "money_spin", "qty_spin", "int_spin", "date_edit", "qdate_to_date", "run_safely"]
