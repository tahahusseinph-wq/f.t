import pytest
from fastapi.testclient import TestClient

from ftapp.api.app import create_app
from ftapp.services import auth_service, catalog_service


@pytest.fixture()
def client(db, admin):
    return TestClient(create_app(lan_only=True))


def login(client, username="admin", password="Admin1234"):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password, "device_name": "Test"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_ping_and_login(client):
    r = client.get("/api/v1/ping")
    assert r.json()["app"] == "ft-trading"
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "x"}).status_code == 400
    h = login(client)
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert me["role"] == "admin" and "users.manage" in me["permissions"]
    assert client.get("/api/v1/auth/me").status_code == 401


def test_user_sees_only_visible_fields(client, db, admin, product_factory):
    secret = catalog_service.save_field(db, admin, "سري", visible_to_users=False)
    public = catalog_service.save_field(db, admin, "اللون", visible_to_users=True)
    p = product_factory("سماعة", cost=10, margin=50, code="SND-1",
                        custom_values={secret.id: "لا تظهر", public.id: "أسود"})
    auth_service.create_user(db, admin, "viewer1", "Viewer123", "viewer")
    db.commit()
    h = login(client, "viewer1", "Viewer123")
    r = client.get("/api/v1/products/lookup", params={"q": "snd-1"}, headers=h)
    assert r.status_code == 200
    data = r.json()
    labels = [f["label"] for f in data["fields"]]
    assert "اللون" in labels and "سري" not in labels
    assert "cost_price" not in data and "quantity" not in data
    assert data["sale_price"] == 15
    assert client.get("/api/v1/dashboard", headers=h).status_code == 403
    assert client.post("/api/v1/sales", json={"lines": [{"product_id": p.id, "quantity": 1}]},
                       headers=h).status_code == 403
    assert client.get("/api/v1/products/lookup", params={"q": "nope"}, headers=h).status_code == 404


