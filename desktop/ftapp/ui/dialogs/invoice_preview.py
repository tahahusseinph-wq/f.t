"""معاينة الفاتورة القابلة للتعديل: طباعة، حفظ كمستند، وإرسال عبر واتساب."""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QGuiApplication, QPageLayout, QTextCharFormat,
                           QTextDocumentWriter)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFontComboBox, QFrame,
                               QHBoxLayout, QInputDialog, QLabel, QSpinBox, QTextEdit, QToolButton, QVBoxLayout)

from ftapp.core.paths import sub_dir
from ftapp.models import Invoice
from ftapp.services import currency_service, pdf_service, sales_service, settings_service
from ftapp.services.errors import ServiceError
from ftapp.ui.context import ctx
from ftapp.ui.widgets.common import Toast, button, confirm, error
from ftapp.ui.widgets.forms import FormDialog, money_spin

RECEIPTS = ("80mm", "58mm")


class InvoiceSizesDialog(FormDialog):
    """قياسات الفاتورة المحفوظة: حجم اسم المنشأة والنص والشعار ورموز QR والختم والهوامش."""

    def __init__(self, parent) -> None:
        super().__init__(parent, "قياسات الفاتورة", 460)
        with ctx.session() as (s, _):
            style = settings_service.get(s, "invoice")
        self.spins: dict[str, QSpinBox] = {}
        for key, label, default, lo, hi in pdf_service.INVOICE_SIZES:
            sb = QSpinBox()
            sb.setRange(lo, hi)
            sb.setSingleStep(5)
            sb.setSuffix(" %")
            sb.setValue(int(round(pdf_service.size_factor(style, key) * 100)))
            self.spins[key] = sb
            self.row(label, sb)
        self.margin = QSpinBox()
        self.margin.setRange(*pdf_service.MARGIN_RANGE)
        self.margin.setSuffix(" مم")
        self.margin.setValue(int(pdf_service.invoice_margin(style)))
        self.row("هوامش الورقة", self.margin, "تُطبّق على ورق A4 وما يشبهه (الإيصالات الحرارية لها هوامش ثابتة).")
        self.root.addWidget(button("استعادة القياسات الافتراضية", on_click=self._defaults))
        hint = QLabel("100% = الحجم الأساسي. القياسات تُحفظ وتُطبّق على كل الفواتير (الكمبيوتر والموبايل).")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self.root.addWidget(hint)
        self.on_save = self._do
        self.finish_layout()

    def _defaults(self) -> None:
        for key, _label, default, _lo, _hi in pdf_service.INVOICE_SIZES:
            self.spins[key].setValue(default)
        self.margin.setValue(12)

    def _do(self):
        with ctx.session() as (s, _):
            settings_service.update(s, "invoice", margin_mm=self.margin.value(),
                                    **{k: sb.value() for k, sb in self.spins.items()})
        return True


