"""البيانات الافتراضية عند الإعداد الأول."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ftapp.models import Currency, ExpenseCategory, PriceTier, Warehouse
from ftapp.services import settings_service as settings

KNOWN_CURRENCIES = {
    "USD": ("دولار أمريكي", "$", 2),
    "SYP": ("ليرة سورية", "ل.س", 0),
    "EUR": ("يورو", "€", 2),
    "TRY": ("ليرة تركية", "₺", 2),
    "AED": ("درهم إماراتي", "د.إ", 2),
    "SAR": ("ريال سعودي", "ر.س", 2),
}


def seed_defaults(session: Session, base_currency: str = "USD", secondary: str | None = "SYP",
                  secondary_rate: float = 0.0) -> None:
    if session.scalar(select(Warehouse).limit(1)) is None:
        session.add(Warehouse(name="المستودع الرئيسي", is_default=True))

    if session.scalar(select(PriceTier).limit(1)) is None:
        session.add_all([
            PriceTier(name="مفرّق", is_default=True, sort_order=0),
            PriceTier(name="جملة", default_margin=None, sort_order=1),
            PriceTier(name="جملة الجملة", default_margin=None, sort_order=2),
        ])

    if session.scalar(select(ExpenseCategory).limit(1)) is None:
        for name in ("إيجار", "كهرباء", "رواتب", "نقل وشحن", "صيانة", "ضيافة", "متفرقات"):
            session.add(ExpenseCategory(name=name))

    if session.get(Currency, base_currency) is None:
        name, symbol, dec = KNOWN_CURRENCIES.get(base_currency, (base_currency, base_currency, 2))
        session.add(Currency(code=base_currency, name=name, symbol=symbol, rate=1.0, is_base=True, decimals=dec))
    if secondary and secondary != base_currency and session.get(Currency, secondary) is None:
        name, symbol, dec = KNOWN_CURRENCIES.get(secondary, (secondary, secondary, 2))
        session.add(Currency(code=secondary, name=name, symbol=symbol, rate=secondary_rate or 1.0,
                             is_base=False, decimals=dec))
    settings.set(session, "base_currency", base_currency)
    settings.set(session, "display_currency", base_currency)
    session.flush()
