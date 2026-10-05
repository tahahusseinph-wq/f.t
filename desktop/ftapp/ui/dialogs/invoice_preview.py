"""معاينة الفاتورة القابلة للتعديل: طباعة، حفظ كمستند، وإرسال عبر واتساب."""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QGuiApplication, QPageLayout, QTextCharFormat,
                           QTextDocumentWriter)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QFileDialog, QFontComboBox, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QSpinBox, QTextEdit, QToolButton, QVBoxLayout)

from ftapp.core.paths import sub_dir
from ftapp.models import Invoice
from ftapp.services import currency_service, pdf_service, settings_service
from ftapp.ui.context import ctx
from ftapp.ui.widgets.common import Toast, button, confirm, error

RECEIPTS = ("80mm", "58mm")


def whatsapp_number(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("09") and len(digits) == 10:  # رقم سوري محلي
        digits = "963" + digits[1:]
    return digits


class InvoicePreviewDialog(QDialog):
    """معاينة فاتورة قابلة للتعديل: تحرير النص، اختيار نوع الورق، طباعة، وحفظ كمستند على الجهاز."""

    def __init__(self, parent, invoice_id: int) -> None:
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(980, screen.width() - 40), min(860, screen.height() - 60))
        with ctx.session() as (s, _):
            inv = s.get(Invoice, invoice_id)
            self.number = inv.number
            self.phone = inv.customer_phone
            self.customer = inv.customer_name
            self.total_text = currency_service.format_amount(s, inv.total, inv.currency_code)
            self.paper = settings_service.get(s, "printing").get("paper", "A4")
            self.company = settings_service.get(s, "company").get("name", "")
        if self.paper not in pdf_service.PAPERS:
            self.paper = "A4"
        self.setWindowTitle(f"الفاتورة {self.number}")
        self._paper_now = self.paper
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        # ---- العنوان + نوع الورق ----
        bar = QHBoxLayout()
        t = QLabel(f"الفاتورة {self.number}")
        t.setObjectName("pageTitle")
        bar.addWidget(t)
        bar.addStretch(1)
        bar.addWidget(QLabel("نوع الورق"))
        self.paper_combo = QComboBox()
        for p, label in pdf_service.PAPERS.items():
            self.paper_combo.addItem(label, p)
        self.paper_combo.setCurrentIndex(max(0, self.paper_combo.findData(self.paper)))
        self.paper_combo.currentIndexChanged.connect(self._paper_changed)
        bar.addWidget(self.paper_combo)
        self.orient_combo = QComboBox()
        self.orient_combo.addItem("طولي", False)
        self.orient_combo.addItem("عرضي", True)
        self.orient_combo.currentIndexChanged.connect(self._paper_changed)
        bar.addWidget(self.orient_combo)
        lay.addLayout(bar)

        # ---- شريط التنسيق ----
        fmt = QHBoxLayout()
        fmt.setSpacing(4)
        self.font_combo = QFontComboBox()
        self.font_combo.setMaximumWidth(150)
        self.font_combo.currentFontChanged.connect(lambda f: self._merge(font_family=f.family()))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(5, 40)
        self.size_spin.setValue(10)
        self.size_spin.setSuffix(" pt")
        self.size_spin.valueChanged.connect(lambda v: self._merge(size=v))
        fmt.addWidget(self.font_combo)
        fmt.addWidget(self.size_spin)
        tools = (("B", "عريض", lambda: self._toggle("bold")), ("I", "مائل", lambda: self._toggle("italic")),
                 ("U", "تسطير", lambda: self._toggle("underline")), ("A", "لون النص", self._color),
                 ("⬅", "محاذاة لليسار", lambda: self._align(Qt.AlignmentFlag.AlignLeft)),
                 ("⬌", "توسيط", lambda: self._align(Qt.AlignmentFlag.AlignHCenter)),
                 ("➡", "محاذاة لليمين", lambda: self._align(Qt.AlignmentFlag.AlignRight)),
                 ("＋ نص", "إضافة نص أو تفاصيل عند المؤشر", self._insert_text),
                 ("↶", "تراجع", lambda: self.view.undo()), ("↷", "إعادة", lambda: self.view.redo()))
        for text, tip, slot in tools:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=slot: f())
            fmt.addWidget(b)
        fmt.addStretch(1)
        fmt.addWidget(button("استعادة الأصل", on_click=self._reset))
        lay.addLayout(fmt)
        hint = QLabel("المعاينة قابلة للتعديل: انقر على أي نص لتعديله أو لإضافة كتابة وتفاصيل. "
                      "ما تراه هو ما سيُطبع ويُحفظ.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # ---- ورقة المعاينة ----
        self.view = QTextEdit()
        self.view.setStyleSheet(
            "QTextEdit { background: white; color: black; border: 1px solid #B0BEC5; border-radius: 4px; }")
        self.view.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.view.cursorPositionChanged.connect(self._sync_format)
        holder = QFrame()
        holder.setStyleSheet("QFrame { background: #CFD8DC; border-radius: 10px; }")
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(8, 8, 8, 8)
        hl.addStretch(1)
        hl.addWidget(self.view)
        hl.addStretch(1)
        lay.addWidget(holder, 1)

        # ---- الأزرار ----
        row = QHBoxLayout()
        row.addWidget(button("طباعة", "print", "primary", on_click=self._print))
        row.addWidget(button("حفظ كمستند", "pdf", on_click=self._save_document))
        row.addWidget(button("واتساب", "whatsapp", on_click=self._whatsapp))
        row.addStretch(1)
        row.addWidget(button("إغلاق", on_click=self.accept))
        lay.addLayout(row)
        self._render()

    # ---------------- بناء المعاينة ----------------
    @property
    def _paper_id(self) -> str:
        return self.paper_combo.currentData()

    @property
    def _landscape(self) -> bool:
        return bool(self.orient_combo.currentData()) and self._paper_id not in RECEIPTS

    def _doc(self):
        with ctx.session() as (s, _):
            return pdf_service.build_invoice_document(s, s.get(Invoice, self.invoice_id), self._paper_id)

    def _render(self) -> None:
        self.orient_combo.setEnabled(self._paper_id not in RECEIPTS)
        doc = self._doc()
        self.view.setDocument(doc)
        self._keep = doc
        self._paper_now = self._paper_id
        self._fit_width()
        doc.setModified(False)

    def _fit_width(self) -> None:
        """عرض الورقة في المعاينة = عرض الطباعة الفعلي، فتتطابق الأسطر مع الناتج."""
        layout = pdf_service.page_layout(self._paper_id, None, self._landscape)
        width = layout.paintRect(QPageLayout.Unit.Point).width()
        self.view.setFixedWidth(int(min(width + 26, max(300, self.width() - 90))))

    def _paper_changed(self) -> None:
        if self._paper_id == self._paper_now:
            self._fit_width()
            return
        if self._keep.isModified() and not confirm(self, "تغيير نوع الورق يعيد بناء الفاتورة وستضيع تعديلاتك. متابعة؟"):
            self.paper_combo.blockSignals(True)
            self.paper_combo.setCurrentIndex(self.paper_combo.findData(self._paper_now))
            self.paper_combo.blockSignals(False)
            return
        self._render()

    def _reset(self) -> None:
        if not self._keep.isModified() or confirm(self, "التخلي عن كل التعديلات واستعادة الفاتورة الأصلية؟"):
            self._render()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_keep"):
            self._fit_width()

    # ---------------- التنسيق ----------------
    def _merge(self, font_family: str | None = None, size: int | None = None) -> None:
        f = QTextCharFormat()
        if font_family:
            f.setFontFamilies([font_family])
        if size:
            f.setFontPointSize(size)
        self.view.mergeCurrentCharFormat(f)
        self.view.setFocus()

    def _toggle(self, attr: str) -> None:
        cur = self.view.currentCharFormat()
        f = QTextCharFormat()
        if attr == "bold":
            f.setFontWeight(QFont.Weight.Normal if cur.fontWeight() > QFont.Weight.Normal else QFont.Weight.Bold)
        elif attr == "italic":
            f.setFontItalic(not cur.fontItalic())
        else:
            f.setFontUnderline(not cur.fontUnderline())
        self.view.mergeCurrentCharFormat(f)
        self.view.setFocus()

    def _color(self) -> None:
        c = QColorDialog.getColor(self.view.textColor(), self, "لون النص")
        if c.isValid():
            f = QTextCharFormat()
            f.setForeground(QColor(c))
            self.view.mergeCurrentCharFormat(f)

    def _align(self, a) -> None:
        self.view.setAlignment(a)
        self.view.setFocus()

    def _sync_format(self) -> None:
        size = int(self.view.currentCharFormat().fontPointSize() or self.view.font().pointSize() or 10)
        self.size_spin.blockSignals(True)
        self.size_spin.setValue(max(5, min(40, size)))
        self.size_spin.blockSignals(False)

    def _insert_text(self) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "إضافة تفاصيل",
                                                 "النص الذي سيُضاف إلى الفاتورة عند موضع المؤشر:")
        if ok and text.strip():
            self.view.textCursor().insertText(text.strip())
            self.view.setFocus()

    # ---------------- الإخراج ----------------
    def _output_doc(self):
        """نسخة من المعاينة (بتعديلاتها) للطباعة والحفظ، حتى لا يتغير تخطيط المعاينة."""
        return self.view.document().clone()

    def _print(self) -> None:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageLayout(pdf_service.page_layout(self._paper_id, None, self._landscape))
        if QPrintDialog(printer, self).exec():
            pdf_service.print_document(self._output_doc(), printer, self._paper_id, self._landscape)
            Toast.show_message(self, "تم إرسال الفاتورة للطابعة", "success")

    def _pdf(self, path: Path) -> Path:
        pdf_service.ensure_qt()
        path.parent.mkdir(parents=True, exist_ok=True)
        return pdf_service.document_to_pdf(self._output_doc(), path, self._paper_id, self._landscape)

    def _save_document(self) -> None:
        pdf_filter = "ملف PDF (*.pdf)"
        odt_filter = "مستند Word / LibreOffice (*.odt)"
        html_filter = "صفحة ويب (*.html)"
        path, chosen = QFileDialog.getSaveFileName(
            self, "حفظ الفاتورة كمستند", str(sub_dir("invoices") / f"{self.number}.pdf"),
            ";;".join((pdf_filter, odt_filter, html_filter)))
        if not path:
            return
        ext = Path(path).suffix.lower()
        if ext not in (".pdf", ".odt", ".html"):
            ext = {odt_filter: ".odt", html_filter: ".html"}.get(chosen, ".pdf")
            path += ext
        try:
            if ext == ".pdf":
                self._pdf(Path(path))
            elif not QTextDocumentWriter(path, b"odf" if ext == ".odt" else b"HTML").write(self._output_doc()):
                raise OSError("تعذر كتابة الملف")
        except Exception as exc:
            error(self, str(exc))
            return
        self._keep.setModified(False)
        Toast.show_message(self, f"تم حفظ المستند: {path}", "success", 5000)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _whatsapp(self) -> None:
        try:
            pdf = self._pdf(sub_dir("invoices") / f"{self.number}.pdf")
        except Exception as exc:
            error(self, str(exc))
            return
        text = (f"مرحباً {self.customer or ''}\nشكراً لتعاملكم مع {self.company}\n"
                f"فاتورة رقم {self.number}\nالإجمالي: {self.total_text}\n(الفاتورة مرفقة كملف PDF)")
        number = whatsapp_number(self.phone)
        url = f"https://wa.me/{number}?text={urllib.parse.quote(text)}" if number else \
              f"https://wa.me/?text={urllib.parse.quote(text)}"
        QDesktopServices.openUrl(QUrl(url))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf.parent)))
        Toast.show_message(self, "تم فتح واتساب ومجلد الفاتورة — اسحب ملف PDF إلى المحادثة لإرفاقه", "info", 6000)
