"""البيع، الفواتير، المرتجعات، عروض الأسعار، الزبائن والديون."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ftapp.core.events import SALES_CHANGED, bus
from ftapp.core.utils import money, now, qty
from ftapp.models import Currency, Customer, CustomerPayment, Invoice, InvoiceItem, Product, User
from ftapp.services import (audit, catalog_service, currency_service, inventory_service, notification_service,
                            numbering, permissions, settings_service as settings)
from ftapp.services.errors import NotFound, PermissionDenied, ValidationError

PAYMENT_METHODS = {"cash": "نقدي", "shamcash": "شام كاش", "credit": "آجل", "partial": "دفع جزئي"}
PAID_IN_FULL = ("cash", "shamcash")  # طرق دفع تُسدَّد كامل المبلغ لحظة البيع
KINDS = {"sale": "فاتورة بيع", "return": "مرتجع", "quotation": "عرض سعر"}
STATUSES = {"posted": "مكتملة", "cancelled": "ملغاة", "converted": "محوّل لفاتورة", "open": "مفتوح"}


@dataclass
class CartLine:
    product_id: int
    quantity: float
    unit_price: float | None = None   # None = السعر التلقائي حسب الشريحة والعروض
    discount: float = 0.0             # مبلغ خصم على السطر


@dataclass
class SaleRequest:
    lines: list[CartLine]
    customer_id: int | None = None
    customer_name: str = ""
    customer_phone: str = ""
    customer_address: str = ""
    warehouse_id: int | None = None
    tier_id: int | None = None
    discount: float = 0.0
    tax_rate: float | None = None
    paid: float | None = None
    payment_method: str = "cash"
    currency_code: str | None = None
    notes: str = ""
    source: str = "desktop"
    valid_until: date | None = None


# ---------------- حساب السلة ----------------

def price_line(session: Session, product: Product, tier_id: int | None) -> tuple[float, Any]:
    return catalog_service.final_price(session, product, tier_id)


def compute_totals(session: Session, req: SaleRequest) -> dict[str, Any]:
    """يحسب أسطر الفاتورة والإجماليات بدون حفظ (يُستخدم للمعاينة أيضاً)."""
    tier_id = req.tier_id
    if tier_id is None and req.customer_id:
        cust = session.get(Customer, req.customer_id)
        tier_id = cust.tier_id if cust else None
    lines = []
    subtotal = cost_total = 0.0
    for ln in req.lines:
        if ln.quantity <= 0:
            continue
        product = session.get(Product, ln.product_id)
        if product is None:
            raise NotFound("منتج غير موجود في السلة")
        auto_price, promo = price_line(session, product, tier_id)
        unit_price = money(auto_price if ln.unit_price is None else ln.unit_price)
        line_total = money(unit_price * ln.quantity - (ln.discount or 0))
        if line_total < 0:
            raise ValidationError(f"خصم السطر أكبر من قيمته: {product.name}")
        subtotal += line_total
        cost_total += product.cost_price * ln.quantity
        lines.append({"product": product, "quantity": qty(ln.quantity), "unit_price": unit_price,
                      "auto_price": auto_price, "discount": money(ln.discount or 0), "line_total": line_total,
                      "promotion": promo})
    subtotal = money(subtotal)
    discount = money(req.discount or 0)
    if discount > subtotal:
        raise ValidationError("الخصم أكبر من إجمالي الفاتورة")
    tax_rate = settings.get(session, "tax_rate") if req.tax_rate is None else req.tax_rate
    tax_amount = money((subtotal - discount) * (tax_rate or 0) / 100.0)
    total = money(subtotal - discount + tax_amount)
    return {"lines": lines, "subtotal": subtotal, "discount": discount, "tax_rate": tax_rate or 0,
            "tax_amount": tax_amount, "total": total, "cost_total": money(cost_total), "tier_id": tier_id}


def _check_discount_permission(actor: User | None, calc: dict[str, Any]) -> None:
    if actor is None or permissions.has(actor, "sales.discount"):
        return
    if calc["discount"] > 0 or any(l["discount"] > 0 or l["unit_price"] < l["auto_price"] for l in calc["lines"]):
        raise PermissionDenied("ليس لديك صلاحية منح خصومات")


def _fill_header(session: Session, inv: Invoice, req: SaleRequest, calc: dict[str, Any], actor: User | None) -> None:
    cur = (session.get(Currency, req.currency_code) if req.currency_code else None) or currency_service.display(session)
    inv.customer_id = req.customer_id
    if req.customer_id:
        cust = session.get(Customer, req.customer_id)
        inv.customer_name = req.customer_name or (cust.name if cust else "")
        inv.customer_phone = req.customer_phone or (cust.phone if cust else "")
        inv.customer_address = req.customer_address or (cust.address if cust else "")
    else:
        inv.customer_name, inv.customer_phone = req.customer_name.strip(), req.customer_phone.strip()
        inv.customer_address = req.customer_address.strip()
    inv.user_id = actor.id if actor else None
    inv.warehouse_id = req.warehouse_id or inventory_service.default_warehouse(session).id
    inv.tier_id = calc["tier_id"]
    inv.currency_code, inv.exchange_rate = cur.code, cur.rate
    inv.subtotal, inv.discount = calc["subtotal"], calc["discount"]
    inv.tax_rate, inv.tax_amount, inv.total = calc["tax_rate"], calc["tax_amount"], calc["total"]
    inv.cost_total = calc["cost_total"]
    inv.notes, inv.source = req.notes, req.source
    for l in calc["lines"]:
        p = l["product"]
        inv.items.append(InvoiceItem(product_id=p.id, product_name=p.name, product_code=p.code, unit=p.unit,
                                     quantity=l["quantity"], unit_price=l["unit_price"], discount=l["discount"],
                                     cost_price=p.cost_price, line_total=l["line_total"],
                                     warranty=p.warranty or ""))


def create_sale(session: Session, actor: User | None, req: SaleRequest, agreed_prices: bool = False) -> Invoice:
    """agreed_prices: أسعار متفق عليها مسبقاً (تحويل عرض سعر) فلا يُفحص إذن الخصم."""
    from ftapp.services import finance_service

    calc = compute_totals(session, req)
    if not calc["lines"]:
        raise ValidationError("السلة فارغة")
    if not agreed_prices:
        _check_discount_permission(actor, calc)
    if req.payment_method not in PAYMENT_METHODS:
        raise ValidationError("طريقة دفع غير معروفة")

    total = calc["total"]
    if req.payment_method in PAID_IN_FULL:
        paid = total
    else:
        paid = money(req.paid or 0)
        if paid > total:
            paid = total
    remaining = money(total - paid)
    if remaining > 0 and not req.customer_id:
        raise ValidationError("البيع الآجل أو الجزئي يحتاج اختيار زبون مسجّل")

    allow_neg = bool(settings.get(session, "allow_negative_stock")) or permissions.has(actor, "sales.oversell")
    inv = Invoice(number=numbering.next_document_number(session, "sale"), kind="sale", status="posted",
                  payment_method=req.payment_method if remaining > 0 or req.payment_method in PAID_IN_FULL else "cash")
    _fill_header(session, inv, req, calc, actor)
    inv.paid = paid
    shift = finance_service.current_shift(session, actor) if actor else None
    inv.shift_id = shift.id if shift else None
    session.add(inv)
    session.flush()

    for item in inv.items:
        inventory_service.adjust(session, actor, item.product_id, inv.warehouse_id, -item.quantity, "sale",
                                 f"فاتورة {inv.number}", "invoice", inv.id, allow_negative=allow_neg)
        product = session.get(Product, item.product_id)
        if product:
            catalog_service.touch_last_sold(product)

    if remaining > 0:
        cust = session.get(Customer, req.customer_id)
        if cust.credit_limit and cust.balance + remaining > cust.credit_limit:
            notification_service.add(session, "debt", f"تجاوز حد الدين: {cust.name}",
                                     f"الدين بعد الفاتورة {cust.balance + remaining:,.2f}", "warning", "customer", cust.id)
        cust.balance = money(cust.balance + remaining)

    large = float(settings.get(session, "large_invoice_amount") or 0)
    if large and total >= large:
        notification_service.add(session, "large_invoice", f"فاتورة كبيرة {inv.number}",
                                 f"الإجمالي {currency_service.format_amount(session, total)} — {inv.customer_name or 'زبون نقدي'}",
                                 "info", "invoice", inv.id)
    audit.log(session, actor, "sale", "invoice", inv.id, source=req.source, number=inv.number, total=total)
    session.flush()
    bus.publish(SALES_CHANGED, invoice_id=inv.id)
    return inv


def create_quotation(session: Session, actor: User | None, req: SaleRequest) -> Invoice:
    calc = compute_totals(session, req)
    if not calc["lines"]:
        raise ValidationError("عرض السعر فارغ")
    inv = Invoice(number=numbering.next_document_number(session, "quotation"), kind="quotation", status="open",
                  valid_until=req.valid_until or (date.today() + timedelta(days=7)))
    _fill_header(session, inv, req, calc, actor)
    session.add(inv)
    session.flush()
    audit.log(session, actor, "quotation", "invoice", inv.id, number=inv.number)
    bus.publish(SALES_CHANGED, invoice_id=inv.id)
    return inv


def convert_quotation(session: Session, actor: User | None, quotation_id: int, payment_method: str = "cash",
                      paid: float | None = None) -> Invoice:
    q = get_invoice(session, quotation_id)
    if q.kind != "quotation" or q.status != "open":
        raise ValidationError("عرض السعر غير متاح للتحويل")
    req = SaleRequest(
        lines=[CartLine(i.product_id, i.quantity, i.unit_price, i.discount) for i in q.items if i.product_id],
        customer_id=q.customer_id, customer_name=q.customer_name, customer_phone=q.customer_phone,
        customer_address=q.customer_address, warehouse_id=q.warehouse_id, tier_id=q.tier_id, discount=q.discount, tax_rate=q.tax_rate,
        payment_method=payment_method, paid=paid, currency_code=q.currency_code,
        notes=f"محوّل من عرض السعر {q.number}" + (f"\n{q.notes}" if q.notes else ""),
    )
    inv = create_sale(session, actor, req, agreed_prices=True)
    q.status = "converted"
    return inv


def create_return(session: Session, actor: User | None, original_id: int, items: list[tuple[int, float]],
                  refund_to: str = "cash", notes: str = "") -> Invoice:
    """items: [(invoice_item_id, الكمية المرتجعة)]. refund_to: cash أو balance (خصم من دين الزبون)."""
    from ftapp.services import finance_service

    orig = get_invoice(session, original_id)
    if orig.kind != "sale" or orig.status != "posted":
        raise ValidationError("لا يمكن الإرجاع من هذه الفاتورة")
    by_id = {i.id: i for i in orig.items}
    ret = Invoice(number=numbering.next_document_number(session, "return"), kind="return", status="posted",
                  original_invoice_id=orig.id, customer_id=orig.customer_id, customer_name=orig.customer_name,
                  customer_phone=orig.customer_phone, customer_address=orig.customer_address, user_id=actor.id if actor else None,
                  warehouse_id=orig.warehouse_id, currency_code=orig.currency_code, exchange_rate=orig.exchange_rate,
                  notes=notes, payment_method="cash" if refund_to == "cash" else "credit", tier_id=orig.tier_id)
    shift = finance_service.current_shift(session, actor) if actor else None
    ret.shift_id = shift.id if shift else None
    session.add(ret)
    session.flush()
    subtotal = cost_total = 0.0
    # الخصم العام على الفاتورة الأصلية يوزّع نسبياً على الأصناف
    ratio = (orig.subtotal - orig.discount) / orig.subtotal if orig.subtotal else 1
    tax_ratio = (1 + orig.tax_rate / 100.0)
    for item_id, rqty in items:
        item = by_id.get(item_id)
        if item is None or rqty <= 0:
            continue
        available = qty(item.quantity - item.returned_qty)
        if rqty > available + 1e-9:
            raise ValidationError(f"الكمية المرتجعة من «{item.product_name}» أكبر من المتاح ({available:g})")
        unit_net = item.line_total / item.quantity if item.quantity else 0
        line_total = money(unit_net * rqty)
        ret.items.append(InvoiceItem(product_id=item.product_id, product_name=item.product_name,
                                     product_code=item.product_code, unit=item.unit, quantity=rqty,
                                     unit_price=money(unit_net), cost_price=item.cost_price, line_total=line_total))
        item.returned_qty = qty(item.returned_qty + rqty)
        subtotal += line_total
        cost_total += item.cost_price * rqty
        if item.product_id:
            inventory_service.adjust(session, actor, item.product_id, orig.warehouse_id, rqty, "return",
                                     f"مرتجع {ret.number}", "invoice", ret.id)
    if not ret.items:
        raise ValidationError("اختر أصنافاً وكميات للإرجاع")
    ret.subtotal = money(subtotal)
    ret.discount = money(subtotal - subtotal * ratio)
    ret.tax_rate = orig.tax_rate
    net = subtotal * ratio
    ret.tax_amount = money(net * (tax_ratio - 1))
    ret.total = money(net * tax_ratio)
    ret.cost_total = money(cost_total)
    if refund_to == "balance" and orig.customer_id:
        cust = session.get(Customer, orig.customer_id)
        cust.balance = money(cust.balance - ret.total)
        ret.paid = 0.0
    else:
        ret.paid = ret.total
    audit.log(session, actor, "return", "invoice", ret.id, original=orig.number, total=ret.total)
    bus.publish(SALES_CHANGED, invoice_id=ret.id)
    return ret


def cancel_invoice(session: Session, actor: User | None, invoice_id: int, reason: str = "") -> Invoice:
    inv = get_invoice(session, invoice_id)
    if inv.status != "posted" or inv.kind == "return":
        if inv.kind == "quotation" and inv.status == "open":
            inv.status = "cancelled"
            return inv
        raise ValidationError("لا يمكن إلغاء هذه الفاتورة")
    if any(i.returned_qty > 0 for i in inv.items):
        raise ValidationError("الفاتورة عليها مرتجعات، لا يمكن إلغاؤها")
    for item in inv.items:
        if item.product_id:
            inventory_service.adjust(session, actor, item.product_id, inv.warehouse_id, item.quantity, "cancel",
                                     f"إلغاء {inv.number}", "invoice", inv.id)
    if inv.customer_id and inv.remaining > 0:
        cust = session.get(Customer, inv.customer_id)
        cust.balance = money(cust.balance - inv.remaining)
    inv.status = "cancelled"
    inv.notes = (inv.notes + f"\nسبب الإلغاء: {reason}").strip() if reason else inv.notes
    audit.log(session, actor, "invoice_cancelled", "invoice", inv.id, number=inv.number, reason=reason)
    bus.publish(SALES_CHANGED, invoice_id=inv.id)
    return inv


def get_invoice(session: Session, invoice_id: int) -> Invoice:
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFound("الفاتورة غير موجودة")
    return inv


def find_invoice(session: Session, number: str) -> Invoice | None:
    return session.scalar(select(Invoice).where(Invoice.number == number.strip().upper()))


def list_invoices(session: Session, kind: str | None = "sale", date_from: date | None = None,
                  date_to: date | None = None, user_id: int | None = None, customer_id: int | None = None,
                  search: str = "", status: str | None = None, limit: int = 1000) -> list[Invoice]:
    stmt = (select(Invoice).options(selectinload(Invoice.items), selectinload(Invoice.user))
            .order_by(Invoice.id.desc()).limit(limit))
    if kind:
        stmt = stmt.where(Invoice.kind == kind)
    if status:
        stmt = stmt.where(Invoice.status == status)
    if date_from:
        stmt = stmt.where(Invoice.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        stmt = stmt.where(Invoice.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    if user_id:
        stmt = stmt.where(Invoice.user_id == user_id)
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if search.strip():
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(Invoice.number.ilike(like), Invoice.customer_name.ilike(like),
                              Invoice.customer_phone.ilike(like)))
    return list(session.scalars(stmt))


# ---------------- الزبائن ----------------

def list_customers(session: Session, search: str = "", debtors_only: bool = False) -> list[Customer]:
    stmt = select(Customer).order_by(Customer.name)
    if search.strip():
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(Customer.name.ilike(like), Customer.phone.ilike(like)))
    if debtors_only:
        stmt = stmt.where(Customer.balance > 0)
    return list(session.scalars(stmt))


def save_customer(session: Session, name: str, phone: str = "", address: str = "", tier_id: int | None = None,
                  credit_limit: float = 0.0, notes: str = "", customer_id: int | None = None) -> Customer:
    if not name.strip():
        raise ValidationError("أدخل اسم الزبون")
    if phone.strip():
        dup = session.scalar(select(Customer).where(Customer.phone == phone.strip(), Customer.id != (customer_id or -1)))
        if dup:
            raise ValidationError(f"رقم الهاتف مسجل للزبون «{dup.name}»")
    c = session.get(Customer, customer_id) if customer_id else None
    if c is None:
        c = Customer()
        session.add(c)
    c.name, c.phone, c.address, c.tier_id = name.strip(), phone.strip(), address, tier_id
    c.credit_limit, c.notes = credit_limit or 0.0, notes
    session.flush()
    return c


def delete_customer(session: Session, customer_id: int) -> None:
    c = session.get(Customer, customer_id)
    if c is None:
        return
    if abs(c.balance) > 0.009:
        raise ValidationError("لا يمكن حذف زبون عليه رصيد")
    session.delete(c)


def receive_payment(session: Session, actor: User | None, customer_id: int, amount: float, notes: str = "",
                    method: str = "cash") -> CustomerPayment:
    from ftapp.services import finance_service

    c = session.get(Customer, customer_id)
    if c is None:
        raise NotFound("الزبون غير موجود")
    if amount <= 0:
        raise ValidationError("أدخل مبلغاً صحيحاً")
    if method not in ("cash", "shamcash"):
        raise ValidationError("طريقة دفع غير معروفة")
    shift = finance_service.current_shift(session, actor) if actor else None
    pay = CustomerPayment(customer_id=c.id, amount=money(amount), notes=notes, method=method, user_id=actor.id if actor else None,
                          shift_id=shift.id if shift else None)
    session.add(pay)
    c.balance = money(c.balance - amount)
    audit.log(session, actor, "payment", "customer", c.id, amount=amount)
    session.flush()
    bus.publish(SALES_CHANGED)
    return pay


def customer_statement(session: Session, customer_id: int) -> list[dict[str, Any]]:
    """كشف حساب: مدين (فواتير) / دائن (دفعات ومرتجعات) مع الرصيد التراكمي."""
    entries: list[dict[str, Any]] = []
    for inv in session.scalars(select(Invoice).where(Invoice.customer_id == customer_id,
                                                     Invoice.kind.in_(["sale", "return"]),
                                                     Invoice.status == "posted")):
        if inv.kind == "sale":
            entries.append({"date": inv.created_at, "desc": f"فاتورة {inv.number}", "debit": inv.total, "credit": 0.0})
            if inv.paid:
                entries.append({"date": inv.created_at, "desc": f"دفعة مع الفاتورة {inv.number}", "debit": 0.0,
                                "credit": inv.paid})
        elif inv.payment_method == "credit":
            entries.append({"date": inv.created_at, "desc": f"مرتجع {inv.number}", "debit": 0.0, "credit": inv.total})
    for pay in session.scalars(select(CustomerPayment).where(CustomerPayment.customer_id == customer_id)):
        label = "دفعة (شام كاش)" if pay.method == "shamcash" else "دفعة"
        entries.append({"date": pay.created_at, "desc": f"{label} {pay.notes}".strip(), "debit": 0.0,
                        "credit": pay.amount})
    entries.sort(key=lambda e: e["date"])
    balance = 0.0
    for e in entries:
        balance = money(balance + e["debit"] - e["credit"])
        e["balance"] = balance
    return entries


def sold_quantity(session: Session, product_id: int, days: int) -> float:
    since = now() - timedelta(days=days)
    sold = session.scalar(select(func.coalesce(func.sum(InvoiceItem.quantity - InvoiceItem.returned_qty), 0))
                          .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                          .where(InvoiceItem.product_id == product_id, Invoice.kind == "sale",
                                 Invoice.status == "posted", Invoice.created_at >= since))
    return qty(sold)
