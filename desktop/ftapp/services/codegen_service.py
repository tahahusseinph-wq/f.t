"""توليد كود منتج مقروء ومقارب لاسم المنتج وتفاصيله.

الصيغة: [رمز القسم]-[اختصار الماركة]-[اختصار الاسم/الموديل]-[رقم تسلسلي]
مثال: ELC-SAMS-A54-0007
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ftapp.models import Category, Product
from ftapp.services import settings_service as settings

# تحويل الحروف العربية إلى لاتينية (مبسّط ومناسب للأكواد)
_AR_MAP = {
    "ا": "A", "أ": "A", "إ": "E", "آ": "A", "ء": "", "ؤ": "O", "ئ": "E", "ب": "B", "ت": "T",
    "ث": "TH", "ج": "J", "ح": "H", "خ": "KH", "د": "D", "ذ": "TH", "ر": "R", "ز": "Z", "س": "S",
    "ش": "SH", "ص": "S", "ض": "D", "ط": "T", "ظ": "Z", "ع": "A", "غ": "GH", "ف": "F", "ق": "Q",
    "ك": "K", "ل": "L", "م": "M", "ن": "N", "ه": "H", "ة": "A", "و": "W", "ي": "Y", "ى": "A",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
}

# كلمات شائعة لا تفيد في الكود
_STOP_WORDS = {"AL", "THE", "OF", "AND", "WITH", "FOR", "MN", "FY", "ALA", "MA"}


def transliterate(text: str) -> str:
    out = []
    for ch in text or "":
        if ch in _AR_MAP:
            out.append(_AR_MAP[ch])
        elif ch.isascii():
            out.append(ch.upper())
        elif ch.isspace():
            out.append(" ")
    result = "".join(out)
    # إزالة "ال" التعريف في بداية الكلمات
    result = re.sub(r"\bAL(?=[A-Z]{2,})", "", result)
    return result


def _clean_words(text: str) -> list[str]:
    words = re.findall(r"[A-Z0-9]+", transliterate(text))
    return [w for w in words if w not in _STOP_WORDS]


def abbreviate(text: str, length: int = 4) -> str:
    words = _clean_words(text)
    if not words:
        return ""
    if len(words) == 1:
        return words[0][:length]
    # كلمة فيها أرقام (موديل) نحتفظ بها كما هي غالباً
    for w in words:
        if any(c.isdigit() for c in w) and len(w) <= 6:
            return w
    first = words[0][: max(2, length - (len(words) - 1))]
    rest = "".join(w[0] for w in words[1:])
    return (first + rest)[:length]


def category_prefix(session: Session, category_id: int | None) -> str:
    if not category_id:
        return "GEN"
    cat = session.get(Category, category_id)
    if cat is None:
        return "GEN"
    if cat.code:
        return re.sub(r"[^A-Z0-9]", "", cat.code.upper())[:4] or "GEN"
    return abbreviate(cat.name, 3) or "GEN"


def code_exists(session: Session, code: str, exclude_id: int | None = None) -> bool:
    stmt = select(Product.id).where(Product.code == code)
    if exclude_id:
        stmt = stmt.where(Product.id != exclude_id)
    return session.scalar(stmt) is not None


def generate_code(session: Session, name: str, category_id: int | None = None, brand: str = "",
                  model: str = "", exclude_id: int | None = None) -> str:
    fmt = settings.get(session, "code_format")
    sep = fmt.get("separator", "-")
    digits = int(fmt.get("serial_digits", 4))

    parts = [category_prefix(session, category_id)]
    brand_part = abbreviate(brand, 4)
    if brand_part:
        parts.append(brand_part)
    model_part = abbreviate(model, 6) if model else ""
    name_part = model_part or abbreviate(name, 4)
    if name_part and name_part != brand_part:
        parts.append(name_part)
    stem = sep.join(p for p in parts if p)

    # الرقم التسلسلي التالي لنفس البادئة
    existing = session.scalars(select(Product.code).where(Product.code.like(f"{stem}{sep}%"))).all()
    serial = 0
    for code in existing:
        tail = code[len(stem) + len(sep):]
        if tail.isdigit():
            serial = max(serial, int(tail))
    while True:
        serial += 1
        code = f"{stem}{sep}{serial:0{digits}d}"
        if not code_exists(session, code, exclude_id):
            return code


def ean13_checksum(digits12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits12))
    return str((10 - total % 10) % 10)


def generate_internal_barcode(session: Session) -> str:
    """باركود EAN-13 داخلي يبدأ بـ 200 (نطاق الاستخدام الداخلي)."""
    from ftapp.services.numbering import next_number

    n = next_number(session, "barcode")
    body = f"200{n:09d}"
    return body + ean13_checksum(body)
