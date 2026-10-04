from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ftapp.core.utils import now
from ftapp.models.base import Base, TimestampMixin
from ftapp.models.catalog import Product, Supplier


class Warehouse(Base, TimestampMixin):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    location: Mapped[str] = mapped_column(String(256), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class StockLevel(Base):
    __tablename__ = "stock_levels"
    __table_args__ = (UniqueConstraint("product_id", "warehouse_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)

    warehouse: Mapped[Warehouse] = relationship()


class Batch(Base):
    """دفعة بضاعة بتاريخ صلاحية (للمنتجات التي تتبع الصلاحية)."""
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"), index=True)
    batch_no: Mapped[str] = mapped_column(String(64), default="")
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    product: Mapped[Product] = relationship()
    warehouse: Mapped[Warehouse] = relationship()


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"), index=True)
    # in, out, sale, return, adjust, damage, purchase, transfer_in, transfer_out, count
    kind: Mapped[str] = mapped_column(String(16), index=True)
    quantity: Mapped[float] = mapped_column(Float)  # موجب = دخول، سالب = خروج
    balance_after: Mapped[float] = mapped_column(Float, default=0.0)
    ref_type: Mapped[str] = mapped_column(String(32), default="")
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(256), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    product: Mapped[Product] = relationship()
    warehouse: Mapped[Warehouse] = relationship()


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    to_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    from_warehouse: Mapped[Warehouse] = relationship(foreign_keys=[from_warehouse_id])
    to_warehouse: Mapped[Warehouse] = relationship(foreign_keys=[to_warehouse_id])
    items: Mapped[list["TransferItem"]] = relationship(cascade="all, delete-orphan")


class TransferItem(Base):
    __tablename__ = "transfer_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("transfers.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    quantity: Mapped[float] = mapped_column(Float)

    product: Mapped[Product] = relationship()


class StockCount(Base):
    """جلسة جرد فعلي."""
    __tablename__ = "stock_counts"

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open, applied, cancelled
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    warehouse: Mapped[Warehouse] = relationship()
    lines: Mapped[list["StockCountLine"]] = relationship(cascade="all, delete-orphan")


class StockCountLine(Base):
    __tablename__ = "stock_count_lines"
    __table_args__ = (UniqueConstraint("count_id", "product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    count_id: Mapped[int] = mapped_column(ForeignKey("stock_counts.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    system_qty: Mapped[float] = mapped_column(Float, default=0.0)
    counted_qty: Mapped[float] = mapped_column(Float, default=0.0)

    product: Mapped[Product] = relationship()

    @property
    def difference(self) -> float:
        return round(self.counted_qty - self.system_qty, 3)


class PurchaseInvoice(Base, TimestampMixin):
    __tablename__ = "purchase_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    supplier_ref: Mapped[str] = mapped_column(String(64), default="")
    total: Mapped[float] = mapped_column(Float, default=0.0)
    paid: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="posted")  # draft, posted
    notes: Mapped[str] = mapped_column(Text, default="")

    supplier: Mapped[Supplier | None] = relationship()
    warehouse: Mapped[Warehouse] = relationship()
    items: Mapped[list["PurchaseItem"]] = relationship(cascade="all, delete-orphan")


class PurchaseItem(Base):
    __tablename__ = "purchase_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchase_invoices.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float)
    batch_no: Mapped[str] = mapped_column(String(64), default="")
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    product: Mapped[Product] = relationship()
