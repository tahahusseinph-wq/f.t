from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ftapp.api.deps import AuthContext, get_db, require
from ftapp.api.routers.auth import user_out
from ftapp.api.schemas import UserIn, UserPatch
from ftapp.services import auth_service, permissions

router = APIRouter(tags=["users"])


def _full(u) -> dict:
    return {**user_out(u).model_dump(), "is_active": u.is_active, "phone": u.phone or "",
            "commission_rate": u.commission_rate or 0, "overrides": dict(u.permissions or {}),
            "last_login": u.last_login.isoformat() if u.last_login else None}


@router.get("/users")
def users(ctx: AuthContext = Depends(require("users.manage")), db: Session = Depends(get_db)) -> list[dict]:
    return [_full(u) for u in auth_service.list_users(db)]


@router.get("/roles")
def roles(ctx: AuthContext = Depends(require("users.manage"))) -> dict:
    return permissions.ROLES


@router.get("/permissions")
def permission_list(ctx: AuthContext = Depends(require("users.manage"))) -> dict:
    """كل الصلاحيات مع افتراضيات كل دور — لشاشة تعديل المستخدم في الموبايل."""
    return {"permissions": permissions.PERMISSIONS, "roles": permissions.ROLES,
            "defaults": {r: sorted(p) for r, p in permissions.ROLE_DEFAULTS.items()},
            "opt_in": sorted(permissions.OPT_IN)}


@router.post("/users")
def add_user(body: UserIn, ctx: AuthContext = Depends(require("users.manage")), db: Session = Depends(get_db)) -> dict:
    u = auth_service.create_user(db, ctx.user, body.username, body.password, body.role, body.full_name, body.phone,
                                 body.commission_rate, body.permissions, body.is_active)
    db.flush()
    return _full(u)


@router.patch("/users/{user_id}")
def edit_user(user_id: int, body: UserPatch, ctx: AuthContext = Depends(require("users.manage")),
              db: Session = Depends(get_db)) -> dict:
    u = auth_service.update_user(db, ctx.user, user_id, full_name=body.full_name, phone=body.phone, role=body.role,
                                 is_active=body.is_active, commission_rate=body.commission_rate,
                                 permissions=body.permissions, new_password=body.password or None)
    return _full(u)


@router.delete("/users/{user_id}")
def remove_user(user_id: int, ctx: AuthContext = Depends(require("users.manage")),
                db: Session = Depends(get_db)) -> dict:
    auth_service.delete_user(db, ctx.user, user_id)
    return {"ok": True}
