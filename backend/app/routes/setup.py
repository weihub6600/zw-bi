from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..db import get_db
from ..services.setup_service import setup_status, initialize_system

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
def initialize(body:SetupBody,db:Session=Depends(get_db)):
    try:return initialize_system(db,**body.model_dump())
    except PermissionError as exc:raise HTTPException(status_code=409,detail=str(exc))
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc))
