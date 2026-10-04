"""مركز الإشعارات: نقص المخزون، الصلاحية، الديون، الفواتير الكبيرة."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ftapp.core.events import NOTIFICATIONS_CHANGED, bus
from ftapp.core.utils import fmt_qty
from ftapp.models import Batch, Customer, Notification, Product
from ftapp.services import settings_service as settings

KIND_LABELS = {
    "low_stock": "مخزون منخفض",
    "out_of_stock": "نفد من المخزون",
    "expiry": "قرب انتهاء الصلاحية",
    "expired": "منتهي الصلاحية",
    "debt": "دين متجاوز للحد",
    "large_invoice": "فاتورة كبيرة",
    "system": "النظام",
    "update": "تحديث متوفر",
}


def _upsert(session: Session, dedupe_key: str, kind: str, severity: str, title: str, body: str = "",
            entity: str = "", entity_id: int | None = None) -> Notification:
    n = session.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key))
    created = n is None
    if created:
        n = Notification(dedupe_key=dedupe_key)
        session.add(n)
    escalated = not created and (n.kind != kind)
    n.kind, n.severity, n.title, n.body, n.entity, n.entity_id = kind, severity, title, body, entity, entity_id
    if created or escalated:
        n.is_read = False
        from ftapp.core.utils import now
        n.created_at = now()
    session.flush()
    if created or escalated:
        bus.publish(NOTIFICATIONS_CHANGED, kind=kind, title=title, body=body, severity=severity,
                    entity=entity, entity_id=entity_id)
    return n


def _resolve(session: Session, dedupe_key: str) -> None:
    res = session.execute(delete(Notification).where(Notification.dedupe_key == dedupe_key))
    if res.rowcount:
        bus.publish(NOTIFICATIONS_CHANGED)


def add(session: Session, kind: str, title: str, body: str = "", severity: str = "info", entity: str = "",
        entity_id: int | None = None) -> Notification:
    """إشعار لمرة واحدة (بدون منع تكرار)."""
    n = Notification(kind=kind, title=title, body=body, severity=severity, entity=entity, entity_id=entity_id)
    session.add(n)
    session.flush()
    bus.publish(NOTIFICATIONS_CHANGED, kind=kind, title=title, body=body, severity=severity,
                entity=entity, entity_id=entity_id)
    return n


def check_product_stock(session: Session, product: Product) -> None:
    from ftapp.services import catalog_service

    key = f"stock:{product.id}"
    if not product.is_active:
        _resolve(session, key)
        return
    session.flush()
    session.refresh(product, attribute_names=["stock_levels"])
    status = catalog_service.stock_status(session, product)
    if status == "out":
        _upsert(session, key, "out_of_stock", "danger", f"نفد المنتج: {product.name}",
                f"الكود {product.code} — الكمية صفر", "product", product.id)
    elif status == "low":
        limit = catalog_service.min_stock_for(session, product)
        _upsert(session, key, "low_stock", "warning", f"قارب على النفاد: {product.name}",
                f"الكود {product.code} — المتبقي {fmt_qty(product.quantity)} {product.unit} (حد التنبيه {fmt_qty(limit)})",
                "product", product.id)
    else:
        _resolve(session, key)


def scan_all(session: Session) -> None:
    """فحص شامل دوري لكل أنواع التنبيهات."""
    from ftapp.services import catalog_service

    products, _ = catalog_service.search_products(session, active=None, limit=None)
    for p in products:
        check_product_stock(session, p)

    days = int(settings.get(session, "expiry_warning_days") or 30)
    today = date.today()
    active_keys = set()
    for b in session.scalars(select(Batch).where(Batch.quantity > 0, Batch.expiry_date.is_not(None),
                                                 Batch.expiry_date <= today + timedelta(days=days))):
        key = f"expiry:{b.id}"
        active_keys.add(key)
        expired = b.expiry_date < today
        _upsert(session, key, "expired" if expired else "expiry", "danger" if expired else "warning",
                f"{'انتهت صلاحية' if expired else 'تنتهي صلاحية'}: {b.product.name}",
                f"الكمية {fmt_qty(b.quantity)} — تاريخ الانتهاء {b.expiry_date:%Y-%m-%d}", "product", b.product_id)
    for n in session.scalars(select(Notification).where(Notification.dedupe_key.like("expiry:%"))):
        if n.dedupe_key not in active_keys:
            session.delete(n)

    for c in session.scalars(select(Customer).where(Customer.balance > 0)):
        key = f"debt:{c.id}"
        if c.credit_limit and c.balance > c.credit_limit:
            _upsert(session, key, "debt", "warning", f"دين متجاوز للحد: {c.name}",
                    f"الدين {c.balance:,.2f} — الحد {c.credit_limit:,.2f}", "customer", c.id)
        else:
            _resolve(session, key)
    session.flush()


def list_notifications(session: Session, unread_only: bool = False, limit: int = 300) -> list[Notification]:
    stmt = select(Notification).order_by(Notification.is_read, Notification.created_at.desc()).limit(limit)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return list(session.scalars(stmt))


def important_alerts(session: Session, limit: int = 50) -> list[Notification]:
    severity_order = {"danger": 0, "warning": 1, "info": 2}
    rows = list(session.scalars(select(Notification).where(Notification.kind.in_(
        ["low_stock", "out_of_stock", "expiry", "expired", "debt"]))))
    rows.sort(key=lambda n: (severity_order.get(n.severity, 3), -n.id))
    return rows[:limit]


def unread_count(session: Session) -> int:
    return session.scalar(select(func.count(Notification.id)).where(Notification.is_read.is_(False))) or 0


def mark_read(session: Session, notification_id: int | None = None) -> None:
    stmt = update(Notification).values(is_read=True)
    if notification_id:
        stmt = stmt.where(Notification.id == notification_id)
    session.execute(stmt)
    bus.publish(NOTIFICATIONS_CHANGED)


def clear_read(session: Session) -> None:
    session.execute(delete(Notification).where(Notification.is_read.is_(True), Notification.dedupe_key.is_(None)))
    bus.publish(NOTIFICATIONS_CHANGED)
