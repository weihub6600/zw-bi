from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..core.auth import require_actor
from ..services.permission_service import ActorNotFound, PermissionDenied
from ..services.preset_service import delete_preset, list_presets, save_preset

router = APIRouter(prefix="/presets", tags=["presets"])


class PresetBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    shops: list[str] = Field(default_factory=list)
    warehouses: list[str] = Field(default_factory=list)
    product_codes: list[str] = Field(default_factory=list)
    include_name_keywords: list[str] = Field(default_factory=list)
    exclude_name_keywords: list[str] = Field(default_factory=list)


def _handle(exc: Exception):
    if isinstance(exc, ActorNotFound):
        raise HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, PermissionDenied):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (ValueError, IntegrityError)):
        raise HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("")
def get_presets(actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        return {"system_preset": {"name": "全部", "immutable": True}, "rows": list_presets(db, actor["user_id"])}
    except Exception as exc:
        _handle(exc)


@router.post("")
def create_preset(body: PresetBody, actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        return save_preset(db, actor["user_id"], **body.model_dump())
    except Exception as exc:
        db.rollback()
        _handle(exc)


@router.put("/{preset_id}")
def update_preset(preset_id: int, body: PresetBody, actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        return save_preset(db, actor["user_id"], preset_id=preset_id, **body.model_dump())
    except Exception as exc:
        db.rollback()
        _handle(exc)


@router.delete("/{preset_id}")
def remove_preset(preset_id: int, actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        return delete_preset(db, actor["user_id"], preset_id)
    except Exception as exc:
        db.rollback()
        _handle(exc)
