"""أدوات الموبايل: تعبئة المنتج من صورته بالذكاء الاصطناعي، رفع صورة المنتج، واستيراد المنتجات من ملف Excel."""
from __future__ import annotations

import base64
import binascii
import uuid
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ftapp.api.deps import AuthContext, get_db, require
from ftapp.core.paths import sub_dir
from ftapp.models import Currency
from ftapp.services import catalog_service, currency_service, excel_service, gemini_service

router = APIRouter(tags=["tools"])

MAX_IMAGE = 8 * 1024 * 1024
MAX_EXCEL = 15 * 1024 * 1024


def _decode(data: str, limit: int) -> bytes:
    try:
        raw = base64.b64decode(data.split(",", 1)[-1], validate=False)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "ملف غير صالح")
    if not raw:
        raise HTTPException(400, "الملف فارغ")
    if len(raw) > limit:
        raise HTTPException(413, "الملف كبير جداً")
    return raw


class ImageIn(BaseModel):
    image_base64: str
    mime: str = "image/jpeg"
    hint: str = ""


def _match_category(db: Session, name: str) -> int | None:
    name = (name or "").strip()
    if not name:
        return None
    best, score = None, 0.0
    for c, _depth in catalog_service.category_tree(db):
        s = 1.0 if c.name.strip() == name else SequenceMatcher(None, c.name.strip(), name).ratio()
        if s > score:
            best, score = c.id, s
    return best if score >= 0.75 else None


@router.post("/ai/product-from-image")
def product_from_image(body: ImageIn, ctx: AuthContext = Depends(require("products.edit")),
                       db: Session = Depends(get_db)) -> dict:
    """يتعرف على المنتج من صورته ويعيد حقول نموذج المنتج جاهزة للتعبئة."""
    raw = _decode(body.image_base64, MAX_IMAGE)
    cats = [c.name for c, _ in catalog_service.category_tree(db)]
    info = gemini_service.product_info_from_image(db, raw, body.mime or "image/jpeg", body.hint, None, cats)
    details = (info.description or "").strip()
    specs = {s.name: s.value for s in info.specs if s.name and s.value}
    extra = []
    if info.uses:
        extra.append("الاستخدامات: " + "، ".join(info.uses))
    if info.origin_country:
        extra.append(f"المنشأ: {info.origin_country}")
    if specs:
        extra.append("\n".join(f"• {k}: {v}" for k, v in specs.items()))
    if extra:
        details = (details + "\n\n" + "\n".join(extra)).strip()
    price = 0.0
    usd = db.get(Currency, "USD")
    if info.estimated_price_usd and info.estimated_price_usd > 0 and usd is not None:
        price = round(info.estimated_price_usd * currency_service.unit_value(usd), 2)
    return {"name": info.name, "brand": info.brand, "model": info.model, "barcode": info.barcode,
            "unit": info.unit, "warranty": info.warranty, "details": details, "specs": specs,
            "category_id": _match_category(db, info.suggested_category),
            "suggested_category": info.suggested_category, "estimated_price": price,
            "confidence": info.confidence}


@router.post("/products/{product_id}/image")
def upload_image(product_id: int, body: ImageIn, ctx: AuthContext = Depends(require("products.edit")),
                 db: Session = Depends(get_db)) -> dict:
    raw = _decode(body.image_base64, MAX_IMAGE)
    ext = ".png" if "png" in (body.mime or "") else ".jpg"
    img = catalog_service.add_image_bytes(db, product_id, raw, ext)
    return {"image": img.path}


# ---------------- استيراد Excel ----------------

class ExcelIn(BaseModel):
    file_base64: str
    filename: str = "products.xlsx"


class ImportIn(BaseModel):
    file_id: str
    mapping: dict[int, str] = Field(default_factory=dict)
    update_existing: bool = True


def _import_path(file_id: str):
    if not file_id or not all(ch in "0123456789abcdef" for ch in file_id):
        raise HTTPException(400, "معرّف ملف غير صالح")
    path = sub_dir("tmp") / f"mobile_import_{file_id}.xlsx"
    if not path.exists():
        raise HTTPException(404, "انتهت صلاحية الملف، اختره من جديد")
    return path


@router.post("/products/import/preview")
def import_preview(body: ExcelIn, ctx: AuthContext = Depends(require("products.edit")),
                   db: Session = Depends(get_db)) -> dict:
    """يرفع ملف Excel ويعيد أعمدته مع ربط تلقائي مقترح بحقول المنتج."""
    if not body.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "اختر ملف Excel بصيغة xlsx")
    raw = _decode(body.file_base64, MAX_EXCEL)
    file_id = uuid.uuid4().hex
    path = sub_dir("tmp") / f"mobile_import_{file_id}.xlsx"
    path.write_bytes(raw)
    try:
        preview = excel_service.read_preview(path, max_rows=5)
    except Exception:
        path.unlink(missing_ok=True)
        raise HTTPException(400, "تعذر قراءة الملف. تأكد أنه ملف Excel صحيح")
    fields = [(f.id, f.name) for f in catalog_service.list_fields(db, all_fields=True)]
    mapping = excel_service.auto_map(preview["headers"], fields)
    targets = [{"key": k, "label": v} for k, v in excel_service.IMPORT_TARGETS.items()]
    targets += [{"key": f"cf:{fid}", "label": name} for fid, name in fields]
    return {"file_id": file_id, "headers": preview["headers"], "total": preview["total"],
            "rows": [[("" if v is None else str(v)) for v in r] for r in preview["rows"]],
            "mapping": {str(k): v for k, v in mapping.items()}, "targets": targets}


@router.post("/products/import")
def import_products(body: ImportIn, ctx: AuthContext = Depends(require("products.edit")),
                    db: Session = Depends(get_db)) -> dict:
    path = _import_path(body.file_id)
    mapping = {int(k): v for k, v in body.mapping.items() if v}
    result = excel_service.import_products(db, ctx.user, path, mapping, update_existing=body.update_existing)
    path.unlink(missing_ok=True)
    return {"created": result.created, "updated": result.updated, "skipped": result.skipped,
            "errors": [{"row": r, "error": e} for r, e in result.errors[:50]], "error_count": len(result.errors)}
