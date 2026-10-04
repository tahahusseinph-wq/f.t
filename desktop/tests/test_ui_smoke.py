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
        assert win.stack.currentWidget() is win.pages[spec.key]
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
