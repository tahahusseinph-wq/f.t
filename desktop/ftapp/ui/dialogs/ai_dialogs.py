"""معاينة نتائج الذكاء الاصطناعي قبل تطبيقها."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ftapp.services import gemini_service
from ftapp.ui.widgets.common import button, muted


class AIDetailsPreview(QDialog):
    def __init__(self, parent, details: gemini_service.ProductDetails, fields: list[Any]) -> None:
        super().__init__(parent)
        self.details = details
        self.setWindowTitle("تفاصيل المنتج من الذكاء الاصطناعي")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(760, 640)
        lay = QVBoxLayout(self)
        t = QLabel("✨ نتيجة البحث — اختر ما تريد تطبيقه")
        t.setObjectName("pageTitle")
        lay.addWidget(t)
        conf = {"high": "عالية", "medium": "متوسطة", "low": "منخفضة"}.get(details.confidence, details.confidence)
        lay.addWidget(muted(f"درجة الثقة: {conf}. راجع المعلومات قبل الحفظ، فقد تحتوي أخطاء."))

        self.use_desc = QCheckBox("الوصف")
        self.use_desc.setChecked(bool(details.description))
        lay.addWidget(self.use_desc)
        self.desc = QPlainTextEdit(details.description)
        self.desc.setMaximumHeight(110)
        lay.addWidget(self.desc)
        extra = []
        if details.uses:
            extra.append("الاستخدامات: " + "، ".join(details.uses))
        if details.origin_country:
            extra.append(f"المنشأ: {details.origin_country}")
        if extra:
            self.desc.appendPlainText("\n" + "\n".join(extra))

        lay.addWidget(QLabel("المواصفات والخانات"))
        self.match = gemini_service.match_custom_fields(details, fields)
        names = {f.id: f.name for f in fields}
        rows = [("spec", s.name, s.value) for s in details.specs] + \
               [("field", fid, v) for fid, v in self.match.items()]
        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(["تطبيق", "الاسم", "القيمة"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        for r, (kind, key, value) in enumerate(rows):
            cb = QTableWidgetItem()
            cb.setFlags(cb.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            cb.setCheckState(Qt.CheckState.Checked)
            cb.setData(Qt.ItemDataRole.UserRole, (kind, key))
            self.table.setItem(r, 0, cb)
            label = f"خانة: {names[key]}" if kind == "field" else key
            self.table.setItem(r, 1, QTableWidgetItem(label))
            self.table.setItem(r, 2, QTableWidgetItem(value))
        lay.addWidget(self.table, 1)
        self.use_cat = QCheckBox(f"القسم المقترح: {details.suggested_category}")
        self.use_cat.setVisible(bool(details.suggested_category))
        lay.addWidget(self.use_cat)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("إلغاء", on_click=self.reject))
        row.addWidget(button("تطبيق المحدد", "check", "primary", on_click=self.accept))
        lay.addLayout(row)

    def selection(self) -> dict[str, Any]:
        out: dict[str, Any] = {"specs": {}, "fields": {}}
        if self.use_desc.isChecked():
            out["description"] = self.desc.toPlainText().strip()
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            kind, key = item.data(Qt.ItemDataRole.UserRole)
            value = self.table.item(r, 2).text().strip()
            if kind == "spec":
                out["specs"][key] = value
            else:
                out["fields"][key] = value
        if self.use_cat.isChecked():
            out["category"] = self.details.suggested_category
        return out
