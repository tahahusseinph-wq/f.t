"""الإعداد الأول، تسجيل الدخول، إدارة المستخدمين والجلسات."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ftapp.core import security
from ftapp.core.events import DEVICES_CHANGED, USERS_CHANGED, bus
from ftapp.core.utils import now
from ftapp.models import DeviceSession, User
from ftapp.services import audit, settings_service as settings
from ftapp.services.errors import NotFound, ValidationError
from ftapp.services.permissions import ROLES

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 5


@dataclass
class SetupData:
    username: str
    password: str
    full_name: str = ""
    company_name: str = ""
    company_address: str = ""
    company_phone: str = ""
    base_currency: str = "SYP"
    secondary_currency: str | None = "USD"
    secondary_rate: float = 0.0
    gemini_key: str = ""


def _hash_recovery(key: str) -> str:
    return hashlib.sha256(security.normalize_recovery_key(key).encode()).hexdigest()


def is_setup_done(session: Session) -> bool:
    return bool(settings.get(session, "setup_done")) and session.scalar(select(func.count(User.id))) > 0


def validate_username(username: str) -> str:
    username = (username or "").strip()
    if len(username) < 3:
        raise ValidationError("اسم المستخدم يجب أن يكون 3 أحرف على الأقل")
    if " " in username:
        raise ValidationError("اسم المستخدم لا يجب أن يحتوي مسافات")
    return username


def run_setup(session: Session, data: SetupData) -> str:
    """ينشئ حساب الأدمن والبيانات الأساسية، ويعيد مفتاح الاسترجاع (يُعرض مرة واحدة)."""
    from ftapp.services import bootstrap, secrets_service

    if is_setup_done(session):
        raise ValidationError("تم الإعداد مسبقاً")
    username = validate_username(data.username)
    err = security.validate_password(data.password)
    if err:
        raise ValidationError(err)

    admin = User(username=username, full_name=data.full_name or username,
                 password_hash=security.hash_password(data.password), role="admin")
    session.add(admin)
    session.flush()

    company = settings.get(session, "company")
    if data.company_name:
        company["name"] = data.company_name
    company["address"] = data.company_address
    company["phone"] = data.company_phone
    settings.set(session, "company", company)

    bootstrap.seed_defaults(session, data.base_currency, data.secondary_currency, data.secondary_rate)
    if data.gemini_key:
        secrets_service.set_gemini_key(data.gemini_key)

    recovery = security.generate_recovery_key()
    settings.set(session, "recovery_key_hash", _hash_recovery(recovery))
    settings.set(session, "setup_done", True)
    ensure_server_identity(session)
    audit.log(session, admin, "setup", "user", admin.id)
    return recovery


def authenticate(session: Session, username: str, password: str, source: str = "desktop") -> User:
    user = session.scalar(select(User).where(func.lower(User.username) == (username or "").strip().lower()))
    if user is None:
        raise ValidationError("اسم المستخدم أو كلمة السر غير صحيحة")
    if not user.is_active:
        raise ValidationError("هذا الحساب موقوف، راجع الأدمن")
    if user.locked_until and user.locked_until > now():
        minutes = max(1, int((user.locked_until - now()).total_seconds() // 60) + 1)
        raise ValidationError(f"الحساب مقفل مؤقتاً بسبب محاولات خاطئة، حاول بعد {minutes} دقيقة")
    if not security.verify_password(password or "", user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = now() + timedelta(minutes=LOCK_MINUTES)
            user.failed_attempts = 0
        audit.log(session, user, "login_failed", "user", user.id, source=source)
        session.commit()
        raise ValidationError("اسم المستخدم أو كلمة السر غير صحيحة")
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login = now()
    audit.log(session, user, "login", "user", user.id, source=source)
    session.flush()
    return user


def change_password(session: Session, user: User, old_password: str, new_password: str) -> None:
    if not security.verify_password(old_password, user.password_hash):
        raise ValidationError("كلمة السر الحالية غير صحيحة")
    err = security.validate_password(new_password)
    if err:
        raise ValidationError(err)
    user.password_hash = security.hash_password(new_password)
    user.token_version += 1
    audit.log(session, user, "password_changed", "user", user.id)


def reset_with_recovery_key(session: Session, recovery_key: str, username: str, new_password: str) -> str:
    """يعيد تعيين كلمة سر الأدمن بمفتاح الاسترجاع ويولّد مفتاحاً جديداً."""
    stored = settings.get(session, "recovery_key_hash")
    if not stored or _hash_recovery(recovery_key) != stored:
        raise ValidationError("مفتاح الاسترجاع غير صحيح")
    user = session.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
    if user is None or user.role != "admin":
        raise ValidationError("لا يوجد أدمن بهذا الاسم")
    err = security.validate_password(new_password)
    if err:
        raise ValidationError(err)
    user.password_hash = security.hash_password(new_password)
    user.failed_attempts = 0
    user.locked_until = None
    user.is_active = True
    user.token_version += 1
    new_key = security.generate_recovery_key()
    settings.set(session, "recovery_key_hash", _hash_recovery(new_key))
    audit.log(session, user, "password_reset", "user", user.id)
    return new_key


def regenerate_recovery_key(session: Session, actor: User) -> str:
    key = security.generate_recovery_key()
    settings.set(session, "recovery_key_hash", _hash_recovery(key))
    audit.log(session, actor, "settings_changed", "recovery_key")
    return key


# ---------- المستخدمون ----------

def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.id)))


def get_user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise NotFound("المستخدم غير موجود")
    return user


def create_user(session: Session, actor: User | None, username: str, password: str, role: str,
                full_name: str = "", phone: str = "", commission_rate: float = 0.0,
                permissions: dict | None = None, is_active: bool = True) -> User:
    username = validate_username(username)
    if role not in ROLES:
        raise ValidationError("دور غير معروف")
    if session.scalar(select(User).where(func.lower(User.username) == username.lower())):
        raise ValidationError("اسم المستخدم مستخدم مسبقاً")
    err = security.validate_password(password)
    if err:
        raise ValidationError(err)
    user = User(username=username, full_name=full_name, phone=phone, role=role,
                password_hash=security.hash_password(password), commission_rate=commission_rate or 0.0,
                permissions=permissions or {}, is_active=is_active)
    session.add(user)
    session.flush()
    audit.log(session, actor, "user_created", "user", user.id, username=username, role=role)
    bus.publish(USERS_CHANGED)
    return user


def update_user(session: Session, actor: User | None, user_id: int, *, full_name: str | None = None,
                phone: str | None = None, role: str | None = None, is_active: bool | None = None,
                commission_rate: float | None = None, permissions: dict | None = None,
                new_password: str | None = None) -> User:
    user = get_user(session, user_id)
    if role is not None and role != user.role:
        if role not in ROLES:
            raise ValidationError("دور غير معروف")
        if user.role == "admin" and _admin_count(session) <= 1:
            raise ValidationError("لا يمكن تغيير دور آخر أدمن في النظام")
        user.role = role
        user.token_version += 1
    if is_active is not None and is_active != user.is_active:
        if not is_active and user.role == "admin" and _admin_count(session) <= 1:
            raise ValidationError("لا يمكن إيقاف آخر أدمن في النظام")
        user.is_active = is_active
        if not is_active:
            user.token_version += 1
    if full_name is not None:
        user.full_name = full_name
    if phone is not None:
        user.phone = phone
    if commission_rate is not None:
        user.commission_rate = commission_rate
    if permissions is not None:
        user.permissions = permissions
    if new_password:
        err = security.validate_password(new_password)
        if err:
            raise ValidationError(err)
        user.password_hash = security.hash_password(new_password)
        user.token_version += 1
        user.locked_until = None
        user.failed_attempts = 0
    audit.log(session, actor, "user_updated", "user", user.id)
    bus.publish(USERS_CHANGED)
    return user


def delete_user(session: Session, actor: User, user_id: int) -> None:
    user = get_user(session, user_id)
    if user.id == actor.id:
        raise ValidationError("لا يمكنك حذف حسابك الحالي")
    if user.role == "admin" and _admin_count(session) <= 1:
        raise ValidationError("لا يمكن حذف آخر أدمن")
    audit.log(session, actor, "user_deleted", "user", user.id, username=user.username)
    session.delete(user)
    bus.publish(USERS_CHANGED)


def _admin_count(session: Session) -> int:
    return session.scalar(select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))) or 0


# ---------- جلسات الأجهزة (الموبايل) ----------

def ensure_server_identity(session: Session) -> None:
    """يولّد معرّف السيرفر ومفتاح توقيع الجلسات مرة واحدة (عند الإعداد وعند كل تشغيل)."""
    if not settings.get(session, "jwt_secret"):
        settings.set(session, "jwt_secret", security.generate_secret())
    if not settings.get(session, "server_id"):
        settings.set(session, "server_id", uuid.uuid4().hex[:12])


def jwt_secret(session: Session) -> str:
    secret = settings.get(session, "jwt_secret")
    if not secret:
        raise ValidationError("السيرفر غير مهيأ بعد")
    return secret


def server_id(session: Session) -> str:
    return settings.get(session, "server_id") or ""


def issue_device_token(session: Session, user: User, device_name: str, ip: str) -> str:
    token, jti = security.create_token(jwt_secret(session), user.id, user.role, user.token_version, hours=24 * 7)
    session.add(DeviceSession(user_id=user.id, jti=jti, device_name=device_name[:128], ip=ip))
    bus.publish(DEVICES_CHANGED)
    return token


def resolve_token(session: Session, token: str) -> tuple[User, DeviceSession]:
    import jwt as pyjwt

    try:
        payload = security.decode_token(jwt_secret(session), token)
    except pyjwt.ExpiredSignatureError:
        raise ValidationError("انتهت صلاحية الجلسة، سجّل الدخول من جديد")
    except pyjwt.PyJWTError:
        raise ValidationError("جلسة غير صالحة")
    device = session.scalar(select(DeviceSession).where(DeviceSession.jti == payload.get("jti")))
    user = session.get(User, int(payload["sub"]))
    if device is None or device.revoked or user is None or not user.is_active:
        raise ValidationError("تم إنهاء الجلسة")
    if user.token_version != payload.get("tv"):
        raise ValidationError("تم تغيير بيانات الحساب، سجّل الدخول من جديد")
    device.last_seen = now()
    return user, device


def list_devices(session: Session, active_only: bool = True) -> list[DeviceSession]:
    stmt = select(DeviceSession).order_by(DeviceSession.last_seen.desc())
    if active_only:
        stmt = stmt.where(DeviceSession.revoked.is_(False))
    return list(session.scalars(stmt))


def revoke_device(session: Session, actor: User | None, device_id: int) -> None:
    device = session.get(DeviceSession, device_id)
    if device:
        device.revoked = True
        audit.log(session, actor, "device_revoked", "device", device.id, device=device.device_name)
        bus.publish(DEVICES_CHANGED)


def revoke_jti(session: Session, jti: str) -> None:
    device = session.scalar(select(DeviceSession).where(DeviceSession.jti == jti))
    if device:
        device.revoked = True
        bus.publish(DEVICES_CHANGED)
