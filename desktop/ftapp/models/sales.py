from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ftapp.core.utils import now
from ftapp.models.base import Base, TimestampMixin
from ftapp.models.catalog import PriceTier, Product


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    phone: Mapped[str] = mapped_column(String(32), default="", index=True)
    address: Mapped[str] = mapped_column(String(256), default="")
    tier_id: Mapped[int | None] = mapped_column(ForeignKey("price_tiers.id", ondelete="SET NULL"), nullable=True)
    # الدين المستحق على الزبون (بالعملة الأساسية)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    credit_limit: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")

    tier: Mapped[PriceTier | None] = relationship()


class Invoice(Base, TimestampMixin):
    """فاتورة بيع أو مرتجع أو عرض سعر. كل المبالغ بالعملة الأساسية."""
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="sale", index=True)  # sale, return, quotation
    status: Mapped[str] = mapped_column(String(16), default="posted")  # posted, cancelled, converted, open
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    customer_phone: Mapped[str] = mapped_column(String(32), default="")
    customer_address: Mapped[str] = mapped_column(String(256), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True)
    tier_id: Mapped[int | None] = mapped_column(ForeignKey("price_tiers.id", ondelete="SET NULL"), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(8), default="USD")
    exchange_rate: Mapped[float] = mapped_column(Float, default=1.0)
    subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    discount: Mapped[float] = mapped_column(Float, default=0.0)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0)
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    paid: Mapped[float] = mapped_column(Float, default=0.0)
    cost_total: Mapped[float] = mapped_column(Float, default=0.0)
    payment_method: Mapped[str] = mapped_column(String(16), default="cash")  # cash, credit, partial
    notes: Mapped[str] = mapped_column(Text, default="")
    original_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="desktop")

    customer: Mapped[Customer | None] = relationship()
    items: Mapped[list["InvoiceItem"]] = relationship(cascade="all, delete-orphan")
    original: Mapped["Invoice | None"] = relationship(remote_side="Invoice.id")
    user: Mapped["User | None"] = relationship()  # noqa: F821

    @property
    def remaining(self) -> float:
        return round(self.total - self.paid, 2)

    @property
    def profit(self) -> float:
        return round(self.total - self.tax_amount - self.cost_total, 2)


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    product_name: Mapped[str] = mapped_column(String(256))
    product_code: Mapped[str] = mapped_column(String(64), default="")
    unit: Mapped[str] = mapped_column(String(32), default="")
    quantity: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float] = mapped_column(Float)
    discount: Mapped[float] = mapped_column(Float, default=0.0)  # مبلغ خصم السطر
    cost_price: Mapped[float] = mapped_column(Float, default=0.0)
    line_total: Mapped[float] = mapped_column(Float)
    returned_qty: Mapped[float] = mapped_column(Float, default=0.0)

    product: Mapped[Product | None] = relationship()


class CustomerPayment(Base):
    __tablename__ = "customer_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str] = mapped_column(String(256), default="")
    method: Mapped[str] = mapped_column(String(16), default="cash", server_default="cash")  # cash, shamcash
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
