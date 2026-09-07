from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.timezone import now_local
from .auth_service import hash_password, record_activity
from .permission_service import PermissionDenied, get_department


def _actor_admin_departments(db: Session, actor: dict) -> set[int]:
    if actor["is_system_admin"]:
        return {int(r[0]) for r in db.execute(text("SELECT id FROM departments WHERE status='enabled'")).all()}
    rows = db.execute(
        text("SELECT department_id FROM user_departments WHERE user_pk=:uid AND role='dept_admin' AND status='enabled'"),
        {"uid": actor["user_pk"]},
    ).all()
    return {int(r[0]) for r in rows}


def assert_can_admin_department(db: Session, actor: dict, department_code: str) -> dict:
    department = get_department(db, department_code)
    if actor["is_system_admin"]:
        return department
    if int(department["id"]) not in _actor_admin_departments(db, actor):
        raise PermissionDenied("只能管理自己担任部门管理员的部门")
    return department


def _target_membership(db: Session, target_pk: int, department_id: int) -> dict | None:
    row = db.execute(text("SELECT role,status FROM user_departments WHERE user_pk=:u AND department_id=:d"), {"u": target_pk, "d": department_id}).mappings().first()
    return dict(row) if row else None


def _target_user(db: Session, user_id: str) -> dict:
    row = db.execute(text("SELECT id,user_id,username,is_system_admin,status,last_login_time,last_active_time,login_count,created_at FROM users WHERE user_id=:uid"), {"uid": user_id}).mappings().first()
    if not row:
        raise LookupError("用户不存在")
    return dict(row)


def _target_has_external_membership(db: Session, target_pk: int, allowed_department_ids: set[int]) -> bool:
    if not allowed_department_ids:
        return bool(db.execute(text("SELECT COUNT(*) FROM user_departments WHERE user_pk=:u AND status='enabled'"), {"u": target_pk}).scalar())
    placeholders = ",".join(str(int(x)) for x in sorted(allowed_department_ids))
    count = db.execute(text(f"SELECT COUNT(*) FROM user_departments WHERE user_pk=:u AND status='enabled' AND department_id NOT IN ({placeholders})"), {"u": target_pk}).scalar()
    return bool(count)


def list_users(db: Session, actor: dict, department_code: str, *, search: str = "", role: str = "", membership_status: str = "") -> dict:
    department = assert_can_admin_department(db, actor, department_code)
    params = {"did": department["id"], "search": f"%{search.strip()}%"}
    where = ["ud.department_id=:did"]
    if search.strip(): where.append("(u.user_id LIKE :search OR u.username LIKE :search)")
    if role: where.append("ud.role=:role"); params["role"] = role
    if membership_status: where.append("ud.status=:mstatus"); params["mstatus"] = membership_status
    rows = db.execute(text(f"""
        SELECT u.id AS user_pk,u.user_id,u.username,u.is_system_admin,u.status AS account_status,
               u.last_login_time,u.last_active_time,u.login_count,u.created_at,
               ud.role,ud.status AS membership_status
        FROM users u JOIN user_departments ud ON ud.user_pk=u.id
        WHERE {' AND '.join(where)}
        ORDER BY CASE ud.role WHEN 'dept_admin' THEN 0 ELSE 1 END,u.username
    """), params).mappings().all()
    now = now_local()
    items=[]
    for r in rows:
        x=dict(r)
        last=x.get("last_active_time")
        minutes=(now-last).total_seconds()/60 if last else 10**9
        x["presence"] = "online" if minutes <= 10 else "recent" if minutes <= 1440 else "inactive" if minutes > 43200 else "offline"
        x["can_edit"] = bool(actor["is_system_admin"] or (not x["is_system_admin"] and x["role"] == "member"))
        items.append(x)
    return {"department": department, "items": items}


