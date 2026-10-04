"""نوافذ اختيار سريعة."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout


def choose_product(parent, items: list[tuple[str, int]], title: str = "اختر المنتج") -> int | None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    dlg.resize(560, 420)
    lay = QVBoxLayout(dlg)
    search = QLineEdit()
    search.setObjectName("searchBox")
    search.setPlaceholderText("تصفية...")
    lst = QListWidget()
    for text, data in items:
        it = QListWidgetItem(text)
        it.setData(Qt.ItemDataRole.UserRole, data)
        lst.addItem(it)
    lst.setCurrentRow(0)

    def filt(t: str) -> None:
        for i in range(lst.count()):
            lst.item(i).setHidden(t.strip().lower() not in lst.item(i).text().lower())
    search.textChanged.connect(filt)
    search.returnPressed.connect(dlg.accept)
    lst.itemActivated.connect(lambda *_: dlg.accept())
    lay.addWidget(search)
    lay.addWidget(lst, 1)
    search.setFocus()
    if dlg.exec() and lst.currentItem():
        return lst.currentItem().data(Qt.ItemDataRole.UserRole)
    return None
