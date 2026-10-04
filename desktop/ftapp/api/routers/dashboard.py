from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ftapp.api.deps import AuthContext, current, get_db, require
from ftapp.services import currency_service, notification_service, report_service

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(period: str = "today", ctx: AuthContext = Depends(require("dashboard.view")),
              db: Session = Depends(get_db)) -> dict:
    p = report_service.period(period)
    cur = currency_service.display(db)
    conv = lambda v: currency_service.convert(v, cur)  # noqa: E731
    k = report_service.kpis(db, p)
    money_keys = {"sales", "gross_sales", "returns", "cost", "gross_profit", "expenses", "net_profit", "avg_invoice",
                  "collected", "credit", "stock_cost", "stock_value"}
    if not ctx.can("products.view_cost"):
        for key in ("cost", "gross_profit", "net_profit", "stock_cost", "margin_percent"):
            k.pop(key, None)
    kpis = {key: (conv(v) if key in money_keys else v) for key, v in k.items()}
    series_p = report_service.period("30days") if period in ("today", "yesterday") else p
    series = [{"label": r["label"], "sales": conv(r["sales"]),
               **({"profit": conv(r["profit"])} if ctx.can("products.view_cost") else {})}
              for r in report_service.sales_series(db, series_p)]
    return {
        "period": p.label, "currency": cur.code, "currency_symbol": cur.symbol, "kpis": kpis, "series": series,
        "top_products": [{"name": r["name"], "quantity": r["quantity"], "revenue": conv(r["revenue"]),
                          "share": r["share"]} for r in report_service.top_products(db, p, 10)],
        "categories": [{"name": r["name"], "color": r["color"], "revenue": conv(r["revenue"]), "share": r["share"]}
                       for r in report_service.sales_by_category(db, p)],
        "alerts": [_notif(n) for n in notification_service.important_alerts(db, 30)],
    }


def _notif(n) -> dict:
    return {"id": n.id, "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body,
            "entity": n.entity, "entity_id": n.entity_id, "is_read": n.is_read,
            "created_at": n.created_at.isoformat()}


@router.get("/notifications")
def notifications(unread_only: bool = False, ctx: AuthContext = Depends(current), db: Session = Depends(get_db)) -> dict:
    if not ctx.can("dashboard.view") and not ctx.can("inventory.view"):
        return {"unread": 0, "items": []}
    items = notification_service.list_notifications(db, unread_only, 200)
    return {"unread": notification_service.unread_count(db), "items": [_notif(n) for n in items]}


@router.post("/notifications/{notification_id}/read")
def read_one(notification_id: int, ctx: AuthContext = Depends(current), db: Session = Depends(get_db)) -> dict:
    notification_service.mark_read(db, notification_id)
    return {"ok": True}


@router.post("/notifications/read-all")
def read_all(ctx: AuthContext = Depends(current), db: Session = Depends(get_db)) -> dict:
    notification_service.mark_read(db)
    return {"ok": True}
