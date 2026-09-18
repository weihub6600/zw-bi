from pathlib import Path
import unittest
from unittest import mock
from fastapi import HTTPException, Response
from starlette.requests import Request
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.core.config import settings, validate_runtime_security
from app.routes.auth import LoginBody, _client, login
from app.services.auth_service import (
    AuthenticationError, LoginRateLimitError, authenticate, create_session,
    hash_password, login_failure_limiter, resolve_session, token_hash, verify_password,
)
from app.services.admin_service import create_user, update_user
from app.services.permission_service import PermissionDenied


def _admin_schema_engine():
    """最小化的用户/部门/成员/审计表结构，供 admin_service 测试使用。"""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE departments(id INTEGER PRIMARY KEY,code TEXT UNIQUE,name TEXT UNIQUE,status TEXT)"))
        conn.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,user_id TEXT UNIQUE,username TEXT UNIQUE,password_hash TEXT,is_system_admin INTEGER,status TEXT,last_login_time DATETIME,last_active_time DATETIME,login_count INTEGER DEFAULT 0,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
        conn.execute(text("CREATE TABLE user_departments(id INTEGER PRIMARY KEY,user_pk INTEGER,department_id INTEGER,role TEXT,status TEXT)"))
        conn.execute(text("CREATE TABLE activity_logs(id INTEGER PRIMARY KEY,user_pk INTEGER,department_id INTEGER,action_type TEXT,action_detail TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
        conn.execute(text("CREATE TABLE auth_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_pk INTEGER,session_token_hash TEXT UNIQUE,expires_at DATETIME,last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,ip_address TEXT,user_agent TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO departments(id,code,name,status) VALUES(1,'B2C','B2C事业部','enabled')"))
        # 部门管理员（非系统管理员）
        conn.execute(text("INSERT INTO users(id,user_id,username,password_hash,is_system_admin,status) VALUES(10,'DEPADMIN','dept_admin',:pw,0,'enabled')"), {"pw": hash_password("StrongPass123!", iterations=10_000, salt=b"0123456789abcdef")})
        conn.execute(text("INSERT INTO user_departments(user_pk,department_id,role,status) VALUES(10,1,'dept_admin','enabled')"))
    return engine


class V154AdminCreateUserEscalationTests(unittest.TestCase):
    def _dept_admin_actor(self):
        # 模拟 require_actor 返回的会话 actor：is_system_admin=False，user_pk=10
        return {"user_pk": 10, "user_id": "DEPADMIN", "username": "dept_admin", "is_system_admin": False, "status": "enabled"}

    def test_dept_admin_create_user_with_dept_admin_role_is_rejected(self):
        engine = _admin_schema_engine()
        with Session(engine) as db:
            with self.assertRaises(PermissionDenied):
                create_user(
                    db, self._dept_admin_actor(), "B2C",
                    user_id="U100", username="newuser", password="StrongPass123!", role="dept_admin",
                )

    def test_dept_admin_create_user_with_member_role_succeeds(self):
        engine = _admin_schema_engine()
        with Session(engine) as db:
            user = create_user(
                db, self._dept_admin_actor(), "B2C",
                user_id="U100", username="newuser", password="StrongPass123!", role="member",
            )
            self.assertEqual(user["user_id"], "U100")
            role = db.execute(text("SELECT role FROM user_departments WHERE user_pk=:u AND department_id=1"), {"u": user["id"]}).scalar_one()
            self.assertEqual(role, "member")

    def test_system_admin_create_user_with_dept_admin_role_succeeds(self):
        engine = _admin_schema_engine()
        sys_actor = {"user_pk": 1, "user_id": "SYS0001", "username": "admin", "is_system_admin": True, "status": "enabled"}
        with Session(engine) as db:
            user = create_user(
                db, sys_actor, "B2C",
                user_id="U200", username="newadmin", password="StrongPass123!", role="dept_admin",
            )
            self.assertEqual(user["user_id"], "U200")
            role = db.execute(text("SELECT role FROM user_departments WHERE user_pk=:u AND department_id=1"), {"u": user["id"]}).scalar_one()
            self.assertEqual(role, "dept_admin")


class V146AuthAdminTests(unittest.TestCase):
    def tearDown(self):
        login_failure_limiter.reset()

    def test_password_hash_roundtrip(self):
        encoded=hash_password("StrongPass123!",iterations=10_000,salt=b"0123456789abcdef")
        self.assertTrue(verify_password("StrongPass123!",encoded))
        self.assertFalse(verify_password("wrong-password",encoded))
        self.assertNotIn("StrongPass123!",encoded)
    def test_session_token_hash_is_sha256(self):
        self.assertEqual(len(token_hash("abc")),64)
        self.assertEqual(token_hash("abc"),token_hash("abc"))

    def test_auth_session_roundtrip_with_sqlite(self):
        engine=create_engine("sqlite+pysqlite:///:memory:",future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,user_id TEXT UNIQUE,username TEXT UNIQUE,password_hash TEXT,is_system_admin INTEGER,status TEXT,last_login_time DATETIME,last_active_time DATETIME,login_count INTEGER DEFAULT 0)"))
            conn.execute(text("CREATE TABLE login_logs(id INTEGER PRIMARY KEY,user_pk INTEGER,login_key TEXT,login_time DATETIME DEFAULT CURRENT_TIMESTAMP,ip_address TEXT,user_agent TEXT,result TEXT)"))
            conn.execute(text("CREATE TABLE auth_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_pk INTEGER,session_token_hash TEXT UNIQUE,expires_at DATETIME,last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,ip_address TEXT,user_agent TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
            conn.execute(text("INSERT INTO users(id,user_id,username,password_hash,is_system_admin,status) VALUES(1,'SYS0001','admin',:pw,1,'enabled')"), {"pw":hash_password("StrongPass123!",iterations=10_000,salt=b"0123456789abcdef")})
        with Session(engine) as db:
            user=authenticate(db,"SYS0001","StrongPass123!")
            raw,_=create_session(db,user["id"],remember=False,session_hours=12,remember_days=7)
            actor=resolve_session(db,raw,touch=False)
            self.assertEqual(actor["user_id"],"SYS0001")
            self.assertNotEqual(raw,token_hash(raw))

    def test_failed_login_is_limited_by_account_across_ips(self):
        engine=create_engine("sqlite+pysqlite:///:memory:",future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,user_id TEXT UNIQUE,username TEXT UNIQUE,password_hash TEXT,is_system_admin INTEGER,status TEXT,last_login_time DATETIME,last_active_time DATETIME,login_count INTEGER DEFAULT 0)"))
            conn.execute(text("CREATE TABLE login_logs(id INTEGER PRIMARY KEY,user_pk INTEGER,login_key TEXT,login_time DATETIME DEFAULT CURRENT_TIMESTAMP,ip_address TEXT,user_agent TEXT,result TEXT)"))
        with Session(engine) as db, mock.patch.object(settings, "login_rate_limit_attempts", 2):
            for ip in ("198.51.100.1", "198.51.100.2"):
                with self.assertRaises(AuthenticationError):
                    authenticate(db, "missing-user", "wrong-password", ip_address=ip)
            with self.assertRaises(LoginRateLimitError):
                authenticate(db, "missing-user", "wrong-password", ip_address="198.51.100.3")

    def test_login_error_does_not_reveal_account_existence(self):
        engine=create_engine("sqlite+pysqlite:///:memory:",future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,user_id TEXT UNIQUE,username TEXT UNIQUE,password_hash TEXT,is_system_admin INTEGER,status TEXT,last_login_time DATETIME,last_active_time DATETIME,login_count INTEGER DEFAULT 0)"))
            conn.execute(text("CREATE TABLE login_logs(id INTEGER PRIMARY KEY,user_pk INTEGER,login_key TEXT,login_time DATETIME DEFAULT CURRENT_TIMESTAMP,ip_address TEXT,user_agent TEXT,result TEXT)"))
            conn.execute(text("INSERT INTO users(id,user_id,username,password_hash,is_system_admin,status) VALUES(1,'KNOWN','known',:pw,0,'enabled')"), {"pw": hash_password("CorrectPass123!", iterations=10_000, salt=b"0123456789abcdef")})
        with Session(engine) as db:
            messages = []
            for account in ("KNOWN", "MISSING"):
                with self.assertRaises(AuthenticationError) as ctx:
                    authenticate(db, account, "wrong-password", ip_address=f"198.51.100.{len(messages) + 1}")
                messages.append(str(ctx.exception))
        self.assertEqual(messages, ["账号或密码错误", "账号或密码错误"])

    def test_failed_login_is_limited_by_ip_across_accounts(self):
        engine=create_engine("sqlite+pysqlite:///:memory:",future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,user_id TEXT UNIQUE,username TEXT UNIQUE,password_hash TEXT,is_system_admin INTEGER,status TEXT,last_login_time DATETIME,last_active_time DATETIME,login_count INTEGER DEFAULT 0)"))
            conn.execute(text("CREATE TABLE login_logs(id INTEGER PRIMARY KEY,user_pk INTEGER,login_key TEXT,login_time DATETIME DEFAULT CURRENT_TIMESTAMP,ip_address TEXT,user_agent TEXT,result TEXT)"))
        with Session(engine) as db, mock.patch.object(settings, "login_rate_limit_attempts", 10), mock.patch.object(settings, "login_rate_limit_ip_attempts", 2):
            for account in ("missing-a", "missing-b"):
                with self.assertRaises(AuthenticationError):
                    authenticate(db, account, "wrong-password", ip_address="198.51.100.9")
            with self.assertRaises(LoginRateLimitError):
                authenticate(db, "missing-c", "wrong-password", ip_address="198.51.100.9")

    def test_login_route_returns_429_with_retry_after(self):
        request = Request({
            "type": "http", "method": "POST", "path": "/api/auth/login",
            "headers": [], "client": ("198.51.100.10", 4567),
        })
        with mock.patch("app.routes.auth.authenticate", side_effect=LoginRateLimitError(42)):
            with self.assertRaises(HTTPException) as ctx:
                login(LoginBody(login_key="user", password="wrong"), request, Response(), mock.MagicMock())
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.headers["Retry-After"], "42")

    def test_forwarded_for_is_ignored_without_trusted_proxy(self):
        request = Request({
            "type": "http", "method": "POST", "path": "/api/auth/login",
            "headers": [(b"x-forwarded-for", b"203.0.113.9")],
            "client": ("198.51.100.10", 4567),
        })
        with mock.patch.object(settings, "trusted_proxy_ips", ""):
            self.assertEqual(_client(request)[0], "198.51.100.10")

    def test_forwarded_for_uses_first_untrusted_hop_from_trusted_proxy(self):
        request = Request({
            "type": "http", "method": "POST", "path": "/api/auth/login",
            "headers": [(b"x-forwarded-for", b"203.0.113.9, 10.0.0.4")],
            "client": ("10.0.0.2", 4567),
        })
        with mock.patch.object(settings, "trusted_proxy_ips", "10.0.0.0/8"):
            self.assertEqual(_client(request)[0], "203.0.113.9")

    def test_production_mode_rejects_insecure_cookie_but_development_allows_it(self):
        with mock.patch.object(settings, "app_environment", "development"), mock.patch.object(settings, "session_cookie_secure", False):
            validate_runtime_security()
        with mock.patch.object(settings, "app_environment", "production"), mock.patch.object(settings, "session_cookie_secure", False):
            with self.assertRaisesRegex(RuntimeError, "SESSION_COOKIE_SECURE"):
                validate_runtime_security()

    def test_admin_password_reset_revokes_existing_sessions(self):
        engine = _admin_schema_engine()
        sys_actor = {"user_pk": 1, "user_id": "SYS0001", "username": "admin", "is_system_admin": True, "status": "enabled"}
        with Session(engine) as db:
            db.execute(text("INSERT INTO users(id,user_id,username,password_hash,is_system_admin,status) VALUES(20,'U200','member',:pw,0,'enabled')"), {"pw": hash_password("OldPassword123!", iterations=10_000, salt=b"0123456789abcdef")})
            db.execute(text("INSERT INTO user_departments(user_pk,department_id,role,status) VALUES(20,1,'member','enabled')"))
            db.commit()
            raw, _ = create_session(db, 20, remember=False, session_hours=12, remember_days=7)
            self.assertIsNotNone(resolve_session(db, raw, touch=False))
            update_user(db, sys_actor, "B2C", "U200", password="NewPassword123!")
            self.assertIsNone(resolve_session(db, raw, touch=False))

    def test_schema_contains_server_sessions(self):
        schema=(Path(__file__).resolve().parents[1]/"sql"/"schema_tables.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS auth_sessions",schema)
        self.assertIn("session_token_hash CHAR(64)",schema)
    def test_business_routes_use_server_session_dependency(self):
        root=Path(__file__).resolve().parents[1]/"app"/"routes"
        for name in ["dashboard.py","analysis.py","imports.py","presets.py","tasks.py"]:
            source=(root/name).read_text(encoding="utf-8")
            self.assertIn("require_actor",source,name)
        self.assertNotIn("actor_user_id: str",(root/"dashboard.py").read_text(encoding="utf-8"))
    def test_admin_boundaries_are_explicit(self):
        source=(Path(__file__).resolve().parents[1]/"app"/"services"/"admin_service.py").read_text(encoding="utf-8")
        self.assertIn("部门管理员只能管理本部门普通用户",source)
        self.assertIn("部门管理员不能授予部门管理员权限",source)
        self.assertIn("用户名/密码属于全局身份",source)

if __name__ == "__main__": unittest.main()
