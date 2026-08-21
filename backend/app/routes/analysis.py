from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..core.auth import require_actor
from ..services.analysis_service import (
    get_expiry_batches,
    get_inventory_analysis,
    get_product_detail,
    search_products,
    save_product_note,
)
from ..services.dashboard_service import DashboardScope
from ..services.permission_service import ActorNotFound, PermissionDenied

router = APIRouter(prefix="/analysis", tags=["analysis"])


def _handle(exc: Exception):
    if isinstance(exc, ActorNotFound):
        raise HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, PermissionDenied):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise exc


def _scope(
    actor_user_id: str,
    department_code: str,
    days: int,
    shops: list[str],
    warehouses: list[str],
    product_search: str,
    include_name: str,
    exclude_name: str,
    product_codes: list[str] | tuple[str, ...] = (),
    start_date: date | None = None,
    end_date: date | None = None,
) -> DashboardScope:
    return DashboardScope(
        actor_user_id=actor_user_id,
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
    )


@router.get("/inventory")
def inventory_analysis(
    department_code: str = "B2C",
    days: int = Query(30, ge=1, le=30),
    shops: list[str] = Query(default=[]),
    warehouses: list[str] = Query(default=[]),
    product_search: str = "",
    include_name: str = "",
    exclude_name: str = "",
    product_codes: list[str] = Query(default=[]),
    category: str | None = None,
    high_cover_days: int = Query(90, ge=1, le=3650),
    stagnant_aging_days: int = Query(180, ge=1, le=3650),
    stagnant_cover_days: int = Query(180, ge=1, le=3650),
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return get_inventory_analysis(
            db,
            _scope(actor["user_id"], department_code, days, shops, warehouses, product_search, include_name, exclude_name, product_codes),
            category=category,
            high_cover_days=high_cover_days,
            stagnant_aging_days=stagnant_aging_days,
            stagnant_cover_days=stagnant_cover_days,
        )
    except Exception as exc:
        _handle(exc)


@router.get("/expiry")
def expiry_batches(
    department_code: str = "B2C",
    warehouses: list[str] = Query(default=[]),
    product_search: str = "",
    include_name: str = "",
    exclude_name: str = "",
    product_codes: list[str] = Query(default=[]),
    statuses: list[str] = Query(default=[]),
    remaining_days_min: int | None = None,
    remaining_days_max: int | None = None,
    remaining_pct_min: float | None = Query(default=None, ge=0, le=100),
    remaining_pct_max: float | None = Query(default=None, ge=0, le=100),
    limit: int = Query(1000, ge=1, le=5000),
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return get_expiry_batches(
            db,
            _scope(actor["user_id"], department_code, 30, [], warehouses, product_search, include_name, exclude_name, product_codes),
            statuses=tuple(statuses),
            remaining_days_min=remaining_days_min,
            remaining_days_max=remaining_days_max,
            remaining_pct_min=remaining_pct_min,
            remaining_pct_max=remaining_pct_max,
            limit=limit,
        )
    except Exception as exc:
        _handle(exc)


@router.get("/products/search")
def product_search(
    q: str = Query("", min_length=0, max_length=255),
    department_code: str = "B2C",
    limit: int = Query(20, ge=1, le=30),
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return search_products(
            db,
            DashboardScope(actor_user_id=actor["user_id"], department_code=department_code),
            q,
            limit=limit,
        )
    except Exception as exc:
        _handle(exc)


@router.get("/products/{merchant_code}")
def product_detail(
    merchant_code: str,
    department_code: str = "B2C",
    days: int = Query(30, ge=1, le=30),
    start_date: date | None = None,
    end_date: date | None = None,
    shops: list[str] = Query(default=[]),
    warehouses: list[str] = Query(default=[]),
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return get_product_detail(
            db,
            _scope(actor["user_id"], department_code, days, shops, warehouses, "", "", "", start_date=start_date, end_date=end_date),
            merchant_code,
        )
    except Exception as exc:
        _handle(exc)


class ProductNoteBody(BaseModel):
    note: str = Field(default="", max_length=20000)


@router.put("/products/{merchant_code}/note")
def product_note(
    merchant_code: str,
    body: ProductNoteBody,
    department_code: str = "B2C",
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return save_product_note(
            db,
            DashboardScope(actor_user_id=actor["user_id"], department_code=department_code),
            merchant_code,
            body.note,
        )
    except Exception as exc:
        _handle(exc)
