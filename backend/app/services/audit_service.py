from __future__ import annotations

from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session

from .permission_service import PermissionDenied
from .admin_service import assert_can_admin_department


def list_audit_logs(db: Session, actor: dict, *, department_code: str = "", user_id: str = "", action_type: str = "", days: int = 7, limit: int = 200) -> dict:
    limit=max(1,min(int(limit),500)); days=max(1,min(int(days),365))
    params={"limit":limit}
    where=[f"al.created_at>=DATE_SUB(CURRENT_TIMESTAMP,INTERVAL {days} DAY)"]
    department=None
    if department_code:
        department=assert_can_admin_department(db,actor,department_code)
        where.append("al.department_id=:did");params["did"]=department["id"]
    elif not actor.get("is_system_admin"):
        rows=db.execute(text("SELECT department_id FROM user_departments WHERE user_pk=:u AND role='dept_admin' AND status='enabled'"),{"u":actor["user_pk"]}).all()
        ids=[str(int(r[0])) for r in rows]
        if not ids: raise PermissionDenied("无权查看操作审计")
        where.append(f"al.department_id IN ({','.join(ids)})")
    if user_id.strip(): where.append("u.user_id=:user_id");params["user_id"]=user_id.strip()
    if action_type.strip(): where.append("al.action_type=:action");params["action"]=action_type.strip()
    rows=db.execute(text(f"""
      SELECT al.id,al.created_at,al.action_type,al.action_detail,
             u.user_id,u.username,d.code AS department_code,d.name AS department_name
      FROM activity_logs al JOIN users u ON u.id=al.user_pk
      LEFT JOIN departments d ON d.id=al.department_id
      WHERE {' AND '.join(where)}
      ORDER BY al.id DESC LIMIT :limit
    """),params).mappings().all()
    actions=db.execute(text("SELECT DISTINCT action_type FROM activity_logs ORDER BY action_type")).scalars().all()
    login_items=[]
    if actor.get("is_system_admin"):
        login_rows=db.execute(text(f"""
          SELECT ll.id,ll.login_key,ll.login_time,ll.ip_address,ll.user_agent,ll.result,u.user_id,u.username
          FROM login_logs ll LEFT JOIN users u ON u.id=ll.user_pk
          WHERE ll.login_time>=DATE_SUB(CURRENT_TIMESTAMP,INTERVAL {days} DAY)
          ORDER BY ll.id DESC LIMIT 200
        """)).mappings().all()
        login_items=[dict(r) for r in login_rows]
    return {"department":department,"items":[dict(r) for r in rows],"login_items":login_items,"actions":list(actions),"range_days":days}
