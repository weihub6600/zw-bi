from __future__ import annotations
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from ..core.auth import require_actor
from ..db import get_db
from ..services.dashboard_service import DashboardScope, get_dashboard, get_filter_options
from ..services.permission_service import ActorNotFound, PermissionDenied
router = APIRouter(prefix="/dashboard", tags=["dashboard"])
def _handle(exc):
    if isinstance(exc,ActorNotFound): raise HTTPException(status_code=401,detail=str(exc))
    if isinstance(exc,PermissionDenied): raise HTTPException(status_code=403,detail=str(exc))
    if isinstance(exc,ValueError): raise HTTPException(status_code=400,detail=str(exc))
    raise exc
@router.get("")
def dashboard(
    department_code: str = "B2C",
    days: int = Query(30, ge=1, le=30),
    start_date: date | None = None,
    end_date: date | None = None,
    shops: list[str] = Query(default=[]),
    warehouses: list[str] = Query(default=[]),
    product_search: str = "",
    include_name: str = "",
    exclude_name: str = "",
    product_codes: list[str] = Query(default=[]),
    product_category_ids: list[int] = Query(default=[]),
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return get_dashboard(
            db,
            DashboardScope(
                actor_user_id=actor["user_id"],
                department_code=department_code,
                days=days,
                start_date=start_date,
                end_date=end_date,
                shops=tuple(shops),
                warehouses=tuple(warehouses),
                product_search=product_search,
                include_name=include_name,
                exclude_name=exclude_name,
                product_codes=tuple(product_codes),
                product_category_ids=tuple(product_category_ids),
            ),
        )
    except Exception as exc:
        _handle(exc)
@router.get("/options")
def dashboard_options(
    department_code: str = "B2C",
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return get_filter_options(
            db,
            DashboardScope(
                actor_user_id=actor["user_id"],
                department_code=department_code,
            ),
        )
    except Exception as exc:
        _handle(exc)