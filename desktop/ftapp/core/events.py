"""ناقل أحداث بسيط مستقل عن Qt، يستخدمه السيرفر والخدمات لإبلاغ الواجهة بالتغييرات."""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            self._handlers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            if handler in self._handlers.get(topic, []):
                self._handlers[topic].remove(handler)

    def publish(self, topic: str, **payload: Any) -> None:
        with self._lock:
            handlers = list(self._handlers.get(topic, [])) + list(self._handlers.get("*", []))
        for handler in handlers:
            try:
                handler(topic, payload)
            except Exception:  # لا نسمح لمستمع واحد بإيقاف البقية
                log.exception("event handler failed for %s", topic)


bus = EventBus()

# أسماء الأحداث المستخدمة
PRODUCTS_CHANGED = "products.changed"
STOCK_CHANGED = "stock.changed"
SALES_CHANGED = "sales.changed"
NOTIFICATIONS_CHANGED = "notifications.changed"
USERS_CHANGED = "users.changed"
SETTINGS_CHANGED = "settings.changed"
DEVICES_CHANGED = "devices.changed"
