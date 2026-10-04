"""تخزين المفاتيح الحساسة (Gemini، Telegram) بشكل مشفّر.

نستخدم keyring الخاص بنظام التشغيل إن توفر، وإلا نشفّر القيمة بـ Fernet
بمفتاح محلي محفوظ في مجلد البيانات.
"""
from __future__ import annotations

import json
import logging

from cryptography.fernet import Fernet, InvalidToken

from ftapp import APP_ID
from ftapp.core.paths import data_dir

log = logging.getLogger(__name__)

_FALLBACK_FILE = "secrets.enc"
_KEY_FILE = ".secret.key"


def _use_keyring() -> bool:
    try:
        import keyring
        from keyring.backends import fail

        return not isinstance(keyring.get_keyring(), fail.Keyring)
    except Exception:
        return False


def _fernet() -> Fernet:
    key_path = data_dir() / _KEY_FILE
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
    return Fernet(key_path.read_bytes())


def _load_fallback() -> dict[str, str]:
    path = data_dir() / _FALLBACK_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(_fernet().decrypt(path.read_bytes()).decode("utf-8"))
    except (InvalidToken, ValueError):
        log.error("secrets file could not be decrypted")
        return {}


def _save_fallback(data: dict[str, str]) -> None:
    path = data_dir() / _FALLBACK_FILE
    path.write_bytes(_fernet().encrypt(json.dumps(data).encode("utf-8")))


def set_secret(name: str, value: str | None) -> None:
    if _use_keyring():
        import keyring

        try:
            if value:
                keyring.set_password(APP_ID, name, value)
            else:
                try:
                    keyring.delete_password(APP_ID, name)
                except Exception:
                    pass
            return
        except Exception:
            log.warning("keyring unavailable, using encrypted file")
    data = _load_fallback()
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    _save_fallback(data)


def get_secret(name: str) -> str | None:
    if _use_keyring():
        import keyring

        try:
            value = keyring.get_password(APP_ID, name)
            if value:
                return value
        except Exception:
            pass
    return _load_fallback().get(name)
