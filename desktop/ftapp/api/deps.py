"""اعتماديات FastAPI: الجلسة، المستخدم الحالي، الصلاحيات، حماية الشبكة المحلية."""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import defaultdict, deque
from typing import Iterator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from ftapp.core.db import new_session
from ftapp.models import DeviceSession, User
from ftapp.services import auth_service, permissions
from ftapp.services.errors import ValidationError


def get_db() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class AuthContext:
    def __init__(self, user: User, device: DeviceSession) -> None:
        self.user = user
        self.device = device

    @property
    def privileged(self) -> bool:
        return permissions.is_privileged(self.user)

    def can(self, perm: str) -> bool:
        return permissions.has(self.user, perm)


def current(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> AuthContext:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "سجّل الدخول أولاً")
    try:
        user, device = auth_service.resolve_token(db, authorization[7:].strip())
    except ValidationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc))
    db.commit()
    return AuthContext(user, device)


def require(perm: str):
    def checker(ctx: AuthContext = Depends(current)) -> AuthContext:
        if not ctx.can(perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "ليس لديك صلاحية لهذه العملية")
        return ctx
    return checker


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def is_lan_address(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host in ("testclient", "localhost")
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local


class RateLimiter:
    """حد بسيط لمحاولات الدخول لكل عنوان IP."""

    def __init__(self, max_attempts: int = 10, window_seconds: int = 300) -> None:
        self.max = max_attempts
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "محاولات كثيرة، انتظر بضع دقائق")
            q.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


login_limiter = RateLimiter()
