"""استقبال العمليات المؤجلة من الموبايل بعد عودة الاتصال (Offline queue)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ftapp.api.deps import AuthContext, current, get_db
from ftapp.api.routers.inventory import add_count_line_op
from ftapp.api.routers.products import apply_stock_change
from ftapp.api.routers.sales import create_sale_op
from ftapp.api.schemas import CountLineIn, SaleIn, StockChangeIn
from ftapp.services.errors import ServiceError

router = APIRouter(tags=["sync"])

PERMS = {"sale": "sales.create", "stock": "inventory.adjust", "count_line": "inventory.adjust"}


@router.post("/sync/ops")
def sync_ops(body: dict, ctx: AuthContext = Depends(current), db: Session = Depends(get_db)) -> dict:
    results = []
    for raw in body.get("ops", []):
        op_id = raw.get("client_op_id")
        kind = raw.get("type")
        payload = dict(raw.get("payload") or {})
        sp = db.begin_nested()
        try:
            if kind not in PERMS:
                raise HTTPException(400, "نوع عملية غير معروف")
            if not ctx.can(PERMS[kind]):
                raise HTTPException(403, "ليس لديك صلاحية")
            if kind == "sale":
                result = create_sale_op(db, ctx, SaleIn(**payload, client_op_id=op_id))
            elif kind == "stock":
                pid = int(payload.pop("product_id"))
                result = apply_stock_change(db, ctx, pid, StockChangeIn(**payload, client_op_id=op_id))
            else:
                cid = int(payload.pop("count_id"))
                result = add_count_line_op(db, ctx, cid, CountLineIn(**payload, client_op_id=op_id))
            sp.commit()
            results.append({"client_op_id": op_id, "ok": True, "result": result})
        except (ServiceError, HTTPException, ValueError, KeyError, TypeError) as exc:
            sp.rollback()
            msg = exc.detail if isinstance(exc, HTTPException) else str(exc)
            results.append({"client_op_id": op_id, "ok": False, "error": msg})
    return {"results": results}
