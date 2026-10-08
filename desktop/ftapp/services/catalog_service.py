"""الأقسام، المنتجات، المتغيرات، الخانات المخصصة، التسعير والعروض."""
from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ftapp.core.events import PRODUCTS_CHANGED, bus
from ftapp.core.paths import sub_dir
from ftapp.core.utils import money
from ftapp.models import (Category, Currency, CustomField, InvoiceItem, PriceHistory, PriceTier, Product,
                          ProductFieldValue, ProductImage, ProductTierPrice, Promotion, StockLevel,
                          StockMovement, Supplier, User)
from ftapp.services import audit, codegen_service, settings_service as settings
from ftapp.services.errors import NotFound, ValidationError

FIELD_TYPES = {
    "text": "نص",
    "number": "رقم صحيح",
    "decimal": "رقم عشري",
    "date": "تاريخ",
    "bool": "نعم / لا",
    "choice": "قائمة اختيارات",
    "url": "رابط",
    "image": "صورة",
}

UNITS = ["قطعة", "علبة", "كرتونة", "دزينة", "متر", "كيلو", "لتر", "طقم", "رول", "زوج"]


# =====================================================================
# الأقسام
# =====================================================================

def list_categories(session: Session) -> list[Category]:
    return list(session.scalars(select(Category).order_by(Category.parent_id.is_not(None), Category.sort_order,
                                                          Category.name)))


def category_tree(session: Session) -> list[tuple[Category, int]]:
    """قائمة مسطحة مرتبة كشجرة مع العمق."""
    cats = list_categories(session)
    by_parent: dict[int | None, list[Category]] = {}
    for c in cats:
        by_parent.setdefault(c.parent_id, []).append(c)
    out: list[tuple[Category, int]] = []

    def walk(parent_id: int | None, depth: int) -> None:
        for c in sorted(by_parent.get(parent_id, []), key=lambda x: (x.sort_order, x.name)):
            out.append((c, depth))
            walk(c.id, depth + 1)

    walk(None, 0)
    return out


def category_path(cat: Category | None) -> str:
    names = []
    while cat is not None:
        names.append(cat.name)
        cat = cat.parent
    return " / ".join(reversed(names))


def descendant_ids(session: Session, category_id: int) -> list[int]:
    ids = [category_id]
    frontier = [category_id]
    while frontier:
        children = session.scalars(select(Category.id).where(Category.parent_id.in_(frontier))).all()
        frontier = [c for c in children if c not in ids]
        ids.extend(frontier)
    return ids


def ancestor_ids(session: Session, category_id: int | None) -> list[int]:
    ids = []
    cat = session.get(Category, category_id) if category_id else None
    while cat is not None and cat.id not in ids:
        ids.append(cat.id)
        cat = cat.parent
    return ids


def save_category(session: Session, actor: User | None, name: str, code: str = "", parent_id: int | None = None,
                  default_margin: float | None = None, color: str = "#1565C0", category_id: int | None = None,
                  sort_order: int = 0) -> Category:
    name = (name or "").strip()
    if not name:
        raise ValidationError("أدخل اسم القسم")
    code = re.sub(r"[^A-Za-z0-9]", "", code or "").upper()[:6]
    if category_id:
        cat = session.get(Category, category_id)
        if cat is None:
            raise NotFound("القسم غير موجود")
        if parent_id and parent_id in descendant_ids(session, cat.id):
            raise ValidationError("لا يمكن نقل القسم داخل أحد أقسامه الفرعية")
    else:
        cat = Category()
        session.add(cat)
    cat.name, cat.code, cat.parent_id = name, code, parent_id or None
    cat.default_margin, cat.color, cat.sort_order = default_margin, color, sort_order
    session.flush()
    bus.publish(PRODUCTS_CHANGED)
    return cat


def delete_category(session: Session, actor: User | None, category_id: int) -> None:
    cat = session.get(Category, category_id)
    if cat is None:
        raise NotFound("القسم غير موجود")
    if session.scalar(select(func.count(Category.id)).where(Category.parent_id == cat.id)):
        raise ValidationError("القسم يحتوي أقساماً فرعية، انقلها أو احذفها أولاً")
    count = session.scalar(select(func.count(Product.id)).where(Product.category_id == cat.id)) or 0
    if count:
        raise ValidationError(f"القسم يحتوي {count} منتج، انقلها إلى قسم آخر أولاً")
    audit.log(session, actor, "category_deleted", "category", cat.id, name=cat.name)
    session.delete(cat)
    bus.publish(PRODUCTS_CHANGED)


