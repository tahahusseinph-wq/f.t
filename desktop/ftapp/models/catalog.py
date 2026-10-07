from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ftapp.core.utils import now
from ftapp.models.base import Base, TimestampMixin


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(8), default="")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True, index=True)
    default_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    color: Mapped[str] = mapped_column(String(16), default="#1565C0")
    icon: Mapped[str] = mapped_column(String(32), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id", back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent", order_by="Category.sort_order")


class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str] = mapped_column(String(32), default="")
    address: Mapped[str] = mapped_column(String(256), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    # المبلغ المستحق للمورد علينا (بالعملة الأساسية)
    balance: Mapped[float] = mapped_column(Float, default=0.0)


class PriceTier(Base):
    """شرائح الأسعار: مفرق، جملة، جملة الجملة..."""
    __tablename__ = "price_tiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    # نسبة ربح افتراضية لهذه الشريحة عند عدم تحديد سعر صريح للمنتج
    default_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    # المنتج الأب عند كون هذا السجل متغيراً (لون/مقاس...)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=True, index=True)
    variant_attrs: Mapped[dict] = mapped_column(JSON, default=dict)

    name: Mapped[str] = mapped_column(String(256), index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    barcode: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True)
    brand: Mapped[str] = mapped_column(String(128), default="", index=True)
    model: Mapped[str] = mapped_column(String(128), default="")
    unit: Mapped[str] = mapped_column(String(32), default="قطعة")

    # الأسعار مخزنة بالعملة الأساسية
    cost_price: Mapped[float] = mapped_column(Float, default=0.0)
    margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    sale_price: Mapped[float] = mapped_column(Float, default=0.0)

    min_stock: Mapped[float | None] = mapped_column(Float, nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    location: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    specs: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    track_expiry: Mapped[bool] = mapped_column(Boolean, default=False)
    warranty: Mapped[str] = mapped_column(String(64), default="")  # مدة الكفالة، فارغ = بدون كفالة
    last_sold_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    category: Mapped[Category | None] = relationship()
    supplier: Mapped[Supplier | None] = relationship()
    parent: Mapped["Product | None"] = relationship(remote_side="Product.id", back_populates="variants")
    variants: Mapped[list["Product"]] = relationship(back_populates="parent", cascade="all, delete-orphan")
    images: Mapped[list["ProductImage"]] = relationship(cascade="all, delete-orphan", order_by="ProductImage.sort_order")
    field_values: Mapped[list["ProductFieldValue"]] = relationship(cascade="all, delete-orphan")
    tier_prices: Mapped[list["ProductTierPrice"]] = relationship(cascade="all, delete-orphan")
    stock_levels: Mapped[list["StockLevel"]] = relationship(cascade="all, delete-orphan")  # noqa: F821

    @property
    def quantity(self) -> float:
        return round(sum(s.quantity for s in self.stock_levels), 3)

    @property
    def variant_label(self) -> str:
        return " / ".join(f"{v}" for v in (self.variant_attrs or {}).values())


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(512))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ProductTierPrice(Base):
    __tablename__ = "product_tier_prices"
    __table_args__ = (UniqueConstraint("product_id", "tier_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    tier_id: Mapped[int] = mapped_column(ForeignKey("price_tiers.id", ondelete="CASCADE"))
    price: Mapped[float] = mapped_column(Float, default=0.0)

    tier: Mapped[PriceTier] = relationship()


class CustomField(Base, TimestampMixin):
    """خانة يضيفها الأدمن بنفسه للمنتجات."""
    __tablename__ = "custom_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    key: Mapped[str] = mapped_column(String(64), unique=True)
    # text, number, decimal, date, bool, choice, url, image
    field_type: Mapped[str] = mapped_column(String(16), default="text")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    default_value: Mapped[str] = mapped_column(String(256), default="")
    options: Mapped[list] = mapped_column(JSON, default=list)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    visible_to_users: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped[Category | None] = relationship()


class ProductFieldValue(Base):
    __tablename__ = "product_field_values"
    __table_args__ = (UniqueConstraint("product_id", "field_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("custom_fields.id", ondelete="CASCADE"), index=True)
    value: Mapped[str] = mapped_column(Text, default="")

    field: Mapped[CustomField] = relationship()


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    old_cost: Mapped[float] = mapped_column(Float, default=0.0)
    new_cost: Mapped[float] = mapped_column(Float, default=0.0)
    old_price: Mapped[float] = mapped_column(Float, default=0.0)
    new_price: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(String(128), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class Promotion(Base, TimestampMixin):
    """خصم مؤقت على منتج أو قسم."""
    __tablename__ = "promotions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=True)
    percent: Mapped[float] = mapped_column(Float, default=0.0)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped[Product | None] = relationship()
    category: Mapped[Category | None] = relationship()
