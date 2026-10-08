"""يفتح كل صفحات الواجهة ونوافذها الأساسية (بدون شاشة) للتأكد من عدم وجود أعطال."""
import pytest

pytest.importorskip("PySide6.QtCharts")


@pytest.fixture()
def app():
    from PySide6.QtWidgets import QApplication

    from ftapp.ui import theme
    application = QApplication.instance() or QApplication([])
    theme.load_fonts()
    theme.apply(application)
    return application


def test_all_pages_open(app, db, admin, product_factory):
    from ftapp.services import sales_service
    from ftapp.ui.context import ctx
    from ftapp.ui.main_window import MainWindow

    p = product_factory("منتج تجريبي", qty=3, min_stock=5)
    sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 1)]))
    db.commit()
    ctx.set_user(admin)
    win = MainWindow()
    win.show()
    for spec in win.visible_specs:
        win.navigate(spec.key)
        for _ in range(5):
            app.processEvents()
        assert win.stack.currentWidget().widget() is win.pages[spec.key]
        if hasattr(win.pages[spec.key], "tabs"):
            tabs = win.pages[spec.key].tabs
            for i in range(tabs.count()):
                tabs.setCurrentIndex(i)
                app.processEvents()
    win.close()


def test_dialogs_open(app, db, admin, product_factory):
    from ftapp.ui.context import ctx
    from ftapp.ui.dialogs.auth_dialogs import LoginDialog
    from ftapp.ui.dialogs.product_dialog import ProductDialog

    p = product_factory("منتج", qty=2)
    ctx.set_user(admin)
    for dlg in (ProductDialog(None, p.id), ProductDialog(None), LoginDialog()):
        dlg.show()
        app.processEvents()
        dlg.done(0)


def test_invoice_preview_edit_and_save(app, db, admin, product_factory, tmp_path):
    from ftapp.services import sales_service
    from ftapp.ui.context import ctx
    from ftapp.ui.dialogs.invoice_preview import InvoicePreviewDialog

    p = product_factory("منتج", qty=5)
    inv = sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 1)]))
    db.commit()
    ctx.set_user(admin)
    dlg = InvoicePreviewDialog(None, inv.id)
    dlg.show()
    app.processEvents()
    dlg.view.textCursor().insertText("ملاحظة مضافة يدوياً")
    for paper in ("A4", "A5", "Letter", "80mm"):
        dlg._keep.setModified(False)
        dlg.paper_combo.setCurrentIndex(dlg.paper_combo.findData(paper))
        dlg.view.textCursor().insertText("تفاصيل إضافية")
        out = tmp_path / f"{paper}.pdf"
        dlg._pdf(out)
        assert out.stat().st_size > 1000
    assert "تفاصيل إضافية" in dlg.view.toPlainText()
    dlg._keep.setModified(False)
    dlg.done(0)


def test_pos_checkout_with_typed_customer_creates_invoice(app, db, admin, product_factory, monkeypatch):
    from ftapp.models import Customer, Invoice
    from ftapp.ui.context import ctx
    from ftapp.ui.dialogs import invoice_preview
    from ftapp.ui.pages import pos_page

    shown = []
    monkeypatch.setattr(invoice_preview.InvoicePreviewDialog, "exec", lambda self: shown.append(self.invoice_id))
    monkeypatch.setattr(pos_page, "confirm", lambda *a, **k: True)
    p = product_factory("طابعة", qty=4)
    ctx.set_user(admin)
    page = pos_page.POSPage()
    page.add_product(p.id, 2)
    page.m_details.setChecked(True)
    page.c_name.setText("مؤسسة الأمل")
    page.c_phone.setText("0944555666")
    page.c_address.setText("حمص - الوعر")
    page._checkout()
    db.expire_all()
    inv = db.get(Invoice, shown[0])
    cust = db.query(Customer).filter_by(phone="0944555666").one()
    assert inv.customer_id == cust.id and cust.address == "حمص - الوعر"
    assert inv.customer_name == "مؤسسة الأمل" and inv.customer_address == "حمص - الوعر"
    assert not page.cart and page.m_existing.isChecked() and not page.c_name.text()


