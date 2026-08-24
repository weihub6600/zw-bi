from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.auth import require_actor
from ..core.config import settings
from ..db import get_db
from ..services.auth_service import (
    AuthenticationError, all_enabled_departments, authenticate, create_session, heartbeat,
    memberships_for_user, record_activity, revoke_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    login_key: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    remember: bool = False


def _client(request: Request) -> tuple[str | None, str | None]:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    ip = forwarded or (request.client.host if request.client else None)
    return ip, request.headers.get("user-agent")


def _profile(db: Session, actor: dict) -> dict:
    memberships = all_enabled_departments(db) if actor["is_system_admin"] else memberships_for_user(db, actor["user_pk"])
    can_manage_users = bool(actor["is_system_admin"] or any(m["role"] == "dept_admin" for m in memberships))
    can_import = can_manage_users
    # 数据下载：系统管理员恒可下载；其余用户只要存在至少一个 enabled 部门成员关系即可下载本部门数据。
    can_download_data = bool(actor["is_system_admin"] or memberships)
    return {
        "user": {
            "user_id": actor["user_id"], "username": actor["username"],
            "is_system_admin": bool(actor["is_system_admin"]),
        },
        "memberships": memberships,
        "capabilities": {
            "can_import": can_import,
            "can_download_data": can_download_data,
            "can_manage_users": can_manage_users,
            "can_manage_expiry_rules": can_manage_users,
            "can_manage_departments": bool(actor["is_system_admin"]),
            "can_view_all_departments": bool(actor["is_system_admin"]),
        },
    }


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    ip, ua = _client(request)
    try:
        user = authenticate(db, body.login_key, body.password, ip_address=ip, user_agent=ua)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    raw, expires_at = create_session(
        db, int(user["id"]), remember=body.remember,
        session_hours=settings.session_hours, remember_days=settings.remember_session_days,
        ip_address=ip, user_agent=ua,
    )
    max_age = settings.remember_session_days * 86400 if body.remember else settings.session_hours * 3600
    response.set_cookie(
        settings.session_cookie_name, raw, max_age=max_age,
        httponly=True, samesite="lax", secure=settings.session_cookie_secure, path="/",
    )
    actor = {"user_pk": user["id"], **user}
    record_activity(db, int(user["id"]), "login", detail={"ip": ip})
    return _profile(db, actor)


@router.get("/me")
def me(actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    return _profile(db, actor)


@router.post("/heartbeat")
def auth_heartbeat(actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    heartbeat(db, int(actor["session_id"]), int(actor["user_pk"]))
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response, actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    raw = request.cookies.get(settings.session_cookie_name)
    revoke_session(db, raw)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"ok": True}
