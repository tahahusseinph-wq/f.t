"""إنشاء ملفات PDF (الفواتير، الملصقات، التقارير) عبر Qt لدعم العربية بشكل كامل."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import (QFont, QFontDatabase, QGuiApplication, QImage, QPageLayout, QPageSize, QPainter,
                           QPdfWriter, QTextDocument)
from sqlalchemy.orm import Session

from ftapp.core.paths import assets_dir, logo_path, sub_dir, templates_dir
from ftapp.core.utils import fmt_money, fmt_qty
from ftapp.models import Currency, Invoice, Product, User
from ftapp.services import (barcode_service, catalog_service, currency_service, sales_service,
                            settings_service as settings)

_lock = threading.RLock()
_fonts_loaded = False
_env = Environment(loader=FileSystemLoader(str(templates_dir())), autoescape=select_autoescape(["html"]))

# أنواع الورق: (الاسم الظاهر، معرّف Qt أو عرض الإيصال بالمم)
PAPERS = {"A3": "A3", "A4": "A4", "A5": "A5", "A6": "A6", "Letter": "Letter", "Legal": "Legal",
          "80mm": "إيصال 80mm", "58mm": "إيصال 58mm"}
_PAGE_IDS = {"A3": QPageSize.PageSizeId.A3, "A4": QPageSize.PageSizeId.A4, "A5": QPageSize.PageSizeId.A5,
             "A6": QPageSize.PageSizeId.A6, "Letter": QPageSize.PageSizeId.Letter, "Legal": QPageSize.PageSizeId.Legal}
_FONT_SIZES = {"A3": 11, "A4": 9, "A5": 8, "A6": 7, "Letter": 9, "Legal": 9, "80mm": 7, "58mm": 6}
_LOGO_HEIGHTS = {"A3": 135, "A4": 110, "Letter": 110, "Legal": 110, "A5": 88, "A6": 68}  # ارتفاع اللوغو بالنقاط
_logo_cache: dict[tuple, QImage] = {}


def transparent_logo() -> QImage:
    """اللوغو بخلفية مفرغة: البياض يتحول إلى شفافية فيظهر نظيفاً على أي ورقة."""
    import io
    from PIL import Image

    path = logo_path()
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _logo_cache:
        im = Image.open(path).convert("RGBA")
        px = im.load()
        for y in range(im.height):
            for x in range(im.width):
                r, g, b, a = px[x, y]
                whiteness = min(r, g, b)
                if whiteness > 232:
                    px[x, y] = (r, g, b, 0)
                elif whiteness > 190:  # حواف ناعمة
                    px[x, y] = (r, g, b, int(a * (232 - whiteness) / 42))
        box = im.getchannel("A").getbbox()
        if box:
            im = im.crop(box)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        _logo_cache.clear()
        _logo_cache[key] = QImage.fromData(buf.getvalue())
    return _logo_cache[key]


def ensure_qt() -> None:
    """Qt يحتاج تطبيقاً لتحميل الخطوط. ننشئ واحداً بدون واجهة إن لم يوجد."""
    global _fonts_loaded
    if QGuiApplication.instance() is None:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication([])  # QApplication (وليس QGuiApplication) حتى تعمل الواجهات لاحقاً في نفس العملية
    if not _fonts_loaded:
        for f in (assets_dir() / "fonts").glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(f))
        _fonts_loaded = True


def _currency(session: Session, inv: Invoice) -> Currency:
    return session.get(Currency, inv.currency_code) or currency_service.base(session)


def facebook_link(value: str) -> str:
    """يقبل رابطاً كاملاً أو اسم الصفحة فقط ويعيد رابطاً صالحاً."""
    value = (value or "").strip()
    if not value:
        return ""
    if "://" in value:
        return value
    if "facebook.com" in value or "fb.com" in value or "fb.me" in value:
        return "https://" + value.lstrip("/")
    return "https://www.facebook.com/" + value.lstrip("@/")


def _logo_box(height: int) -> tuple[int, int]:
    """أبعاد اللوغو على الفاتورة مع الحفاظ على نسبته (بدون تمطيط)."""
    try:
        img = transparent_logo()
        ratio = img.width() / img.height() if img.height() else 1
    except Exception:
        ratio = 1
    ratio = max(0.5, min(ratio, 3.5))
    return int(height * ratio), height


def _tint(color: str, amount: float) -> str:
    """لون فاتح مشتق من لون الفاتورة (amount: 0 = نفس اللون، 1 = أبيض)."""
    from PySide6.QtGui import QColor

    c = QColor(color)
    if not c.isValid():
        c = QColor("#1565C0")
    mix = lambda v: int(v + (255 - v) * amount)  # noqa: E731
    return QColor(mix(c.red()), mix(c.green()), mix(c.blue())).name()


def invoice_style(session: Session) -> dict[str, Any]:
    """إعدادات تصميم الفاتورة مع الألوان المشتقة."""
    from PySide6.QtGui import QColor

    cfg = settings.get(session, "invoice")
    accent = cfg.get("accent_color") or "#1565C0"
    if not QColor(accent).isValid():
        accent = "#1565C0"
    cfg["accent"] = accent
    cfg["accent_soft"] = _tint(accent, 0.88)
    cfg["accent_line"] = _tint(accent, 0.6)
    return cfg


def invoice_context(session: Session, inv: Invoice, paper: str = "A4") -> dict[str, Any]:
    cur = _currency(session, inv)
    rate = inv.exchange_rate or 1

    def m(v: float) -> str:
        return fmt_money(round(v * rate, cur.decimals), cur.symbol, cur.decimals)

    seller = ""
    if inv.user_id:
        u = session.get(User, inv.user_id)
        seller = u.display_name if u else ""
    items = [{"code": it.product_code, "name": it.product_name, "unit": it.unit, "qty": fmt_qty(it.quantity),
              "price": m(it.unit_price), "discount": m(it.discount) if it.discount else "—",
              "total": m(it.line_total), "warranty": (it.warranty or "").strip(),
              "warranty_label": catalog_service.warranty_label(it.warranty)} for it in inv.items]
    style = invoice_style(session)
    titles = {"sale": style.get("sale_title") or "فاتورة مبيعات", "return": style.get("return_title") or "إشعار مرتجع",
              "quotation": style.get("quotation_title") or "عرض سعر"}
    base = currency_service.base(session)
    alt_total = ""
    if cur.code != base.code:
        alt_total = fmt_money(inv.total, base.symbol, base.decimals)
    thermal = paper in ("80mm", "58mm")
    print_cfg = settings.get(session, "printing")
    status_note = "ملغاة" if inv.status == "cancelled" else ""
    company = settings.get(session, "company")
    logo_h = 80 if thermal else _LOGO_HEIGHTS.get(paper, 110)
    logo_w, logo_h = _logo_box(logo_h)
    return {
        "inv": inv, "company": company, "currency": cur, "seller": seller, "style": style,
        "terms": [ln.strip() for ln in (style.get("terms") or "").splitlines() if ln.strip()],
        "payment_info": [ln.strip() for ln in (style.get("payment_info") or "").splitlines() if ln.strip()],
        "customer_address": getattr(inv, "customer_address", "") or (inv.customer.address if inv.customer else ""),
        "item_count": len(items), "qty_total": fmt_qty(sum(it.quantity for it in inv.items)),
        "items": items, "doc_title": titles.get(inv.kind, "فاتورة"), "thermal": thermal,
        "fs": _FONT_SIZES.get(paper, 9),
        "logo_w": logo_w, "logo_h": logo_h, "qr_size": 75 if thermal else 64,
        "details": [ln.strip() for ln in (company.get("invoice_details") or "").splitlines() if ln.strip()],
        "facebook": facebook_link(company.get("facebook_url", "")),
        "shamcash": (company.get("shamcash_account") or "").strip(),
        "show_logo": print_cfg.get("show_logo", True),
        "payment_label": sales_service.PAYMENT_METHODS.get(inv.payment_method, inv.payment_method),
        "original": inv.original.number if inv.original else "",
        "totals": {"subtotal": m(inv.subtotal), "discount": m(inv.discount), "tax": m(inv.tax_amount),
                   "total": m(inv.total), "paid": m(inv.paid), "remaining": m(inv.remaining)},
        "alt_total": alt_total, "status_note": status_note,
    }


def invoice_qr_text(session: Session, inv: Invoice) -> str:
    return json.dumps({"inv": inv.number, "date": inv.created_at.strftime("%Y-%m-%d %H:%M"),
                       "total": round(inv.total, 2), "cur": currency_service.base(session).code,
                       "company": settings.get(session, "company").get("name_en", "")}, ensure_ascii=False)


def build_invoice_document(session: Session, inv: Invoice, paper: str = "A4") -> QTextDocument:
    ensure_qt()
    html = _env.get_template("invoice.html").render(**invoice_context(session, inv, paper))
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Cairo", 10))
    doc.addResource(QTextDocument.ResourceType.ImageResource, "logo", transparent_logo())
    qr = QImage.fromData(barcode_service.qr_png(invoice_qr_text(session, inv)))
    doc.addResource(QTextDocument.ResourceType.ImageResource, "qr", qr)
    fb = facebook_link(settings.get(session, "company").get("facebook_url", ""))
    if fb:
        doc.addResource(QTextDocument.ResourceType.ImageResource, "fb", QImage.fromData(barcode_service.qr_png(fb)))
    doc.setHtml(html)
    return doc


def page_layout(paper: str, doc: QTextDocument | None = None, landscape: bool = False) -> QPageLayout:
    if paper in ("80mm", "58mm"):
        width_mm = 80 if paper == "80mm" else 58
        margin = 3
        height_mm = 200.0
        if doc is not None:
            # طول الإيصال حسب المحتوى (صفحة واحدة متصلة)
            doc.setTextWidth((width_mm - 2 * margin) / 25.4 * 72)
            height_mm = max(60.0, doc.size().height() / 72 * 25.4 + 2 * margin + 2)
        return QPageLayout(QPageSize(QSizeF(width_mm, height_mm), QPageSize.Unit.Millimeter, paper),
                           QPageLayout.Orientation.Portrait, QMarginsF(margin, margin, margin, margin),
                           QPageLayout.Unit.Millimeter)
    orientation = QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait
    return QPageLayout(QPageSize(_PAGE_IDS.get(paper, QPageSize.PageSizeId.A4)), orientation,
                       QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)


def paint_document(doc: QTextDocument, device, layout: QPageLayout, new_page) -> None:
    """يرسم المستند صفحة صفحة على جهاز رسم (PDF أو طابعة)."""
    rect_pt = layout.paintRect(QPageLayout.Unit.Point)
    doc.setPageSize(QSizeF(rect_pt.width(), rect_pt.height()))
    painter = QPainter(device)
    painter.scale(device.logicalDpiX() / 72.0, device.logicalDpiY() / 72.0)
    page_h = rect_pt.height()
    for i in range(doc.pageCount()):
        if i:
            new_page()
        painter.save()
        painter.translate(0, -i * page_h)
        doc.drawContents(painter, QRectF(0, i * page_h, rect_pt.width(), page_h))
        painter.restore()
    painter.end()


def document_to_pdf(doc: QTextDocument, path: Path, paper: str = "A4", landscape: bool = False) -> Path:
    """يرسم المستند صفحة صفحة (بدون أرقام صفحات تلقائية)."""
    with _lock:
        layout = page_layout(paper, doc, landscape)
        writer = QPdfWriter(str(path))
        writer.setResolution(300)
        writer.setPageLayout(layout)
        writer.setTitle(path.stem)
        writer.setCreator("Al-Toumma Trading Group")
        paint_document(doc, writer, layout, writer.newPage)
    return path


def print_document(doc: QTextDocument, printer, paper: str = "A4", landscape: bool = False) -> None:
    with _lock:
        layout = page_layout(paper, doc, landscape)
        printer.setPageLayout(layout)
        paint_document(doc, printer, layout, printer.newPage)


def _dispose(doc: QTextDocument) -> None:
    """حذف المستند فوراً في نفس الخيط.

    عند الإنشاء من خيوط السيرفر، ترك المستند لجامع القمامة يجعله يُحذف لاحقاً من خيط آخر
    بعد انتهاء خيطه الأصلي، فتتعطل مؤقتات Qt الداخلية."""
    import shiboken6

    if shiboken6.isValid(doc):
        shiboken6.delete(doc)


def invoice_pdf(session: Session, inv: Invoice, path: Path | str | None = None, paper: str | None = None) -> Path:
    paper = paper or settings.get(session, "printing").get("paper", "A4")
    with _lock:
        doc = build_invoice_document(session, inv, paper)
        out = Path(path) if path else sub_dir("invoices") / f"{inv.number}.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            return document_to_pdf(doc, out, paper)
        finally:
            _dispose(doc)


def html_to_pdf(html: str, path: Path | str, paper: str = "A4", landscape: bool = False) -> Path:
    ensure_qt()
    with _lock:
        doc = QTextDocument()
        doc.setDefaultFont(QFont("Cairo", 9))
        doc.addResource(QTextDocument.ResourceType.ImageResource, "logo", transparent_logo())
        doc.setHtml(html)
        try:
            return document_to_pdf(doc, Path(path), paper, landscape)
        finally:
            _dispose(doc)


# ---------------- ملصقات الباركود ----------------

def labels_pdf(session: Session, items: list[tuple[Product, int]], path: Path | str, width_mm: float = 50,
               height_mm: float = 30, sheet: str = "single", show_price: bool = True, show_company: bool = True,
               tier_id: int | None = None) -> Path:
    """sheet: single = ملصق في كل صفحة (طابعات الملصقات)، a4 = شبكة على ورقة A4."""
    ensure_qt()
    path = Path(path)
    company = settings.get(session, "company")
    cur = currency_service.display(session)
    with _lock:
        writer = QPdfWriter(str(path))
        writer.setResolution(300)
        if sheet == "a4":
            layout = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                 QMarginsF(5, 5, 5, 5), QPageLayout.Unit.Millimeter)
        else:
            layout = QPageLayout(QPageSize(QSizeF(width_mm, height_mm), QPageSize.Unit.Millimeter, "label"),
                                 QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
        writer.setPageLayout(layout)
        dpmm = writer.resolution() / 25.4
        painter = QPainter(writer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        lw, lh = width_mm * dpmm, height_mm * dpmm
        cols = max(1, int(writer.width() // lw)) if sheet == "a4" else 1
        rows = max(1, int(writer.height() // lh)) if sheet == "a4" else 1
        slot = 0
        labels = [p for p, n in items for _ in range(max(0, n))]
        for idx, product in enumerate(labels):
            if sheet == "a4":
                if slot and slot % (cols * rows) == 0:
                    writer.newPage()
                pos = slot % (cols * rows)
                x, y = (pos % cols) * lw, (pos // cols) * lh
            else:
                if idx:
                    writer.newPage()
                x = y = 0
            slot += 1
            _draw_label(painter, product, QRectF(x, y, lw, lh), dpmm, company.get("name", ""), cur,
                        session, show_price, show_company, tier_id, outline=(sheet == "a4"))
        painter.end()
    return path


def _draw_label(painter: QPainter, p: Product, rect: QRectF, dpmm: float, company: str, cur: Currency,
                session: Session, show_price: bool, show_company: bool, tier_id: int | None, outline: bool) -> None:
    pad = 1.2 * dpmm
    inner = rect.adjusted(pad, pad, -pad, -pad)
    if outline:
        painter.setPen(Qt.GlobalColor.lightGray)
        painter.drawRect(rect)
    painter.setPen(Qt.GlobalColor.black)
    y = inner.top()
    line_h = inner.height()
    if show_company:
        f = QFont("Cairo")
        f.setPixelSize(int(2.2 * dpmm))
        painter.setFont(f)
        painter.drawText(QRectF(inner.left(), y, inner.width(), 3 * dpmm), Qt.AlignmentFlag.AlignCenter, company)
        y += 3 * dpmm
    f = QFont("Cairo")
    f.setPixelSize(int(2.8 * dpmm))
    f.setBold(True)
    painter.setFont(f)
    name_rect = QRectF(inner.left(), y, inner.width(), 4 * dpmm)
    name = painter.fontMetrics().elidedText(p.name, Qt.TextElideMode.ElideLeft, int(name_rect.width()))
    painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, name)
    y += 4 * dpmm
    price_h = 4.5 * dpmm if show_price else 0
    bc_h = inner.bottom() - y - price_h
    value = p.barcode or p.code
    try:
        img = QImage.fromData(barcode_service.barcode_png(value, module_height=8, with_text=True))
        target = QRectF(inner.left(), y, inner.width(), max(bc_h, 6 * dpmm))
        scaled = img.scaled(int(target.width()), int(target.height()), Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        painter.drawImage(QRectF(target.center().x() - scaled.width() / 2, target.top(), scaled.width(),
                                 scaled.height()), scaled)
    except Exception:
        painter.drawText(QRectF(inner.left(), y, inner.width(), bc_h), Qt.AlignmentFlag.AlignCenter, value)
    if show_price:
        price, _ = catalog_service.final_price(session, p, tier_id)
        f = QFont("Cairo")
        f.setPixelSize(int(3.4 * dpmm))
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(QRectF(inner.left(), inner.bottom() - price_h, inner.width(), price_h),
                         Qt.AlignmentFlag.AlignCenter,
                         fmt_money(currency_service.convert(price, cur), cur.symbol, cur.decimals))
    _ = line_h
