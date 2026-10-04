import pytest

from ftapp.models import Notification
from ftapp.services import (finance_service, inventory_service, notification_service, purchase_service,
                            report_service, sales_service)
from ftapp.services.errors import ValidationError


def test_sale_reduces_stock_and_triggers_alert(db, admin, product_factory):
    p = product_factory("سماعة", cost=10, margin=50, qty=8, min_stock=5)
    inv = sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 4)]))
    db.commit()
    assert inv.total == 60 and inv.paid == 60
    assert p.quantity == 4
    n = db.query(Notification).filter_by(dedupe_key=f"stock:{p.id}").one()
    assert n.kind == "low_stock"
    sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 4)]))
    db.commit()
    db.refresh(n)
    assert n.kind == "out_of_stock"


def test_cannot_oversell(db, admin, product_factory):
    from ftapp.services import auth_service

    seller = auth_service.create_user(db, admin, "seller1", "Seller123", "seller")
    p = product_factory("قلم", qty=1)
    with pytest.raises(ValidationError):
        sales_service.create_sale(db, seller, sales_service.SaleRequest([sales_service.CartLine(p.id, 3)]))


def test_credit_sale_needs_customer_and_updates_balance(db, admin, product_factory):
    p = product_factory("مروحة", cost=20, margin=50, qty=5)
    with pytest.raises(ValidationError):
        sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 1)],
                                                                       payment_method="credit"))
    c = sales_service.save_customer(db, "أبو أحمد", "0999")
    inv = sales_service.create_sale(db, admin, sales_service.SaleRequest(
        [sales_service.CartLine(p.id, 2)], customer_id=c.id, payment_method="partial", paid=20))
    assert inv.total == 60 and c.balance == 40
    sales_service.receive_payment(db, admin, c.id, 15)
    assert c.balance == 25
    statement = sales_service.customer_statement(db, c.id)
    assert statement[-1]["balance"] == 25


def test_return_and_cancel(db, admin, product_factory):
    p = product_factory("ماوس", cost=5, margin=100, qty=10)
    inv = sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 4)],
                                                                         discount=4))
    assert inv.total == 36
    ret = sales_service.create_return(db, admin, inv.id, [(inv.items[0].id, 2)])
    assert ret.total == 18 and p.quantity == 8
    with pytest.raises(ValidationError):
        sales_service.create_return(db, admin, inv.id, [(inv.items[0].id, 3)])
    with pytest.raises(ValidationError):
        sales_service.cancel_invoice(db, admin, inv.id)
    inv2 = sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 1)]))
    sales_service.cancel_invoice(db, admin, inv2.id)
    assert p.quantity == 8 and inv2.status == "cancelled"


def test_quotation_convert(db, admin, product_factory):
    p = product_factory("طابعة", cost=100, margin=20, qty=3)
    q = sales_service.create_quotation(db, admin, sales_service.SaleRequest(
        [sales_service.CartLine(p.id, 2, unit_price=110)]))
    assert p.quantity == 3 and q.total == 220
    inv = sales_service.convert_quotation(db, admin, q.id)
    assert inv.total == 220 and p.quantity == 1 and q.status == "converted"


def test_purchase_updates_cost_and_supplier(db, admin, product_factory):
    from ftapp.services import catalog_service

    s = catalog_service.save_supplier(db, "مورد 1")
    p = product_factory("شاحن", cost=3, margin=100, qty=0)
    purchase_service.create_purchase(db, admin, s.id, None,
                                     [purchase_service.PurchaseLine(p.id, 10, 4)], paid=15)
    assert p.quantity == 10 and p.cost_price == 4 and p.sale_price == 8
    assert s.balance == 25


def test_expiry_batches_fefo(db, admin, product_factory):
    from datetime import date, timedelta

    p = product_factory("حليب", qty=0, track_expiry=True)
    wh = inventory_service.default_warehouse(db).id
    inventory_service.adjust(db, admin, p.id, wh, 5, "in", expiry=date.today() + timedelta(days=60))
    inventory_service.adjust(db, admin, p.id, wh, 5, "in", expiry=date.today() + timedelta(days=5))
    sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 6)]))
    batches = {b.expiry_date: b.quantity for b in inventory_service.batches(db, p.id, include_empty=True)}
    assert batches[date.today() + timedelta(days=5)] == 0
    assert batches[date.today() + timedelta(days=60)] == 4


def test_transfer_and_count(db, admin, product_factory):
    p = product_factory("علبة", qty=10)
    main = inventory_service.default_warehouse(db)
    branch = inventory_service.save_warehouse(db, "فرع 2")
    inventory_service.create_transfer(db, admin, main.id, branch.id, [(p.id, 3)])
    assert inventory_service.quantity_in(db, p.id, main.id) == 7
    assert inventory_service.quantity_in(db, p.id, branch.id) == 3
    count = inventory_service.start_count(db, admin, main.id)
    inventory_service.set_count_line(db, count.id, p.id, 2, mode="add")
    inventory_service.set_count_line(db, count.id, p.id, 4, mode="add")
    assert inventory_service.apply_count(db, admin, count.id) == 1
    assert inventory_service.quantity_in(db, p.id, main.id) == 6


def test_shift_close_expected_cash(db, admin, product_factory):
    p = product_factory("فنجان", cost=1, margin=100, qty=20)
    finance_service.open_shift(db, admin, 50)
    sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 5)]))
    finance_service.add_expense(db, admin, 3, None, "ضيافة")
    shift = finance_service.close_shift(db, admin, 56)
    assert shift.expected_cash == 57 and shift.difference == -1


def test_reports(db, admin, product_factory):
    a = product_factory("أ", cost=10, margin=50, qty=100)
    b = product_factory("ب", cost=5, margin=100, qty=100)
    sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(a.id, 2),
                                                                    sales_service.CartLine(b.id, 3)]))
    db.commit()
    p = report_service.period("today")
    k = report_service.kpis(db, p)
    assert k["sales"] == 60 and k["gross_profit"] == 25 and k["invoices"] == 1
    shares = {r["name"]: r["share"] for r in report_service.product_sales(db, p)}
    assert shares == {"أ": 50.0, "ب": 50.0}
    series = report_service.sales_series(db, report_service.period("week"))
    assert series[-1]["sales"] == 60
    assert "التقرير اليومي" in report_service.daily_summary_text(db)
    ctx = report_service.ai_context(db)
    assert ctx["kpis_today"]["sales"] == 60


def test_reorder_suggestions(db, admin, product_factory):
    p = product_factory("سريع", cost=1, margin=100, qty=12, min_stock=2)
    sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 9)]))
    db.commit()
    rows = report_service.reorder_suggestions(db, lookback_days=3)
    assert rows and rows[0]["product"].id == p.id and rows[0]["suggested"] > 0
    notification_service.scan_all(db)
