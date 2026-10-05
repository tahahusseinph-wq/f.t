"""الصفحة الأساسية: رأس بعنوان وأزرار، وتحديث كسول عند الظهور."""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ftapp.ui.i18n import tr
from ftapp.ui.theme import compact


class Page(QWidget):
    title = ""
    subtitle = ""
    icon = "home"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self._dirty = True
        self.root = QVBoxLayout(self)
        small = compact()
        self.root.setContentsMargins(14, 10, 14, 10) if small else self.root.setContentsMargins(26, 20, 26, 20)
        self.root.setSpacing(8 if small else 14)
        head = QHBoxLayout()
        head.setSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title_label = QLabel(tr(self.title))
        self.title_label.setObjectName("pageTitle")
        self.subtitle_label = QLabel(self.subtitle)
        self.subtitle_label.setObjectName("pageSubtitle")
        titles.addWidget(self.title_label)
        if self.subtitle:
            titles.addWidget(self.subtitle_label)
        head.addLayout(titles)
        head.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        head.addLayout(self.actions)
        self.root.addLayout(head)

    def mark_dirty(self) -> None:
        self._dirty = True
        if self.isVisible():
            self.refresh_now()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._dirty:
            self.refresh_now()

    def refresh_now(self) -> None:
        self._dirty = False
        self.refresh()

    def refresh(self) -> None:  # تعاد كتابتها في الصفحات
        pass

    def open_item(self, payload: Any) -> None:
        """فتح عنصر معيّن عند التنقل من صفحة أخرى (مثل منتج من التنبيهات)."""