def test_admin_sale_idempotent_and_pdf(client, db, product_factory):
    p = product_factory("شاحن", cost=5, margin=100, qty=10)
    h = login(client)
    body = {"lines": [{"product_id": p.id, "quantity": 2}], "client_op_id": "op-1"}
    r1 = client.post("/api/v1/sales", json=body, headers=h)
    r2 = client.post("/api/v1/sales", json=body, headers=h)
    assert r1.status_code == 200 and r1.json()["number"] == r2.json()["number"]
    db.expire_all()
    assert p.quantity == 8
    pdf = client.get(f"/api/v1/invoices/{r1.json()['id']}/pdf", params={"paper": "80mm"}, headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    dash = client.get("/api/v1/dashboard", headers=h).json()
    assert dash["kpis"]["sales"] == 20 and dash["kpis"]["invoices"] == 1


def test_sync_ops_and_products(client, db, product_factory):
    p = product_factory("مصباح", qty=5)
    h = login(client)
    full = client.get("/api/v1/sync/products", headers=h).json()
    assert full["full"] and any(i["id"] == p.id for i in full["items"])
    auth_service.create_user(db, None, "seller2", "Seller123", "seller", permissions={"inventory.adjust": True})
    db.commit()
    h = login(client, "seller2", "Seller123")
    count = client.post("/api/v1/counts", json={}, headers=h).json()
    ops = {"ops": [
        {"client_op_id": "a1", "type": "sale", "payload": {"lines": [{"product_id": p.id, "quantity": 1}]}},
        {"client_op_id": "a2", "type": "sale", "payload": {"lines": [{"product_id": p.id, "quantity": 99}]}},
        {"client_op_id": "a3", "type": "count_line", "payload": {"count_id": count["id"], "code": p.code, "quantity": 3}},
        {"client_op_id": "a4", "type": "stock", "payload": {"product_id": p.id, "delta": 2}},
    ]}
    res = client.post("/api/v1/sync/ops", json=ops, headers=h).json()["results"]
    assert [r["ok"] for r in res] == [True, False, True, True]
    assert "غير كافية" in res[1]["error"]
    again = client.post("/api/v1/sync/ops", json=ops, headers=h).json()["results"]
    assert again[0]["result"]["number"] == res[0]["result"]["number"]
    delta = client.get("/api/v1/sync/products", params={"since": full["server_time"]}, headers=h).json()
    assert any(i["id"] == p.id for i in delta["items"])
    assert all("quantity" in i for i in delta["items"])  # البائع يرى الكمية المتبقية في المستودع
    db.expire_all()
    assert p.quantity == 6


def test_rate_limit_and_lan_guard(db, admin):
    from ftapp.api import deps

    deps.login_limiter.reset("testclient")
    c = TestClient(create_app())
    codes = [c.post("/api/v1/auth/login", json={"username": "zz", "password": "x"}).status_code for _ in range(11)]
    assert codes[-1] == 429
    deps.login_limiter.reset("testclient")
    assert deps.is_lan_address("192.168.1.20") and not deps.is_lan_address("8.8.8.8")


def test_revoked_device(client, db, admin):
    h = login(client)
    db.expire_all()
    devices = auth_service.list_devices(db)
    auth_service.revoke_device(db, admin, devices[0].id)
    db.commit()
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401


def test_server_runs(db, admin):
    import httpx

    from ftapp.api.server import ApiServer, local_ips, pairing_payload

    srv = ApiServer()
    srv.start(port=18765, server_id="abc", company="FT")
    try:
        assert srv.running, srv.error
        assert httpx.get("http://127.0.0.1:18765/api/v1/ping", timeout=5).json()["app"] == "ft-trading"
    finally:
        srv.stop()
    assert '"id":"abc"' in pairing_payload("abc", "FT", 8765) and local_ips()


def test_company_settings_and_rate_from_mobile(client, db, admin, product_factory):
    h = login(client)
    r = client.put("/api/v1/settings/company", headers=h,
                   json={"facebook_url": "ft.trading", "shamcash_account": "SC-1", "invoice_details": "سطر 1\nسطر 2",
                         "name": "  "})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["facebook_url"] == "ft.trading" and data["shamcash_account"] == "SC-1"
    assert data["name"]  # الاسم الفارغ لا يمسح اسم المنشأة
    assert client.get("/api/v1/settings/company", headers=h).json()["invoice_details"] == "سطر 1\nسطر 2"

    syp = next(c for c in client.get("/api/v1/meta", headers=h).json()["currencies"] if not c["is_base"])
    r = client.put(f"/api/v1/currencies/{syp['code']}/rate", headers=h, json={"rate": 16000})
    assert r.status_code == 200 and r.json()["rate"] == 16000
    assert client.put(f"/api/v1/currencies/{syp['code']}/rate", headers=h, json={"rate": 0}).status_code == 422

    p = product_factory("شاحن", cost=10, margin=0, qty=5)
    r = client.post("/api/v1/sales", headers=h, json={"lines": [{"product_id": p.id, "quantity": 1}],
                                                     "payment_method": "shamcash", "notes": "رقم عملية شام كاش: 9"})
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["payment_method"] == "shamcash" and inv["remaining"] == 0 and "9" in inv["notes"]

    auth_service.create_user(db, admin, "seller1", "Seller123", "seller")
    db.commit()
    hs = login(client, "seller1", "Seller123")
    assert client.get("/api/v1/settings/company", headers=hs).status_code == 200
    assert client.put("/api/v1/settings/company", headers=hs, json={"phone": "1"}).status_code == 403
    assert client.put(f"/api/v1/currencies/{syp['code']}/rate", headers=hs, json={"rate": 1}).status_code == 403


def test_admin_full_edit_from_mobile(client, db, admin, product_factory):
    """الأدمن يعدّل كل شيء من الموبايل: المنتجات، المستخدمين وصلاحياتهم، وقياسات الفاتورة."""
    h = login(client)
    p = product_factory("سماعة", cost=10, margin=50)
    raw = client.get(f"/api/v1/products/{p.id}/edit", headers=h).json()
    assert raw["cost_price"] == 10 and raw["name"] == "سماعة"
    body = {**{k: raw[k] for k in ("name", "code", "barcode", "category_id", "brand", "model", "unit", "cost_price",
                                    "margin", "min_stock", "location", "details", "notes", "warranty")},
            "name": "سماعة بلوتوث", "sale_price": 33, "price_locked": True}
    r = client.put(f"/api/v1/products/{p.id}", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/v1/products/{p.id}/edit", headers=h).json()["sale_price"] == 33

    perms = client.get("/api/v1/permissions", headers=h).json()
    assert "sales.create" in perms["permissions"] and "admin" in perms["defaults"]
    u = client.post("/api/v1/users", headers=h, json={"username": "seller1", "password": "Seller1234",
                                                      "role": "seller", "full_name": "بائع"}).json()
    r = client.patch(f"/api/v1/users/{u['id']}", headers=h,
                     json={"permissions": {"reports.view": True}, "commission_rate": 5, "phone": "0944"})
    assert r.status_code == 200, r.text
    assert "reports.view" in r.json()["permissions"] and r.json()["commission_rate"] == 5
    assert client.delete(f"/api/v1/users/{u['id']}", headers=h).json()["ok"] is True

    iv = client.get("/api/v1/settings/invoice", headers=h).json()
    assert any(s["key"] == "size_name" for s in iv["sizes"])
    iv = client.put("/api/v1/settings/invoice", headers=h, json={"size_name": 200, "margin_mm": 8}).json()
    assert next(s["value"] for s in iv["sizes"] if s["key"] == "size_name") == 200 and iv["margin_mm"] == 8
    assert client.delete(f"/api/v1/products/{p.id}", headers=h).json()["result"] in ("deleted", "deactivated")


def test_invoice_sizes_change_render(db, admin, product_factory):
    from ftapp.services import pdf_service, sales_service, settings_service

    p = product_factory("كبل", cost=5, margin=20)
    inv = sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 1)]))
    db.commit()
    ctx1 = pdf_service.invoice_context(db, inv, "A4")
    settings_service.update(db, "invoice", size_name=200, size_logo=50)
    ctx2 = pdf_service.invoice_context(db, inv, "A4")
    assert ctx2["name_fs"] > ctx1["name_fs"] and ctx2["logo_h"] < ctx1["logo_h"]
    assert pdf_service.invoice_pdf(db, inv, paper="A4").exists()


