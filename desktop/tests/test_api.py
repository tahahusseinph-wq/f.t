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
    assert all("quantity" not in i for i in delta["items"])  # البائع لا يرى الكميات افتراضياً
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
