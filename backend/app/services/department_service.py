from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth_service import record_activity
from .permission_service import PermissionDenied, get_department


def require_system_admin(actor: dict) -> None:
    if not actor.get("is_system_admin"):
        raise PermissionDenied("仅系统管理员可以管理部门和跨部门成员关系")


def list_departments(db: Session, actor: dict, *, include_disabled: bool = True) -> dict:
    require_system_admin(actor)
    where = "" if include_disabled else "WHERE d.status='enabled'"
    rows = db.execute(text(f"""
        SELECT d.id,d.code,d.name,d.status,d.created_at,d.updated_at,
          (SELECT COUNT(*) FROM user_departments ud WHERE ud.department_id=d.id AND ud.status='enabled') member_count,
          (SELECT COUNT(*) FROM user_departments ud WHERE ud.department_id=d.id AND ud.status='enabled' AND ud.role='dept_admin') admin_count,
          (SELECT MAX(business_date) FROM sales_daily s WHERE s.department_id=d.id) latest_sales_date,
          (SELECT COUNT(*) FROM todo_tasks t WHERE t.department_id=d.id AND t.status IN ('running','pending_delete','delete_rejected')) open_task_count
        FROM departments d {where}
        ORDER BY CASE d.status WHEN 'enabled' THEN 0 ELSE 1 END,d.name
    """)).mappings().all()
    return {"items": [dict(r) for r in rows]}


def create_department(db: Session, actor: dict, *, code: str, name: str) -> dict:
    require_system_admin(actor)
    code = code.strip().upper()
    name = name.strip()
    if not code or not name:
        raise ValueError("部门编码和名称不能为空")
    try:
        result = db.execute(text("INSERT INTO departments(code,name,status) VALUES(:code,:name,'enabled')"), {"code": code, "name": name})
        did = int(result.lastrowid)
        record_activity(db, int(actor["user_pk"]), "department_create", department_id=did, detail={"code": code, "name": name})
        return dict(db.execute(text("SELECT id,code,name,status,created_at,updated_at FROM departments WHERE id=:id"), {"id": did}).mappings().one())
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("部门编码或名称已存在") from exc


def update_department(db: Session, actor: dict, department_code: str, *, name: str | None = None, status: str | None = None) -> dict:
    require_system_admin(actor)
    department = get_department_any_status(db, department_code)
    sets, params = [], {"id": department["id"]}
    if name is not None:
        if not name.strip():
            raise ValueError("部门名称不能为空")
        sets.append("name=:name"); params["name"] = name.strip()
    if status is not None:
        if status not in {"enabled", "disabled"}:
            raise ValueError("部门状态无效")
        sets.append("status=:status"); params["status"] = status
    if sets:
        try:
            db.execute(text("UPDATE departments SET " + ",".join(sets) + " WHERE id=:id"), params)
            record_activity(db, int(actor["user_pk"]), "department_update", department_id=int(department["id"]), detail={"name": name, "status": status})
        except IntegrityError as exc:
            db.rollback(); raise ValueError("部门名称已存在") from exc
    return dict(db.execute(text("SELECT id,code,name,status,created_at,updated_at FROM departments WHERE id=:id"), {"id": department["id"]}).mappings().one())


def get_department_any_status(db: Session, code: str) -> dict:
    row = db.execute(text("SELECT id,code,name,status FROM departments WHERE code=:code"), {"code": code}).mappings().first()
    if not row:
        raise LookupError("部门不存在")
    return dict(row)


