"""معاينة الفاتورة: طباعة، حفظ PDF، وإرسال عبر واتساب."""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout

from ftapp.core.paths import sub_dir
from ftapp.models import Invoice
from ftapp.services import currency_service, pdf_service, settings_service
from ftapp.ui.context import ctx
from ftapp.ui.widgets.common import Toast, button, error


def whatsapp_number(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("09") and len(digits) == 10:  # رقم سوري محلي
        digits = "963" + digits[1:]
    return digits


class InvoicePreviewDialog(QDialog):
    def __init__(self, parent, invoice_id: int) -> None:
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(860, 900)
        with ctx.session() as (s, _):
            inv = s.get(Invoice, invoice_id)
            self.number = inv.number
            self.phone = inv.customer_phone
            self.customer = inv.customer_name
            self.total_text = currency_service.format_amount(s, inv.total, inv.currency_code)
            self.paper = settings_service.get(s, "printing").get("paper", "A4")
            self.company = settings_service.get(s, "company").get("name", "")
        self.setWindowTitle(f"الفاتورة {self.number}")
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        t = QLabel(f"الفاتورة {self.number}")
        t.setObjectName("pageTitle")
        bar.addWidget(t)
        bar.addStretch(1)
        self.paper_combo = QComboBox()
        for p, label in (("A4", "A4"), ("A5", "A5"), ("80mm", "إيصال 80mm"), ("58mm", "إيصال 58mm")):
            self.paper_combo.addItem(label, p)
        self.paper_combo.setCurrentIndex(max(0, self.paper_combo.findData(self.paper)))
        self.paper_combo.currentIndexChanged.connect(self._render)
        bar.addWidget(self.paper_combo)
        lay.addLayout(bar)
        self.view = QTextBrowser()
        self.view.setStyleSheet("background: white; color: black; border-radius: 10px;")
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addWidget(button("طباعة", "print", "primary", on_click=self._print))
        row.addWidget(button("حفظ PDF", "pdf", on_click=self._save_pdf))
        row.addWidget(button("واتساب", "whatsapp", on_click=self._whatsapp))
        row.addStretch(1)
        row.addWidget(button("إغلاق", on_click=self.accept))
        lay.addLayout(row)
        self._render()

    def _doc(self):
        with ctx.session() as (s, _):
            return pdf_service.build_invoice_document(s, s.get(Invoice, self.invoice_id), self.paper_combo.currentData())

    def _render(self) -> None:
        doc = self._doc()
        self.view.setDocument(doc)
        self._keep = doc

    def _print(self) -> None:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec():
            self._doc().print_(printer)
            Toast.show_message(self, "تم إرسال الفاتورة للطابعة", "success")

    def _pdf(self, path: Path | None = None) -> Path:
        with ctx.session() as (s, _):
            return pdf_service.invoice_pdf(s, s.get(Invoice, self.invoice_id), path, self.paper_combo.currentData())

    def _save_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "حفظ PDF", f"{self.number}.pdf", "PDF (*.pdf)")
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._pdf(Path(path)))))

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
