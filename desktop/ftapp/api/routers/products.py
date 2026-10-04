from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ftapp.api.deps import AuthContext, current, get_db, require
from ftapp.api.schemas import ProductIn, StockChangeIn
from ftapp.core.paths import sub_dir
from ftapp.core.utils import now
from ftapp.models import Product, SyncLog
from ftapp.services import (catalog_service, codegen_service, currency_service, finance_service, inventory_service,
                            settings_service as settings)

router = APIRouter(tags=["products"])


def _view(db: Session, ctx: AuthContext, p: Product, currency: str | None = None) -> dict:
    return catalog_service.product_view(db, p, ctx.privileged, currency_code=currency)


def compact(db: Session, ctx: AuthContext, p: Product, currency: str | None = None) -> dict:
    v = _view(db, ctx, p, currency)
    keep = ("id", "name", "code", "barcode", "brand", "model", "unit", "sale_price", "base_price", "promotion",
            "quantity", "stock_status", "currency", "currency_symbol", "category", "updated_at", "is_active",
            "parent_id", "variant_attrs")
    out = {k: v[k] for k in keep if k in v}
    out["image"] = v.get("images", [None])[0] if v.get("images") else None
    return out


@router.get("/products/lookup")
def lookup(q: str, currency: str | None = None, ctx: AuthContext = Depends(require("products.view")),
           db: Session = Depends(get_db)) -> dict:
    p = catalog_service.find_by_code(db, q)
    if p is None or (not p.is_active and not ctx.privileged):
        raise HTTPException(404, "لا يوجد منتج بهذا الكود")
    return _view(db, ctx, p, currency)


@router.get("/products")
def search(q: str = "", category_id: int | None = None, stock: str = "all", limit: int = Query(50, le=500),
           offset: int = 0, currency: str | None = None, ctx: AuthContext = Depends(require("products.view")),
           db: Session = Depends(get_db)) -> dict:
    if stock != "all" and not ctx.can("inventory.view"):
        stock = "all"
    items, total = catalog_service.search_products(db, q, category_id=category_id, stock_filter=stock,
                                                   limit=limit, offset=offset)
    return {"total": total, "items": [compact(db, ctx, p, currency) for p in items]}


@router.get("/products/generate-code")
def generate_code(name: str, category_id: int | None = None, brand: str = "", model: str = "",
                  ctx: AuthContext = Depends(require("products.edit")), db: Session = Depends(get_db)) -> dict:
    return {"code": codegen_service.generate_code(db, name, category_id, brand, model)}


@router.get("/products/{product_id}")
def get_product(product_id: int, currency: str | None = None, ctx: AuthContext = Depends(require("products.view")),
                db: Session = Depends(get_db)) -> dict:
    p = catalog_service.get_product(db, product_id)
    return _view(db, ctx, p, currency)


def _to_input(body: ProductIn, base=None) -> catalog_service.ProductInput:
    data = base or catalog_service.ProductInput(name=body.name)
    for key in ("name", "code", "barcode", "category_id", "brand", "model", "unit", "cost_price", "margin",
                "price_locked", "sale_price", "min_stock", "location", "details", "notes"):
        setattr(data, key, getattr(body, key))
    data.custom_values.update(body.custom_values)
    return data


@router.post("/products")
def create_product(body: ProductIn, ctx: AuthContext = Depends(require("products.edit")),
                   db: Session = Depends(get_db)) -> dict:
    data = _to_input(body)
    data.initial_quantity = body.initial_quantity
    p = catalog_service.create_product(db, ctx.user, data, source="mobile")
    db.flush()
    return _view(db, ctx, p)


@router.put("/products/{product_id}")
def update_product(product_id: int, body: ProductIn, ctx: AuthContext = Depends(require("products.edit")),
                   db: Session = Depends(get_db)) -> dict:
    p = catalog_service.get_product(db, product_id)
    data = _to_input(body, catalog_service.product_input_from(p))
    p = catalog_service.update_product(db, ctx.user, product_id, data, source="mobile")
    return _view(db, ctx, p)


