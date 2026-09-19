from __future__ import annotations

from contextlib import contextmanager
import threading

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .auth_service import hash_password


_setup_process_lock = threading.Lock()


@contextmanager
def _setup_lock(db: Session):
    """Serialize first-run initialization across workers on MySQL."""
    acquired_db_lock = False
    try:
        try:
            acquired_db_lock = db.execute(
                text("SELECT GET_LOCK(:name, 10)"),
                {"name": "baijiarui_bi_setup_initialize"},
            ).scalar() == 1
        except SQLAlchemyError:
            acquired_db_lock = False
        if acquired_db_lock:
            yield
        else:
            if not _setup_process_lock.acquire(timeout=10):
                raise PermissionError("首次初始化正在进行，请稍后重试")
            try:
                yield
            finally:
                _setup_process_lock.release()
    finally:
        if acquired_db_lock:
            try:
                db.execute(
                    text("SELECT RELEASE_LOCK(:name)"),
                    {"name": "baijiarui_bi_setup_initialize"},
                )
            except SQLAlchemyError:
                pass


def setup_status(db: Session) -> dict:
    users=int(db.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0)
    admins=int(db.execute(text("SELECT COUNT(*) FROM users WHERE is_system_admin=1")).scalar() or 0)
    departments=int(db.execute(text("SELECT COUNT(*) FROM departments WHERE status='enabled'")).scalar() or 0)
    return {"initialized": bool(users and admins), "user_count": users, "system_admin_count": admins, "department_count": departments, "external_wdt_api": False}


def initialize_system(db: Session, *, department_code: str, department_name: str, admin_user_id: str, admin_username: str, admin_password: str) -> dict:
    with _setup_lock(db):
        status=setup_status(db)
        if status["user_count"] > 0:
            raise PermissionError("系统已初始化，首次初始化接口已关闭")
        code=department_code.strip().upper() or "B2C"
        name=department_name.strip() or "B2C事业部"
        try:
            dep=db.execute(text("SELECT id FROM departments WHERE code=:code"),{"code":code}).scalar()
            if dep:
                db.execute(text("UPDATE departments SET name=:name,status='enabled' WHERE id=:id"),{"name":name,"id":dep})
                did=int(dep)
            else:
                did=int(db.execute(text("INSERT INTO departments(code,name,status) VALUES(:code,:name,'enabled')"),{"code":code,"name":name}).lastrowid)
            uid=int(db.execute(text("""
              INSERT INTO users(user_id,username,password_hash,is_system_admin,status,last_active_time)
              VALUES(:user_id,:username,:password_hash,1,'enabled',CURRENT_TIMESTAMP)
            """),{"user_id":admin_user_id.strip(),"username":admin_username.strip(),"password_hash":hash_password(admin_password)}).lastrowid)
            db.execute(text("INSERT INTO user_departments(user_pk,department_id,role,status) VALUES(:u,:d,'dept_admin','enabled')"),{"u":uid,"d":did})
            db.commit()
            return {"ok":True,"department":{"code":code,"name":name},"admin":{"user_id":admin_user_id.strip(),"username":admin_username.strip()},"external_wdt_api":False}
        except IntegrityError as exc:
            db.rollback();raise ValueError("初始化失败：部门、user_id 或用户名存在冲突") from exc
