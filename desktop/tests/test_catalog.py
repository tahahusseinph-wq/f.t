import pytest

from ftapp.services import catalog_service, codegen_service, settings_service
from ftapp.services.errors import ValidationError


def test_transliterate_and_abbreviate():
    assert codegen_service.transliterate("سامسونج") == "SAMSWNJ"
    assert codegen_service.abbreviate("Galaxy A54") == "A54"


def test_generate_code_sequence(db, admin):
    cat = catalog_service.save_category(db, admin, "إلكترونيات", code="ELC")
    c1 = codegen_service.generate_code(db, "Galaxy A54", cat.id, "Samsung", "A54")
    assert c1 == "ELC-SAMS-A54-0001"
    catalog_service.create_product(db, admin, catalog_service.ProductInput(name="Galaxy A54", category_id=cat.id,
                                                                          brand="Samsung", model="A54"))
    c2 = codegen_service.generate_code(db, "Galaxy A54", cat.id, "Samsung", "A54")
    assert c2 == "ELC-SAMS-A54-0002"


def test_price_from_category_margin(db, admin):
    cat = catalog_service.save_category(db, admin, "أدوات", default_margin=50)
    p = catalog_service.create_product(db, admin, catalog_service.ProductInput(name="مفك", cost_price=4,
                                                                              category_id=cat.id))
    assert p.sale_price == 6.0
    p2 = catalog_service.create_product(db, admin, catalog_service.ProductInput(name="مطرقة", cost_price=10,
                                                                               margin=25))
    assert p2.sale_price == 12.5


def test_duplicate_code_rejected(db, admin):
    catalog_service.create_product(db, admin, catalog_service.ProductInput(name="أ", code="X1"))
    with pytest.raises(ValidationError):
        catalog_service.create_product(db, admin, catalog_service.ProductInput(name="ب", code="x1"))


def test_custom_fields_and_visibility(db, admin):
    f_public = catalog_service.save_field(db, admin, "بلد المنشأ", "text", visible_to_users=True)
    f_private = catalog_service.save_field(db, admin, "ملاحظة داخلية", "text", visible_to_users=False)
    f_req = catalog_service.save_field(db, admin, "الضمان بالأشهر", "number", required=True, default_value="12")
    p = catalog_service.create_product(db, admin, catalog_service.ProductInput(
        name="شاشة", cost_price=100, margin=20, custom_values={f_public.id: "الصين", f_private.id: "سري"}))
    db.commit()
    user_view = catalog_service.product_view(db, p, privileged=False)
    labels = {f["label"]: f["value"] for f in user_view["fields"]}
    assert labels["بلد المنشأ"] == "الصين"
    assert "ملاحظة داخلية" not in labels
    assert labels["الضمان بالأشهر"] == "12"
    assert "cost_price" not in user_view
    admin_view = catalog_service.product_view(db, p, privileged=True)
    assert {f["label"] for f in admin_view["fields"]} >= {"ملاحظة داخلية", "سعر التكلفة"}

    vis = settings_service.builtin_visibility(db)
    vis["sale_price"] = False
    settings_service.set(db, "builtin_visibility", vis)
    assert "sale_price" not in catalog_service.product_view(db, p, privileged=False)


def test_tier_price_and_promotion(db, admin, product_factory):
    from datetime import date, timedelta

    p = product_factory("كابل", cost=2, margin=50)
    tiers = catalog_service.list_tiers(db)
    wholesale = next(t for t in tiers if t.name == "جملة")
    data = catalog_service.product_input_from(p)
    data.tier_prices = {wholesale.id: 2.6}
    catalog_service.update_product(db, admin, p.id, data)
    assert catalog_service.final_price(db, p, wholesale.id)[0] == 2.6
    assert catalog_service.final_price(db, p, None)[0] == 3.0
    catalog_service.save_promotion(db, "عرض", 10, date.today() - timedelta(days=1), date.today() + timedelta(days=1),
                                   product_id=p.id)
    price, promo = catalog_service.final_price(db, p, None)
    assert price == 2.7 and promo is not None


def test_variants(db, admin, product_factory):
    p = product_factory("قميص", cost=5, margin=100, code="SHIRT")
    variants = catalog_service.create_variants(db, admin, p.id, [{"اللون": "أحمر", "المقاس": "L"},
                                                                {"اللون": "أزرق", "المقاس": "M"}])
    assert len(variants) == 2
    assert all(v.parent_id == p.id and v.code.startswith("SHIRT-") for v in variants)
    assert variants[0].sale_price == 10


def test_bulk_price_update(db, admin, product_factory):
    p = product_factory("أ", cost=10, margin=None, brand="X", sale_price=20)
    catalog_service.bulk_price_apply(db, admin, catalog_service.BulkPriceFilter(brand="X"), 10, "both")
    assert p.cost_price == 11 and p.sale_price == 22
    assert len(catalog_service.price_history(db, p.id)) == 2


def test_search_low_stock(db, admin, product_factory):
    product_factory("قليل", qty=2)
    product_factory("كثير", qty=50)
    low, total = catalog_service.search_products(db, stock_filter="low")
    assert [p.name for p in low] == ["قليل"] and total == 1
