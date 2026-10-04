"""العملات وأسعار الصرف."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ftapp.core.utils import fmt_money
from ftapp.models import Currency, ExchangeRateHistory, User
from ftapp.services import audit, settings_service as settings
from ftapp.services.errors import NotFound, ValidationError


def list_currencies(session: Session) -> list[Currency]:
    return list(session.scalars(select(Currency).order_by(Currency.is_base.desc(), Currency.code)))


def base(session: Session) -> Currency:
    cur = session.scalar(select(Currency).where(Currency.is_base.is_(True)))
    if cur is None:
        cur = Currency(code="USD", name="دولار أمريكي", symbol="$", rate=1.0, is_base=True)
        session.add(cur)
        session.flush()
    return cur


def get(session: Session, code: str) -> Currency:
    cur = session.get(Currency, code)
    if cur is None:
        raise NotFound("العملة غير موجودة")
    return cur


def display(session: Session) -> Currency:
    code = settings.get(session, "display_currency")
    return session.get(Currency, code) or base(session)


def convert(amount: float, currency: Currency) -> float:
    """من العملة الأساسية إلى العملة المطلوبة."""
    return round((amount or 0) * (currency.rate or 1), currency.decimals)


def to_base(amount: float, currency: Currency) -> float:
    return round((amount or 0) / (currency.rate or 1), 4)


def format_amount(session: Session, amount_base: float, code: str | None = None) -> str:
    cur = session.get(Currency, code) if code else display(session)
    cur = cur or base(session)
    return fmt_money(convert(amount_base, cur), cur.symbol, cur.decimals)


def save_currency(session: Session, actor: User | None, code: str, name: str, symbol: str, rate: float,
                  decimals: int = 2) -> Currency:
    code = code.strip().upper()
    if not code or rate <= 0:
        raise ValidationError("أدخل رمز العملة وسعر صرف أكبر من صفر")
    cur = session.get(Currency, code)
    if cur is None:
        cur = Currency(code=code, name=name, symbol=symbol, rate=rate, decimals=decimals, is_base=False)
        session.add(cur)
        session.add(ExchangeRateHistory(currency_code=code, rate=rate, user_id=actor.id if actor else None))
    else:
        if cur.is_base and rate != 1:
            raise ValidationError("سعر صرف العملة الأساسية دائماً 1")
        if abs(cur.rate - rate) > 1e-9:
            session.add(ExchangeRateHistory(currency_code=code, rate=rate, user_id=actor.id if actor else None))
            audit.log(session, actor, "rate_changed", "currency", None, code=code, old=cur.rate, new=rate)
        cur.name, cur.symbol, cur.rate, cur.decimals = name, symbol, rate, decimals
    session.flush()
    return cur


def delete_currency(session: Session, code: str) -> None:
    cur = get(session, code)
    if cur.is_base:
        raise ValidationError("لا يمكن حذف العملة الأساسية")
    if settings.get(session, "display_currency") == code:
        settings.set(session, "display_currency", base(session).code)
    session.delete(cur)


def rate_history(session: Session, code: str) -> list[ExchangeRateHistory]:
    return list(session.scalars(select(ExchangeRateHistory).where(ExchangeRateHistory.currency_code == code)
                                .order_by(ExchangeRateHistory.changed_at)))
