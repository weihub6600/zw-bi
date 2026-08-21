from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


class PermissionDenied(PermissionError):
    pass


class ActorNotFound(PermissionError):
    pass


def get_actor(db: Session, actor_user_id: str) -> dict:
    row = db.execute(
        text("SELECT id,user_id,username,is_system_admin,status FROM users WHERE user_id=:user_id"),
        {"user_id": actor_user_id},
    ).mappings().first()
    if not row:
        raise ActorNotFound(f"用户不存在：{actor_user_id}")
    if row["status"] != "enabled":
        raise PermissionDenied(f"用户已停用：{actor_user_id}")
    return dict(row)


def get_department(db: Session, department_code: str) -> dict:
    row = db.execute(
        text("SELECT id,code,name,status FROM departments WHERE code=:code"),
        {"code": department_code},
    ).mappings().first()
    if not row:
        raise PermissionDenied(f"部门不存在：{department_code}")
    if row["status"] != "enabled":
        raise PermissionDenied(f"部门已停用：{department_code}")
    return dict(row)


def assert_can_import(db: Session, actor_user_id: str, department_code: str) -> tuple[dict, dict]:
    """导入权限锁定：仅系统管理员、目标部门的部门管理员可导入；普通用户永远不可导入。"""
    actor = get_actor(db, actor_user_id)
    department = get_department(db, department_code)
    if actor["is_system_admin"]:
        return actor, department

    membership = db.execute(
        text(
            """
            SELECT role,status
            FROM user_departments
            WHERE user_pk=:user_pk AND department_id=:department_id
            """
        ),
        {"user_pk": actor["id"], "department_id": department["id"]},
    ).mappings().first()

    if not membership or membership["status"] != "enabled":
        raise PermissionDenied("无权访问目标部门")
    if membership["role"] != "dept_admin":
        raise PermissionDenied("普通用户不能导入数据；仅系统管理员或本部门部门管理员可导入")
    return actor, department


def assert_can_view_department(db: Session, actor_user_id: str, department_code: str) -> tuple[dict, dict]:
    actor = get_actor(db, actor_user_id)
    department = get_department(db, department_code)
    if actor["is_system_admin"]:
        return actor, department
    membership = db.execute(
        text(
            """
            SELECT role,status FROM user_departments
            WHERE user_pk=:user_pk AND department_id=:department_id
            """
        ),
        {"user_pk": actor["id"], "department_id": department["id"]},
    ).mappings().first()
    if not membership or membership["status"] != "enabled":
        raise PermissionDenied("无权访问目标部门")
    return actor, department
