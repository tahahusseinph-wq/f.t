from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ftapp.api.deps import AuthContext, get_db, require
from ftapp.api.routers.auth import user_out
from ftapp.api.schemas import UserIn, UserPatch
from ftapp.services import auth_service, permissions

router = APIRouter(tags=["users"])


@router.get("/users")
def users(ctx: AuthContext = Depends(require("users.manage")), db: Session = Depends(get_db)) -> list[dict]:
    return [{**user_out(u).model_dump(), "is_active": u.is_active,
             "last_login": u.last_login.isoformat() if u.last_login else None}
            for u in auth_service.list_users(db)]


@router.get("/roles")
def roles(ctx: AuthContext = Depends(require("users.manage"))) -> dict:
    return permissions.ROLES


@router.post("/users")
def add_user(body: UserIn, ctx: AuthContext = Depends(require("users.manage")), db: Session = Depends(get_db)) -> dict:
    u = auth_service.create_user(db, ctx.user, body.username, body.password, body.role, body.full_name, body.phone)
    return {**user_out(u).model_dump(), "is_active": u.is_active}


@router.patch("/users/{user_id}")
def edit_user(user_id: int, body: UserPatch, ctx: AuthContext = Depends(require("users.manage")),
              db: Session = Depends(get_db)) -> dict:
    u = auth_service.update_user(db, ctx.user, user_id, full_name=body.full_name, role=body.role,
                                 is_active=body.is_active, new_password=body.password)
    return {**user_out(u).model_dump(), "is_active": u.is_active}
