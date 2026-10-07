"""نماذج طلبات وإجابات الـ API."""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str
    device_name: str = "Android"


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    role_label: str
    permissions: list[str]


class LoginOut(BaseModel):
    token: str
    user: UserOut
    server_id: str
    company: dict[str, Any]


class CartLineIn(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    unit_price: float | None = None
    discount: float = 0.0


class SaleIn(BaseModel):
    lines: list[CartLineIn]
    customer_id: int | None = None
    customer_name: str = ""
    customer_phone: str = ""
    customer_address: str = ""
    warehouse_id: int | None = None
    tier_id: int | None = None
    discount: float = 0.0
    paid: float | None = None
    payment_method: str = "cash"
    currency_code: str | None = None
    notes: str = ""
    kind: str = "sale"  # sale | quotation
    client_op_id: str | None = None


class StockChangeIn(BaseModel):
    quantity: float | None = None   # كمية جديدة مطلقة
    delta: float | None = None      # أو تغيير نسبي
    reason: str = "تعديل من الموبايل"
    warehouse_id: int | None = None
    client_op_id: str | None = None


class ProductIn(BaseModel):
    name: str
    code: str = ""
    barcode: str = ""
    category_id: int | None = None
    brand: str = ""
    model: str = ""
    unit: str = "قطعة"
    cost_price: float = 0.0
    margin: float | None = None
    price_locked: bool = False
    sale_price: float = 0.0
    min_stock: float | None = None
    location: str = ""
    details: str = ""
    notes: str = ""
    warranty: str | None = None   # None = بدون تغيير (نسخ الموبايل القديمة)، "" = بدون كفالة
    initial_quantity: float = 0.0
    custom_values: dict[int, Any] = Field(default_factory=dict)


class CountLineIn(BaseModel):
    code: str | None = None
    product_id: int | None = None
    quantity: float = Field(ge=0)
    mode: str = "add"  # add | set
    client_op_id: str | None = None


class CountIn(BaseModel):
    warehouse_id: int | None = None
    notes: str = ""


class CustomerIn(BaseModel):
    name: str
    phone: str = ""
    address: str = ""
    tier_id: int | None = None


class PaymentIn(BaseModel):
    amount: float = Field(gt=0)
    notes: str = ""


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "viewer"
    full_name: str = ""
    phone: str = ""


class UserPatch(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


class SyncOp(BaseModel):
    client_op_id: str
    type: str  # sale | stock | count_line
    payload: dict[str, Any]
    created_at: str | None = None


class SyncIn(BaseModel):
    ops: list[SyncOp]


class ReturnIn(BaseModel):
    items: list[tuple[int, float]]
    refund_to: str = "cash"
    notes: str = ""


class DateRange(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
