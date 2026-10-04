"""واجهة مبسطة للمفاتيح السرية للتطبيق."""
from __future__ import annotations

from ftapp.core import secrets_store

GEMINI = "gemini_api_key"
TELEGRAM = "telegram_bot_token"
BACKUP_PASSWORD = "backup_password"


def set_gemini_key(key: str | None) -> None:
    secrets_store.set_secret(GEMINI, (key or "").strip() or None)


def gemini_key() -> str | None:
    return secrets_store.get_secret(GEMINI)


def set_telegram_token(token: str | None) -> None:
    secrets_store.set_secret(TELEGRAM, (token or "").strip() or None)


def telegram_token() -> str | None:
    return secrets_store.get_secret(TELEGRAM)


def set_backup_password(pw: str | None) -> None:
    secrets_store.set_secret(BACKUP_PASSWORD, pw or None)


def backup_password() -> str | None:
    return secrets_store.get_secret(BACKUP_PASSWORD)
