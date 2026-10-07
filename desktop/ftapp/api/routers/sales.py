from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ftapp.api.deps import AuthContext, get_db, require
from ftapp.api.schemas import CustomerIn, PaymentIn, ReturnIn, SaleIn
from ftapp.core.paths import sub_dir
from ftapp.models import Currency, Invoice, SyncLog
from ftapp.services import currency_service, pdf_service, sales_service

router = APIRouter(tags=["sales"])


def _request(body: SaleIn) -> sales_service.SaleRequest:
    return sales_service.SaleRequest(
        lines=[sales_service.CartLine(l.product_id, l.quantity, l.unit_price, l.discount) for l in body.lines],
        customer_id=body.customer_id, customer_name=body.customer_name, customer_phone=body.customer_phone,
        customer_address=body.customer_address, warehouse_id=body.warehouse_id, tier_id=body.tier_id, discount=body.discount, paid=body.paid,
        payment_method=body.payment_method, currency_code=body.currency_code, notes=body.notes, source="mobile")


def invoice_out(db: Session, inv: Invoice, detailed: bool = False) -> dict:
    cur = db.get(Currency, inv.currency_code) or currency_service.base(db)
    rate = inv.exchange_rate or 1
    m = lambda v: round(v * rate, cur.decimals)  # noqa: E731
    out = {"id": inv.id, "number": inv.number, "kind": inv.kind, "status": inv.status,
           "created_at": inv.created_at.isoformat(), "customer_name": inv.customer_name,
           "customer_phone": inv.customer_phone, "currency": cur.code, "currency_symbol": cur.symbol,
           "subtotal": m(inv.subtotal), "discount": m(inv.discount), "tax": m(inv.tax_amount), "total": m(inv.total),
           "paid": m(inv.paid), "remaining": m(inv.remaining), "payment_method": inv.payment_method,
           "seller": inv.user.display_name if inv.user else ""}
    if detailed:
        out["items"] = [{"id": i.id, "product_id": i.product_id, "name": i.product_name, "code": i.product_code,
                         "unit": i.unit, "quantity": i.quantity, "unit_price": m(i.unit_price),
                         "discount": m(i.discount), "total": m(i.line_total), "returned": i.returned_qty}
                        for i in inv.items]
        out["notes"] = inv.notes
    return out


@router.post("/sales/preview")
def preview(body: SaleIn, ctx: AuthContext = Depends(require("sales.create")), db: Session = Depends(get_db)) -> dict:
    calc = sales_service.compute_totals(db, _request(body))
    cur = (db.get(Currency, body.currency_code) if body.currency_code else None) or currency_service.display(db)
    conv = lambda v: currency_service.convert(v, cur)  # noqa: E731
    return {"currency": cur.code, "currency_symbol": cur.symbol,
            "lines": [{"product_id": l["product"].id, "name": l["product"].name, "quantity": l["quantity"],
                       "unit_price": conv(l["unit_price"]), "line_total": conv(l["line_total"]),
                       "promotion": l["promotion"].name if l["promotion"] else None,
                       "available": l["product"].quantity} for l in calc["lines"]],
            "subtotal": conv(calc["subtotal"]), "discount": conv(calc["discount"]), "tax": conv(calc["tax_amount"]),
            "total": conv(calc["total"])}


def create_sale_op(db: Session, ctx: AuthContext, body: SaleIn) -> dict:
    if body.client_op_id:
        done = db.get(SyncLog, body.client_op_id)
        if done:
            return done.result
    # الأسعار والخصم يرسلها الموبايل بعملة العرض، نحولها للعملة الأساسية
    cur = (db.get(Currency, body.currency_code) if body.currency_code else None) or currency_service.display(db)
    for line in body.lines:
        if line.unit_price is not None:
            line.unit_price = currency_service.to_base(line.unit_price, cur)
        line.discount = currency_service.to_base(line.discount, cur)
    body.discount = currency_service.to_base(body.discount, cur)
    if body.paid is not None:
        body.paid = currency_service.to_base(body.paid, cur)
    body.currency_code = cur.code
    req = _request(body)
    if body.kind == "quotation":
        inv = sales_service.create_quotation(db, ctx.user, req)
    else:
        inv = sales_service.create_sale(db, ctx.user, req)
    db.flush()
    result = invoice_out(db, inv, detailed=True)
    if body.client_op_id:
        db.add(SyncLog(client_op_id=body.client_op_id, user_id=ctx.user.id, result=result))
    return result


