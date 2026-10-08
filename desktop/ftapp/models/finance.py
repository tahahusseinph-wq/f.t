from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, String, Text
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
    # أرصدة الصندوق لكل عملة: {"SYP": 500000, "USD": 100}
    opening_balances: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_balances: Mapped[dict] = mapped_column(JSON, default=dict)
    actual_balances: Mapped[dict] = mapped_column(JSON, default=dict)

    user: Mapped["User"] = relationship()  # noqa: F821


class CashMovement(Base):
    """حركة نقدية فعلية في الصندوق بعملتها (بيع، مرتجع، دفعة، مصروف، صرف عملات...)."""
    __tablename__ = "cash_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(8))
    amount: Mapped[float] = mapped_column(Float)  # بعملة الحركة: موجب = دخول للصندوق، سالب = خروج
    kind: Mapped[str] = mapped_column(String(16))  # sale, return, payment, expense, exchange, salary, advance
    ref_type: Mapped[str] = mapped_column(String(16), default="")
    ref_id: Mapped[int | None] = mapped_column(nullable=True)
    notes: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class CurrencyExchange(Base):
    """عملية صرف عملات مع زبون: الزبون يعطي عملة ويأخذ عملة أخرى."""
    __tablename__ = "currency_exchanges"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    direction: Mapped[str] = mapped_column(String(8))  # sell = بعت العملة للزبون، buy = اشتريتها منه
    currency_code: Mapped[str] = mapped_column(String(8))  # العملة المصروفة (دولار، يورو...)
    amount: Mapped[float] = mapped_column(Float)            # كميتها
    counter_code: Mapped[str] = mapped_column(String(8))   # العملة المقابلة (الليرة)
    counter_amount: Mapped[float] = mapped_column(Float)    # المبلغ المقابل
    rate_used: Mapped[float] = mapped_column(Float)         # سعر الوحدة المطبَّق (بالعملة المقابلة)
    rate_official: Mapped[float] = mapped_column(Float)     # سعر الصرف المعتمد في الإعدادات وقتها
    profit: Mapped[float] = mapped_column(Float, default=0.0)  # الربح (+) أو الخسارة (-) بالعملة الأساسية
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    notes: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    user: Mapped["User | None"] = relationship()  # noqa: F821


class Employee(Base, TimestampMixin):
    """موظف براتب يومي أو أسبوعي أو شهري."""
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str] = mapped_column(String(32), default="")
    pay_period: Mapped[str] = mapped_column(String(16), default="monthly")  # daily, weekly, monthly
    salary: Mapped[float] = mapped_column(Float, default=0.0)  # بالعملة الأساسية لكل فترة
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class EmployeeTransaction(Base):
    """راتب مدفوع أو سلفة مسحوبة. السلف تُخصم من الرواتب اللاحقة."""
    __tablename__ = "employee_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # salary, advance
    amount: Mapped[float] = mapped_column(Float)    # الراتب الإجمالي أو قيمة السلفة
    deducted: Mapped[float] = mapped_column(Float, default=0.0)  # المخصوم من السلف (للراتب)
    net: Mapped[float] = mapped_column(Float, default=0.0)       # المدفوع فعلياً
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    pay_date: Mapped[date] = mapped_column(Date, index=True)
    expense_id: Mapped[int | None] = mapped_column(ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    employee: Mapped[Employee] = relationship()