def move_products(session: Session, product_ids: Iterable[int], category_id: int | None) -> int:
    n = 0
    for p in session.scalars(select(Product).where(Product.id.in_(list(product_ids)))):
        p.category_id = category_id
        n += 1
    bus.publish(PRODUCTS_CHANGED)
    return n


# =====================================================================
# التسعير
# =====================================================================

def effective_margin(session: Session, product: Product) -> float | None:
    if product.margin is not None:
        return product.margin
    for cid in ancestor_ids(session, product.category_id):
        cat = session.get(Category, cid)
        if cat and cat.default_margin is not None:
            return cat.default_margin
    return None


def price_from_margin(cost: float, margin: float | None) -> float:
    if margin is None:
        return money(cost)
    return money(cost * (1 + margin / 100.0))


def recompute_price(session: Session, product: Product) -> None:
    if product.price_locked:
        return
    margin = effective_margin(session, product)
    if margin is not None:
        product.sale_price = price_from_margin(product.cost_price, margin)


def actual_margin_percent(product: Product) -> float | None:
    if not product.cost_price:
        return None
    return round((product.sale_price - product.cost_price) / product.cost_price * 100, 2)


def active_promotion(session: Session, product: Product, on: date | None = None) -> Promotion | None:
    on = on or date.today()
    cat_ids = ancestor_ids(session, product.category_id)
    product_ids = [product.id] + ([product.parent_id] if product.parent_id else [])
    stmt = select(Promotion).where(
        Promotion.is_active.is_(True), Promotion.start_date <= on, Promotion.end_date >= on,
        or_(Promotion.product_id.in_(product_ids), Promotion.category_id.in_(cat_ids or [-1])),
    ).order_by(Promotion.percent.desc())
    return session.scalars(stmt).first()


def tier_price(session: Session, product: Product, tier_id: int | None) -> float:
    """سعر المنتج لشريحة معينة قبل العروض."""
    if tier_id:
        tier = session.get(PriceTier, tier_id)
        if tier and not tier.is_default:
            explicit = next((tp.price for tp in product.tier_prices if tp.tier_id == tier_id and tp.price > 0), None)
            if explicit is not None:
                return money(explicit)
            if tier.default_margin is not None and product.cost_price:
                return price_from_margin(product.cost_price, tier.default_margin)
    return money(product.sale_price)


def final_price(session: Session, product: Product, tier_id: int | None = None) -> tuple[float, Promotion | None]:
    price = tier_price(session, product, tier_id)
    promo = active_promotion(session, product)
    if promo:
        price = money(price * (1 - promo.percent / 100.0))
    return price, promo


def _record_price_change(session: Session, product: Product, old_cost: float, old_price: float,
                         actor: User | None, reason: str) -> None:
    if abs(old_cost - product.cost_price) > 1e-9 or abs(old_price - product.sale_price) > 1e-9:
        session.add(PriceHistory(product_id=product.id, old_cost=old_cost, new_cost=product.cost_price,
                                 old_price=old_price, new_price=product.sale_price, reason=reason,
                                 user_id=actor.id if actor else None))


def price_history(session: Session, product_id: int) -> list[PriceHistory]:
    return list(session.scalars(select(PriceHistory).where(PriceHistory.product_id == product_id)
                                .order_by(PriceHistory.changed_at)))


def list_tiers(session: Session) -> list[PriceTier]:
    return list(session.scalars(select(PriceTier).order_by(PriceTier.sort_order, PriceTier.id)))


def save_tier(session: Session, name: str, default_margin: float | None, tier_id: int | None = None) -> PriceTier:
    if not name.strip():
        raise ValidationError("أدخل اسم الشريحة")
    tier = session.get(PriceTier, tier_id) if tier_id else None
    if tier is None:
        tier = PriceTier(sort_order=len(list_tiers(session)))
        session.add(tier)
    tier.name, tier.default_margin = name.strip(), default_margin
    session.flush()
    return tier


def delete_tier(session: Session, tier_id: int) -> None:
    tier = session.get(PriceTier, tier_id)
    if tier is None:
        return
    if tier.is_default:
        raise ValidationError("لا يمكن حذف شريحة المفرّق الافتراضية")
    session.delete(tier)


