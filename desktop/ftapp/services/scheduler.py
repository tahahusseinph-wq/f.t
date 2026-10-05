"""مهام دورية في الخلفية: فحص التنبيهات، النسخ الاحتياطي، التقرير اليومي، فحص التحديثات."""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime

from ftapp.core.db import session_scope
from ftapp.services import settings_service as settings

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, interval_seconds: int = 60) -> None:
        self.interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick = 0
        self._last_update_check: date | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        self._safe(self.scan_notifications)
        self._safe(self.backup)
        while not self._stop.wait(self.interval):
            self._tick += 1
            if self._tick % 10 == 0:
                self._safe(self.scan_notifications)
            if self._tick % 30 == 0:
                self._safe(self.backup)
            self._safe(self.check_updates)

    def _safe(self, fn) -> None:
        try:
            fn()
        except Exception:
            log.exception("scheduled task %s failed", fn.__name__)

    @staticmethod
    def scan_notifications() -> None:
        from ftapp.services import notification_service

        with session_scope() as s:
            notification_service.scan_all(s)

    @staticmethod
    def backup() -> None:
        from ftapp.services import backup_service

        with session_scope() as s:
            backup_service.auto_backup_if_due(s)

    def check_updates(self) -> None:
        from ftapp.services import notification_service, update_service

        if self._last_update_check == date.today():
            return
        with session_scope() as s:
            cfg = settings.get(s, "updates")
            self._last_update_check = date.today()
            if not cfg.get("auto_check") or not cfg.get("check_url"):
                return
            info = update_service.check(cfg["check_url"])
            if info and info.is_newer and cfg.get("notified_version") != info.version:
                notification_service.add(s, "update", f"يتوفر إصدار جديد {info.version}",
                                         info.notes[:300] or info.url, "info")
                cfg["notified_version"] = info.version
                settings.set(s, "updates", cfg)
