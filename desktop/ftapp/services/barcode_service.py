"""توليد صور الباركود (Code128 / EAN-13) و QR."""
from __future__ import annotations

import io

import qrcode
from barcode import get_barcode_class
from barcode.writer import ImageWriter
from PIL import Image


def barcode_png(value: str, symbology: str | None = None, module_height: float = 12.0, with_text: bool = True,
                dpi: int = 300) -> bytes:
    """صورة PNG للباركود. يُستخدم EAN-13 تلقائياً إذا كانت القيمة 13 رقماً صحيحاً."""
    value = (value or "").strip()
    if not value:
        raise ValueError("empty barcode value")
    if symbology is None:
        symbology = "ean13" if value.isdigit() and len(value) == 13 else "code128"
    cls = get_barcode_class(symbology)
    data = value[:12] if symbology == "ean13" else value
    writer = ImageWriter()
    buf = io.BytesIO()
    cls(data, writer=writer).write(buf, options={
        "module_height": module_height, "module_width": 0.25, "quiet_zone": 2.0, "font_size": 8 if with_text else 0,
        "text_distance": 3.5, "write_text": with_text, "dpi": dpi, "background": "white", "foreground": "black",
    })
    return buf.getvalue()


def qr_png(text: str, box_size: int = 8, border: int = 2) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=border)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_with_logo(text: str, logo_file: str | None = None) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
    if logo_file:
        try:
            logo = Image.open(logo_file).convert("RGBA")
            size = img.size[0] // 4
            logo = logo.resize((size, size), Image.LANCZOS)
            pos = ((img.size[0] - size) // 2, (img.size[1] - size) // 2)
            img.alpha_composite(logo, pos)
        except OSError:
            pass
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
