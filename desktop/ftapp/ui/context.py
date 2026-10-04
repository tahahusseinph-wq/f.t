"""سياق التطبيق: المستخدم الحالي، الصلاحيات، وجسر الأحداث إلى إشارات Qt."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from PySide6.QtCore import QObject, Signal
from sqlalchemy.orm import Session

from ftapp.core import events
from ftapp.core.db import session_scope
from ftapp.models import User
from ftapp.services import permissions


class Signals(QObject):
    products_changed = Signal()
    stock_changed = Signal()
    sales_changed = Signal()
    notifications_changed = Signal()
    users_changed = Signal()
    settings_changed = Signal()
    devices_changed = Signal()
    notification_popup = Signal(str, str, str)  # severity, title, body
    navigate = Signal(str, object)  # اسم الصفحة، معطيات


class AppContext:
    def __init__(self) -> None:
        self.signals = Signals()
        self.user_id: int | None = None
        self.username = ""
        self.display_name = ""
        self.role = ""
        self._perms: set[str] = set()
        self._bridge()

    def _bridge(self) -> None:
        mapping = {
            events.PRODUCTS_CHANGED: self.signals.products_changed,
            events.STOCK_CHANGED: self.signals.stock_changed,
            events.SALES_CHANGED: self.signals.sales_changed,
            events.NOTIFICATIONS_CHANGED: self.signals.notifications_changed,
            events.USERS_CHANGED: self.signals.users_changed,
            events.SETTINGS_CHANGED: self.signals.settings_changed,
            events.DEVICES_CHANGED: self.signals.devices_changed,
        }
        for topic, signal in mapping.items():
            # الإشارات تنتقل تلقائياً إلى الخيط الرئيسي (Queued) عند صدورها من خيط السيرفر
            events.bus.subscribe(topic, lambda _t, _p, s=signal: s.emit())

        def popup(_t: str, payload: dict) -> None:
            if payload.get("kind"):
                self.signals.notification_popup.emit(payload.get("severity", "info"), payload.get("title", ""),
                                                     payload.get("body", ""))
        events.bus.subscribe(events.NOTIFICATIONS_CHANGED, popup)

    def set_user(self, user: User | None) -> None:
        if user is None:
            self.user_id, self.username, self.display_name, self.role, self._perms = None, "", "", "", set()
            return
        self.user_id = user.id
        self.username = user.username
        self.display_name = user.display_name
        self.role = user.role
        self._perms = permissions.effective_permissions(user)

    def can(self, perm: str) -> bool:
        return perm in self._perms

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def user(self, session: Session) -> User | None:
        return session.get(User, self.user_id) if self.user_id else None

    @contextmanager
    def session(self) -> Iterator[tuple[Session, User | None]]:
        with session_scope() as s:
            yield s, self.user(s)


ctx = AppContext()
