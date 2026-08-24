from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..core.auth import require_actor
from ..services.permission_service import ActorNotFound, PermissionDenied
from ..services.task_crud_service import (
    create_task,
    decide_delete,
    list_assignees,
    list_task_dimensions,
    list_tasks,
    request_delete,
    update_owner_note,
    withdraw_delete,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


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


class CreateTaskBody(BaseModel):
    merchant_code: str = Field(min_length=1, max_length=128)
    owner_user_id: str = Field(min_length=1, max_length=32)
    target_qty: float | None = Field(default=None, ge=0)
    assign_date: date
    manager_note: str = Field(default="", max_length=20000)
    shop_name: str | None = Field(default=None, max_length=255)
    warehouse_name: str | None = Field(default=None, max_length=255)
    shop_ids: list[int] | None = Field(default=None)
    warehouse_ids: list[int] | None = Field(default=None)


class OwnerNoteBody(BaseModel):
    note: str = Field(default="", max_length=20000)


class DeleteRequestBody(BaseModel):
    reason: str = Field(default="", max_length=20000)


class DeleteDecisionBody(BaseModel):
    decision: str


@router.get("")
def tasks(
    department_code: str = "B2C",
    view: str = Query("mine"),
    owner_user_id: str = "",
    status: str = "",
    product_search: str = "",
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return list_tasks(
            db, actor_user_id=actor["user_id"], department_code=department_code, view=view,
            owner_user_id=owner_user_id, status=status, product_search=product_search,
        )
    except Exception as exc:
        _handle(exc)


@router.get("/assignees")
def assignees(department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        return list_assignees(db, actor["user_id"], department_code)
    except Exception as exc:
        _handle(exc)


@router.get("/options")
def task_options(department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        return list_task_dimensions(db, actor["user_id"], department_code)
    except Exception as exc:
        _handle(exc)


@router.post("")
def add_task(body: CreateTaskBody, department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        return create_task(db, actor_user_id=actor["user_id"], department_code=department_code, **body.model_dump())
    except Exception as exc:
        db.rollback()
        _handle(exc)


@router.put("/{task_no}/owner-note")
def owner_note(task_no: str, body: OwnerNoteBody, actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        return update_owner_note(db, actor["user_id"], task_no, body.note)
    except Exception as exc:
        db.rollback()
        _handle(exc)


@router.post("/{task_no}/delete-request")
def delete_request(task_no: str, body: DeleteRequestBody, actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        return request_delete(db, actor["user_id"], task_no, body.reason)
    except Exception as exc:
        db.rollback()
        _handle(exc)


@router.post("/{task_no}/delete-withdraw")
def delete_withdraw(task_no: str, actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        return withdraw_delete(db, actor["user_id"], task_no)
    except Exception as exc:
        db.rollback()
        _handle(exc)


@router.post("/{task_no}/delete-decision")
def delete_decision(task_no: str, body: DeleteDecisionBody, actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        return decide_delete(db, actor["user_id"], task_no, body.decision)
    except Exception as exc:
        db.rollback()
        _handle(exc)