def apply_stock_change(db: Session, ctx: AuthContext, product_id: int, body: StockChangeIn) -> dict:
    if body.client_op_id:
        done = db.get(SyncLog, body.client_op_id)
        if done:
            return done.result
    p = catalog_service.get_product(db, product_id)
    if body.quantity is not None:
        inventory_service.set_quantity(db, ctx.user, p.id, body.warehouse_id, body.quantity, body.reason)
    elif body.delta:
        inventory_service.adjust(db, ctx.user, p.id, body.warehouse_id, body.delta,
                                 "in" if body.delta > 0 else "out", body.reason, allow_negative=False)
    else:
        raise HTTPException(400, "أدخل الكمية")
    db.refresh(p)
    result = {"id": p.id, "quantity": p.quantity, "stock_status": catalog_service.stock_status(db, p)}
    if body.client_op_id:
        db.add(SyncLog(client_op_id=body.client_op_id, user_id=ctx.user.id, result=result))
    return result


@router.patch("/products/{product_id}/stock")
def change_stock(product_id: int, body: StockChangeIn, ctx: AuthContext = Depends(require("inventory.adjust")),
                 db: Session = Depends(get_db)) -> dict:
    return apply_stock_change(db, ctx, product_id, body)


_SAFE_NAME = re.compile(r"^[\w\-.]+$")


@router.get("/images/{name}")
def image(name: str, ctx: AuthContext = Depends(current)) -> FileResponse:
    if not _SAFE_NAME.match(name):
        raise HTTPException(400, "اسم ملف غير صالح")
    path = sub_dir("images") / name
    if not path.exists():
        raise HTTPException(404, "الصورة غير موجودة")
    return FileResponse(path)


@router.get("/meta")
def meta(ctx: AuthContext = Depends(current), db: Session = Depends(get_db)) -> dict:
    """بيانات مرجعية للتطبيق: الأقسام، الشرائح، العملات، المستودعات، الخانات."""
    cats = [{"id": c.id, "name": c.name, "parent_id": c.parent_id, "depth": d, "color": c.color}
            for c, d in catalog_service.category_tree(db)]
    shift = finance_service.current_shift(db, ctx.user)
    data = {
        "categories": cats,
        "tiers": [{"id": t.id, "name": t.name, "is_default": t.is_default} for t in catalog_service.list_tiers(db)],
        "currencies": [{"code": c.code, "name": c.name, "symbol": c.symbol, "rate": c.rate, "is_base": c.is_base,
                        "decimals": c.decimals} for c in currency_service.list_currencies(db)],
        "display_currency": currency_service.display(db).code,
        "warehouses": [{"id": w.id, "name": w.name, "is_default": w.is_default}
                       for w in inventory_service.list_warehouses(db)],
        "units": catalog_service.UNITS,
        "tax_rate": settings.get(db, "tax_rate"),
        "shift_open": shift is not None,
    }
    if ctx.can("products.edit"):
        data["fields"] = [{"id": f.id, "name": f.name, "type": f.field_type, "required": f.required,
                           "options": f.options, "category_id": f.category_id}
                          for f in catalog_service.list_fields(db, all_fields=True)]
    return data


@router.get("/sync/products")
def sync_products(since: str | None = None, currency: str | None = None,
                  ctx: AuthContext = Depends(require("products.view")), db: Session = Depends(get_db)) -> dict:
    """مزامنة تفاضلية لنسخة الموبايل المحلية (وضع Offline)."""
    stmt = select(Product)
    if since:
        try:
            stmt = stmt.where(Product.updated_at > datetime.fromisoformat(since))
        except ValueError:
            raise HTTPException(400, "تاريخ غير صالح")
    server_time = now().isoformat()
    items, removed = [], []
    for p in db.scalars(stmt):
        if p.is_active or ctx.privileged:
            items.append(compact(db, ctx, p, currency))
        else:
            removed.append(p.id)
    return {"server_time": server_time, "items": items, "removed": removed, "full": since is None}
