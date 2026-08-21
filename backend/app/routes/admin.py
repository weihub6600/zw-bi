from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.auth import require_actor
from ..db import get_db
from ..services.admin_service import (
    activity_summary, create_user, get_department_expiry_rule, list_users,
    save_department_expiry_rule, update_user, user_detail,
)
from ..services.permission_service import PermissionDenied
from ..services.department_service import list_departments, create_department, update_department, delete_department, list_department_members, set_membership, remove_membership
from ..services.audit_service import list_audit_logs

router = APIRouter(prefix="/admin", tags=["admin"])


def _handle(exc: Exception):
    if isinstance(exc, PermissionDenied): raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError): raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError): raise HTTPException(status_code=400, detail=str(exc))
    raise exc


class CreateUserBody(BaseModel):
    user_id: str = Field(min_length=1, max_length=32)
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    role: str = "member"


class UpdateUserBody(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    account_status: str | None = None
    membership_status: str | None = None
    role: str | None = None


class ExpiryRuleBody(BaseModel):
    near_days: int = Field(ge=0, le=36500)
    near_pct: float = Field(ge=0, le=100)
    warn_days: int = Field(ge=0, le=36500)
    warn_pct: float = Field(ge=0, le=100)


@router.get("/users")
def users(department_code: str = "B2C", search: str = "", role: str = "", membership_status: str = "", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try: return list_users(db, actor, department_code, search=search, role=role, membership_status=membership_status)
    except Exception as exc: _handle(exc)


@router.get("/users/{user_id}")
def detail(user_id: str, department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try: return user_detail(db, actor, department_code, user_id)
    except Exception as exc: _handle(exc)


@router.post("/users")
def add_user(body: CreateUserBody, department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try: return create_user(db, actor, department_code, **body.model_dump())
    except Exception as exc: db.rollback(); _handle(exc)


@router.put("/users/{user_id}")
def edit_user(user_id: str, body: UpdateUserBody, department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try: return update_user(db, actor, department_code, user_id, **body.model_dump())
    except Exception as exc: db.rollback(); _handle(exc)


@router.get("/activity")
def activity(department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try: return activity_summary(db, actor, department_code)
    except Exception as exc: _handle(exc)


@router.get("/expiry-rules/department/{department_code}")
def expiry_rule(department_code: str, actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try: return get_department_expiry_rule(db, actor, department_code)
    except Exception as exc: _handle(exc)


@router.put("/expiry-rules/department/{department_code}")
def update_expiry_rule(department_code: str, body: ExpiryRuleBody, actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try: return save_department_expiry_rule(db, actor, department_code, **body.model_dump())
    except Exception as exc: db.rollback(); _handle(exc)


class DepartmentBody(BaseModel):
    code: str = Field(min_length=1,max_length=64)
    name: str = Field(min_length=1,max_length=128)

class DepartmentUpdateBody(BaseModel):
    name: str | None = Field(default=None,min_length=1,max_length=128)
    status: str | None = None

class MembershipBody(BaseModel):
    role: str = 'member'
    status: str = 'enabled'

@router.get('/departments')
def departments(include_disabled: bool=True, actor: dict=Depends(require_actor), db: Session=Depends(get_db)):
    try:return list_departments(db,actor,include_disabled=include_disabled)
    except Exception as exc:_handle(exc)

@router.post('/departments')
def add_department(body:DepartmentBody, actor:dict=Depends(require_actor), db:Session=Depends(get_db)):
    try:return create_department(db,actor,**body.model_dump())
    except Exception as exc:db.rollback();_handle(exc)

@router.put('/departments/{department_code}')
def edit_department(department_code:str,body:DepartmentUpdateBody,actor:dict=Depends(require_actor),db:Session=Depends(get_db)):
    try:return update_department(db,actor,department_code,**body.model_dump())
    except Exception as exc:db.rollback();_handle(exc)

@router.delete('/departments/{department_code}')
def remove_department(department_code:str,actor:dict=Depends(require_actor),db:Session=Depends(get_db)):
    try:return delete_department(db,actor,department_code)
    except Exception as exc:db.rollback();_handle(exc)

@router.get('/departments/{department_code}/members')
def department_members(department_code:str,actor:dict=Depends(require_actor),db:Session=Depends(get_db)):
    try:return list_department_members(db,actor,department_code)
    except Exception as exc:_handle(exc)

@router.put('/departments/{department_code}/members/{user_id}')
def edit_membership(department_code:str,user_id:str,body:MembershipBody,actor:dict=Depends(require_actor),db:Session=Depends(get_db)):
    try:return set_membership(db,actor,department_code,user_id,**body.model_dump())
    except Exception as exc:db.rollback();_handle(exc)

@router.delete('/departments/{department_code}/members/{user_id}')
def delete_membership(department_code:str,user_id:str,actor:dict=Depends(require_actor),db:Session=Depends(get_db)):
    try:return remove_membership(db,actor,department_code,user_id)
    except Exception as exc:db.rollback();_handle(exc)

@router.get('/audit')
def audit(department_code:str='',user_id:str='',action_type:str='',days:int=7,limit:int=200,actor:dict=Depends(require_actor),db:Session=Depends(get_db)):
    try:return list_audit_logs(db,actor,department_code=department_code,user_id=user_id,action_type=action_type,days=days,limit=limit)
    except Exception as exc:_handle(exc)
