from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ftapp.api.deps import AuthContext, get_db, require
from ftapp.api.schemas import CountIn, CountLineIn
from ftapp.models import StockCount, SyncLog
from ftapp.services import catalog_service, inventory_service

router = APIRouter(tags=["inventory"])


def count_out(c: StockCount, with_lines: bool = True) -> dict:
    out = {"id": c.id, "warehouse_id": c.warehouse_id, "warehouse": c.warehouse.name, "status": c.status,
           "notes": c.notes, "created_at": c.created_at.isoformat(), "lines_count": len(c.lines)}
    if with_lines:
        out["lines"] = [{"id": l.id, "product_id": l.product_id, "code": l.product.code, "name": l.product.name,
                         "system_qty": l.system_qty, "counted_qty": l.counted_qty, "difference": l.difference}
                        for l in c.lines]
    return out


@router.get("/counts")
def counts(ctx: AuthContext = Depends(require("inventory.adjust")), db: Session = Depends(get_db)) -> list[dict]:
    return [count_out(c, False) for c in inventory_service.open_counts(db)]


@router.post("/counts")
def start_count(body: CountIn, ctx: AuthContext = Depends(require("inventory.adjust")),
                db: Session = Depends(get_db)) -> dict:
    c = inventory_service.start_count(db, ctx.user, body.warehouse_id, body.notes)
    db.flush()
    db.refresh(c)
    return count_out(c)


@router.get("/counts/{count_id}")
def get_count(count_id: int, ctx: AuthContext = Depends(require("inventory.adjust")),
              db: Session = Depends(get_db)) -> dict:
    return count_out(inventory_service.get_count(db, count_id))


def add_count_line_op(db: Session, ctx: AuthContext, count_id: int, body: CountLineIn) -> dict:
    if body.client_op_id:
        done = db.get(SyncLog, body.client_op_id)
        if done:
            return done.result
    pid = body.product_id
    if pid is None:
        p = catalog_service.find_by_code(db, body.code or "")
        if p is None:
            raise HTTPException(404, f"لا يوجد منتج بالكود {body.code}")
        pid = p.id
    line = inventory_service.set_count_line(db, count_id, pid, body.quantity, body.mode)
    db.flush()
    result = {"id": line.id, "product_id": pid, "name": line.product.name, "code": line.product.code,
              "system_qty": line.system_qty, "counted_qty": line.counted_qty, "difference": line.difference}
    if body.client_op_id:
        db.add(SyncLog(client_op_id=body.client_op_id, user_id=ctx.user.id, result=result))
    return result


@router.post("/counts/{count_id}/lines")
def add_line(count_id: int, body: CountLineIn, ctx: AuthContext = Depends(require("inventory.adjust")),
             db: Session = Depends(get_db)) -> dict:
    return add_count_line_op(db, ctx, count_id, body)


@router.get("/stock/low")
def low_stock(ctx: AuthContext = Depends(require("inventory.view")), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": p.id, "name": p.name, "code": p.code, "quantity": p.quantity,
             "min_stock": catalog_service.min_stock_for(db, p), "status": catalog_service.stock_status(db, p)}
            for p in inventory_service.low_stock_products(db)]