@dataclass
class BulkPriceFilter:
    category_id: int | None = None
    brand: str | None = None
    supplier_id: int | None = None
    product_ids: list[int] | None = None


def bulk_price_preview(session: Session, flt: BulkPriceFilter, percent: float, target: str = "both"
                       ) -> list[tuple[Product, float, float, float, float]]:
    """يعيد (المنتج، التكلفة القديمة، الجديدة، السعر القديم، الجديد) بدون حفظ."""
    stmt = select(Product).where(Product.is_active.is_(True))
    if flt.product_ids:
        stmt = stmt.where(Product.id.in_(flt.product_ids))
    if flt.category_id:
        stmt = stmt.where(Product.category_id.in_(descendant_ids(session, flt.category_id)))
    if flt.brand:
        stmt = stmt.where(Product.brand == flt.brand)
    if flt.supplier_id:
        stmt = stmt.where(Product.supplier_id == flt.supplier_id)
    factor = 1 + percent / 100.0
    out = []
    for p in session.scalars(stmt.order_by(Product.name)):
        new_cost = money(p.cost_price * factor) if target in ("cost", "both") else p.cost_price
        if target in ("price", "both"):
            new_price = money(p.sale_price * factor)
        elif not p.price_locked and effective_margin(session, p) is not None:
            new_price = price_from_margin(new_cost, effective_margin(session, p))
        else:
            new_price = p.sale_price
        out.append((p, p.cost_price, new_cost, p.sale_price, new_price))
    return out


def bulk_price_apply(session: Session, actor: User | None, flt: BulkPriceFilter, percent: float,
                     target: str = "both") -> int:
    rows = bulk_price_preview(session, flt, percent, target)
    for p, old_cost, new_cost, old_price, new_price in rows:
        p.cost_price, p.sale_price = new_cost, new_price
        _record_price_change(session, p, old_cost, old_price, actor, f"تحديث جماعي {percent:+g}%")
    audit.log(session, actor, "price_bulk_update", "product", None, percent=percent, target=target, count=len(rows))
    bus.publish(PRODUCTS_CHANGED)
    return len(rows)


# =====================================================================
# الخانات المخصصة
# =====================================================================

def list_fields(session: Session, category_id: int | None = None, all_fields: bool = False) -> list[CustomField]:
    stmt = select(CustomField).order_by(CustomField.sort_order, CustomField.id)
    if not all_fields:
        cats = ancestor_ids(session, category_id) if category_id else []
        stmt = stmt.where(or_(CustomField.category_id.is_(None), CustomField.category_id.in_(cats or [-1])))
    return list(session.scalars(stmt))


def _field_key(name: str) -> str:
    base = codegen_service.transliterate(name).lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_") or "field"
    return f"{base[:40]}_{uuid.uuid4().hex[:4]}"


def save_field(session: Session, actor: User | None, name: str, field_type: str = "text", required: bool = False,
               default_value: str = "", options: list[str] | None = None, category_id: int | None = None,
               visible_to_users: bool = True, sort_order: int | None = None, field_id: int | None = None
               ) -> CustomField:
    name = name.strip()
    if not name:
        raise ValidationError("أدخل اسم الخانة")
    if field_type not in FIELD_TYPES:
        raise ValidationError("نوع خانة غير معروف")
    if field_type == "choice" and not options:
        raise ValidationError("أضف خيارات القائمة")
    if field_id:
        fld = session.get(CustomField, field_id)
        if fld is None:
            raise NotFound("الخانة غير موجودة")
    else:
        fld = CustomField(key=_field_key(name))
        session.add(fld)
        audit.log(session, actor, "field_created", "field", None, name=name)
    fld.name, fld.field_type, fld.required = name, field_type, required
    fld.default_value, fld.options = default_value or "", [o.strip() for o in (options or []) if o.strip()]
    fld.category_id, fld.visible_to_users = category_id, visible_to_users
    if sort_order is not None:
        fld.sort_order = sort_order
    elif not field_id:
        fld.sort_order = (session.scalar(select(func.max(CustomField.sort_order))) or 0) + 1
    session.flush()
    bus.publish(PRODUCTS_CHANGED)
    return fld


