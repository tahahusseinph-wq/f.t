"""المستودعات، الكميات، حركات المخزون، الدفعات، النقل والجرد."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ftapp.core.events import STOCK_CHANGED, bus
from ftapp.core.utils import now, qty
from ftapp.models import (Batch, Product, StockCount, StockCountLine, StockLevel, StockMovement, Transfer,
                          TransferItem, User, Warehouse)
from ftapp.services import audit, settings_service as settings
from ftapp.services.errors import NotFound, ValidationError

MOVEMENT_KINDS = {
    "in": "إدخال", "out": "إخراج", "sale": "بيع", "return": "مرتجع", "adjust": "تعديل",
    "damage": "تالف", "purchase": "شراء", "transfer_in": "نقل وارد", "transfer_out": "نقل صادر",
    "count": "جرد", "cancel": "إلغاء فاتورة",
}


# ---------------- المستودعات ----------------

def list_warehouses(session: Session, active_only: bool = True) -> list[Warehouse]:
    stmt = select(Warehouse).order_by(Warehouse.is_default.desc(), Warehouse.name)
    if active_only:
        stmt = stmt.where(Warehouse.is_active.is_(True))
    return list(session.scalars(stmt))


def default_warehouse(session: Session) -> Warehouse:
    wh = session.scalar(select(Warehouse).where(Warehouse.is_default.is_(True)))
    if wh is None:
        wh = session.scalar(select(Warehouse).order_by(Warehouse.id))
    if wh is None:
        wh = Warehouse(name="المستودع الرئيسي", is_default=True)
        session.add(wh)
        session.flush()
    return wh


def save_warehouse(session: Session, name: str, location: str = "", is_default: bool = False,
                   warehouse_id: int | None = None, is_active: bool = True) -> Warehouse:
    if not name.strip():
        raise ValidationError("أدخل اسم المستودع")
    wh = session.get(Warehouse, warehouse_id) if warehouse_id else None
    if wh is None:
        wh = Warehouse()
        session.add(wh)
    if is_default:
        for other in session.scalars(select(Warehouse).where(Warehouse.is_default.is_(True))):
            other.is_default = False
    wh.name, wh.location, wh.is_default, wh.is_active = name.strip(), location, is_default, is_active
    session.flush()
    return wh


def delete_warehouse(session: Session, warehouse_id: int) -> None:
    wh = session.get(Warehouse, warehouse_id)
    if wh is None:
        return
    if wh.is_default:
        raise ValidationError("لا يمكن حذف المستودع الافتراضي")
    total = session.scalar(select(func.coalesce(func.sum(StockLevel.quantity), 0))
                           .where(StockLevel.warehouse_id == wh.id)) or 0
    if total > 0:
        raise ValidationError("المستودع يحتوي بضاعة، انقلها أولاً")
    wh.is_active = False


# ---------------- الكميات ----------------

def ensure_level(session: Session, product_id: int, warehouse_id: int) -> StockLevel:
    level = session.scalar(select(StockLevel).where(StockLevel.product_id == product_id,
                                                    StockLevel.warehouse_id == warehouse_id))
    if level is None:
        level = StockLevel(product_id=product_id, warehouse_id=warehouse_id, quantity=0.0)
        session.add(level)
        session.flush()
        product = session.get(Product, product_id)
        if product is not None and level not in product.stock_levels:
            product.stock_levels.append(level)
    return level


def quantity_in(session: Session, product_id: int, warehouse_id: int | None = None) -> float:
    stmt = select(func.coalesce(func.sum(StockLevel.quantity), 0)).where(StockLevel.product_id == product_id)
    if warehouse_id:
        stmt = stmt.where(StockLevel.warehouse_id == warehouse_id)
    return qty(session.scalar(stmt))


def _consume_batches(session: Session, product_id: int, warehouse_id: int, amount: float) -> None:
    """خصم الكمية من الدفعات بنظام الأقرب انتهاءً أولاً (FEFO)."""
    batches = session.scalars(select(Batch).where(Batch.product_id == product_id, Batch.warehouse_id == warehouse_id,
                                                  Batch.quantity > 0)
                              .order_by(Batch.expiry_date.is_(None), Batch.expiry_date, Batch.id)).all()
    remaining = amount
    for b in batches:
        if remaining <= 0:
            break
        take = min(b.quantity, remaining)
        b.quantity = qty(b.quantity - take)
        remaining = qty(remaining - take)


def adjust(session: Session, actor: User | None, product_id: int, warehouse_id: int | None, delta: float,
           kind: str, reason: str = "", ref_type: str = "", ref_id: int | None = None,
           expiry: date | None = None, batch_no: str = "", allow_negative: bool | None = None) -> StockMovement:
    """تغيير كمية منتج في مستودع وتسجيل الحركة."""
    from ftapp.services import notification_service

    if delta == 0:
        raise ValidationError("الكمية يجب ألا تكون صفراً")
    product = session.get(Product, product_id)
    if product is None:
        raise NotFound("المنتج غير موجود")
    warehouse_id = warehouse_id or default_warehouse(session).id
    level = ensure_level(session, product_id, warehouse_id)
    new_qty = qty(level.quantity + delta)
    if allow_negative is None:
        allow_negative = bool(settings.get(session, "allow_negative_stock"))
    if new_qty < 0 and not allow_negative:
        raise ValidationError(f"الكمية غير كافية من «{product.name}» (المتوفر {qty(level.quantity):g})")
    level.quantity = new_qty
    product.updated_at = now()  # حتى تلتقط مزامنة الموبايل تغيّر الكمية

    if product.track_expiry:
        if delta > 0:
            session.add(Batch(product_id=product_id, warehouse_id=warehouse_id, batch_no=batch_no,
                              expiry_date=expiry, quantity=delta))
        else:
            _consume_batches(session, product_id, warehouse_id, -delta)

    mv = StockMovement(product_id=product_id, warehouse_id=warehouse_id, kind=kind, quantity=qty(delta),
                       balance_after=0.0,
                       ref_type=ref_type, ref_id=ref_id, reason=reason, user_id=actor.id if actor else None)
    session.add(mv)
    session.flush()
    mv.balance_after = quantity_in(session, product_id)
    notification_service.check_product_stock(session, product)
    bus.publish(STOCK_CHANGED, product_id=product_id)
    return mv


def set_quantity(session: Session, actor: User | None, product_id: int, warehouse_id: int | None,
                 new_quantity: float, reason: str = "تعديل يدوي", kind: str = "adjust") -> StockMovement | None:
    warehouse_id = warehouse_id or default_warehouse(session).id
    current = quantity_in(session, product_id, warehouse_id)
    delta = qty(new_quantity - current)
    if delta == 0:
        return None
    mv = adjust(session, actor, product_id, warehouse_id, delta, kind, reason, allow_negative=True)
    audit.log(session, actor, "stock_adjusted", "product", product_id, old=current, new=new_quantity, reason=reason)
    return mv


def movements(session: Session, product_id: int | None = None, warehouse_id: int | None = None,
              kind: str | None = None, date_from: date | None = None, date_to: date | None = None,
              limit: int = 1000) -> list[StockMovement]:
    stmt = (select(StockMovement).options(selectinload(StockMovement.product), selectinload(StockMovement.warehouse))
            .order_by(StockMovement.id.desc()).limit(limit))
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if warehouse_id:
        stmt = stmt.where(StockMovement.warehouse_id == warehouse_id)
    if kind:
        stmt = stmt.where(StockMovement.kind == kind)
    if date_from:
        stmt = stmt.where(StockMovement.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        stmt = stmt.where(StockMovement.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    return list(session.scalars(stmt))


def low_stock_products(session: Session, include_out: bool = True) -> list[Product]:
    from ftapp.services import catalog_service

    products, _ = catalog_service.search_products(session, stock_filter="low", limit=None)
    if not include_out:
        products = [p for p in products if p.quantity > 0]
    return sorted(products, key=lambda p: p.quantity)


def batches(session: Session, product_id: int | None = None, expiring_within: int | None = None,
            include_empty: bool = False) -> list[Batch]:
    stmt = select(Batch).options(selectinload(Batch.product), selectinload(Batch.warehouse)).order_by(Batch.expiry_date)
    if product_id:
        stmt = stmt.where(Batch.product_id == product_id)
    if not include_empty:
        stmt = stmt.where(Batch.quantity > 0)
    if expiring_within is not None:
        stmt = stmt.where(Batch.expiry_date.is_not(None),
                          Batch.expiry_date <= date.today() + timedelta(days=expiring_within))
    return list(session.scalars(stmt))


def valuation(session: Session, warehouse_id: int | None = None) -> dict[str, float]:
    stmt = (select(func.coalesce(func.sum(StockLevel.quantity * Product.cost_price), 0),
                   func.coalesce(func.sum(StockLevel.quantity * Product.sale_price), 0),
                   func.coalesce(func.sum(StockLevel.quantity), 0))
            .join(Product, Product.id == StockLevel.product_id)
            .where(Product.is_active.is_(True), StockLevel.quantity > 0))
    if warehouse_id:
        stmt = stmt.where(StockLevel.warehouse_id == warehouse_id)
    cost, sale, units = session.execute(stmt).one()
    return {"cost": round(cost, 2), "sale": round(sale, 2), "units": round(units, 3)}


# ---------------- النقل بين المستودعات ----------------

def create_transfer(session: Session, actor: User | None, from_id: int, to_id: int,
                    items: list[tuple[int, float]], notes: str = "") -> Transfer:
    if from_id == to_id:
        raise ValidationError("اختر مستودعين مختلفين")
    items = [(pid, q) for pid, q in items if q > 0]
    if not items:
        raise ValidationError("أضف منتجات للنقل")
    tr = Transfer(from_warehouse_id=from_id, to_warehouse_id=to_id, user_id=actor.id if actor else None, notes=notes)
    session.add(tr)
    session.flush()
    for pid, q in items:
        product = session.get(Product, pid)
        expiry = None
        if product and product.track_expiry:
            first = session.scalar(select(Batch).where(Batch.product_id == pid, Batch.warehouse_id == from_id,
                                                       Batch.quantity > 0).order_by(Batch.expiry_date))
            expiry = first.expiry_date if first else None
        adjust(session, actor, pid, from_id, -q, "transfer_out", notes, "transfer", tr.id, allow_negative=False)
        adjust(session, actor, pid, to_id, q, "transfer_in", notes, "transfer", tr.id, expiry=expiry)
        tr.items.append(TransferItem(product_id=pid, quantity=q))
    audit.log(session, actor, "transfer", "transfer", tr.id, items=len(items))
    return tr


def list_transfers(session: Session, limit: int = 300) -> list[Transfer]:
    return list(session.scalars(select(Transfer).order_by(Transfer.id.desc()).limit(limit)))


# ---------------- الجرد الفعلي ----------------

def open_counts(session: Session) -> list[StockCount]:
    return list(session.scalars(select(StockCount).where(StockCount.status == "open").order_by(StockCount.id.desc())))


def list_counts(session: Session, limit: int = 100) -> list[StockCount]:
    return list(session.scalars(select(StockCount).order_by(StockCount.id.desc()).limit(limit)))


def start_count(session: Session, actor: User | None, warehouse_id: int | None = None, notes: str = "") -> StockCount:
    count = StockCount(warehouse_id=warehouse_id or default_warehouse(session).id, notes=notes,
                       created_by=actor.id if actor else None)
    session.add(count)
    session.flush()
    return count


def get_count(session: Session, count_id: int) -> StockCount:
    count = session.get(StockCount, count_id)
    if count is None:
        raise NotFound("جلسة الجرد غير موجودة")
    return count


def set_count_line(session: Session, count_id: int, product_id: int, counted: float, mode: str = "set"
                   ) -> StockCountLine:
    count = get_count(session, count_id)
    if count.status != "open":
        raise ValidationError("جلسة الجرد مغلقة")
    if counted < 0:
        raise ValidationError("الكمية لا يمكن أن تكون سالبة")
    line = session.scalar(select(StockCountLine).where(StockCountLine.count_id == count_id,
                                                       StockCountLine.product_id == product_id))
    if line is None:
        line = StockCountLine(count_id=count_id, product_id=product_id,
                              system_qty=quantity_in(session, product_id, count.warehouse_id), counted_qty=0)
        session.add(line)
        count.lines.append(line)
    line.counted_qty = qty(line.counted_qty + counted) if mode == "add" else qty(counted)
    session.flush()
    return line


def remove_count_line(session: Session, line_id: int) -> None:
    line = session.get(StockCountLine, line_id)
    if line:
        session.delete(line)


def apply_count(session: Session, actor: User | None, count_id: int) -> int:
    count = get_count(session, count_id)
    if count.status != "open":
        raise ValidationError("تم تطبيق هذا الجرد مسبقاً")
    changed = 0
    for line in count.lines:
        current = quantity_in(session, line.product_id, count.warehouse_id)
        delta = qty(line.counted_qty - current)
        if delta:
            adjust(session, actor, line.product_id, count.warehouse_id, delta, "count",
                   f"جرد رقم {count.id}", "count", count.id, allow_negative=True)
            changed += 1
    count.status = "applied"
    count.applied_at = now()
    audit.log(session, actor, "count_applied", "count", count.id, changed=changed)
    return changed


def cancel_count(session: Session, count_id: int) -> None:
    count = get_count(session, count_id)
    if count.status == "open":
        count.status = "cancelled"
