"""العملات وأسعار الصرف.

كل المبالغ مخزّنة بالعملة الأساسية (الليرة السورية افتراضياً). حقل rate في جدول العملات =
عدد وحدات العملة مقابل 1 من العملة الأساسية، أما الواجهة فتعرض السعر بالشكل المألوف:
«1 دولار = 13,000 ل.س» عبر unit_value().
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ftapp.core.utils import fmt_money
from ftapp.models import Currency, ExchangeRateHistory, User
from ftapp.services import audit, settings_service as settings
from ftapp.services.errors import NotFound, ValidationError

# العملات المفعّلة دائماً: (الاسم، الرمز، الخانات العشرية، سعر تقريبي مقابل الدولار للبداية فقط)
STANDARD = {
    "SYP": ("ليرة سورية", "ل.س", 0, None),
    "USD": ("دولار أمريكي", "$", 2, 1.0),
    "EUR": ("يورو", "€", 2, 0.86),
    "TRY": ("ليرة تركية", "₺", 2, 41.0),
}
MAIN_CODE = "SYP"
REF_CODE = "USD"  # العملة المرجعية لسطر «ما يعادل» وسعر الصرف عند الطباعة


def list_currencies(session: Session) -> list[Currency]:
    order = {code: i for i, code in enumerate(STANDARD)}
    curs = list(session.scalars(select(Currency)))
    return sorted(curs, key=lambda c: (not c.is_base, order.get(c.code, 99), c.code))


def base(session: Session) -> Currency:
    cur = session.scalar(select(Currency).where(Currency.is_base.is_(True)))
    if cur is None:
        name, symbol, dec, _ = STANDARD[MAIN_CODE]
        cur = session.get(Currency, MAIN_CODE)
        if cur is None:
            cur = Currency(code=MAIN_CODE, name=name, symbol=symbol, rate=1.0, decimals=dec)
            session.add(cur)
        cur.is_base, cur.rate = True, 1.0
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


def reference(session: Session) -> Currency | None:
    """العملة المرجعية (الدولار) إن لم تكن هي الأساسية."""
    cur = session.get(Currency, REF_CODE)
    if cur is None or cur.is_base:
        cur = next((c for c in list_currencies(session) if not c.is_base), None)
    return cur


def convert(amount: float, currency: Currency) -> float:
    """من العملة الأساسية إلى العملة المطلوبة."""
    return round((amount or 0) * (currency.rate or 1), currency.decimals)


def to_base(amount: float, currency: Currency) -> float:
    return round((amount or 0) / (currency.rate or 1), 4)


def unit_value(currency: Currency) -> float:
    """قيمة وحدة واحدة من العملة بالعملة الأساسية (مثال: 1 دولار = 13000 ل.س)."""
    return 1.0 / currency.rate if currency.rate else 0.0


def nice(value: float) -> float:
    """تقريب لطيف لقيمة سعر الصرف (يزيل كسور القسمة العشرية)."""
    return round(value, 2) if value >= 1 else round(value, 6)


def format_amount(session: Session, amount_base: float, code: str | None = None) -> str:
    cur = session.get(Currency, code) if code else display(session)
    cur = cur or base(session)
    return fmt_money(convert(amount_base, cur), cur.symbol, cur.decimals)


def format_in(cur: Currency, amount: float) -> str:
    """تنسيق مبلغ مكتوب أصلاً بعملته."""
    return fmt_money(amount, cur.symbol, cur.decimals)


def rate_label(session: Session, cur: Currency) -> str:
    b = base(session)
    return f"1 {cur.code} = {fmt_money(nice(unit_value(cur)), b.symbol, 2 if unit_value(cur) < 100 else 0)}"


def _record(session: Session, actor: User | None, cur: Currency, new_rate: float) -> None:
    if abs((cur.rate or 0) - new_rate) > 1e-12:
        session.add(ExchangeRateHistory(currency_code=cur.code, rate=new_rate, user_id=actor.id if actor else None))
        audit.log(session, actor, "rate_changed", "currency", None, code=cur.code,
                  old=nice(unit_value(cur)) if cur.rate else 0, new=nice(1 / new_rate))
    cur.rate = new_rate


def save_currency(session: Session, actor: User | None, code: str, name: str, symbol: str, rate: float | None = None,
                  decimals: int = 2, unit: float | None = None) -> Currency:
    """rate: وحدات العملة مقابل 1 أساسية، أو unit: قيمة الوحدة بالعملة الأساسية (الشكل المألوف)."""
    code = code.strip().upper()
    if unit is not None:
        if unit <= 0:
            raise ValidationError("أدخل سعر صرف أكبر من صفر")
        rate = 1.0 / unit
    if not code or not rate or rate <= 0:
        raise ValidationError("أدخل رمز العملة وسعر صرف أكبر من صفر")
    cur = session.get(Currency, code)
    if cur is None:
        cur = Currency(code=code, name=name, symbol=symbol, rate=rate, decimals=decimals, is_base=False)
        session.add(cur)
        session.add(ExchangeRateHistory(currency_code=code, rate=rate, user_id=actor.id if actor else None))
    else:
        if cur.is_base and abs(rate - 1) > 1e-12:
            raise ValidationError("سعر صرف العملة الأساسية دائماً 1")
        _record(session, actor, cur, rate)
        cur.name, cur.symbol, cur.decimals = name, symbol, decimals
    session.flush()
    return cur


def set_unit_values(session: Session, actor: User | None, values: dict[str, float]) -> list[str]:
    """حفظ أسعار صرف عدة عملات دفعة واحدة بالشكل المألوف {"USD": 13000, "EUR": 15200}.
    يعيد رموز العملات التي تغيّر سعرها."""
    changed = []
    for code, unit in values.items():
        cur = get(session, code)
        if cur.is_base:
            continue
        if not unit or unit <= 0:
            raise ValidationError(f"سعر صرف {cur.name} يجب أن يكون أكبر من صفر")
        if abs(unit_value(cur) - unit) > 1e-9 * max(1.0, unit):
            _record(session, actor, cur, 1.0 / unit)
            changed.append(code)
    session.flush()
    return changed


def delete_currency(session: Session, code: str) -> None:
    cur = get(session, code)
    if cur.is_base:
        raise ValidationError("لا يمكن حذف العملة الأساسية")
    if code in STANDARD:
        raise ValidationError("هذه العملة من العملات الأساسية للبرنامج ولا يمكن حذفها")
    if settings.get(session, "display_currency") == code:
        settings.set(session, "display_currency", base(session).code)
    session.delete(cur)


def rate_history(session: Session, code: str) -> list[ExchangeRateHistory]:
    return list(session.scalars(select(ExchangeRateHistory).where(ExchangeRateHistory.currency_code == code)
                                .order_by(ExchangeRateHistory.changed_at)))


# ---------------- العملات القياسية وتحويل العملة الأساسية ----------------

def ensure_standard(session: Session) -> list[str]:
    """تفعيل الليرة السورية والدولار واليورو والليرة التركية. يعيد العملات التي أُضيفت."""
    added = []
    base(session)
    usd = session.get(Currency, "USD")
    for code, (name, symbol, dec, per_usd) in STANDARD.items():
        if session.get(Currency, code) is not None:
            continue
        if per_usd is None or usd is None:
            continue  # لا نعرف سعراً تقريبياً
        rate = (usd.rate if not usd.is_base else 1.0) * per_usd
        session.add(Currency(code=code, name=name, symbol=symbol, rate=rate, decimals=dec, is_base=False))
        session.add(ExchangeRateHistory(currency_code=code, rate=rate))
        added.append(code)
    session.flush()
    if added:
        from ftapp.services import notification_service
        for code in added:
            notification_service.add(session, "rate", f"تم تفعيل عملة {STANDARD[code][0]}",
                                     "سعر صرفها تقريبي، عدّله من الإعدادات ← أسعار الصرف", "warning")
    return added


# أعمدة المبالغ المخزنة بالعملة الأساسية (تُضرب بمعامل التحويل عند تغيير العملة الأساسية)
MONEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "products": ("cost_price", "sale_price"),
    "product_tier_prices": ("price",),
    "price_history": ("old_cost", "new_cost", "old_price", "new_price"),
    "suppliers": ("balance",),
    "customers": ("balance", "credit_limit"),
    "invoices": ("subtotal", "discount", "tax_amount", "total", "paid", "cost_total", "ref_rate"),
    "invoice_items": ("unit_price", "discount", "cost_price", "line_total"),
    "customer_payments": ("amount",),
    "purchase_invoices": ("total", "paid"),
    "purchase_items": ("unit_cost",),
    "expenses": ("amount",),
    "shifts": ("opening_cash", "expected_cash", "actual_cash", "difference"),
    "currency_exchanges": ("profit",),
    "employees": ("salary",),
    "employee_transactions": ("amount", "deducted", "net"),
}


def change_base(session: Session, actor: User | None, new_code: str) -> float:
    """جعل عملة أخرى هي الأساسية وتحويل كل المبالغ المخزنة إليها بسعر الصرف الحالي.
    يعيد معامل التحويل المستخدم."""
    old = base(session)
    new = get(session, new_code)
    if new.is_base:
        return 1.0
    factor = new.rate  # وحدات العملة الجديدة مقابل 1 من القديمة
    if not factor or factor <= 0:
        raise ValidationError("سعر صرف العملة الجديدة غير صالح")
    session.flush()
    for table, cols in MONEY_COLUMNS.items():
        sets = ", ".join(f"{c} = {c} * :f" for c in cols)
        session.execute(text(f"UPDATE {table} SET {sets}"), {"f": factor})
    # أسعار الفواتير المخزنة: وحدات عملة الفاتورة مقابل 1 أساسية
    session.execute(text("UPDATE invoices SET exchange_rate = exchange_rate / :f"), {"f": factor})
    session.execute(text("UPDATE exchange_rate_history SET rate = rate / :f"), {"f": factor})
    for cur in session.scalars(select(Currency)):
        cur.rate = cur.rate / factor
        cur.is_base = False
    new.rate, new.is_base = 1.0, True
    # تاريخ سعر العملة الأساسية القديمة يصبح تاريخ سعرها مقابل الجديدة
    session.add(ExchangeRateHistory(currency_code=old.code, rate=old.rate, user_id=actor.id if actor else None))
    large = float(settings.get(session, "large_invoice_amount") or 0)
    if large:
        settings.set(session, "large_invoice_amount", round(large * factor, 2))
    settings.set(session, "base_currency", new.code)
    settings.set(session, "display_currency", new.code)
    audit.log(session, actor, "base_currency_changed", "currency", None, old=old.code, new=new.code, factor=factor)
    session.flush()
    session.expire_all()
    return factor


def needs_main_base(session: Session) -> bool:
    """هل يجب تحويل العملة الأساسية إلى الليرة السورية (مرة واحدة للبيانات القديمة)؟"""
    if settings.get(session, "main_base_done"):
        return False
    syp = session.get(Currency, MAIN_CODE)
    return syp is not None and not syp.is_base and (syp.rate or 0) > 0


def prepare(session: Session) -> None:
    """يُستدعى عند كل تشغيل: العملات القياسية + الليرة السورية عملة أساسية + عملة العرض."""
    if not settings.get(session, "setup_done"):
        return
    if needs_main_base(session):
        change_base(session, None, MAIN_CODE)
    settings.set(session, "main_base_done", True)
    ensure_standard(session)
    if settings.get(session, "display_currency") != base(session).code and not settings.get(session, "display_fixed"):
        settings.set(session, "display_currency", base(session).code)
    settings.set(session, "display_fixed", True)
