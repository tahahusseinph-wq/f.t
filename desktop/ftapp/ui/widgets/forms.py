"""أساس النوافذ الحوارية والنماذج."""
from __future__ import annotations

from datetime import date
from typing import Callable

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QSpinBox, QVBoxLayout, QWidget)

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


class FormDialog(QDialog):
    """نافذة نموذج: عنوان، حقول، رسالة خطأ، وزرا حفظ/إلغاء."""

    def __init__(self, parent: QWidget | None, title: str, width: int = 460, save_text: str = "حفظ") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(direction())
        self.setMinimumWidth(width)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 18, 22, 18)
        self.root.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        self.root.addWidget(heading)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(10)
        self.root.addLayout(self.form)
        self.error_label = QLabel()
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self.root.addWidget(self.error_label)
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
        self.root.addLayout(self.buttons)

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


__all__ = ["FormDialog", "money_spin", "qty_spin", "int_spin", "date_edit", "qdate_to_date", "run_safely"]