def user_detail(db: Session, actor: dict, department_code: str, user_id: str) -> dict:
    department=assert_can_admin_department(db,actor,department_code)
    target=_target_user(db,user_id)
    membership=_target_membership(db,target["id"],department["id"])
    if not membership and not actor["is_system_admin"]: raise PermissionDenied("无权查看该用户")
    if actor["is_system_admin"]:
        memberships=db.execute(text("""
          SELECT d.code,d.name,ud.role,ud.status FROM user_departments ud JOIN departments d ON d.id=ud.department_id
          WHERE ud.user_pk=:u ORDER BY d.name
        """),{"u":target["id"]}).mappings().all()
    else:
        memberships=[{"code":department["code"],"name":department["name"],**membership}] if membership else []
    logs=db.execute(text("""
      SELECT action_type,action_detail,created_at FROM activity_logs WHERE user_pk=:u ORDER BY id DESC LIMIT 30
    """),{"u":target["id"]}).mappings().all()
    return {"user":target,"memberships":[dict(x) for x in memberships],"recent_activity":[dict(x) for x in logs]}


def create_user(db: Session, actor: dict, department_code: str, *, user_id: str, username: str, password: str, role: str = "member") -> dict:
    department=assert_can_admin_department(db,actor,department_code)
    if role not in {"member","dept_admin"}: raise ValueError("角色无效")
    if not actor["is_system_admin"] and role == "dept_admin":
        raise PermissionDenied("部门管理员不能创建部门管理员；仅系统管理员可授予 dept_admin 角色")
    try:
        result=db.execute(text("""
          INSERT INTO users(user_id,username,password_hash,status) VALUES(:uid,:username,:password_hash,'enabled')
        """),{"uid":user_id.strip(),"username":username.strip(),"password_hash":hash_password(password)})
        pk=int(result.lastrowid)
        db.execute(text("INSERT INTO user_departments(user_pk,department_id,role,status) VALUES(:u,:d,:role,'enabled')"),{"u":pk,"d":department["id"],"role":role})
        record_activity(db,int(actor["user_pk"]),"user_create",department_id=int(department["id"]),detail={"target_user_id":user_id,"role":role})
        return _target_user(db,user_id)
    except IntegrityError as exc:
        db.rollback(); raise ValueError("user_id 或用户名已存在") from exc


def update_user(db: Session, actor: dict, department_code: str, user_id: str, *, username: str | None = None, password: str | None = None, account_status: str | None = None, membership_status: str | None = None, role: str | None = None) -> dict:
    department=assert_can_admin_department(db,actor,department_code)
    target=_target_user(db,user_id)
    membership=_target_membership(db,target["id"],department["id"])
    if not membership: raise PermissionDenied("目标用户不属于当前部门")
    if not actor["is_system_admin"]:
        if target["is_system_admin"] or membership["role"] != "member": raise PermissionDenied("部门管理员只能管理本部门普通用户")
        # 多部门用户的用户名/密码属于全局身份。为防止影响其它部门，存在外部有效成员关系时禁止修改全局身份。
        managed=_actor_admin_departments(db,actor)
        if (username is not None or password) and _target_has_external_membership(db,target["id"],managed):
            raise PermissionDenied("该用户同时属于其他部门；用户名/密码属于全局身份，请由系统管理员修改")
        if account_status is not None: raise PermissionDenied("部门管理员不能停用全局账号；请修改当前部门成员状态")
        if role is not None and role != "member": raise PermissionDenied("部门管理员不能授予部门管理员权限")
    sets=[];params={"pk":target["id"]}
    if username is not None:
        sets.append("username=:username");params["username"]=username.strip()
    if password:
        sets.append("password_hash=:password_hash");params["password_hash"]=hash_password(password)
    if account_status is not None:
        if account_status not in {"enabled","disabled"}: raise ValueError("账号状态无效")
        sets.append("status=:status");params["status"]=account_status
    try:
        if sets: db.execute(text("UPDATE users SET "+",".join(sets)+" WHERE id=:pk"),params)
        msets=[];mparams={"u":target["id"],"d":department["id"]}
        if membership_status is not None:
            if membership_status not in {"enabled","disabled"}: raise ValueError("成员状态无效")
            msets.append("status=:ms");mparams["ms"]=membership_status
        if role is not None:
            if role not in {"member","dept_admin"}: raise ValueError("角色无效")
            msets.append("role=:role");mparams["role"]=role
        if msets: db.execute(text("UPDATE user_departments SET "+",".join(msets)+" WHERE user_pk=:u AND department_id=:d"),mparams)
        record_activity(db,int(actor["user_pk"]),"user_update",department_id=int(department["id"]),detail={"target_user_id":user_id})
        return user_detail(db,actor,department_code,user_id)
    except IntegrityError as exc:
        db.rollback(); raise ValueError("用户名已存在") from exc