def test_mobile_search_stock_rates_and_excel_import(client, db, admin, product_factory, tmp_path):
    import base64

    from openpyxl import Workbook

    product_factory("شاشة سامسونج ذكية", cost=100000, margin=10, qty=7, code="TV-1")
    auth_service.create_user(db, admin, "seller2", "Seller123", "seller")
    db.commit()
    hs = login(client, "seller2", "Seller123")
    # البحث بالاسم بأكثر من كلمة وبكتابة مختلفة للتاء المربوطة
    items = client.get("/api/v1/products", params={"q": "سامسونج شاشه"}, headers=hs).json()["items"]
    assert len(items) == 1 and items[0]["code"] == "TV-1"
    # البائع يرى الكمية المتبقية
    assert items[0]["quantity"] == 7
    assert client.get("/api/v1/products/lookup", params={"q": "TV-1"}, headers=hs).json()["quantity"] == 7

    h = login(client)
    meta = client.get("/api/v1/meta", headers=h).json()
    usd = next(c for c in meta["currencies"] if c["code"] == "USD")
    assert usd["unit"] == 15000 and meta["base_currency"] == "SYP" and meta["tax_rate"] == 0
    r = client.put("/api/v1/currencies/USD/rate", headers=h, json={"unit": 14000})
    assert r.status_code == 200 and r.json()["unit"] == 14000

    wb = Workbook()
    ws = wb.active
    ws.append(["الكود", "اسم المنتج", "سعر التكلفة", "الكمية"])
    ws.append(["X-1", "مروحة", 50000, 4])
    ws.append(["X-2", "سخان", 75000, 2])
    path = tmp_path / "p.xlsx"
    wb.save(path)
    b64 = base64.b64encode(path.read_bytes()).decode()
    pv = client.post("/api/v1/products/import/preview", headers=h, json={"file_base64": b64, "filename": "p.xlsx"})
    assert pv.status_code == 200, pv.text
    data = pv.json()
    assert data["total"] == 2 and "name" in data["mapping"].values()
    res = client.post("/api/v1/products/import", headers=h, json={"file_id": data["file_id"], "mapping": data["mapping"]})
    assert res.status_code == 200 and res.json()["created"] == 2
    assert client.get("/api/v1/products/lookup", params={"q": "X-2"}, headers=h).json()["name"] == "سخان"
    assert client.post("/api/v1/products/import/preview", headers=hs,
                       json={"file_base64": b64, "filename": "p.xlsx"}).status_code == 403


def test_permissions_apply_without_relogin(client, db, admin):
    auth_service.create_user(db, admin, "seller3", "Seller123", "seller")
    db.commit()
    hs = login(client, "seller3", "Seller123")
    assert "reports.view" not in client.get("/api/v1/auth/me", headers=hs).json()["permissions"]
    h = login(client)
    uid = next(u["id"] for u in client.get("/api/v1/users", headers=h).json() if u["username"] == "seller3")
    assert client.patch(f"/api/v1/users/{uid}", headers=h, json={"permissions": {"reports.view": True}}).status_code == 200
    assert "reports.view" in client.get("/api/v1/auth/me", headers=hs).json()["permissions"]


def test_product_from_image_endpoint(client, db, admin, monkeypatch):
    import base64

    from ftapp.services import gemini_service

    catalog_service.save_category(db, admin, "إلكترونيات")
    db.commit()

    def fake(session, image, mime="image/jpeg", hint="", field_names=None, categories=None):
        assert image == b"img" and "إلكترونيات" in categories
        return gemini_service.ImageProductInfo(
            name="سماعة سوني WH-1000XM5", brand="Sony", model="WH-1000XM5", description="سماعة لاسلكية",
            specs=[gemini_service.SpecItem(name="البطارية", value="30 ساعة")], suggested_category="إلكترونيات",
            unit="قطعة", estimated_price_usd=2, warranty="سنة")
    monkeypatch.setattr(gemini_service, "product_info_from_image", fake)
    h = login(client)
    r = client.post("/api/v1/ai/product-from-image", headers=h,
                    json={"image_base64": base64.b64encode(b"img").decode()})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["brand"] == "Sony" and d["category_id"] and "البطارية" in d["details"]
    assert d["estimated_price"] == 30000  # 2$ × 15000
