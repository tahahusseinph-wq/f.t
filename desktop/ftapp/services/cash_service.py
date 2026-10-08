"""الصندوق متعدد العملات: حركات النقد الفعلية بكل عملة، وصرف العملات للزبائن مع ربحه أو خسارته."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ftapp.core.events import SALES_CHANGED, bus
from ftapp.core.utils import money
from ftapp.models import CashMovement, Currency, CurrencyExchange, Shift, User
from ftapp.services import audit, currency_service
from ftapp.services.errors import ValidationError

KINDS = {"sale": "مبيعات", "return": "مرتجعات", "payment": "دفعات زبائن", "expense": "مصاريف",
         "exchange": "صرف عملات", "salary": "رواتب", "advance": "سلف موظفين", "adjust": "تسوية"}


def _round(cur: Currency | None, amount: float) -> float:
    return round(amount or 0, cur.decimals if cur else 2)


def record(session: Session, actor: User | None, currency_code: str, amount: float, kind: str,
           ref_type: str = "", ref_id: int | None = None, notes: str = "", shift: Shift | None = None) -> CashMovement | None:
    """تسجيل دخول (+) أو خروج (-) مبلغ من الصندوق بعملته. يُربط بوردية المستخدم المفتوحة إن وجدت."""
    if not amount:
        return None
    from ftapp.services import finance_service

    if shift is None and actor is not None:
        shift = finance_service.current_shift(session, actor)
    cur = session.get(Currency, currency_code)
    mv = CashMovement(shift_id=shift.id if shift else None, user_id=actor.id if actor else None,
                      currency_code=currency_code, amount=_round(cur, amount), kind=kind, ref_type=ref_type,
                      ref_id=ref_id, notes=notes[:256])
    session.add(mv)
    session.flush()
    return mv


def reverse(session: Session, ref_type: str, ref_id: int) -> None:
    """إلغاء حركات مستند (عند حذف مصروف مثلاً)."""
    for mv in session.scalars(select(CashMovement).where(CashMovement.ref_type == ref_type,
                                                         CashMovement.ref_id == ref_id)):
        session.delete(mv)


def shift_flows(session: Session, shift: Shift) -> dict[str, dict[str, float]]:
    """{عملة: {نوع الحركة: المجموع}} لحركات الوردية."""
    rows = session.execute(select(CashMovement.currency_code, CashMovement.kind, func.sum(CashMovement.amount))
                           .where(CashMovement.shift_id == shift.id)
                           .group_by(CashMovement.currency_code, CashMovement.kind)).all()
    out: dict[str, dict[str, float]] = {}
    for code, kind, total in rows:
        out.setdefault(code, {})[kind] = float(total or 0)
    return out


def shift_balances(session: Session, shift: Shift) -> dict[str, dict[str, float]]:
    """لكل عملة: الرصيد الافتتاحي، الداخل، الخارج، والمتوقع في الصندوق الآن."""
    flows = shift_flows(session, shift)
    opening = dict(shift.opening_balances or {})
    if not opening and shift.opening_cash:
        opening = {currency_service.base(session).code: shift.opening_cash}
    out: dict[str, dict[str, float]] = {}
    for cur in currency_service.list_currencies(session):
        f = flows.get(cur.code, {})
        inflow = sum(v for v in f.values() if v > 0)
        outflow = -sum(v for v in f.values() if v < 0)
        op = float(opening.get(cur.code, 0) or 0)
        out[cur.code] = {"opening": op, "in": _round(cur, inflow), "out": _round(cur, outflow),
                         "expected": _round(cur, op + sum(f.values())), "by_kind": f}
    return out


def balances_in_base(session: Session, balances: dict[str, float]) -> float:
    total = 0.0
    for code, amount in (balances or {}).items():
        cur = session.get(Currency, code)
        if cur is not None:
            total += currency_service.to_base(float(amount or 0), cur)
    return money(total)


# ---------------- صرف العملات ----------------

def exchange_quote(session: Session, direction: str, currency_code: str, amount: float, rate_used: float
                   ) -> dict[str, float]:
    """direction: sell = أعطيت الزبون العملة (دولار) وأخذت المقابل بالليرة، buy = العكس.
    rate_used: سعر الوحدة بالعملة الأساسية. الربح يُحسب مقارنة بسعر الصرف المعتمد في الإعدادات."""
    cur = currency_service.get(session, currency_code)
    base = currency_service.base(session)
    official = currency_service.unit_value(cur)
    counter = _round(base, amount * rate_used)
    if direction == "sell":   # بعت بسعر أعلى من المعتمد = ربح
        profit = amount * (rate_used - official)
    else:                     # اشتريت بسعر أقل من المعتمد = ربح
        profit = amount * (official - rate_used)
    return {"counter_amount": counter, "official": official, "profit": money(profit)}


def create_exchange(session: Session, actor: User | None, direction: str, currency_code: str, amount: float,
                    rate_used: float, customer_name: str = "", notes: str = "") -> CurrencyExchange:
    if direction not in ("sell", "buy"):
        raise ValidationError("نوع عملية الصرف غير معروف")
    if amount <= 0 or rate_used <= 0:
        raise ValidationError("أدخل المبلغ وسعر الصرف")
    cur = currency_service.get(session, currency_code)
    if cur.is_base:
        raise ValidationError("اختر عملة غير العملة الأساسية")
    base = currency_service.base(session)
    q = exchange_quote(session, direction, currency_code, amount, rate_used)
    from ftapp.services import finance_service

    shift = finance_service.current_shift(session, actor) if actor else None
    ex = CurrencyExchange(shift_id=shift.id if shift else None, user_id=actor.id if actor else None,
                          direction=direction, currency_code=cur.code, amount=_round(cur, amount),
                          counter_code=base.code, counter_amount=q["counter_amount"], rate_used=rate_used,
                          rate_official=q["official"], profit=q["profit"], customer_name=customer_name.strip(),
                          notes=notes.strip())
    session.add(ex)
    session.flush()
    sign = -1 if direction == "sell" else 1
    label = f"صرف {'بيع' if direction == 'sell' else 'شراء'} {cur.name} بسعر {rate_used:,.2f}"
    record(session, actor, cur.code, sign * amount, "exchange", "exchange", ex.id, label, shift)
    record(session, actor, base.code, -sign * q["counter_amount"], "exchange", "exchange", ex.id, label, shift)
    audit.log(session, actor, "currency_exchange", "exchange", ex.id, direction=direction, currency=cur.code,
              amount=amount, rate=rate_used, profit=q["profit"])
    bus.publish(SALES_CHANGED, exchange_id=ex.id)
    return ex


def delete_exchange(session: Session, actor: User | None, exchange_id: int) -> None:
    ex = session.get(CurrencyExchange, exchange_id)
    if ex is None:
        return
    reverse(session, "exchange", ex.id)
    audit.log(session, actor, "exchange_deleted", "exchange", ex.id, amount=ex.amount, currency=ex.currency_code)
    session.delete(ex)
    bus.publish(SALES_CHANGED, exchange_id=exchange_id)


def list_exchanges(session: Session, date_from: date | None = None, date_to: date | None = None,
                   limit: int = 500) -> list[CurrencyExchange]:
    stmt = (select(CurrencyExchange).options(selectinload(CurrencyExchange.user))
            .order_by(CurrencyExchange.id.desc()).limit(limit))
    if date_from:
        stmt = stmt.where(CurrencyExchange.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        stmt = stmt.where(CurrencyExchange.created_at < datetime.combine(date_to + timedelta(days=1),
                                                                         datetime.min.time()))
    return list(session.scalars(stmt))


def exchange_profit(session: Session, start: datetime, end: datetime) -> dict[str, float]:
    """ربح/خسارة الصرف بالعملة الأساسية خلال فترة."""
    rows = session.execute(select(func.coalesce(func.sum(CurrencyExchange.profit), 0),
                                  func.coalesce(func.sum(func.max(CurrencyExchange.profit, 0)), 0),
                                  func.coalesce(func.sum(func.min(CurrencyExchange.profit, 0)), 0),
                                  func.count(CurrencyExchange.id))
                           .where(CurrencyExchange.created_at >= start, CurrencyExchange.created_at < end)).one()
    return {"net": money(rows[0]), "gains": money(rows[1]), "losses": money(-rows[2]), "count": int(rows[3] or 0)}