def activity_summary(db: Session, actor: dict, department_code: str) -> dict:
    department=assert_can_admin_department(db,actor,department_code)
    rows=db.execute(text("""
      SELECT u.user_id,u.username,u.last_login_time,u.last_active_time,u.login_count,ud.role,
        (SELECT COUNT(*) FROM activity_logs al WHERE al.user_pk=u.id AND al.created_at>=CURRENT_DATE) today_ops,
        (SELECT COUNT(*) FROM activity_logs al WHERE al.user_pk=u.id AND al.created_at>=DATE_SUB(CURRENT_DATE,INTERVAL 7 DAY)) week_ops,
        (SELECT COUNT(*) FROM todo_tasks t WHERE t.owner_user_pk=u.id AND t.department_id=:did AND t.status IN ('running','pending_delete','delete_rejected')) incomplete_tasks
      FROM users u JOIN user_departments ud ON ud.user_pk=u.id
      WHERE ud.department_id=:did AND ud.status='enabled'
      ORDER BY u.username
    """),{"did":department["id"]}).mappings().all()
    now=now_local();items=[]
    for r in rows:
        x=dict(r); la=x.get("last_active_time"); ll=x.get("last_login_time")
        mins=(now-la).total_seconds()/60 if la else 10**9
        x["presence"]="online" if mins<=10 else "recent" if mins<=1440 else "inactive" if mins>43200 else "offline"
        items.append(x)
    return {
      "department":department,
      "summary":{
        "today_login":sum(1 for x in items if x.get("last_login_time") and x["last_login_time"].date()==now.date()),
        "today_active":sum(1 for x in items if x.get("last_active_time") and x["last_active_time"].date()==now.date()),
        "no_login_7d":sum(1 for x in items if not x.get("last_login_time") or (now-x["last_login_time"]).days>=7),
        "inactive_30d":sum(1 for x in items if not x.get("last_active_time") or (now-x["last_active_time"]).days>=30),
      },
      "items":items,
    }


def get_department_expiry_rule(db: Session, actor: dict, department_code: str) -> dict:
    department=assert_can_admin_department(db,actor,department_code)
    row=db.execute(text("""
      SELECT near_days,near_pct,warn_days,warn_pct,updated_at FROM expiry_rules
      WHERE scope_type='department' AND department_id=:did AND product_id IS NULL LIMIT 1
    """),{"did":department["id"]}).mappings().first()
    rule=dict(row) if row else {"near_days":30,"near_pct":10,"warn_days":90,"warn_pct":25,"updated_at":None}
    return {"department":department,"rule":rule,"priority":["product","department","global"]}


