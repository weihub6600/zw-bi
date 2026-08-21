from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.auth_service import resolve_session
from .config import settings


def require_actor(request: Request, db: Session = Depends(get_db)) -> dict:
    raw = request.cookies.get(settings.session_cookie_name)
    actor = resolve_session(db, raw)
    if not actor:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return actor
