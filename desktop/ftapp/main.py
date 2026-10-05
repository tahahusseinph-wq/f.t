"""نقطة تشغيل تطبيق الأدمن."""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QLockFile, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from ftapp import APP_ID, APP_NAME, VERSION
from ftapp.core import db
from ftapp.core.logging_setup import setup_logging
from ftapp.core.paths import assets_dir, data_dir

log = logging.getLogger("ftapp")


def _excepthook(exc_type, exc, tb) -> None:
    log.critical("unhandled exception", exc_info=(exc_type, exc, tb))
    try:
        QMessageBox.critical(None, "خطأ", f"حدث خطأ غير متوقع وتم تسجيله:\n{exc}")
    except Exception:
        pass


def start_background_services() -> None:
    """السيرفر والمهام الدورية (مرة واحدة لكل تشغيل)."""
    from ftapp.api.server import server as api_server
    from ftapp.services import auth_service, scheduler, settings_service

    with db.session_scope() as s:
        cfg = settings_service.get(s, "server")
        sid = auth_service.server_id(s)
        company = settings_service.get(s, "company").get("name", "")
    if cfg.get("enabled", True) and not api_server.running:
        api_server.start(int(cfg.get("port", 8765)), bool(cfg.get("lan_only", True)), sid, company)
        if api_server.error:
            log.warning("API server: %s", api_server.error)

    from ftapp.core import secrets_store
    try:  # حذف رمز بوت تيليغرام القديم (الميزة أُزيلت نهائياً)
        secrets_store.set_secret("telegram_bot_token", None)
    except Exception:
        log.debug("legacy telegram secret cleanup skipped", exc_info=True)

    global _scheduler
    if _scheduler is None:
        _scheduler = scheduler.Scheduler()
        _scheduler.start()


_scheduler = None


def main() -> int:
    setup_logging()
    sys.excepthook = _excepthook
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(QIcon(str(assets_dir() / "icon.png")))
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    lock = QLockFile(str(data_dir() / "app.lock"))
    if not lock.tryLock(100):
        QMessageBox.warning(None, APP_NAME, "البرنامج مفتوح مسبقاً على هذا الجهاز.")
        return 1

    from ftapp.ui import i18n, theme

    theme.load_fonts()
    db.init_engine()
    db.run_migrations()

    from ftapp.services import auth_service, settings_service

    with db.session_scope() as s:
        auth_service.ensure_server_identity(s)
        ui_cfg = settings_service.get(s, "ui")
        setup_done = auth_service.is_setup_done(s)
    theme.apply(app, ui_cfg.get("theme", "light"))
    i18n.set_language(ui_cfg.get("language", "ar"))
    app.setLayoutDirection(i18n.direction())

    from ftapp.ui.dialogs.auth_dialogs import LoginDialog, SetupWizard

    if not setup_done:
        if SetupWizard().exec() != QDialog.DialogCode.Accepted:
            return 0

    from ftapp.models import User
    from ftapp.ui.context import ctx
    from ftapp.ui.main_window import MainWindow

    started = False
    while True:
        login = LoginDialog()
        if login.exec() != QDialog.DialogCode.Accepted or login.user_id is None:
            break
        with db.session_scope() as s:
            ctx.set_user(s.get(User, login.user_id))
        if not started:
            start_background_services()
            started = True
        window = MainWindow()
        window.show()
        app.exec()
        ctx.set_user(None)
        if not window.logout_requested:
            break

    from ftapp.api.server import server as api_server
    api_server.stop()
    if _scheduler:
        _scheduler.stop()
    lock.unlock()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