def save_department_expiry_rule(db: Session, actor: dict, department_code: str, *, near_days: int, near_pct: float, warn_days: int, warn_pct: float) -> dict:
    department=assert_can_admin_department(db,actor,department_code)
    if near_days < 0 or warn_days < 0 or not (0 <= near_pct <= 100) or not (0 <= warn_pct <= 100): raise ValueError("效期规则参数无效")
    if warn_days < near_days or warn_pct < near_pct: raise ValueError("预警阈值不能比临期阈值更严格")
    existing = db.execute(text("SELECT id FROM expiry_rules WHERE scope_type='department' AND department_id=:did AND product_id IS NULL ORDER BY id DESC LIMIT 1"), {"did": department["id"]}).scalar()
    params={"did":department["id"],"near_days":near_days,"near_pct":near_pct,"warn_days":warn_days,"warn_pct":warn_pct,"uid":actor["user_pk"]}
    if existing:
        params["id"]=existing
        db.execute(text("UPDATE expiry_rules SET near_days=:near_days,near_pct=:near_pct,warn_days=:warn_days,warn_pct=:warn_pct,updated_by=:uid WHERE id=:id"), params)
    else:
        db.execute(text("INSERT INTO expiry_rules(scope_type,department_id,product_id,near_days,near_pct,warn_days,warn_pct,updated_by) VALUES('department',:did,NULL,:near_days,:near_pct,:warn_days,:warn_pct,:uid)"), params)
    record_activity(db,int(actor["user_pk"]),"expiry_rule_update",department_id=int(department["id"]),detail={"near_days":near_days,"near_pct":near_pct,"warn_days":warn_days,"warn_pct":warn_pct})
    return get_department_expiry_rule(db,actor,department_code)


# Product categories are shared product-master metadata. Department admins can
# assign categories only for products visible in their managed department;
# dictionary changes remain system-admin-only because category names are global.
def _product_visibility_sql(actor: dict, department_id: int) -> tuple[str, dict]:
    if actor["is_system_admin"]:
        return "1=1", {}
    return (
        "(EXISTS (SELECT 1 FROM sales_daily sd WHERE sd.department_id=:product_department_id AND sd.product_id=p.id) "
        "OR EXISTS (SELECT 1 FROM inventory_batch ib WHERE ib.department_id=:product_department_id AND ib.product_id=p.id) "
        "OR EXISTS (SELECT 1 FROM aging_snapshot ag WHERE ag.department_id=:product_department_id AND ag.product_id=p.id) "
        "OR EXISTS (SELECT 1 FROM import_batches b WHERE b.department_id=:product_department_id AND b.id=p.import_batch_id))",
        {"product_department_id": department_id},
    )


def _category_ids(db: Session, category_ids: list[int] | tuple[int, ...]) -> list[int]:
    normalized = list(dict.fromkeys(int(x) for x in (category_ids or [])))
    if not normalized:
        return []
    placeholders = ",".join(f":category_{i}" for i in range(len(normalized)))
    rows = db.execute(text(f"SELECT id FROM product_categories WHERE id IN ({placeholders})"), {f"category_{i}": value for i, value in enumerate(normalized)}).scalars().all()
    found = {int(x) for x in rows}
    missing = [str(x) for x in normalized if x not in found]
    if missing:
        raise ValueError(f"商品分类不存在：{', '.join(missing)}")
    return normalized


def _category_names_by_product(db: Session, product_ids: list[int]) -> dict[int, list[dict]]:
    if not product_ids:
        return {}
    placeholders = ",".join(f":product_{i}" for i in range(len(product_ids)))
    rows = db.execute(text(f"""
        SELECT pcr.product_id, pc.id, pc.category_name
        FROM product_category_relations pcr
        JOIN product_categories pc ON pc.id=pcr.category_id
        WHERE pcr.product_id IN ({placeholders})
        ORDER BY pcr.product_id, pc.category_name
    """), {f"product_{i}": value for i, value in enumerate(product_ids)}).mappings().all()
    result: dict[int, list[dict]] = {}
    for row in rows:
        result.setdefault(int(row["product_id"]), []).append({"id": int(row["id"]), "name": row["category_name"]})
    return result


