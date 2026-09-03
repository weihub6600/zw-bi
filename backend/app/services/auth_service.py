from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..core.timezone import now_local

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 310_000


class AuthenticationError(PermissionError):
    pass


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, iterations: int = PASSWORD_ITERATIONS, salt: bytes | None = None) -> str:
    if not password or len(password) < 8:
        raise ValueError("密码至少需要 8 个字符")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PASSWORD_ALGORITHM}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iteration_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iteration_text)
        salt = _unb64(salt_text)
        expected = _unb64(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return now_local()


def log_login(db: Session, *, user_pk: int | None, login_key: str, result: str, ip_address: str | None, user_agent: str | None) -> None:
    db.execute(
        text(
            """
            INSERT INTO login_logs(user_pk,login_key,login_time,ip_address,user_agent,result)
            VALUES(:user_pk,:login_key,CURRENT_TIMESTAMP,:ip_address,:user_agent,:result)
            """
        ),
        {"user_pk": user_pk, "login_key": login_key[:128], "ip_address": ip_address, "user_agent": (user_agent or "")[:1000], "result": result},
    )


def authenticate(db: Session, login_key: str, password: str, *, ip_address: str | None = None, user_agent: str | None = None) -> dict:
    key = (login_key or "").strip()
    row = db.execute(
        text(
            """
            SELECT id,user_id,username,password_hash,is_system_admin,status
            FROM users
            WHERE user_id=:key OR username=:key
            LIMIT 1
            """
        ),
        {"key": key},
    ).mappings().first()
    user_pk = int(row["id"]) if row else None
    if not row or row["status"] != "enabled" or not verify_password(password, row["password_hash"]):
        log_login(db, user_pk=user_pk, login_key=key, result="failed", ip_address=ip_address, user_agent=user_agent)
        db.commit()
        raise AuthenticationError("账号或密码错误")

    now = _now()
    db.execute(
        text(
            """
            UPDATE users
            SET last_login_time=:now,last_active_time=:now,login_count=login_count+1
            WHERE id=:id
            """
        ),
        {"now": now, "id": row["id"]},
    )
    log_login(db, user_pk=user_pk, login_key=key, result="success", ip_address=ip_address, user_agent=user_agent)
    db.commit()
    return {k: row[k] for k in ("id", "user_id", "username", "is_system_admin", "status")}


def create_session(db: Session, user_pk: int, *, remember: bool, session_hours: int, remember_days: int, ip_address: str | None = None, user_agent: str | None = None) -> tuple[str, datetime]:
    raw = secrets.token_urlsafe(48)
    expires_at = _now() + (timedelta(days=remember_days) if remember else timedelta(hours=session_hours))
    db.execute(
        text(
            """
            INSERT INTO auth_sessions(user_pk,session_token_hash,expires_at,last_seen_at,ip_address,user_agent)
            VALUES(:user_pk,:token_hash,:expires_at,CURRENT_TIMESTAMP,:ip_address,:user_agent)
            """
        ),
        {
            "user_pk": user_pk,
            "token_hash": token_hash(raw),
            "expires_at": expires_at,
            "ip_address": ip_address,
            "user_agent": (user_agent or "")[:1000],
        },
    )
    db.execute(text("DELETE FROM auth_sessions WHERE expires_at < CURRENT_TIMESTAMP"))
    db.commit()
    return raw, expires_at


def resolve_session(db: Session, raw_token: str | None, *, touch: bool = True) -> dict | None:
    if not raw_token:
        return None
    row = db.execute(
        text(
            """
            SELECT s.id AS session_id,s.user_pk,s.expires_at,s.last_seen_at,
                   u.user_id,u.username,u.is_system_admin,u.status
            FROM auth_sessions s
            JOIN users u ON u.id=s.user_pk
            WHERE s.session_token_hash=:token_hash
              AND s.expires_at > CURRENT_TIMESTAMP
              AND u.status='enabled'
            LIMIT 1
            """
        ),
        {"token_hash": token_hash(raw_token)},
    ).mappings().first()
    if not row:
        return None
    result = dict(row)
    if touch:
        now = _now()
        last_seen = row["last_seen_at"]
        if last_seen is None or (now - last_seen).total_seconds() >= 300:
            db.execute(text("UPDATE auth_sessions SET last_seen_at=:now WHERE id=:id"), {"now": now, "id": row["session_id"]})
            db.execute(text("UPDATE users SET last_active_time=:now WHERE id=:id"), {"now": now, "id": row["user_pk"]})
            db.commit()
            result["last_seen_at"] = now
    return result


def revoke_session(db: Session, raw_token: str | None) -> None:
    if raw_token:
        db.execute(text("DELETE FROM auth_sessions WHERE session_token_hash=:token_hash"), {"token_hash": token_hash(raw_token)})
        db.commit()


def heartbeat(db: Session, session_id: int, user_pk: int) -> None:
    now = _now()
    db.execute(text("UPDATE auth_sessions SET last_seen_at=:now WHERE id=:sid"), {"now": now, "sid": session_id})
    db.execute(text("UPDATE users SET last_active_time=:now WHERE id=:uid"), {"now": now, "uid": user_pk})
    db.commit()


def memberships_for_user(db: Session, user_pk: int) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT d.id AS department_id,d.code,d.name,ud.role,ud.status
            FROM user_departments ud
            JOIN departments d ON d.id=ud.department_id
            WHERE ud.user_pk=:user_pk AND ud.status='enabled' AND d.status='enabled'
            ORDER BY d.name
            """
        ),
        {"user_pk": user_pk},
    ).mappings().all()
    return [dict(r) for r in rows]


def all_enabled_departments(db: Session) -> list[dict]:
    rows = db.execute(text("SELECT id AS department_id,code,name,'system_admin' AS role,'enabled' AS status FROM departments WHERE status='enabled' ORDER BY name")).mappings().all()
    return [dict(r) for r in rows]


def record_activity(db: Session, user_pk: int, action_type: str, *, department_id: int | None = None, detail: dict | None = None) -> None:
    import json
    db.execute(
        text("INSERT INTO activity_logs(user_pk,department_id,action_type,action_detail) VALUES(:user_pk,:department_id,:action_type,:detail)"),
        {"user_pk": user_pk, "department_id": department_id, "action_type": action_type[:64], "detail": json.dumps(detail or {}, ensure_ascii=False)},
    )
    db.commit()
