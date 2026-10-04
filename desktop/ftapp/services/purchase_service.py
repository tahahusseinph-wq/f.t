"""فواتير الشراء من الموردين."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ftapp.core.events import PRODUCTS_CHANGED, bus
from ftapp.core.utils import money
from ftapp.models import Product, PurchaseInvoice, PurchaseItem, Supplier, User
from ftapp.services import audit, catalog_service, inventory_service, numbering
from ftapp.services.errors import NotFound, ValidationError


@dataclass
class PurchaseLine:
    product_id: int
    quantity: float
    unit_cost: float
    batch_no: str = ""
    expiry_date: date | None = None


def create_purchase(session: Session, actor: User | None, supplier_id: int | None, warehouse_id: int | None,
                    lines: list[PurchaseLine], paid: float = 0.0, notes: str = "", supplier_ref: str = "",
                    update_cost: bool = True) -> PurchaseInvoice:
    lines = [ln for ln in lines if ln.quantity > 0]
    if not lines:
        raise ValidationError("أضف أصنافاً لفاتورة الشراء")
    warehouse_id = warehouse_id or inventory_service.default_warehouse(session).id
    inv = PurchaseInvoice(number=numbering.next_document_number(session, "purchase"), supplier_id=supplier_id,
                          warehouse_id=warehouse_id, user_id=actor.id if actor else None, notes=notes,
                          supplier_ref=supplier_ref)
    session.add(inv)
    session.flush()
    total = 0.0
    for ln in lines:
        product = session.get(Product, ln.product_id)
        if product is None:
            raise NotFound("منتج غير موجود في الفاتورة")
        if ln.unit_cost < 0:
            raise ValidationError("سعر الشراء لا يمكن أن يكون سالباً")
        inv.items.append(PurchaseItem(product_id=product.id, quantity=ln.quantity, unit_cost=money(ln.unit_cost),
                                      batch_no=ln.batch_no, expiry_date=ln.expiry_date))
        inventory_service.adjust(session, actor, product.id, warehouse_id, ln.quantity, "purchase",
                                 f"فاتورة شراء {inv.number}", "purchase", inv.id,
                                 expiry=ln.expiry_date, batch_no=ln.batch_no)
        if update_cost and ln.unit_cost > 0 and abs(product.cost_price - ln.unit_cost) > 1e-9:
            old_cost, old_price = product.cost_price, product.sale_price
            product.cost_price = money(ln.unit_cost)
            catalog_service.recompute_price(session, product)
            catalog_service._record_price_change(session, product, old_cost, old_price, actor,
                                                 f"فاتورة شراء {inv.number}")
        if supplier_id and not product.supplier_id:
            product.supplier_id = supplier_id
        total += ln.quantity * ln.unit_cost
    inv.total = money(total)
    inv.paid = money(min(paid, inv.total)) if paid else 0.0
    if supplier_id:
        supplier = session.get(Supplier, supplier_id)
        if supplier:
            supplier.balance = money(supplier.balance + inv.total - inv.paid)
    audit.log(session, actor, "purchase", "purchase", inv.id, number=inv.number, total=inv.total)
    bus.publish(PRODUCTS_CHANGED)
    return inv


def list_purchases(session: Session, supplier_id: int | None = None, limit: int = 500) -> list[PurchaseInvoice]:
    stmt = (select(PurchaseInvoice).options(selectinload(PurchaseInvoice.supplier), selectinload(PurchaseInvoice.items))
            .order_by(PurchaseInvoice.id.desc()).limit(limit))
    if supplier_id:
        stmt = stmt.where(PurchaseInvoice.supplier_id == supplier_id)
    return list(session.scalars(stmt))


def pay_supplier(session: Session, actor: User | None, supplier_id: int, amount: float) -> Supplier:
    supplier = session.get(Supplier, supplier_id)
    if supplier is None:
        raise NotFound("المورد غير موجود")
    if amount <= 0:
        raise ValidationError("أدخل مبلغاً صحيحاً")
    supplier.balance = money(supplier.balance - amount)
    audit.log(session, actor, "payment", "supplier", supplier.id, amount=amount)
    return supplier
