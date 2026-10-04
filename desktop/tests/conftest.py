import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def tmp_data(monkeypatch):
    d = tempfile.mkdtemp(prefix="ft_test_")
    monkeypatch.setenv("FT_DATA_DIR", d)
    return d


@pytest.fixture()
def db(tmp_data):
    from ftapp.core import db as dbm

    dbm.dispose()
    dbm.init_engine(os.path.join(tmp_data, "test.db"))
    dbm.run_migrations()
    session = dbm.new_session()
    yield session
    session.close()
    dbm.dispose()


@pytest.fixture()
def admin(db):
    from ftapp.services import auth_service

    auth_service.run_setup(db, auth_service.SetupData(username="admin", password="Admin1234", secondary_rate=15000))
    db.commit()
    return auth_service.authenticate(db, "admin", "Admin1234")


@pytest.fixture()
def product_factory(db, admin):
    from ftapp.services import catalog_service

    def make(name="منتج", cost=10.0, margin=25.0, qty=10, **kw):
        data = catalog_service.ProductInput(name=name, cost_price=cost, margin=margin, initial_quantity=qty, **kw)
        p = catalog_service.create_product(db, admin, data)
        db.commit()
        return p

    return make