def delete_department(db: Session, actor: dict, department_code: str) -> dict:
    """空部门允许硬删除；已有成员/业务数据时拒绝硬删，避免破坏历史。"""
    require_system_admin(actor)
    department = get_department_any_status(db, department_code)
    checks = {
        "成员": "SELECT COUNT(*) FROM user_departments WHERE department_id=:id",
        "销量": "SELECT COUNT(*) FROM sales_daily WHERE department_id=:id",
        "库存": "SELECT COUNT(*) FROM inventory_batch WHERE department_id=:id",
        "库龄": "SELECT COUNT(*) FROM aging_snapshot WHERE department_id=:id",
        "待办": "SELECT COUNT(*) FROM todo_tasks WHERE department_id=:id",
    }
    blockers = {k: int(db.execute(text(sql), {"id": department["id"]}).scalar() or 0) for k, sql in checks.items()}
    blockers = {k: v for k, v in blockers.items() if v}
    if blockers:
        raise ValueError("部门已有历史数据/成员，禁止硬删除；请改为停用。阻塞项：" + "、".join(f"{k}{v}" for k,v in blockers.items()))
    db.execute(text("DELETE FROM departments WHERE id=:id"), {"id": department["id"]})
    record_activity(db, int(actor["user_pk"]), "department_delete", detail={"code": department_code, "name": department["name"]})
    return {"ok": True, "deleted": department_code}


def list_department_members(db: Session, actor: dict, department_code: str) -> dict:
    require_system_admin(actor)
    department = get_department_any_status(db, department_code)
    rows = db.execute(text("""
      SELECT u.user_id,u.username,u.status AS account_status,u.is_system_admin,
             ud.role,ud.status AS membership_status,ud.created_at
      FROM user_departments ud JOIN users u ON u.id=ud.user_pk
      WHERE ud.department_id=:did
      ORDER BY CASE ud.role WHEN 'dept_admin' THEN 0 ELSE 1 END,u.username
    """), {"did": department["id"]}).mappings().all()
    return {"department": department, "items": [dict(r) for r in rows]}


def set_membership(db: Session, actor: dict, department_code: str, user_id: str, *, role: str, status: str = "enabled") -> dict:
    require_system_admin(actor)
    if role not in {"member", "dept_admin"} or status not in {"enabled", "disabled"}:
        raise ValueError("成员角色或状态无效")
    department = get_department_any_status(db, department_code)
    user = db.execute(text("SELECT id,user_id,username,is_system_admin FROM users WHERE user_id=:uid"), {"uid": user_id}).mappings().first()
    if not user:
        raise LookupError("用户不存在")
    existing = db.execute(text("SELECT id FROM user_departments WHERE user_pk=:u AND department_id=:d"), {"u": user["id"], "d": department["id"]}).scalar()
    if existing:
        db.execute(text("UPDATE user_departments SET role=:role,status=:status WHERE id=:id"), {"role": role, "status": status, "id": existing})
        action = "membership_update"
    else:
        db.execute(text("INSERT INTO user_departments(user_pk,department_id,role,status) VALUES(:u,:d,:role,:status)"), {"u": user["id"], "d": department["id"], "role": role, "status": status})
        action = "membership_create"
    record_activity(db, int(actor["user_pk"]), action, department_id=int(department["id"]), detail={"target_user_id": user_id, "role": role, "status": status})
    return {"department_code": department_code, "user_id": user_id, "role": role, "status": status}


def remove_membership(db: Session, actor: dict, department_code: str, user_id: str) -> dict:
    require_system_admin(actor)
    department = get_department_any_status(db, department_code)
    user = db.execute(text("SELECT id FROM users WHERE user_id=:uid"), {"uid": user_id}).scalar()
    if not user:
        raise LookupError("用户不存在")
    row = db.execute(text("SELECT id FROM user_departments WHERE user_pk=:u AND department_id=:d"), {"u": user, "d": department["id"]}).scalar()
    if not row:
        raise LookupError("该用户不属于此部门")
    task_count = int(db.execute(text("SELECT COUNT(*) FROM todo_tasks WHERE department_id=:d AND owner_user_pk=:u AND status IN ('running','pending_delete','delete_rejected')"), {"d": department["id"], "u": user}).scalar() or 0)
    if task_count:
        raise ValueError(f"该用户在本部门还有 {task_count} 个未完成待办，不能移除成员关系")
    db.execute(text("DELETE FROM user_departments WHERE id=:id"), {"id": row})
    record_activity(db, int(actor["user_pk"]), "membership_delete", department_id=int(department["id"]), detail={"target_user_id": user_id})
    return {"ok": True}