@router.post("/sales")
def create_sale(body: SaleIn, ctx: AuthContext = Depends(require("sales.create")), db: Session = Depends(get_db)) -> dict:
    return create_sale_op(db, ctx, body)


@router.get("/invoices")
def list_invoices(kind: str = "sale", search: str = "", date_from: date | None = None, date_to: date | None = None,
                  ctx: AuthContext = Depends(require("sales.create")), db: Session = Depends(get_db)) -> list[dict]:
    user_id = None if ctx.can("sales.view_all") else ctx.user.id
    rows = sales_service.list_invoices(db, kind, date_from, date_to, user_id=user_id, search=search, limit=200)
    return [invoice_out(db, inv) for inv in rows]


def _get_visible(db: Session, ctx: AuthContext, invoice_id: int) -> Invoice:
    inv = sales_service.get_invoice(db, invoice_id)
    if inv.user_id != ctx.user.id and not ctx.can("sales.view_all"):
        raise HTTPException(403, "لا يمكنك عرض فواتير بائع آخر")
    return inv


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, ctx: AuthContext = Depends(require("sales.create")),
                db: Session = Depends(get_db)) -> dict:
    return invoice_out(db, _get_visible(db, ctx, invoice_id), detailed=True)


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, paper: str = "A4", ctx: AuthContext = Depends(require("sales.create")),
                db: Session = Depends(get_db)) -> FileResponse:
    inv = _get_visible(db, ctx, invoice_id)
    if paper not in pdf_service.PAPERS:
        paper = "A4"
    path = pdf_service.invoice_pdf(db, inv, sub_dir("invoices") / f"{inv.number}_{paper}.pdf", paper)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.post("/invoices/{invoice_id}/return")
def create_return(invoice_id: int, body: ReturnIn, ctx: AuthContext = Depends(require("sales.return")),
                  db: Session = Depends(get_db)) -> dict:
    ret = sales_service.create_return(db, ctx.user, invoice_id, body.items, body.refund_to, body.notes)
    db.flush()
    return invoice_out(db, ret, detailed=True)


@router.post("/invoices/{invoice_id}/convert")
def convert(invoice_id: int, ctx: AuthContext = Depends(require("sales.create")), db: Session = Depends(get_db)) -> dict:
    inv = sales_service.convert_quotation(db, ctx.user, invoice_id)
    db.flush()
    return invoice_out(db, inv, detailed=True)


@router.get("/customers")
def customers(q: str = "", ctx: AuthContext = Depends(require("sales.create")), db: Session = Depends(get_db)) -> list[dict]:
    show_balance = ctx.can("customers.manage")
    return [{"id": c.id, "name": c.name, "phone": c.phone, "tier_id": c.tier_id,
             **({"balance": c.balance} if show_balance else {})}
            for c in sales_service.list_customers(db, q)[:100]]


@router.post("/customers")
def add_customer(body: CustomerIn, ctx: AuthContext = Depends(require("customers.manage")),
                 db: Session = Depends(get_db)) -> dict:
    c = sales_service.save_customer(db, body.name, body.phone, body.address, body.tier_id)
    db.flush()
    return {"id": c.id, "name": c.name, "phone": c.phone, "tier_id": c.tier_id, "balance": c.balance}


@router.post("/customers/{customer_id}/payments")
def pay(customer_id: int, body: PaymentIn, ctx: AuthContext = Depends(require("customers.manage")),
        db: Session = Depends(get_db)) -> dict:
    sales_service.receive_payment(db, ctx.user, customer_id, body.amount, body.notes)
    c = sales_service.list_customers(db)
    return {"ok": True, "balance": next((x.balance for x in c if x.id == customer_id), 0)}
