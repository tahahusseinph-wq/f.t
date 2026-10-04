from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ftapp.core.utils import now
from ftapp.models.base import Base, TimestampMixin


class Currency(Base):
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(8))
    # عدد وحدات هذه العملة مقابل 1 من العملة الأساسية
    rate: Mapped[float] = mapped_column(Float, default=1.0)
    is_base: Mapped[bool] = mapped_column(Boolean, default=False)
    decimals: Mapped[int] = mapped_column(default=2)


class ExchangeRateHistory(Base):
    __tablename__ = "exchange_rate_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    currency_code: Mapped[str] = mapped_column(ForeignKey("currencies.code", ondelete="CASCADE"), index=True)
    rate: Mapped[float] = mapped_column(Float)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("expense_categories.id", ondelete="SET NULL"), nullable=True)
    amount: Mapped[float] = mapped_column(Float)  # بالعملة الأساسية
    description: Mapped[str] = mapped_column(String(256), default="")
    expense_date: Mapped[date] = mapped_column(Date, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True)
    paid_from_cash: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped[ExpenseCategory | None] = relationship()


class Shift(Base):
    """وردية الصندوق لكل بائع."""
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open, closed
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    opening_cash: Mapped[float] = mapped_column(Float, default=0.0)
    expected_cash: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cash: Mapped[float] = mapped_column(Float, default=0.0)
    difference: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")

    user: Mapped["User"] = relationship()  # noqa: F821
