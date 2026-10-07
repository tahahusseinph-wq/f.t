"""إعدادات المنشأة (تظهر على الفواتير) وأسعار صرف العملات — من تطبيق الموبايل."""
from __future__ import annotations

from fastapi import APIRouter, Depends
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
    rate: float = Field(gt=0)


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
    cur = currency_service.get(db, code.upper())
    cur = currency_service.save_currency(db, ctx.user, cur.code, cur.name, cur.symbol, body.rate, cur.decimals)
    return {"code": cur.code, "name": cur.name, "symbol": cur.symbol, "rate": cur.rate, "is_base": cur.is_base,
            "decimals": cur.decimals}
