"""دوال مساعدة عامة."""
from __future__ import annotations

from datetime import datetime, timezone


def now() -> datetime:
    """الوقت المحلي بدون منطقة زمنية (يُخزن بهذا الشكل في SQLite)."""
    return datetime.now()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def money(value: float | int | None) -> float:
    """تقريب المبالغ إلى خانتين عشريتين بشكل ثابت."""
    if value is None:
        return 0.0
    return round(float(value) + 1e-9, 2)


def qty(value: float | int | None) -> float:
    if value is None:
        return 0.0
    return round(float(value), 3)


def fmt_money(value: float | None, symbol: str = "$", decimals: int = 2) -> str:
    value = value or 0
    text = f"{value:,.{decimals}f}"
    return f"{text} {symbol}".strip()


def fmt_qty(value: float | None) -> str:
    value = value or 0
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.3f}".rstrip("0").rstrip(".")