def test_product_info_from_image_fills_dialog(app, db, admin, monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace

    from PySide6.QtGui import QColor, QImage

    from ftapp.models import Category, Product
    from ftapp.services import catalog_service, gemini_service
    from ftapp.ui.context import ctx
    from ftapp.ui.dialogs.ai_dialogs import ImageProductPreview
    from ftapp.ui.dialogs.product_dialog import ProductDialog

    payload = {"name": "سماعة Xiaomi Redmi Buds 4", "brand": "Xiaomi", "model": "Buds 4", "barcode": "6934177 79",
               "unit": "قطعة", "suggested_category": "سماعات", "description": "سماعة لاسلكية بعزل ضوضاء.",
               "specs": [{"name": "البطارية", "value": "30 ساعة"}], "origin_country": "الصين",
               "custom_fields": [], "confidence": "high", "estimated_price_usd": 25, "warranty": "سنة"}
    seen = {}

    class Models:
        def generate_content(self, model, contents, config):
            seen["contents"] = contents
            return SimpleNamespace(parsed=None, text=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(gemini_service, "_client", lambda key=None: SimpleNamespace(models=Models()))
    img_path = tmp_path / "buds.png"
    img = QImage(64, 64, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    img.save(str(img_path))
    data, mime = ProductDialog._prepare_image(str(img_path))
    info = gemini_service.product_info_from_image(db, data, mime, categories=["هواتف"])
    assert info.brand == "Xiaomi" and "هواتف" in seen["contents"][1]

    ctx.set_user(admin)
    dlg = ProductDialog(None)
    preview = ImageProductPreview(dlg, info, [], data, ["هواتف"])
    sel = preview.selection()
    assert sel["basic"]["category"] == "سماعات" and sel["add_image"]
    dlg._apply_image_info(info, sel, str(img_path))
    assert dlg.name.text() == payload["name"] and dlg.model.text() == "Buds 4"
    assert dlg.barcode.text() == "693417779" and dlg.category.currentText().strip(" └") == "سماعات"
    assert "البطارية" in dlg._collect_specs() and dlg.has_warranty.isChecked()
    assert len(dlg.pending_images) == 1
    dlg._save()
    db.expire_all()
    p = db.query(Product).filter_by(model="Buds 4").one()
    assert p.category_id == db.query(Category).filter_by(name="سماعات").one().id
    assert len(p.images) == 1 and catalog_service.image_path(p.images[0]).exists()
    assert p.warranty == "سنة"


def test_money_dialogs_open(app, db, admin, product_factory):
    from ftapp.services import finance_service, payroll_service, sales_service, settings_service
    from ftapp.ui.context import ctx
    from ftapp.ui.dialogs.invoice_preview import InvoicePreviewDialog, PrintRateDialog
    from ftapp.ui.pages.finance_page import (AdvanceDialog, CloseShiftDialog, EmployeeDialog, OpenShiftDialog,
                                             SalaryDialog)
    from ftapp.ui.pages.pos_page import ExchangeDialog
    from ftapp.ui.pages.rates_tab import RatesTab

    ctx.set_user(admin)
    settings_service.update(db, "company", shamcash_account="a1b2c3d4e5f6")
    emp = payroll_service.save_employee(db, "سامر", "daily", 50000)
    db.commit()
    dlg = OpenShiftDialog(None)
    dlg.spins["USD"].setValue(100)
    dlg.spins["SYP"].setValue(250000)
    dlg._save()
    finance_service.current_shift(db, admin)
    ex = ExchangeDialog(None)
    ex.amount.setValue(10)
    ex.rate.setValue(15500)
    assert "ربح" in ex.profit.text()
    ex._save()
    rates = RatesTab()
    rates.refresh()
    assert "USD" in rates.spins
    rates.deleteLater()
    widgets = [dlg, ex]
    for d in (CloseShiftDialog(None), EmployeeDialog(None, emp.id), SalaryDialog(None, emp.id),
              AdvanceDialog(None, emp.id), PrintRateDialog(None, "USD", "$", "ل.س", 15000)):
        d.show()
        app.processEvents()
        d.done(0)
        widgets.append(d)
    p = product_factory("منتج", qty=5)
    inv = sales_service.create_sale(db, admin, sales_service.SaleRequest([sales_service.CartLine(p.id, 1)]))
    db.commit()
    prev = InvoicePreviewDialog(None, inv.id)
    text = prev.view.toPlainText()
    assert "سعر الصرف" in text and "شام كاش" in text and "الضريبة" not in text
    sales_service.set_invoice_ref_rate(db, admin, inv.id, 16000, update_global=True)
    db.commit()
    prev._render()
    assert "16,000" in prev.view.toPlainText()
    prev.done(0)
    widgets.append(prev)
    for w in widgets:
        w.deleteLater()
    app.processEvents()