def delete_field(session: Session, actor: User | None, field_id: int) -> None:
    fld = session.get(CustomField, field_id)
    if fld:
        audit.log(session, actor, "field_deleted", "field", fld.id, name=fld.name)
        session.delete(fld)
        bus.publish(PRODUCTS_CHANGED)


def reorder_fields(session: Session, ordered_ids: list[int]) -> None:
    for i, fid in enumerate(ordered_ids):
        fld = session.get(CustomField, fid)
        if fld:
            fld.sort_order = i


def validate_field_value(fld: CustomField, value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        if fld.required:
            raise ValidationError(f"الخانة «{fld.name}» إجبارية")
        return ""
    try:
        if fld.field_type == "number":
            return str(int(float(text)))
        if fld.field_type == "decimal":
            return str(float(text))
        if fld.field_type == "date":
            return date.fromisoformat(text[:10]).isoformat()
        if fld.field_type == "bool":
            return "1" if text.lower() in ("1", "true", "yes", "نعم", "y") else "0"
        if fld.field_type == "choice" and fld.options and text not in fld.options:
            raise ValidationError(f"القيمة «{text}» غير موجودة في خيارات «{fld.name}»")
    except ValueError:
        raise ValidationError(f"قيمة غير صالحة في الخانة «{fld.name}»")
    return text


def display_field_value(fld: CustomField, value: str) -> str:
    if fld.field_type == "bool":
        return "نعم" if value == "1" else ("لا" if value == "0" else "")
    return value or ""


# =====================================================================
# المنتجات
# =====================================================================

@dataclass
class ProductInput:
    name: str
    code: str = ""
    barcode: str = ""
    category_id: int | None = None
    brand: str = ""
    model: str = ""
    unit: str = "قطعة"
    cost_price: float = 0.0
    margin: float | None = None
    price_locked: bool = False
    sale_price: float = 0.0
    min_stock: float | None = None
    supplier_id: int | None = None
    location: str = ""
    details: str = ""
    specs: dict = field(default_factory=dict)
    notes: str = ""
    is_active: bool = True
    track_expiry: bool = False
    warranty: str = ""                # مدة الكفالة (مثال: سنة)، فارغ = بدون كفالة
    initial_quantity: float = 0.0
    initial_warehouse_id: int | None = None
    initial_expiry: date | None = None
    custom_values: dict[int, Any] = field(default_factory=dict)
    tier_prices: dict[int, float] = field(default_factory=dict)
    variant_attrs: dict = field(default_factory=dict)
    parent_id: int | None = None


def _apply_input(session: Session, p: Product, data: ProductInput) -> None:
    name = (data.name or "").strip()
    if not name:
        raise ValidationError("أدخل اسم المنتج")
    if data.cost_price < 0 or data.sale_price < 0:
        raise ValidationError("الأسعار لا يمكن أن تكون سالبة")
    code = (data.code or "").strip().upper()
    if not code:
        code = codegen_service.generate_code(session, name, data.category_id, data.brand, data.model, p.id)
    if codegen_service.code_exists(session, code, p.id):
        raise ValidationError(f"الكود «{code}» مستخدم لمنتج آخر")
    barcode = (data.barcode or "").strip() or None
    if barcode:
        dup = session.scalar(select(Product.id).where(Product.barcode == barcode, Product.id != (p.id or -1)))
        if dup:
            raise ValidationError(f"الباركود «{barcode}» مستخدم لمنتج آخر")
    p.name, p.code, p.barcode = name, code, barcode
    p.category_id, p.brand, p.model, p.unit = data.category_id, data.brand.strip(), data.model.strip(), data.unit
    p.cost_price, p.margin, p.price_locked = money(data.cost_price), data.margin, data.price_locked
    p.sale_price = money(data.sale_price)
    p.min_stock, p.supplier_id, p.location = data.min_stock, data.supplier_id, data.location
    p.details, p.specs, p.notes = data.details, dict(data.specs or {}), data.notes
    p.is_active, p.track_expiry = data.is_active, data.track_expiry
    p.warranty = (data.warranty or "").strip()[:64]
    p.variant_attrs, p.parent_id = dict(data.variant_attrs or {}), data.parent_id
    recompute_price(session, p)


def _apply_custom_values(session: Session, p: Product, values: dict[int, Any]) -> None:
    fields = {f.id: f for f in list_fields(session, p.category_id)}
    existing = {fv.field_id: fv for fv in p.field_values}
    for fid, fld in fields.items():
        raw = values.get(fid, existing[fid].value if fid in existing else fld.default_value)
        val = validate_field_value(fld, raw)
        if fid in existing:
            existing[fid].value = val
        elif val:
            p.field_values.append(ProductFieldValue(field_id=fid, value=val))


def _apply_tier_prices(p: Product, tier_prices: dict[int, float]) -> None:
    existing = {tp.tier_id: tp for tp in p.tier_prices}
    for tier_id, price in tier_prices.items():
        if price and price > 0:
            if tier_id in existing:
                existing[tier_id].price = money(price)
            else:
                p.tier_prices.append(ProductTierPrice(tier_id=tier_id, price=money(price)))
        elif tier_id in existing:
            p.tier_prices.remove(existing[tier_id])


def create_product(session: Session, actor: User | None, data: ProductInput, source: str = "desktop") -> Product:
    from ftapp.services import inventory_service

    p = Product()
    _apply_input(session, p, data)
    session.add(p)
    session.flush()
    _apply_custom_values(session, p, data.custom_values)
    _apply_tier_prices(p, data.tier_prices)
    wh = data.initial_warehouse_id or inventory_service.default_warehouse(session).id
    inventory_service.ensure_level(session, p.id, wh)
    if data.initial_quantity:
        inventory_service.adjust(session, actor, p.id, wh, data.initial_quantity, "in", "رصيد افتتاحي",
                                 expiry=data.initial_expiry)
    session.add(PriceHistory(product_id=p.id, old_cost=0, new_cost=p.cost_price, old_price=0,
                             new_price=p.sale_price, reason="إضافة المنتج", user_id=actor.id if actor else None))
    audit.log(session, actor, "product_created", "product", p.id, source=source, code=p.code, name=p.name)
    session.flush()
    bus.publish(PRODUCTS_CHANGED, product_id=p.id)
    return p


def update_product(session: Session, actor: User | None, product_id: int, data: ProductInput,
                   source: str = "desktop") -> Product:
    p = get_product(session, product_id)
    old_cost, old_price = p.cost_price, p.sale_price
    _apply_input(session, p, data)
    _apply_custom_values(session, p, data.custom_values)
    _apply_tier_prices(p, data.tier_prices)
    _record_price_change(session, p, old_cost, old_price, actor, "تعديل المنتج")
    audit.log(session, actor, "product_updated", "product", p.id, source=source, code=p.code)
    session.flush()
    bus.publish(PRODUCTS_CHANGED, product_id=p.id)
    return p


def product_input_from(p: Product) -> ProductInput:
    return ProductInput(
        name=p.name, code=p.code, barcode=p.barcode or "", category_id=p.category_id, brand=p.brand,
        model=p.model, unit=p.unit, cost_price=p.cost_price, margin=p.margin, price_locked=p.price_locked,
        sale_price=p.sale_price, min_stock=p.min_stock, supplier_id=p.supplier_id, location=p.location,
        details=p.details, specs=dict(p.specs or {}), notes=p.notes, is_active=p.is_active,
        track_expiry=p.track_expiry, warranty=p.warranty or "", custom_values={fv.field_id: fv.value for fv in p.field_values},
        tier_prices={tp.tier_id: tp.price for tp in p.tier_prices}, variant_attrs=dict(p.variant_attrs or {}),
        parent_id=p.parent_id,
    )


def delete_product(session: Session, actor: User | None, product_id: int) -> str:
    """يحذف المنتج، أو يوقفه إذا كان له مبيعات سابقة. يعيد 'deleted' أو 'deactivated'."""
    p = get_product(session, product_id)
    sold = session.scalar(select(func.count(InvoiceItem.id)).where(InvoiceItem.product_id == p.id)) or 0
    moves = session.scalar(select(func.count(StockMovement.id)).where(StockMovement.product_id == p.id)) or 0
    if sold or moves > 1:
        p.is_active = False
        audit.log(session, actor, "product_updated", "product", p.id, deactivated=True)
        bus.publish(PRODUCTS_CHANGED, product_id=p.id)
        return "deactivated"
    audit.log(session, actor, "product_deleted", "product", p.id, code=p.code, name=p.name)
    session.delete(p)
    bus.publish(PRODUCTS_CHANGED, product_id=product_id)
    return "deleted"


def get_product(session: Session, product_id: int) -> Product:
    p = session.get(Product, product_id)
    if p is None:
        raise NotFound("المنتج غير موجود")
    return p


def find_by_code(session: Session, text: str) -> Product | None:
    text = (text or "").strip()
    if not text:
        return None
    stmt = select(Product).where(or_(func.upper(Product.code) == text.upper(), Product.barcode == text))
    return session.scalars(stmt).first()


def _load_opts():
    return (selectinload(Product.stock_levels), selectinload(Product.category),
            selectinload(Product.field_values), selectinload(Product.tier_prices))


_AR_MAP = {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ـ": ""}


def normalize_ar(text: str) -> str:
    """توحيد كتابة الحروف العربية للبحث (أحمد = احمد، شاشة = شاشه)."""
    text = (text or "").lower()
    for a, b in _AR_MAP.items():
        text = text.replace(a, b)
    return text


def _norm_sql(col):
    expr = func.lower(func.coalesce(col, ""))
    for a, b in _AR_MAP.items():
        expr = func.replace(expr, a, b)
    return expr


def search_products(session: Session, query: str = "", category_id: int | None = None, brand: str | None = None,
                    supplier_id: int | None = None, active: bool | None = True, stock_filter: str = "all",
                    include_variants: bool = True, limit: int | None = 200, offset: int = 0,
                    order: str = "name") -> tuple[list[Product], int]:
    """stock_filter: all, low, out, available."""
    stmt = select(Product).options(*_load_opts())
    q = (query or "").strip()
    if q:
        # كل كلمة يجب أن تظهر في الاسم أو الكود أو الباركود أو الماركة أو الموديل (بغض النظر عن الترتيب
        # وعن اختلاف كتابة الهمزات والتاء المربوطة والألف المقصورة)
        cols = [_norm_sql(c) for c in (Product.name, Product.code, Product.barcode, Product.brand, Product.model,
                                       Product.details)]
        for token in normalize_ar(q).split():
            like = f"%{token}%"
            stmt = stmt.where(or_(*[c.like(like) for c in cols]))
    if category_id:
        stmt = stmt.where(Product.category_id.in_(descendant_ids(session, category_id)))
    if brand:
        stmt = stmt.where(Product.brand == brand)
    if supplier_id:
        stmt = stmt.where(Product.supplier_id == supplier_id)
    if active is not None:
        stmt = stmt.where(Product.is_active.is_(active))
    if not include_variants:
        stmt = stmt.where(Product.parent_id.is_(None))

    if stock_filter != "all":
        default_min = float(settings.get(session, "default_min_stock") or 0)
        qty_sub = (select(StockLevel.product_id, func.coalesce(func.sum(StockLevel.quantity), 0).label("q"))
                   .group_by(StockLevel.product_id).subquery())
        stmt = stmt.outerjoin(qty_sub, qty_sub.c.product_id == Product.id)
        qcol = func.coalesce(qty_sub.c.q, 0)
        if stock_filter == "out":
            stmt = stmt.where(qcol <= 0)
        elif stock_filter == "low":
            stmt = stmt.where(qcol <= func.coalesce(Product.min_stock, default_min))
        elif stock_filter == "available":
            stmt = stmt.where(qcol > 0)

    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    order_col = {"name": Product.name, "code": Product.code, "newest": Product.id.desc(),
                 "price": Product.sale_price}.get(order, Product.name)
    stmt = stmt.order_by(order_col)
    if limit:
        stmt = stmt.limit(limit).offset(offset)
    return list(session.scalars(stmt).unique()), total


def brands(session: Session) -> list[str]:
    rows = session.scalars(select(Product.brand).where(Product.brand != "").distinct().order_by(Product.brand))
    return list(rows)


def min_stock_for(session: Session, p: Product) -> float:
    if p.min_stock is not None:
        return p.min_stock
    return float(settings.get(session, "default_min_stock") or 0)


def stock_status(session: Session, p: Product) -> str:
    """ok, low, out"""
    q = p.quantity
    if q <= 0:
        return "out"
    if q <= min_stock_for(session, p):
        return "low"
    return "ok"


# ---------------- المتغيرات ----------------

def create_variants(session: Session, actor: User | None, parent_id: int, variants: list[dict[str, str]],
                    copy_price: bool = True) -> list[Product]:
    parent = get_product(session, parent_id)
    if parent.parent_id:
        raise ValidationError("لا يمكن إضافة متغيرات لمتغير، اختر المنتج الأساسي")
    created = []
    for attrs in variants:
        attrs = {k: v for k, v in attrs.items() if str(v).strip()}
        if not attrs:
            continue
        label = " ".join(str(v) for v in attrs.values())
        suffix = codegen_service.abbreviate(label, 4) or str(len(parent.variants) + 1)
        code = f"{parent.code}-{suffix}"
        n = 1
        while codegen_service.code_exists(session, code):
            n += 1
            code = f"{parent.code}-{suffix}{n}"
        data = product_input_from(parent)
        data.name = f"{parent.name} - {label}"
        data.code, data.barcode = code, ""
        data.variant_attrs, data.parent_id = attrs, parent.id
        if not copy_price:
            data.sale_price = 0
        created.append(create_product(session, actor, data))
    return created


# ---------------- الصور ----------------

def add_image(session: Session, product_id: int, source: str | Path) -> ProductImage:
    p = get_product(session, product_id)
    src = Path(source)
    if not src.exists():
        raise ValidationError("الملف غير موجود")
    dest = sub_dir("images") / f"{p.id}_{uuid.uuid4().hex[:8]}{src.suffix.lower() or '.jpg'}"
    shutil.copy2(src, dest)
    img = ProductImage(product_id=p.id, path=dest.name, sort_order=len(p.images))
    p.images.append(img)
    session.flush()
    bus.publish(PRODUCTS_CHANGED, product_id=p.id)
    return img


def add_image_bytes(session: Session, product_id: int, data: bytes, ext: str = ".jpg") -> ProductImage:
    p = get_product(session, product_id)
    dest = sub_dir("images") / f"{p.id}_{uuid.uuid4().hex[:8]}{ext}"
    dest.write_bytes(data)
    img = ProductImage(product_id=p.id, path=dest.name, sort_order=len(p.images))
    p.images.append(img)
    session.flush()
    return img


def image_path(img: ProductImage) -> Path:
    return sub_dir("images") / img.path


def remove_image(session: Session, image_id: int) -> None:
    img = session.get(ProductImage, image_id)
    if img:
        try:
            image_path(img).unlink(missing_ok=True)
        except OSError:
            pass
        session.delete(img)


# ---------------- الموردون ----------------

def list_suppliers(session: Session) -> list[Supplier]:
    return list(session.scalars(select(Supplier).order_by(Supplier.name)))


def save_supplier(session: Session, name: str, phone: str = "", address: str = "", notes: str = "",
                  supplier_id: int | None = None) -> Supplier:
    if not name.strip():
        raise ValidationError("أدخل اسم المورد")
    s = session.get(Supplier, supplier_id) if supplier_id else None
    if s is None:
        s = Supplier()
        session.add(s)
    s.name, s.phone, s.address, s.notes = name.strip(), phone, address, notes
    session.flush()
    return s


def delete_supplier(session: Session, supplier_id: int) -> None:
    s = session.get(Supplier, supplier_id)
    if s:
        session.delete(s)


# ---------------- العروض ----------------

def list_promotions(session: Session, active_only: bool = False) -> list[Promotion]:
    stmt = select(Promotion).order_by(Promotion.start_date.desc())
    if active_only:
        today = date.today()
        stmt = stmt.where(Promotion.is_active.is_(True), Promotion.start_date <= today, Promotion.end_date >= today)
    return list(session.scalars(stmt))


def save_promotion(session: Session, name: str, percent: float, start: date, end: date,
                   product_id: int | None = None, category_id: int | None = None, is_active: bool = True,
                   promotion_id: int | None = None) -> Promotion:
    if not name.strip():
        raise ValidationError("أدخل اسم العرض")
    if not (0 < percent < 100):
        raise ValidationError("نسبة الخصم يجب أن تكون بين 0 و 100")
    if end < start:
        raise ValidationError("تاريخ النهاية قبل تاريخ البداية")
    if not product_id and not category_id:
        raise ValidationError("اختر منتجاً أو قسماً للعرض")
    promo = session.get(Promotion, promotion_id) if promotion_id else None
    if promo is None:
        promo = Promotion()
        session.add(promo)
    promo.name, promo.percent, promo.start_date, promo.end_date = name.strip(), percent, start, end
    promo.product_id, promo.category_id, promo.is_active = product_id, category_id, is_active
    session.flush()
    bus.publish(PRODUCTS_CHANGED)
    return promo


def delete_promotion(session: Session, promotion_id: int) -> None:
    promo = session.get(Promotion, promotion_id)
    if promo:
        session.delete(promo)
        bus.publish(PRODUCTS_CHANGED)


# =====================================================================
# تمثيل المنتج حسب الصلاحيات (للموبايل والعرض)
# =====================================================================

def warranty_label(warranty: str) -> str:
    """نص الكفالة للعرض: «كفالة سنة» أو «بدون كفالة»."""
    warranty = (warranty or "").strip()
    return f"كفالة {warranty}" if warranty else "بدون كفالة"


def product_view(session: Session, p: Product, privileged: bool, tier_id: int | None = None,
                 currency_code: str | None = None, show_stock: bool = False) -> dict[str, Any]:
    """show_stock: إظهار الكمية المتبقية في المستودع (للبائع حتى يعرف كم قطعة باقية)."""
    """قاموس بالحقول المسموح رؤيتها فقط. الفلترة تتم هنا في السيرفر."""
    from ftapp.services import currency_service

    vis = settings.builtin_visibility(session)
    show = (lambda key: True) if privileged else (lambda key: bool(vis.get(key)))
    cur = (session.get(Currency, currency_code) if currency_code else None) or currency_service.display(session)
    price, promo = final_price(session, p, tier_id)

    def conv(v: float) -> float:
        return currency_service.convert(v, cur)

    data: dict[str, Any] = {"id": p.id, "name": p.name, "code": p.code,
                            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                            "is_active": p.is_active, "currency": cur.code, "currency_symbol": cur.symbol,
                            "parent_id": p.parent_id, "variant_attrs": p.variant_attrs or {}}
    fields: list[dict[str, Any]] = []

    def add(key: str, label: str, value: Any, kind: str = "text") -> None:
        if show(key) and value not in (None, "", {}, []):
            data[key] = value
            fields.append({"key": key, "label": label, "value": value, "type": kind})

    add("barcode", "الباركود", p.barcode)
    add("category", "القسم", category_path(p.category) if p.category else "")
    add("brand", "الماركة", p.brand)
    add("model", "الموديل", p.model)
    add("unit", "الوحدة", p.unit)
    add("warranty", "الكفالة", warranty_label(p.warranty))
    if show("sale_price"):
        data["sale_price"] = conv(price)
        data["base_price"] = conv(tier_price(session, p, tier_id))
        data["promotion"] = {"name": promo.name, "percent": promo.percent} if promo else None
    add("cost_price", "سعر التكلفة", conv(p.cost_price) if privileged or vis.get("cost_price") else None, "money")
    add("margin", "نسبة الربح", effective_margin(session, p), "percent")
    if show("quantity") or show_stock:
        data["quantity"] = p.quantity
        data["stock_status"] = stock_status(session, p)
    add("min_stock", "حد التنبيه", min_stock_for(session, p), "number")
    add("supplier", "المورد", p.supplier.name if p.supplier else "")
    add("location", "الموقع", p.location)
    add("details", "التفاصيل", p.details, "longtext")
    add("specs", "المواصفات", p.specs or {}, "map")
    add("notes", "ملاحظات", p.notes, "longtext")
    if show("images"):
        data["images"] = [img.path for img in p.images]
    if show("tier_prices"):
        data["tier_prices"] = [{"tier": tp.tier.name, "price": conv(tp.price)} for tp in p.tier_prices]
    for fv in sorted(p.field_values, key=lambda x: x.field.sort_order):
        fld = fv.field
        if (privileged or fld.visible_to_users) and fv.value:
            fields.append({"key": fld.key, "label": fld.name, "value": display_field_value(fld, fv.value),
                           "type": fld.field_type})
    if p.variants:
        data["variants"] = [{"id": v.id, "code": v.code, "name": v.name, "attrs": v.variant_attrs,
                             **({"quantity": v.quantity} if show("quantity") or show_stock else {})}
                            for v in p.variants if v.is_active]
    data["fields"] = fields
    return data


def touch_last_sold(p: Product) -> None:
    p.last_sold_at = datetime.now()
