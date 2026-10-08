"""العملات المتعددة، صندوق الوردية بكل عملة، صرف العملات، الرواتب والسلف."""
from datetime import date

import pytest


def test_standard_currencies_and_syp_base(db, admin):
    from ftapp.services import currency_service

    b = currency_service.base(db)
    assert b.code == "SYP"
    codes = {c.code for c in currency_service.list_currencies(db)}
    assert {"SYP", "USD", "EUR", "TRY"} <= codes
    usd = currency_service.get(db, "USD")
    assert currency_service.unit_value(usd) == pytest.approx(15000)
    assert currency_service.display(db).code == "SYP"


def test_set_unit_values_keeps_others(db, admin):
    from ftapp.services import currency_service

    eur_before = currency_service.unit_value(currency_service.get(db, "EUR"))
    changed = currency_service.set_unit_values(db, admin, {"USD": 13500, "EUR": eur_before})
    db.commit()
    assert changed == ["USD"]
    assert currency_service.unit_value(currency_service.get(db, "USD")) == pytest.approx(13500)
    assert currency_service.unit_value(currency_service.get(db, "EUR")) == pytest.approx(eur_before)


def test_change_base_converts_amounts(db, admin, product_factory):
    from ftapp.models import Currency
    from ftapp.services import currency_service, sales_service

    p = product_factory(cost=150000, margin=0, qty=5)  # بالليرة
    inv = sales_service.create_sale(db, admin, sales_service.SaleRequest(
        lines=[sales_service.CartLine(p.id, 1)], payment_method="cash"))
    db.commit()
    assert inv.total == pytest.approx(150000)
    factor = currency_service.change_base(db, admin, "USD")
    db.commit()
    assert factor == pytest.approx(1 / 15000)
    db.refresh(p)
    db.refresh(inv)
    assert p.cost_price == pytest.approx(10)
    assert inv.total == pytest.approx(10)
    syp = db.get(Currency, "SYP")
    assert syp.rate == pytest.approx(15000) and not syp.is_base
    assert currency_service.base(db).code == "USD"
    # والعودة لليرة
    currency_service.change_base(db, admin, "SYP")
    db.commit()
    db.refresh(p)
    assert p.cost_price == pytest.approx(150000)


def test_multi_currency_shift_and_exchange(db, admin, product_factory):
    from ftapp.services import cash_service, finance_service, report_service, sales_service

    finance_service.open_shift(db, admin, balances={"SYP": 1_000_000, "USD": 100})
    db.commit()
    p = product_factory(cost=150000, margin=0, qty=5)
    # بيع بالدولار نقداً: 10$ تدخل الصندوق بالدولار
    sales_service.create_sale(db, admin, sales_service.SaleRequest(
        lines=[sales_service.CartLine(p.id, 1)], payment_method="cash", currency_code="USD"))
    # بيع 50$ لزبون بسعر 15200 (المعتمد 15000) = ربح 10000 ل.س
    ex = cash_service.create_exchange(db, admin, "sell", "USD", 50, 15200)
    # شراء 20$ من زبون بسعر 14900 = ربح 2000 ل.س
    cash_service.create_exchange(db, admin, "buy", "USD", 20, 14900)
    db.commit()
    assert ex.profit == pytest.approx(10000)
    shift = finance_service.current_shift(db, admin)
    summary = finance_service.shift_summary(db, shift)
    usd = summary["by_currency"]["USD"]
    syp = summary["by_currency"]["SYP"]
    assert usd["expected"] == pytest.approx(100 + 10 - 50 + 20)
    assert syp["expected"] == pytest.approx(1_000_000 + 50 * 15200 - 20 * 14900)
    k = report_service.kpis(db, report_service.period("today"))
    assert k["exchange_profit"] == pytest.approx(12000)
    closed = finance_service.close_shift(db, admin, actual_balances={"SYP": syp["expected"], "USD": usd["expected"] - 1})
    db.commit()
    assert closed.difference == pytest.approx(-15000)  # عجز دولار واحد


def test_payroll_salary_and_advances(db, admin):
    from ftapp.services import finance_service, payroll_service

    finance_service.open_shift(db, admin, balances={"SYP": 500_000})
    emp = payroll_service.save_employee(db, "أحمد", "weekly", 300_000)
    payroll_service.give_advance(db, admin, emp.id, 100_000)
    db.commit()
    assert payroll_service.outstanding_advances(db, emp.id) == pytest.approx(100_000)
    start, end = payroll_service.period_range("weekly", date.today())
    tx = payroll_service.pay_salary(db, admin, emp.id, 300_000, deduct=100_000, period_from=start, period_to=end)
    db.commit()
    assert tx.net == pytest.approx(200_000)
    assert payroll_service.outstanding_advances(db, emp.id) == pytest.approx(0)
    assert finance_service.expenses_total(db, date.today(), date.today()) == pytest.approx(300_000)
    shift = finance_service.current_shift(db, admin)
    assert finance_service.shift_summary(db, shift)["by_currency"]["SYP"]["expected"] == pytest.approx(200_000)
    with pytest.raises(Exception):
        payroll_service.pay_salary(db, admin, emp.id, 300_000, deduct=1)


def test_no_tax_on_sales(db, admin, product_factory):
    from ftapp.services import sales_service, settings_service

    settings_service.set(db, "tax_rate", 10)
    p = product_factory(cost=1000, margin=0, qty=2)
    inv = sales_service.create_sale(db, admin, sales_service.SaleRequest(lines=[sales_service.CartLine(p.id, 1)]))
    assert inv.tax_amount == 0 and inv.total == pytest.approx(1000)
    assert inv.ref_rate == pytest.approx(15000)


def test_prepare_converts_old_usd_database(db):
    from ftapp.services import auth_service, catalog_service, currency_service, settings_service

    auth_service.run_setup(db, auth_service.SetupData(username="admin", password="Admin1234", base_currency="USD",
                                                      secondary_currency="SYP", secondary_rate=1 / 13000))
    settings_service.set(db, "main_base_done", False)   # كقاعدة بيانات من الإصدار القديم
    settings_service.set(db, "display_currency", "USD")
    admin = auth_service.authenticate(db, "admin", "Admin1234")
    p = catalog_service.create_product(db, admin, catalog_service.ProductInput(name="شاحن", cost_price=2, margin=50))
    db.commit()
    assert currency_service.needs_main_base(db)
    currency_service.prepare(db)
    db.commit()
    db.refresh(p)
    assert currency_service.base(db).code == "SYP"
    assert currency_service.display(db).code == "SYP"
    assert p.cost_price == pytest.approx(26000) and p.sale_price == pytest.approx(39000)
    assert currency_service.unit_value(currency_service.get(db, "USD")) == pytest.approx(13000)
    assert not currency_service.needs_main_base(db)
