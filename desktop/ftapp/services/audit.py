"""سجل النشاطات للعمليات الحساسة."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ftapp.models import AuditLog, User


def log(session: Session, user: User | None, action: str, entity: str = "", entity_id: int | None = None,
        source: str = "desktop", **details: Any) -> None:
    session.add(AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "",
        action=action, entity=entity, entity_id=entity_id, details=details, source=source,
    ))


def recent(session: Session, limit: int = 500, user_id: int | None = None, action: str | None = None) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action.contains(action))
    return list(session.scalars(stmt))


ACTION_LABELS = {
    "login": "تسجيل دخول", "login_failed": "محاولة دخول فاشلة", "logout": "تسجيل خروج",
    "setup": "الإعداد الأولي", "password_changed": "تغيير كلمة السر", "password_reset": "استعادة الحساب",
    "user_created": "إضافة مستخدم", "user_updated": "تعديل مستخدم", "user_deleted": "حذف مستخدم",
    "product_created": "إضافة منتج", "product_updated": "تعديل منتج", "product_deleted": "حذف منتج",
    "price_bulk_update": "تحديث أسعار جماعي", "stock_adjusted": "تعديل مخزون",
    "sale": "بيع", "return": "مرتجع", "invoice_cancelled": "إلغاء فاتورة", "quotation": "عرض سعر",
    "purchase": "فاتورة شراء", "transfer": "نقل بضاعة", "count_applied": "تطبيق جرد",
    "expense": "مصروف", "shift_opened": "فتح وردية", "shift_closed": "إغلاق وردية",
    "rate_changed": "تغيير سعر صرف", "backup": "نسخ احتياطي", "restore": "استرجاع نسخة",
    "settings_changed": "تعديل الإعدادات", "device_revoked": "فصل جهاز", "payment": "دفعة زبون",
    "category_deleted": "حذف قسم", "field_created": "إضافة خانة", "field_deleted": "حذف خانة",
    "import": "استيراد", "export": "تصدير",
}
