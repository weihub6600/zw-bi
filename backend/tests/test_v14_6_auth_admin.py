from pathlib import Path
import unittest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.services.auth_service import hash_password, verify_password, token_hash, authenticate, create_session, resolve_session

class V146AuthAdminTests(unittest.TestCase):
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
