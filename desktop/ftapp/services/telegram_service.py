"""بوت تيليغرام: تنبيهات النقص، الفواتير الكبيرة، والتقرير اليومي."""
from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Any

import httpx

from ftapp.core.events import NOTIFICATIONS_CHANGED, bus
from ftapp.services import secrets_service
from ftapp.services.errors import ServiceError

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(ServiceError):
    pass


def _call(method: str, token: str | None = None, files: dict | None = None, **params: Any) -> dict:
    token = token or secrets_service.telegram_token()
    if not token:
        raise TelegramError("لم يتم إدخال رمز بوت تيليغرام")
    try:
        resp = httpx.post(API.format(token=token, method=method), data=params, files=files, timeout=20)
        data = resp.json()
    except httpx.HTTPError as exc:
        raise TelegramError("تعذر الاتصال بتيليغرام، تحقق من الإنترنت") from exc
    except ValueError as exc:
        raise TelegramError("استجابة غير صالحة من تيليغرام") from exc
    if not data.get("ok"):
        desc = data.get("description", "")
        if "Unauthorized" in desc:
            raise TelegramError("رمز البوت غير صحيح")
        if "chat not found" in desc:
            raise TelegramError("معرّف المحادثة غير صحيح، أرسل /start للبوت أولاً")
        raise TelegramError(f"خطأ من تيليغرام: {desc}")
    return data


def send_message(text: str, chat_id: str, token: str | None = None) -> None:
    _call("sendMessage", token, chat_id=chat_id, text=text[:4000])


def send_document(path: Path | str, chat_id: str, caption: str = "", token: str | None = None) -> None:
    with open(path, "rb") as fh:
        _call("sendDocument", token, files={"document": (Path(path).name, fh)}, chat_id=chat_id,
              caption=caption[:1000])


def discover_chat_id(token: str | None = None) -> str | None:
    """بعد إرسال /start للبوت، نقرأ آخر رسالة لمعرفة معرّف المحادثة."""
    data = _call("getUpdates", token)
    for upd in reversed(data.get("result", [])):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            return str(chat["id"])
    return None


class TelegramNotifier:
    """يرسل الإشعارات في خيط منفصل حتى لا تتأخر الواجهة أو البيع."""

    ICONS = {"low_stock": "🟠", "out_of_stock": "🔴", "large_invoice": "💰", "expiry": "⏳", "expired": "⛔",
             "debt": "💳", "update": "⬆️"}

    def __init__(self, config_provider) -> None:
        self._config_provider = config_provider
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread = threading.Thread(target=self._worker, name="telegram", daemon=True)
        self._thread.start()
        bus.subscribe(NOTIFICATIONS_CHANGED, self._on_notification)

    def _on_notification(self, _topic: str, payload: dict[str, Any]) -> None:
        kind = payload.get("kind")
        if not kind:
            return
        cfg = self._config_provider()
        if not cfg.get("enabled") or not cfg.get("chat_id"):
            return
        if kind in ("low_stock", "out_of_stock", "expiry", "expired") and not cfg.get("notify_low_stock", True):
            return
        if kind == "large_invoice" and not cfg.get("notify_large_invoice", True):
            return
        icon = self.ICONS.get(kind, "🔔")
        self._queue.put(f"{icon} {payload.get('title', '')}\n{payload.get('body', '')}".strip())

    def _worker(self) -> None:
        while True:
            text = self._queue.get()
            try:
                cfg = self._config_provider()
                send_message(text, cfg.get("chat_id", ""))
            except Exception:
                log.warning("telegram send failed", exc_info=True)
