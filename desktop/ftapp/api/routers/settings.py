"""إعدادات المنشأة (تظهر على الفواتير) وأسعار صرف العملات — من تطبيق الموبايل."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ftapp.api.deps import AuthContext, get_db, require
from ftapp.services import audit, currency_service, settings_service

router = APIRouter(tags=["settings"])

# حقول المنشأة التي يمكن تعديلها من الموبايل
COMPANY_FIELDS = ("name", "name_en", "address", "phone", "email", "tax_number", "invoice_footer",
                  "invoice_details", "facebook_url", "shamcash_account")


class CompanyIn(BaseModel):
    name: str | None = None
    name_en: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    tax_number: str | None = None
    invoice_footer: str | None = None
    invoice_details: str | None = None
    facebook_url: str | None = None
    shamcash_account: str | None = None


class RateIn(BaseModel):
    rate: float | None = Field(default=None, gt=0)   # وحدات العملة مقابل 1 أساسية (النسخ القديمة)
    unit: float | None = Field(default=None, gt=0)   # قيمة 1 من العملة بالعملة الأساسية (1$ = 13000 ل.س)


def _company(db: Session) -> dict:
    c = settings_service.get(db, "company")
    return {k: c.get(k, "") or "" for k in COMPANY_FIELDS}


@router.get("/settings/company")
def get_company(ctx: AuthContext = Depends(require("sales.create")), db: Session = Depends(get_db)) -> dict:
    return _company(db)


@router.put("/settings/company")
def put_company(body: CompanyIn, ctx: AuthContext = Depends(require("settings.manage")),
                db: Session = Depends(get_db)) -> dict:
    changes = {k: v.strip() for k, v in body.model_dump(exclude_none=True).items()}
    if "name" in changes and not changes["name"]:
        changes.pop("name")  # اسم المنشأة لا يُترك فارغاً
    settings_service.update(db, "company", **changes)
    audit.log(db, ctx.user, "settings_changed", "settings", None, source="mobile")
    return _company(db)


@router.put("/currencies/{code}/rate")
def set_rate(code: str, body: RateIn, ctx: AuthContext = Depends(require("settings.manage")),
             db: Session = Depends(get_db)) -> dict:
    if body.rate is None and body.unit is None:
        raise HTTPException(422, "أدخل سعر الصرف")
    cur = currency_service.get(db, code.upper())
    if body.unit is not None:
        currency_service.set_unit_values(db, ctx.user, {cur.code: body.unit})
    else:
        cur = currency_service.save_currency(db, ctx.user, cur.code, cur.name, cur.symbol, body.rate, cur.decimals)
    return {"code": cur.code, "name": cur.name, "symbol": cur.symbol, "rate": cur.rate, "is_base": cur.is_base,
            "decimals": cur.decimals, "unit": currency_service.nice(currency_service.unit_value(cur))}


# ---- تصميم وقياسات الفاتورة (للأدمن من الموبايل) ----
INVOICE_TEXT = ("sale_title", "quotation_title", "return_title", "accent_color", "terms", "payment_info")
INVOICE_FLAGS = ("show_code", "show_unit", "show_seller", "show_qr", "show_signatures", "show_stamp", "show_warranty")


def _invoice(db: Session) -> dict:
    from ftapp.services import pdf_service

    iv = settings_service.get(db, "invoice")
    return {
        **{k: iv.get(k, "") or "" for k in INVOICE_TEXT},
        **{k: bool(iv.get(k, True)) for k in INVOICE_FLAGS},
        "sizes": [{"key": k, "label": label, "value": round(pdf_service.size_factor(iv, k) * 100), "default": d,
                   "min": lo, "max": hi} for k, label, d, lo, hi in pdf_service.INVOICE_SIZES],
        "margin_mm": pdf_service.invoice_margin(iv),
    }


@router.get("/settings/invoice")
def get_invoice(ctx: AuthContext = Depends(require("settings.manage")), db: Session = Depends(get_db)) -> dict:
    return _invoice(db)


@router.put("/settings/invoice")
def put_invoice(body: dict, ctx: AuthContext = Depends(require("settings.manage")),
                db: Session = Depends(get_db)) -> dict:
    from ftapp.services import pdf_service

    changes: dict = {}
    for k in INVOICE_TEXT:
        if isinstance(body.get(k), str):
            changes[k] = body[k].strip()
    for k in INVOICE_FLAGS:
        if isinstance(body.get(k), bool):
            changes[k] = body[k]
    for k, _label, _d, lo, hi in pdf_service.INVOICE_SIZES:
        if isinstance(body.get(k), (int, float)):
            changes[k] = int(max(lo, min(hi, body[k])))
    if isinstance(body.get("margin_mm"), (int, float)):
        changes["margin_mm"] = int(max(pdf_service.MARGIN_RANGE[0], min(pdf_service.MARGIN_RANGE[1], body["margin_mm"])))
    for k in ("sale_title", "quotation_title", "return_title"):
        if k in changes and not changes[k]:
            changes.pop(k)
    settings_service.update(db, "invoice", **changes)
    audit.log(db, ctx.user, "settings_changed", "settings", None, source="mobile")
    return _invoice(db)
