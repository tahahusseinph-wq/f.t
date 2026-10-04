"""تشفير كلمات السر، رموز JWT، ومفتاح الاسترجاع."""
from __future__ import annotations

import re
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 8
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_strength(password: str) -> int:
    """قوة كلمة السر من 0 إلى 4."""
    if not password:
        return 0
    score = 0
    if len(password) >= MIN_PASSWORD_LENGTH:
        score += 1
    if len(password) >= 12:
        score += 1
    if re.search(r"[A-Za-z؀-ۿ]", password) and re.search(r"\d", password):
        score += 1
    if re.search(r"[^A-Za-z0-9؀-ۿ]", password) or (
        re.search(r"[a-z]", password) and re.search(r"[A-Z]", password)
    ):
        score += 1
    return min(score, 4)


def validate_password(password: str) -> str | None:
    """يعيد رسالة خطأ بالعربية أو None إذا كانت كلمة السر مقبولة."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"كلمة السر يجب أن تكون {MIN_PASSWORD_LENGTH} أحرف على الأقل"
    if password_strength(password) < 2:
        return "كلمة السر ضعيفة: استخدم أحرفاً وأرقاماً معاً"
    return None


def generate_recovery_key() -> str:
    """مفتاح استرجاع بصيغة XXXX-XXXX-XXXX-XXXX-XXXX."""
    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(5)]
    return "-".join(groups)


def normalize_recovery_key(key: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", key.upper())


def generate_secret(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def create_token(secret: str, user_id: int, role: str, token_version: int,
                 hours: int = 12, extra: dict[str, Any] | None = None) -> tuple[str, str]:
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(user_id),
        "role": role,
        "tv": token_version,
        "jti": jti,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM), jti


def decode_token(secret: str, token: str) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