class PrintRateDialog(QDialog):
    """قبل الطباعة: هل سعر صرف الدولار المعتمد في الفاتورة هو نفسه أم تريد تغييره؟"""

    def __init__(self, parent, code: str, symbol: str, base_symbol: str, rate: float) -> None:
        super().__init__(parent)
        self.setWindowTitle("سعر الصرف قبل الطباعة")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.rate = rate
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        q = QLabel(f"سعر صرف {code} المعتمد في هذه الفاتورة:\n1 {symbol} = {rate:,.0f} {base_symbol}\n\n"
                   "هل سعر الصرف هو نفسه أم تريد تغييره؟")
        q.setStyleSheet("font-size: 12pt;")
        q.setWordWrap(True)
        lay.addWidget(q)
        self.box = QFrame()
        bl = QVBoxLayout(self.box)
        bl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel(f"1 {symbol} ="))
        self.spin = money_spin(10**9, 2)
        self.spin.setValue(rate)
        row.addWidget(self.spin, 1)
        row.addWidget(QLabel(base_symbol))
        bl.addLayout(row)
        self.update_global = QCheckBox("تحديث سعر الصرف في الإعدادات أيضاً")
        self.update_global.setChecked(True)
        bl.addWidget(self.update_global)
        self.box.hide()
        lay.addWidget(self.box)
        btns = QHBoxLayout()
        self.same_btn = button("نعم، نفسه — اطبع", "check", "primary", on_click=self.accept)
        self.change_btn = button("تغيير سعر الصرف", "edit", on_click=self._change)
        btns.addWidget(self.same_btn)
        btns.addWidget(self.change_btn)
        btns.addStretch(1)
        btns.addWidget(button("إلغاء", on_click=self.reject))
        lay.addLayout(btns)

    def _change(self) -> None:
        if self.box.isHidden():
            self.box.show()
            self.same_btn.setText("حفظ السعر والطباعة")
            self.change_btn.hide()
            self.spin.setFocus()
            self.spin.selectAll()

    def accept(self) -> None:  # noqa: D102
        if not self.box.isHidden():
            self.rate = self.spin.value()
        super().accept()


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
            self.margin = pdf_service.invoice_margin(settings_service.get(s, "invoice"))
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
        fmt.addWidget(button("قياسات الفاتورة", "settings", on_click=self._sizes,
                             tooltip="تكبير/تصغير اسم المنشأة والنص والشعار... وتُحفظ لكل الفواتير"))
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
        layout = pdf_service.page_layout(self._paper_id, None, self._landscape, self.margin)
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

    def _sizes(self) -> None:
        if self._keep.isModified() and not confirm(self, "تطبيق القياسات يعيد بناء الفاتورة وستضيع تعديلاتك النصية. متابعة؟"):
            return
        if InvoiceSizesDialog(self).exec():
            with ctx.session() as (s, _):
                self.margin = pdf_service.invoice_margin(settings_service.get(s, "invoice"))
            self._render()
            Toast.show_message(self, "تم حفظ قياسات الفاتورة", "success")

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

    def _confirm_rate(self) -> bool:
        """يسأل عن سعر الصرف قبل الطباعة؛ عند تغييره تُعاد بناء الفاتورة بالسعر الجديد."""
        with ctx.session() as (s, _):
            inv = s.get(Invoice, self.invoice_id)
            base = currency_service.base(s)
            ref = currency_service.reference(s)
            if ref is None or inv.currency_code != base.code:
                return True
            rate = inv.ref_rate or currency_service.unit_value(ref)
            info = (ref.code, ref.symbol, base.symbol)
        dlg = PrintRateDialog(self, info[0], info[1], info[2], rate)
        if not dlg.exec():
            return False
        if abs(dlg.rate - rate) > 1e-6:
            if self._keep.isModified() and not confirm(self, "تغيير سعر الصرف يعيد بناء الفاتورة وستضيع تعديلاتك النصية. متابعة؟"):
                return False
            try:
                with ctx.session() as (s, u):
                    sales_service.set_invoice_ref_rate(s, u, self.invoice_id, dlg.rate, dlg.update_global.isChecked())
            except ServiceError as exc:
                error(self, str(exc))
                return False
            self._render()
        return True

    def _print(self) -> None:
        if not self._confirm_rate():
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageLayout(pdf_service.page_layout(self._paper_id, None, self._landscape, self.margin))
        if QPrintDialog(printer, self).exec():
            pdf_service.print_document(self._output_doc(), printer, self._paper_id, self._landscape, self.margin)
            Toast.show_message(self, "تم إرسال الفاتورة للطابعة", "success")

    def _pdf(self, path: Path) -> Path:
        pdf_service.ensure_qt()
        path.parent.mkdir(parents=True, exist_ok=True)
        return pdf_service.document_to_pdf(self._output_doc(), path, self._paper_id, self._landscape, self.margin)

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
