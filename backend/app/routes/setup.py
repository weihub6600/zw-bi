from __future__ import annotations
import hmac
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..services.setup_service import setup_status, initialize_system
from ..core.config import settings

router=APIRouter(prefix='/setup',tags=['setup'])

class SetupBody(BaseModel):
    department_code:str=Field(default='B2C',min_length=1,max_length=64)
    department_name:str=Field(default='B2C事业部',min_length=1,max_length=128)
    admin_user_id:str=Field(default='SYS0001',min_length=1,max_length=32)
    admin_username:str=Field(default='admin',min_length=1,max_length=128)
    admin_password:str=Field(min_length=8,max_length=256)

@router.get('/status')
def status(db:Session=Depends(get_db)):
    return setup_status(db)

@router.post('/initialize')
def initialize(body:SetupBody,db:Session=Depends(get_db),x_setup_token: str | None = Header(default=None)):
    if settings.app_environment.strip().lower() == "production":
        if not x_setup_token or not hmac.compare_digest(x_setup_token, settings.setup_init_token):
            raise HTTPException(status_code=403,detail="首次初始化需要受控初始化令牌")
    try:return initialize_system(db,**body.model_dump())
    except PermissionError as exc:raise HTTPException(status_code=409,detail=str(exc))
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc))
