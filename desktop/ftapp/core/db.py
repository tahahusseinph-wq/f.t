"""الاتصال بقاعدة البيانات وإدارة الجلسات والترحيلات."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ftapp.core.paths import db_path, migrations_dir

log = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _set_sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    # WAL يحمي البيانات عند انقطاع الكهرباء ويسمح بالقراءة أثناء الكتابة
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def init_engine(path: Path | str | None = None) -> Engine:
    global _engine, _SessionLocal
    url = f"sqlite:///{path or db_path()}"
    _engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    event.listen(_engine, "connect", _set_sqlite_pragmas)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def new_session() -> Session:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    """جلسة تُحفظ تلقائياً عند النجاح وتُلغى عند الخطأ."""
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_migrations() -> None:
    """تطبيق ترحيلات Alembic حتى آخر إصدار."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    # configparser يعامل «%» كرمز استبدال، فيجب مضاعفته (مسارات فيها مسافات أو أحرف خاصة)
    cfg.set_main_option("script_location", str(migrations_dir()).replace("%", "%%"))
    cfg.set_main_option("sqlalchemy.url", str(engine().url).replace("%", "%%"))
    with engine().begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    log.info("database migrated to head")


def dispose() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