def list_product_category_admin(db: Session, actor: dict, department_code: str, *, search: str = "", category_id: int | None = None, page: int = 1, page_size: int = 25) -> dict:
    department = assert_can_admin_department(db, actor, department_code)
    page = max(1, int(page)); page_size = min(100, max(10, int(page_size)))
    scope_sql, params = _product_visibility_sql(actor, int(department["id"]))
    where = [scope_sql]
    for i, keyword in enumerate(x.strip().lower() for x in re.split(r"\s+", search or "") if x.strip()):
        key = f"product_search_{i}"; params[key] = f"%{keyword}%"
        where.append(f"(LOWER(p.merchant_code) LIKE :{key} OR LOWER(p.product_name) LIKE :{key} OR LOWER(COALESCE(p.spec,'')) LIKE :{key} OR LOWER(COALESCE(p.brand,'')) LIKE :{key})")
    if category_id is not None:
        params["category_id"] = int(category_id)
        where.append("EXISTS (SELECT 1 FROM product_category_relations fcr WHERE fcr.product_id=p.id AND fcr.category_id=:category_id)")
    where_sql = " AND ".join(where)
    total = int(db.execute(text(f"SELECT COUNT(*) FROM products p WHERE {where_sql}"), params).scalar() or 0)
    params.update({"limit": page_size, "offset": (page - 1) * page_size})
    rows = db.execute(text(f"""
        SELECT p.id,p.merchant_code,p.product_name,p.spec,p.brand,p.updated_at
        FROM products p WHERE {where_sql}
        ORDER BY p.product_name,p.merchant_code LIMIT :limit OFFSET :offset
    """), params).mappings().all()
    ids = [int(row["id"]) for row in rows]; category_map = _category_names_by_product(db, ids)
    items = [{"product_id": int(row["id"]), "sku": row["merchant_code"], "name": row["product_name"], "spec": row["spec"], "brand": row["brand"], "updated_at": row["updated_at"], "categories": category_map.get(int(row["id"]), [])} for row in rows]
    category_rows = db.execute(text("SELECT id,category_name FROM product_categories ORDER BY category_name")).mappings().all()
    return {"department": {"code": department["code"], "name": department["name"]}, "items": items, "total": total, "page": page, "page_size": page_size, "categories": [{"id": int(row["id"]), "name": row["category_name"]} for row in category_rows], "can_manage_dictionary": bool(actor["is_system_admin"])}


def create_product_category(db: Session, actor: dict, department_code: str, name: str) -> dict:
    department = assert_can_admin_department(db, actor, department_code)
    if not actor["is_system_admin"]:
        raise PermissionDenied("商品分类字典仅系统管理员可维护")
    clean_name = str(name or "").strip()
    if not clean_name or len(clean_name) > 100: raise ValueError("分类名称不能为空且不能超过 100 个字符")
    try:
        result = db.execute(text("INSERT INTO product_categories(category_name) VALUES(:name)"), {"name": clean_name})
        record_activity(db, int(actor["user_pk"]), "product_category_create", department_id=int(department["id"]), detail={"category_name": clean_name})
        return {"id": int(result.lastrowid), "name": clean_name}
    except IntegrityError as exc:
        db.rollback(); raise ValueError("商品分类名称已存在") from exc


def rename_product_category(db: Session, actor: dict, department_code: str, category_id: int, name: str) -> dict:
    department = assert_can_admin_department(db, actor, department_code)
    if not actor["is_system_admin"]: raise PermissionDenied("商品分类字典仅系统管理员可维护")
    clean_name = str(name or "").strip()
    if not clean_name or len(clean_name) > 100: raise ValueError("分类名称不能为空且不能超过 100 个字符")
    existing = db.execute(text("SELECT id,category_name FROM product_categories WHERE id=:id"), {"id": category_id}).mappings().first()
    if not existing: raise LookupError("商品分类不存在")
    try:
        db.execute(text("UPDATE product_categories SET category_name=:name WHERE id=:id"), {"name": clean_name, "id": category_id})
        record_activity(db, int(actor["user_pk"]), "product_category_rename", department_id=int(department["id"]), detail={"category_id": category_id, "before": existing["category_name"], "name": clean_name})
        return {"id": int(category_id), "name": clean_name}
    except IntegrityError as exc:
        db.rollback(); raise ValueError("商品分类名称已存在") from exc


