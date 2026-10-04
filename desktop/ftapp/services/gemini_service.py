"""تكامل Google Gemini: جلب تفاصيل المنتج، التعرف من صورة، قراءة فاتورة مورد،
اقتراح كود، والإجابة عن أسئلة حول البيانات.

كل الطلبات تُرجع JSON منظماً عبر response_schema لضمان صحة البيانات.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ftapp.models import AICache
from ftapp.services import secrets_service, settings_service as settings
from ftapp.services.errors import ServiceError

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
CACHE_KINDS = {"details", "code"}


class AIError(ServiceError):
    pass


# ---------------- مخططات الإجابات ----------------

class SpecItem(BaseModel):
    name: str = Field(description="اسم المواصفة بالعربية")
    value: str = Field(description="قيمة المواصفة")


class FieldValue(BaseModel):
    name: str = Field(description="اسم الخانة كما أُعطيت بالضبط")
    value: str


class ProductDetails(BaseModel):
    description: str = Field(description="وصف تسويقي مختصر بالعربية من 2-4 جمل")
    specs: list[SpecItem] = Field(default_factory=list, description="المواصفات الفنية الأساسية")
    origin_country: str = Field(default="", description="بلد المنشأ أو الشركة المصنعة إن كان معروفاً")
    uses: list[str] = Field(default_factory=list, description="الاستخدامات الشائعة")
    suggested_category: str = Field(default="", description="اسم قسم مقترح بالعربية")
    keywords: list[str] = Field(default_factory=list)
    custom_fields: list[FieldValue] = Field(default_factory=list, description="قيم الخانات المطلوبة إن أمكن")
    confidence: str = Field(default="medium", description="high أو medium أو low حسب الثقة بالمعلومات")


class IdentifiedProduct(BaseModel):
    name: str = Field(description="اسم المنتج بالعربية كما يُعرض في المتجر")
    brand: str = ""
    model: str = ""
    suggested_category: str = ""
    description: str = ""
    specs: list[SpecItem] = Field(default_factory=list)
    barcode: str = Field(default="", description="أرقام الباركود إن كانت ظاهرة في الصورة")
    confidence: str = "medium"


class InvoiceLine(BaseModel):
    name: str
    code: str = ""
    quantity: float = 0
    unit_price: float = 0
    total: float = 0


class SupplierInvoice(BaseModel):
    supplier_name: str = ""
    invoice_number: str = ""
    date: str = ""
    currency: str = ""
    items: list[InvoiceLine] = Field(default_factory=list)
    total: float = 0


class CodeSuggestion(BaseModel):
    code: str = Field(description="كود قصير بحروف إنكليزية كبيرة وأرقام وشرطات فقط، أقل من 20 حرفاً")
    reason: str = ""


class DataAnswer(BaseModel):
    answer: str = Field(description="الإجابة بالعربية بشكل واضح ومختصر، يمكن استخدام نقاط")
    highlights: list[str] = Field(default_factory=list, description="أرقام أو حقائق رئيسية")


# ---------------- الأساسيات ----------------

def _config(session: Session | None) -> dict[str, Any]:
    cfg = settings.get(session, "gemini") if session is not None else {}
    return {"model": cfg.get("model") or DEFAULT_MODEL, "enabled": cfg.get("enabled", True)}


def is_configured() -> bool:
    return bool(secrets_service.gemini_key())


def _client(api_key: str | None = None):
    from google import genai

    key = api_key or secrets_service.gemini_key()
    if not key:
        raise AIError("لم يتم إدخال مفتاح Gemini API. أضفه من الإعدادات ← الذكاء الاصطناعي")
    return genai.Client(api_key=key)


def _translate_error(exc: Exception) -> AIError:
    text = str(exc)
    code = getattr(exc, "code", None)
    if code in (401, 403) or "API_KEY_INVALID" in text or "API key not valid" in text:
        return AIError("مفتاح Gemini غير صالح، تأكد منه من الإعدادات")
    if code == 429 or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():
        return AIError("تم تجاوز الحد المسموح من طلبات Gemini، حاول لاحقاً")
    if code == 404 or "not found" in text.lower():
        return AIError("اسم موديل Gemini غير صحيح، غيّره من الإعدادات")
    if any(k in text.lower() for k in ("connect", "timeout", "network", "resolve", "unreachable")):
        return AIError("لا يوجد اتصال بالإنترنت أو تعذر الوصول إلى خدمة Gemini")
    log.exception("gemini error")
    return AIError(f"تعذر تنفيذ الطلب: {text[:200]}")


def _generate(session: Session | None, contents: list[Any], schema: type[BaseModel], system: str,
              temperature: float = 0.3, api_key: str | None = None) -> BaseModel:
    from google.genai import types

    cfg = _config(session)
    if not cfg["enabled"]:
        raise AIError("ميزة الذكاء الاصطناعي معطلة من الإعدادات")
    try:
        client = _client(api_key)
        resp = client.models.generate_content(
            model=cfg["model"], contents=contents,
            config=types.GenerateContentConfig(system_instruction=system, temperature=temperature,
                                               response_mime_type="application/json", response_schema=schema),
        )
    except AIError:
        raise
    except Exception as exc:
        raise _translate_error(exc) from exc
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, schema):
        return parsed
    try:
        return schema.model_validate(json.loads(resp.text or "{}"))
    except Exception as exc:
        raise AIError("استجابة غير مفهومة من Gemini، حاول مرة أخرى") from exc


def _cache_key(kind: str, model: str, *parts: Any) -> str:
    raw = json.dumps([kind, model, *parts], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cached(session: Session | None, kind: str, key: str, schema: type[BaseModel]) -> BaseModel | None:
    if session is None:
        return None
    row = session.get(AICache, key)
    if row is None:
        return None
    try:
        return schema.model_validate(row.payload)
    except Exception:
        return None


def _store(session: Session | None, kind: str, key: str, value: BaseModel) -> None:
    if session is None:
        return
    row = session.get(AICache, key)
    if row is None:
        session.add(AICache(key=key, kind=kind, payload=value.model_dump()))
    else:
        row.payload = value.model_dump()
    session.flush()


SYSTEM_PRODUCT = (
    "أنت خبير منتجات في متجر جملة ومفرق في سوريا. أجب بالعربية الفصحى المبسطة. "
    "قدّم معلومات دقيقة فقط؛ إذا لم تكن متأكداً من معلومة اتركها فارغة ولا تخترع أرقاماً. "
    "أسماء الماركات والموديلات تبقى بالإنكليزية."
)


# ---------------- العمليات ----------------

def test_connection(api_key: str | None = None, model: str | None = None) -> str:
    from google.genai import types

    try:
        client = _client(api_key)
        resp = client.models.generate_content(model=model or DEFAULT_MODEL, contents="رد بكلمة واحدة: تم",
                                              config=types.GenerateContentConfig(temperature=0))
        return (resp.text or "").strip() or "تم"
    except AIError:
        raise
    except Exception as exc:
        raise _translate_error(exc) from exc


def fetch_product_details(session: Session | None, name: str, brand: str = "", model: str = "",
                          extra: str = "", field_names: list[str] | None = None, use_cache: bool = True
                          ) -> ProductDetails:
    if not name.strip():
        raise AIError("أدخل اسم المنتج أولاً")
    cfg = _config(session)
    key = _cache_key("details", cfg["model"], name.strip(), brand.strip(), model.strip(), extra.strip(),
                     sorted(field_names or []))
    if use_cache:
        hit = _cached(session, "details", key, ProductDetails)
        if hit:
            return hit  # type: ignore[return-value]
    prompt = (f"المنتج: {name}\nالماركة: {brand or 'غير محددة'}\nالموديل: {model or 'غير محدد'}\n"
              f"{('معلومات إضافية: ' + extra) if extra else ''}\n"
              "أعطني تفاصيل المنتج والمواصفات الفنية.")
    if field_names:
        prompt += "\nواملأ هذه الخانات إن أمكن (بنفس الأسماء بالضبط): " + "، ".join(field_names)
    result = _generate(session, [prompt], ProductDetails, SYSTEM_PRODUCT)
    _store(session, "details", key, result)
    return result  # type: ignore[return-value]


def identify_from_image(session: Session | None, image: bytes, mime: str = "image/jpeg", hint: str = ""
                        ) -> IdentifiedProduct:
    from google.genai import types

    prompt = "تعرّف على المنتج في الصورة وأعطني اسمه وماركته وموديله ووصفه ومواصفاته."
    if hint:
        prompt += f" ملاحظة من المستخدم: {hint}"
    return _generate(session, [types.Part.from_bytes(data=image, mime_type=mime), prompt],  # type: ignore[return-value]
                     IdentifiedProduct, SYSTEM_PRODUCT)


def parse_supplier_invoice(session: Session | None, image: bytes, mime: str = "image/jpeg") -> SupplierInvoice:
    from google.genai import types

    system = ("أنت محاسب خبير تقرأ فواتير الموردين المكتوبة بالعربية أو الإنكليزية (مطبوعة أو بخط اليد). "
              "استخرج كل الأسطر بدقة. الأرقام بالأرقام الإنكليزية. إذا كان الرقم غير واضح ضع 0.")
    prompt = "استخرج بيانات فاتورة الشراء هذه: اسم المورد، رقم الفاتورة، التاريخ، العملة، والأصناف مع الكميات والأسعار."
    return _generate(session, [types.Part.from_bytes(data=image, mime_type=mime), prompt],  # type: ignore[return-value]
                     SupplierInvoice, system, temperature=0.1)


def suggest_code(session: Session | None, name: str, category: str = "", brand: str = "", model: str = "",
                 existing_examples: list[str] | None = None) -> CodeSuggestion:
    prompt = (f"اقترح كود منتج قصيراً ومقروءاً للمنتج: {name}\nالقسم: {category}\nالماركة: {brand}\n"
              f"الموديل: {model}\n")
    if existing_examples:
        prompt += "اتبع نمط هذه الأكواد الموجودة: " + ", ".join(existing_examples[:10])
    result = _generate(session, [prompt], CodeSuggestion, "أنت مسؤول ترميز منتجات في مستودع.", temperature=0.4)
    result.code = "".join(c for c in result.code.upper() if c.isalnum() or c == "-")[:24]  # type: ignore[attr-defined]
    return result  # type: ignore[return-value]


def ask_data(session: Session, question: str, history: list[tuple[str, str]] | None = None) -> DataAnswer:
    """يجيب عن سؤال اعتماداً على ملخص بيانات محسوب مسبقاً (قراءة فقط، بدون SQL حر)."""
    from ftapp.services import report_service

    if not question.strip():
        raise AIError("اكتب سؤالك أولاً")
    ctx = report_service.ai_context(session)
    system = (
        "أنت مساعد تحليلي لمنظومة مجموعة فاروق الطعمة التجارية. أجب بالعربية فقط واعتماداً على البيانات المرفقة "
        "بصيغة JSON. المبالغ بالعملة الأساسية المذكورة في الحقل currency. إذا لم تكن الإجابة موجودة في البيانات "
        "قل ذلك بوضوح واقترح التقرير المناسب من التطبيق. لا تخترع أرقاماً."
    )
    contents: list[Any] = [f"البيانات:\n{json.dumps(ctx, ensure_ascii=False, default=str)}"]
    for q, a in (history or [])[-4:]:
        contents.append(f"سؤال سابق: {q}\nإجابة سابقة: {a}")
    contents.append(f"السؤال: {question}")
    return _generate(session, contents, DataAnswer, system, temperature=0.2)  # type: ignore[return-value]


def match_custom_fields(details: ProductDetails, fields: list[Any]) -> dict[int, str]:
    """يربط قيم الخانات المقترحة من Gemini بالخانات المخصصة الموجودة (بالاسم)."""
    by_name = {f.name.strip(): f for f in fields}
    out: dict[int, str] = {}
    for fv in details.custom_fields:
        fld = by_name.get(fv.name.strip())
        if fld and fv.value.strip():
            out[fld.id] = fv.value.strip()
    # المواصفات التي تطابق اسم خانة أيضاً
    for spec in details.specs:
        fld = by_name.get(spec.name.strip())
        if fld and fld.id not in out and spec.value.strip():
            out[fld.id] = spec.value.strip()
    return out
