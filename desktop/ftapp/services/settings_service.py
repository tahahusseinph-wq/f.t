"""الإعدادات العامة المخزنة في جدول settings."""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from ftapp.core.events import SETTINGS_CHANGED, bus
from ftapp.models import Setting

# الحقول الأساسية للمنتج وإمكانية إظهارها للمستخدمين (الافتراضي)
BUILTIN_FIELDS: dict[str, str] = {
    "name": "اسم المنتج",
    "code": "الكود",
    "barcode": "الباركود",
    "category": "القسم",
    "brand": "الماركة",
    "model": "الموديل",
    "unit": "الوحدة",
    "sale_price": "سعر البيع",
    "cost_price": "سعر التكلفة",
    "margin": "نسبة الربح",
    "quantity": "الكمية المتوفرة",
    "min_stock": "حد التنبيه",
    "supplier": "المورد",
    "location": "الموقع في المستودع",
    "details": "تفاصيل المنتج",
    "specs": "المواصفات",
    "notes": "ملاحظات",
    "images": "الصور",
    "tier_prices": "أسعار الشرائح",
}

DEFAULT_VISIBILITY = {
    "name": True, "code": True, "barcode": True, "category": True, "brand": True, "model": True,
    "unit": True, "sale_price": True, "cost_price": False, "margin": False, "quantity": False,
    "min_stock": False, "supplier": False, "location": False, "details": True, "specs": True,
    "notes": False, "images": True, "tier_prices": False,
}

DEFAULTS: dict[str, Any] = {
    "setup_done": False,
    "company": {
        "name": "مجموعة فاروق الطعمة التجارية",
        "name_en": "Farouk Toumma Trading Group",
        "address": "",
        "phone": "",
        "email": "",
        "tax_number": "",
        "invoice_footer": "شكراً لتعاملكم معنا",
        "invoice_details": "",   # نص حر يكتبه المستخدم يظهر أعلى الفاتورة
        "facebook_url": "",      # صفحة الفيسبوك: تُطبع كرمز QR على الفاتورة
        "shamcash_account": "",  # رقم/اسم حساب شام كاش لاستلام الدفعات
    },
    "base_currency": "USD",
    "display_currency": "USD",
    "default_min_stock": 5,
    "slow_moving_days": 60,
    "expiry_warning_days": 30,
    "large_invoice_amount": 1000,
    "allow_negative_stock": False,
    "tax_rate": 0.0,
    "builtin_visibility": DEFAULT_VISIBILITY,
    "server": {"enabled": True, "port": 8765, "lan_only": True},
    "server_id": "",
    "jwt_secret": "",
    "gemini": {"model": "gemini-2.5-flash", "enabled": True},
    "backup": {"auto": True, "keep": 14, "encrypt": False, "cloud_folder": "", "last": ""},
    "ui": {"language": "ar", "theme": "light", "idle_lock_minutes": 15},
    "printing": {"paper": "A4", "show_logo": True, "copies": 1, "printer": ""},
    # تصميم الفاتورة التجارية (يُعدَّل من الإعدادات)
    "invoice": {
        "sale_title": "فاتورة مبيعات",
        "quotation_title": "عرض سعر",
        "return_title": "إشعار مرتجع",
        "accent_color": "#1565C0",
        "terms": "البضاعة المباعة لا تُرد ولا تُستبدل إلا بموجب هذه الفاتورة وخلال 7 أيام.",
        "payment_info": "",   # بيانات الدفع/الحساب البنكي تُطبع أسفل الفاتورة
        "show_code": True,
        "show_unit": True,
        "show_seller": True,
        "show_qr": True,
        "show_signatures": True,
        "show_stamp": True,
    },
    "updates": {"check_url": "", "auto_check": True},
    "code_format": {"separator": "-", "serial_digits": 4},
    "recovery_key_hash": "",
}


def get(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    if row is None or row.value is None:
        if key in DEFAULTS:
            return copy.deepcopy(DEFAULTS[key])
        return default
    value = row.value
    # دمج المفاتيح الجديدة الافتراضية مع القيم المحفوظة للقواميس
    if isinstance(value, dict) and isinstance(DEFAULTS.get(key), dict):
        merged = copy.deepcopy(DEFAULTS[key])
        merged.update(value)
        return merged
    return value


def set(session: Session, key: str, value: Any) -> None:  # noqa: A001 - اسم مقصود
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = copy.deepcopy(value)
    session.flush()
    bus.publish(SETTINGS_CHANGED, key=key)


def update(session: Session, key: str, **changes: Any) -> dict:
    current = get(session, key) or {}
    current.update(changes)
    set(session, key, current)
    return current


def builtin_visibility(session: Session) -> dict[str, bool]:
    vis = copy.deepcopy(DEFAULT_VISIBILITY)
    vis.update(get(session, "builtin_visibility") or {})
    return vis