def delete_product_category(db: Session, actor: dict, department_code: str, category_id: int) -> dict:
    department = assert_can_admin_department(db, actor, department_code)
    if not actor["is_system_admin"]: raise PermissionDenied("商品分类字典仅系统管理员可维护")
    existing = db.execute(text("SELECT id,category_name FROM product_categories WHERE id=:id"), {"id": category_id}).mappings().first()
    if not existing: raise LookupError("商品分类不存在")
    linked = int(db.execute(text("SELECT COUNT(*) FROM product_category_relations WHERE category_id=:id"), {"id": category_id}).scalar() or 0)
    if linked: raise ValueError(f"该分类仍关联 {linked} 个商品，请先清空商品关联后再删除")
    db.execute(text("DELETE FROM product_categories WHERE id=:id"), {"id": category_id})
    record_activity(db, int(actor["user_pk"]), "product_category_delete", department_id=int(department["id"]), detail={"category_id": category_id, "category_name": existing["category_name"]})
    return {"ok": True}


def _assert_visible_products(db: Session, actor: dict, department: dict, product_ids: list[int]) -> list[int]:
    normalized = list(dict.fromkeys(int(x) for x in (product_ids or [])))
    if not normalized: raise ValueError("至少选择一个商品")
    scope_sql, scope_params = _product_visibility_sql(actor, int(department["id"]))
    placeholders = ",".join(f":product_{i}" for i in range(len(normalized)))
    params = {**scope_params, **{f"product_{i}": value for i, value in enumerate(normalized)}}
    rows = db.execute(text(f"SELECT p.id FROM products p WHERE p.id IN ({placeholders}) AND {scope_sql}"), params).scalars().all()
    found = {int(x) for x in rows}; missing = [str(x) for x in normalized if x not in found]
    if missing: raise PermissionDenied(f"无权维护这些商品：{', '.join(missing)}")
    return normalized


def set_product_categories(db: Session, actor: dict, department_code: str, product_ids: list[int], category_ids: list[int]) -> dict:
    department = assert_can_admin_department(db, actor, department_code)
    product_ids = _assert_visible_products(db, actor, department, product_ids)
    category_ids = _category_ids(db, category_ids)
    placeholders = ",".join(f":product_{i}" for i in range(len(product_ids)))
    db.execute(text(f"DELETE FROM product_category_relations WHERE product_id IN ({placeholders})"), {f"product_{i}": value for i, value in enumerate(product_ids)})
    insert_sql = "INSERT OR IGNORE" if db.get_bind().dialect.name == "sqlite" else "INSERT IGNORE"
    for product_id in product_ids:
        for category_id in category_ids:
            db.execute(text(f"{insert_sql} INTO product_category_relations(product_id,category_id) VALUES(:product_id,:category_id)"), {"product_id": product_id, "category_id": category_id})
        names = db.execute(text("SELECT pc.category_name FROM product_categories pc JOIN product_category_relations pcr ON pcr.category_id=pc.id WHERE pcr.product_id=:product_id ORDER BY pc.category_name"), {"product_id": product_id}).scalars().all()
        db.execute(text("UPDATE products SET category=:category WHERE id=:product_id"), {"category": "、".join(str(x) for x in names) or None, "product_id": product_id})
    record_activity(db, int(actor["user_pk"]), "product_category_assign", department_id=int(department["id"]), detail={"product_ids": product_ids, "category_ids": category_ids})
    return {"ok": True, "product_ids": product_ids, "category_ids": category_ids}
