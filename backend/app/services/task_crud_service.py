from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth_service import record_activity
from .permission_service import PermissionDenied, assert_can_view_department, get_actor, get_department
from .task_service import completion_percent, task_start_date


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _round(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(_number(value), digits)


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _actor_role(db: Session, actor: dict[str, Any], department_id: int) -> str:
    if actor.get("is_system_admin"):
        return "system_admin"
    role = db.execute(
        text(
            """
            SELECT role FROM user_departments
            WHERE user_pk=:user_pk AND department_id=:department_id AND status='enabled'
            """
        ),
        {"user_pk": actor["id"], "department_id": department_id},
    ).scalar_one_or_none()
    if not role:
        raise PermissionDenied("无权访问目标部门")
    return str(role)


def _resolve_user(db: Session, user_id: str) -> dict[str, Any]:
    row = db.execute(
        text("SELECT id,user_id,username,is_system_admin,status FROM users WHERE user_id=:user_id"),
        {"user_id": user_id},
    ).mappings().first()
    if not row:
        raise LookupError(f"用户不存在：{user_id}")
    if row["status"] != "enabled":
        raise ValueError(f"用户已停用：{user_id}")
    return dict(row)


def _membership_role(db: Session, user_pk: int, department_id: int) -> str | None:
    return db.execute(
        text(
            """
            SELECT role FROM user_departments
            WHERE user_pk=:user_pk AND department_id=:department_id AND status='enabled'
            """
        ),
        {"user_pk": user_pk, "department_id": department_id},
    ).scalar_one_or_none()


def _resolve_product(db: Session, merchant_code: str) -> dict[str, Any]:
    row = db.execute(
        text("SELECT id,merchant_code,product_name FROM products WHERE merchant_code=:code"),
        {"code": merchant_code},
    ).mappings().first()
    if not row:
        raise LookupError(f"商品不存在：{merchant_code}")
    return dict(row)


def _resolve_named_dimension(db: Session, table: str, name: str | None) -> int | None:
    if not name:
        return None
    if table not in {"shops", "warehouses"}:
        raise ValueError("非法维度")
    row = db.execute(text(f"SELECT id FROM {table} WHERE source_name=:name ORDER BY id LIMIT 1"), {"name": name}).scalar_one_or_none()
    if not row:
        raise LookupError(f"{('店铺' if table=='shops' else '仓库')}不存在：{name}")
    return int(row)


def _next_task_no(db: Session, assign_date: date) -> str:
    prefix = f"TD{assign_date.strftime('%Y%m%d')}"
    count = db.execute(
        text("SELECT COUNT(*) FROM todo_tasks WHERE task_no LIKE :prefix"),
        {"prefix": prefix + "%"},
    ).scalar_one()
    return f"{prefix}-{int(count)+1:03d}"


def _assert_can_assign(
    db: Session,
    actor: dict[str, Any],
    actor_role: str,
    department_id: int,
    owner: dict[str, Any],
) -> None:
    owner_role = _membership_role(db, int(owner["id"]), department_id)
    if not owner_role:
        raise PermissionDenied("负责人不属于目标部门")
    if actor_role == "system_admin":
        return
    if actor_role == "dept_admin":
        if int(owner["id"]) == int(actor["id"]):
            return
        if owner_role != "member":
            raise PermissionDenied("部门管理员只能给本部门普通用户下发任务，不能给其他部门管理员下发")
        return
    if int(owner["id"]) != int(actor["id"]):
        raise PermissionDenied("普通用户只能给自己创建待办")


def list_assignees(db: Session, actor_user_id: str, department_code: str) -> dict[str, Any]:
    actor, department = assert_can_view_department(db, actor_user_id, department_code)
    department_id = int(department["id"])
    role = _actor_role(db, actor, department_id)
    rows = db.execute(
        text(
            """
            SELECT u.id,u.user_id,u.username,ud.role
            FROM user_departments ud JOIN users u ON u.id=ud.user_pk
            WHERE ud.department_id=:department_id AND ud.status='enabled' AND u.status='enabled'
            ORDER BY CASE WHEN u.id=:actor_pk THEN 0 ELSE 1 END,ud.role,u.username
            """
        ),
        {"department_id": department_id, "actor_pk": actor["id"]},
    ).mappings().all()
    allowed = []
    for row in rows:
        if role == "system_admin":
            ok = True
        elif role == "dept_admin":
            ok = int(row["id"]) == int(actor["id"]) or row["role"] == "member"
        else:
            ok = int(row["id"]) == int(actor["id"])
        if ok:
            allowed.append({"user_id": row["user_id"], "username": row["username"], "role": row["role"]})
    return {"actor_role": role, "rows": allowed}


def create_task(
    db: Session,
    *,
    actor_user_id: str,
    department_code: str,
    merchant_code: str,
    owner_user_id: str,
    target_qty: float | None,
    assign_date: date,
    manager_note: str,
    shop_name: str | None = None,
    warehouse_name: str | None = None,
) -> dict[str, Any]:
    actor, department = assert_can_view_department(db, actor_user_id, department_code)
    department_id = int(department["id"])
    actor_role = _actor_role(db, actor, department_id)
    owner = _resolve_user(db, owner_user_id)
    _assert_can_assign(db, actor, actor_role, department_id, owner)
    product = _resolve_product(db, merchant_code)
    shop_id = _resolve_named_dimension(db, "shops", shop_name)
    warehouse_id = _resolve_named_dimension(db, "warehouses", warehouse_name)
    start = task_start_date(assign_date)
    task_no = _next_task_no(db, assign_date)
    db.execute(
        text(
            """
            INSERT INTO todo_tasks(
              task_no,department_id,product_id,owner_user_pk,creator_user_pk,
              warehouse_id,shop_id,target_qty,assign_date,start_date,manager_note,status
            ) VALUES(
              :task_no,:department_id,:product_id,:owner_user_pk,:creator_user_pk,
              :warehouse_id,:shop_id,:target_qty,:assign_date,:start_date,:manager_note,'running'
            )
            """
        ),
        {
            "task_no": task_no,
            "department_id": department_id,
            "product_id": product["id"],
            "owner_user_pk": owner["id"],
            "creator_user_pk": actor["id"],
            "warehouse_id": warehouse_id,
            "shop_id": shop_id,
            "target_qty": target_qty,
            "assign_date": assign_date,
            "start_date": start,
            "manager_note": manager_note.strip() or None,
        },
    )
    db.execute(
        text(
            """
            INSERT INTO activity_logs(user_pk,department_id,action_type,action_detail)
            VALUES(:user_pk,:department_id,'task_create',JSON_OBJECT('task_no',:task_no,'owner_user_id',:owner_user_id,'sku',:sku))
            """
        ),
        {"user_pk": actor["id"], "department_id": department_id, "task_no": task_no, "owner_user_id": owner_user_id, "sku": merchant_code},
    )
    db.commit()
    return {"created": True, "task_no": task_no, "start_date": start.isoformat()}


def _latest_sales_date(db: Session, department_id: int) -> date | None:
    return db.execute(
        text("SELECT MAX(business_date) FROM sales_daily WHERE department_id=:department_id"),
        {"department_id": department_id},
    ).scalar_one_or_none()


def task_window_end(start: date, days: int) -> date:
    return start + timedelta(days=days - 1)


def task_window_complete(start: date, days: int, latest_sales_date: date | None) -> bool:
    return bool(latest_sales_date and latest_sales_date >= task_window_end(start, days))


def _task_metrics(db: Session, task: dict[str, Any]) -> dict[str, Any]:
    latest = _latest_sales_date(db, int(task["department_id"]))
    start = task["start_date"]
    if not latest or latest < start:
        return {
            "latest_sales_date": _date_text(latest), "actual_qty_to_date": 0.0, "completion_pct": 0.0,
            "sales7": 0.0, "sales14": 0.0, "sales30": 0.0,
            "avg_price7": None, "avg_price14": None, "avg_price30": None,
            "window_complete": {"7d": False, "14d": False, "30d": False},
        }
    params = {
        "department_id": task["department_id"], "product_id": task["product_id"],
        "start": start, "end": latest,
        "d7": task_window_end(start, 7), "d14": task_window_end(start, 14), "d30": task_window_end(start, 30),
    }
    clauses = []
    if task.get("shop_id"):
        params["shop_id"] = task["shop_id"]
        clauses.append("sd.shop_id=:shop_id")
    if task.get("warehouse_id"):
        params["warehouse_id"] = task["warehouse_id"]
        clauses.append("sd.warehouse_id=:warehouse_id")
    extra = (" AND " + " AND ".join(clauses)) if clauses else ""
    row = db.execute(
        text(
            f"""
            SELECT
              SUM(sd.sales_qty) AS actual_qty,
              SUM(CASE WHEN sd.business_date<=:d7 THEN sd.sales_qty ELSE 0 END) AS sales7,
              SUM(CASE WHEN sd.business_date<=:d14 THEN sd.sales_qty ELSE 0 END) AS sales14,
              SUM(CASE WHEN sd.business_date<=:d30 THEN sd.sales_qty ELSE 0 END) AS sales30,
              SUM(CASE WHEN sd.business_date<=:d7 AND sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty*sd.avg_price ELSE 0 END) AS rev7,
              SUM(CASE WHEN sd.business_date<=:d7 AND sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty ELSE 0 END) AS qty7,
              SUM(CASE WHEN sd.business_date<=:d14 AND sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty*sd.avg_price ELSE 0 END) AS rev14,
              SUM(CASE WHEN sd.business_date<=:d14 AND sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty ELSE 0 END) AS qty14,
              SUM(CASE WHEN sd.business_date<=:d30 AND sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty*sd.avg_price ELSE 0 END) AS rev30,
              SUM(CASE WHEN sd.business_date<=:d30 AND sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty ELSE 0 END) AS qty30
            FROM sales_daily sd
            WHERE sd.department_id=:department_id AND sd.product_id=:product_id
              AND sd.business_date BETWEEN :start AND :end {extra}
            """
        ), params,
    ).mappings().one()
    single_shop = bool(task.get("shop_id"))
    def price(rev, qty):
        q = _number(qty)
        return round(_number(rev)/q, 2) if single_shop and q > 0 else None
    actual = _number(row["actual_qty"])
    target = _number(task.get("target_qty"))
    return {
        "latest_sales_date": latest.isoformat(),
        "actual_qty_to_date": _round(actual, 2),
        "completion_pct": round(completion_percent(actual, target), 2) if target > 0 else 0.0,
        "sales7": _round(row["sales7"], 2), "sales14": _round(row["sales14"], 2), "sales30": _round(row["sales30"], 2),
        "avg_price7": price(row["rev7"], row["qty7"]), "avg_price14": price(row["rev14"], row["qty14"]), "avg_price30": price(row["rev30"], row["qty30"]),
        "window_complete": {
            "7d": task_window_complete(start, 7, latest),
            "14d": task_window_complete(start, 14, latest),
            "30d": task_window_complete(start, 30, latest),
        },
    }


def _task_base_rows(db: Session, department_id: int, where_sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT t.id,t.task_no,t.department_id,t.product_id,t.owner_user_pk,t.creator_user_pk,
                   t.warehouse_id,t.shop_id,t.target_qty,t.assign_date,t.start_date,t.manager_note,t.owner_note,t.status,
                   t.delete_requester_user_pk,t.delete_reason,t.delete_requested_at,t.created_at,t.updated_at,
                   p.merchant_code,p.product_name,
                   ou.user_id AS owner_user_id,ou.username AS owner_name,
                   cu.user_id AS creator_user_id,cu.username AS creator_name,
                   du.user_id AS delete_requester_user_id,du.username AS delete_requester_name,
                   s.source_name AS shop_name,w.source_name AS warehouse_name
            FROM todo_tasks t
            JOIN products p ON p.id=t.product_id
            JOIN users ou ON ou.id=t.owner_user_pk
            JOIN users cu ON cu.id=t.creator_user_pk
            LEFT JOIN users du ON du.id=t.delete_requester_user_pk
            LEFT JOIN shops s ON s.id=t.shop_id
            LEFT JOIN warehouses w ON w.id=t.warehouse_id
            WHERE t.department_id=:department_id {where_sql}
            ORDER BY CASE t.status WHEN 'pending_delete' THEN 0 WHEN 'running' THEN 1 WHEN 'delete_rejected' THEN 2 ELSE 3 END,
                     t.updated_at DESC,t.id DESC
            LIMIT 500
            """
        ),
        {"department_id": department_id, **params},
    ).mappings().all()
    return [dict(r) for r in rows]


def list_tasks(
    db: Session,
    *,
    actor_user_id: str,
    department_code: str,
    view: str = "mine",
    owner_user_id: str = "",
    status: str = "",
    product_search: str = "",
) -> dict[str, Any]:
    actor, department = assert_can_view_department(db, actor_user_id, department_code)
    department_id = int(department["id"])
    role = _actor_role(db, actor, department_id)
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if view == "mine":
        clauses.append("t.owner_user_pk=:actor_pk")
        params["actor_pk"] = actor["id"]
    elif view == "department":
        if role not in {"system_admin", "dept_admin"}:
            raise PermissionDenied("普通用户不能查看部门全部待办")
    elif view == "approval":
        if role not in {"system_admin", "dept_admin"}:
            raise PermissionDenied("普通用户不能查看删除审批")
        clauses.append("t.status='pending_delete'")
    else:
        raise ValueError("view 只能是 mine / department / approval")
    if owner_user_id:
        owner = _resolve_user(db, owner_user_id)
        clauses.append("t.owner_user_pk=:owner_pk")
        params["owner_pk"] = owner["id"]
    if status:
        clauses.append("t.status=:status")
        params["status"] = status
    if product_search.strip():
        params["product_search"] = f"%{product_search.strip().lower()}%"
        clauses.append("(LOWER(p.product_name) LIKE :product_search OR LOWER(p.merchant_code) LIKE :product_search)")
    where_sql = (" AND " + " AND ".join(clauses)) if clauses else ""
    rows = _task_base_rows(db, department_id, where_sql, params)
    public_rows = []
    for task in rows:
        metrics = _task_metrics(db, task)
        can_edit_note = int(task["owner_user_pk"]) == int(actor["id"])
        can_request_delete = can_edit_note and task["status"] in {"running", "delete_rejected"}
        can_withdraw = can_edit_note and task["status"] == "pending_delete" and int(task.get("delete_requester_user_pk") or 0) == int(actor["id"])
        can_decide = role in {"system_admin", "dept_admin"} and task["status"] == "pending_delete" and int(task.get("delete_requester_user_pk") or 0) != int(actor["id"])
        public_rows.append({
            "task_no": task["task_no"], "sku": task["merchant_code"], "product_name": task["product_name"],
            "owner": {"user_id": task["owner_user_id"], "username": task["owner_name"]},
            "creator": {"user_id": task["creator_user_id"], "username": task["creator_name"]},
            "shop_name": task["shop_name"], "warehouse_name": task["warehouse_name"],
            "target_qty": _round(task["target_qty"], 2) if task["target_qty"] is not None else None,
            "assign_date": _date_text(task["assign_date"]), "start_date": _date_text(task["start_date"]),
            "manager_note": task["manager_note"] or "", "owner_note": task["owner_note"] or "", "status": task["status"],
            "delete_request": None if task["status"] != "pending_delete" else {
                "requester_user_id": task["delete_requester_user_id"], "requester_name": task["delete_requester_name"],
                "reason": task["delete_reason"] or "", "requested_at": str(task["delete_requested_at"] or ""),
            },
            "permissions": {"can_edit_owner_note": can_edit_note, "can_request_delete": can_request_delete, "can_withdraw_delete": can_withdraw, "can_decide_delete": can_decide},
            "metrics": metrics,
        })
    mine_count = db.execute(
        text("SELECT COUNT(*) FROM todo_tasks WHERE department_id=:department_id AND owner_user_pk=:actor_pk AND status<>'done'"),
        {"department_id": department_id, "actor_pk": actor["id"]},
    ).scalar_one()
    approval_count = 0
    if role in {"system_admin", "dept_admin"}:
        approval_count = db.execute(
            text("SELECT COUNT(*) FROM todo_tasks WHERE department_id=:department_id AND status='pending_delete'"),
            {"department_id": department_id},
        ).scalar_one()
    return {"meta": {"actor_role": role, "department": department, "mine_incomplete_count": int(mine_count), "approval_count": int(approval_count)}, "rows": public_rows}


def update_owner_note(db: Session, actor_user_id: str, task_no: str, note: str) -> dict[str, Any]:
    actor = get_actor(db, actor_user_id)
    row = db.execute(text("SELECT id,department_id,owner_user_pk FROM todo_tasks WHERE task_no=:task_no"), {"task_no": task_no}).mappings().first()
    if not row:
        raise LookupError("待办不存在")
    if int(row["owner_user_pk"]) != int(actor["id"]):
        raise PermissionDenied("只有任务负责人本人可以修改个人备注")
    db.execute(text("UPDATE todo_tasks SET owner_note=:note WHERE id=:id"), {"note": note, "id": row["id"]})
    db.commit()
    record_activity(db,int(actor["id"]),"task_owner_note_update",department_id=int(row["department_id"]),detail={"task_no":task_no})
    return {"saved": True, "task_no": task_no, "owner_note": note}


def request_delete(db: Session, actor_user_id: str, task_no: str, reason: str) -> dict[str, Any]:
    actor = get_actor(db, actor_user_id)
    row = db.execute(text("SELECT id,department_id,owner_user_pk,status FROM todo_tasks WHERE task_no=:task_no"), {"task_no": task_no}).mappings().first()
    if not row:
        raise LookupError("待办不存在")
    if int(row["owner_user_pk"]) != int(actor["id"]):
        raise PermissionDenied("只有任务负责人可以申请删除待办")
    if row["status"] not in {"running", "delete_rejected"}:
        raise ValueError("当前状态不能申请删除")
    db.execute(
        text(
            """
            UPDATE todo_tasks SET status='pending_delete',delete_requester_user_pk=:actor_pk,
              delete_reason=:reason,delete_requested_at=CURRENT_TIMESTAMP,delete_approver_user_pk=NULL,delete_decided_at=NULL
            WHERE id=:id
            """
        ),
        {"actor_pk": actor["id"], "reason": reason.strip() or None, "id": row["id"]},
    )
    db.commit()
    record_activity(db,int(actor["id"]),"task_delete_request",department_id=int(row["department_id"]),detail={"task_no":task_no,"reason":reason})
    return {"requested": True, "task_no": task_no}


def withdraw_delete(db: Session, actor_user_id: str, task_no: str) -> dict[str, Any]:
    actor = get_actor(db, actor_user_id)
    row = db.execute(
        text("SELECT id,department_id,delete_requester_user_pk,status FROM todo_tasks WHERE task_no=:task_no"),
        {"task_no": task_no},
    ).mappings().first()
    if not row:
        raise LookupError("待办不存在")
    if row["status"] != "pending_delete" or int(row.get("delete_requester_user_pk") or 0) != int(actor["id"]):
        raise PermissionDenied("只能撤回自己的待删除申请")
    db.execute(
        text(
            """
            UPDATE todo_tasks SET status='running',delete_requester_user_pk=NULL,delete_reason=NULL,
              delete_requested_at=NULL,delete_approver_user_pk=NULL,delete_decided_at=NULL WHERE id=:id
            """
        ), {"id": row["id"]},
    )
    db.commit()
    record_activity(db,int(actor["id"]),"task_delete_withdraw",department_id=int(row["department_id"]),detail={"task_no":task_no})
    return {"withdrawn": True, "task_no": task_no}


def decide_delete(db: Session, actor_user_id: str, task_no: str, decision: str) -> dict[str, Any]:
    actor = get_actor(db, actor_user_id)
    row = db.execute(
        text("SELECT id,department_id,delete_requester_user_pk,status FROM todo_tasks WHERE task_no=:task_no"),
        {"task_no": task_no},
    ).mappings().first()
    if not row:
        raise LookupError("待办不存在")
    if row["status"] != "pending_delete":
        raise ValueError("该待办当前不在删除审批状态")
    role = _actor_role(db, actor, int(row["department_id"]))
    if role not in {"system_admin", "dept_admin"}:
        raise PermissionDenied("只有系统管理员或本部门部门管理员可以审批删除")
    if int(row.get("delete_requester_user_pk") or 0) == int(actor["id"]):
        raise PermissionDenied("自己的删除申请不能由自己审批")
    if decision not in {"approve", "reject"}:
        raise ValueError("decision 只能是 approve / reject")
    if decision == "approve":
        db.execute(
            text(
                """
                INSERT INTO activity_logs(user_pk,department_id,action_type,action_detail)
                VALUES(:user_pk,:department_id,'task_delete_approve',JSON_OBJECT('task_no',:task_no))
                """
            ), {"user_pk": actor["id"], "department_id": row["department_id"], "task_no": task_no},
        )
        db.execute(text("DELETE FROM todo_tasks WHERE id=:id"), {"id": row["id"]})
        db.commit()
        return {"approved": True, "deleted": True, "task_no": task_no}
    db.execute(
        text(
            """
            UPDATE todo_tasks SET status='delete_rejected',delete_approver_user_pk=:actor_pk,
              delete_decided_at=CURRENT_TIMESTAMP WHERE id=:id
            """
        ), {"actor_pk": actor["id"], "id": row["id"]},
    )
    db.commit()
    record_activity(db,int(actor["id"]),"task_delete_reject",department_id=int(row["department_id"]),detail={"task_no":task_no})
    return {"rejected": True, "task_no": task_no}
