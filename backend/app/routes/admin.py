from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.auth import require_actor
from ..db import get_db
from ..services.admin_service import (
    activity_summary, create_user, get_department_expiry_rule, list_users,
    save_department_expiry_rule, update_user, user_detail,
    list_product_category_admin, create_product_category, rename_product_category,
    delete_product_category, set_product_categories,
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


class ProductCategoryBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProductCategoryAssignmentBody(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=500)
    category_ids: list[int] = Field(default_factory=list, max_length=100)


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


@router.get("/product-categories")
def product_category_admin(
    department_code: str = "B2C",
    search: str = "",
    category_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=10, le=100),
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return list_product_category_admin(db, actor, department_code, search=search, category_id=category_id, page=page, page_size=page_size)
    except Exception as exc: _handle(exc)


@router.post("/product-categories")
def add_product_category(body: ProductCategoryBody, department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try: return create_product_category(db, actor, department_code, body.name)
    except Exception as exc: db.rollback(); _handle(exc)


@router.put("/product-categories/assign")
def assign_product_categories(body: ProductCategoryAssignmentBody, department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try: return set_product_categories(db, actor, department_code, body.product_ids, body.category_ids)
    except Exception as exc: db.rollback(); _handle(exc)


@router.put("/product-categories/{category_id}")
def edit_product_category(category_id: int, body: ProductCategoryBody, department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try: return rename_product_category(db, actor, department_code, category_id, body.name)
    except Exception as exc: db.rollback(); _handle(exc)


@router.delete("/product-categories/{category_id}")
def remove_product_category(category_id: int, department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try: return delete_product_category(db, actor, department_code, category_id)
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
