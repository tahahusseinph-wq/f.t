from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ftapp import APP_NAME, VERSION
from ftapp.api.deps import AuthContext, client_ip, current, get_db, login_limiter
from ftapp.api.schemas import LoginIn, LoginOut, UserOut
from ftapp.models import User
from ftapp.services import auth_service, permissions, settings_service as settings

router = APIRouter(tags=["auth"])


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, username=user.username, full_name=user.display_name, role=user.role,
                   role_label=permissions.ROLES.get(user.role, user.role),
                   permissions=sorted(permissions.effective_permissions(user)))


@router.get("/ping")
def ping(db: Session = Depends(get_db)) -> dict:
    company = settings.get(db, "company")
    return {"app": "ft-trading", "name": APP_NAME, "version": VERSION, "server_id": auth_service.server_id(db),
            "company": company.get("name"), "company_en": company.get("name_en"),
            "setup_done": auth_service.is_setup_done(db)}


@router.post("/auth/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> LoginOut:
    ip = client_ip(request)
    login_limiter.check(ip)
    user = auth_service.authenticate(db, body.username, body.password, source="mobile")
    login_limiter.reset(ip)
    token = auth_service.issue_device_token(db, user, body.device_name or "Android", ip)
    company = settings.get(db, "company")
    return LoginOut(token=token, user=user_out(user), server_id=auth_service.server_id(db),
                    company={"name": company.get("name"), "name_en": company.get("name_en"),
                             "phone": company.get("phone"), "address": company.get("address")})


@router.post("/auth/logout")
def logout(ctx: AuthContext = Depends(current), db: Session = Depends(get_db)) -> dict:
    auth_service.revoke_jti(db, ctx.device.jti)
    return {"ok": True}


@router.get("/auth/me", response_model=UserOut)
def me(ctx: AuthContext = Depends(current)) -> UserOut:
    return user_out(ctx.user)
