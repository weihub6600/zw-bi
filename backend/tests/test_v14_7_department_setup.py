from pathlib import Path
import unittest
from unittest import mock
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.setup_service import setup_status, initialize_system
from app.services.department_service import require_system_admin
from app.services.permission_service import PermissionDenied
from app.core.config import settings, validate_runtime_security
from app.routes.setup import SetupBody, initialize

class V147DepartmentSetupTests(unittest.TestCase):
    def test_production_security_requires_setup_token_and_proxy(self):
        with self.subTest("missing production settings"):
            with mock.patch.object(settings, "app_environment", "production"), \
                 mock.patch.object(settings, "session_cookie_secure", True), \
                 mock.patch.object(settings, "app_secret", "x" * 32), \
                 mock.patch.object(settings, "cors_origins", "https://bi.example.com"), \
                 mock.patch.object(settings, "trusted_proxy_ips", "127.0.0.1"), \
                 mock.patch.object(settings, "setup_init_token", "short"):
                with self.assertRaisesRegex(RuntimeError, "SETUP_INIT_TOKEN"):
                    validate_runtime_security()

        with mock.patch.object(settings, "app_environment", "production"), \
             mock.patch.object(settings, "session_cookie_secure", True), \
             mock.patch.object(settings, "app_secret", "x" * 32), \
             mock.patch.object(settings, "cors_origins", "https://bi.example.com"), \
             mock.patch.object(settings, "trusted_proxy_ips", "127.0.0.1"), \
             mock.patch.object(settings, "setup_init_token", "t" * 16):
            validate_runtime_security()

    def test_production_setup_requires_matching_token(self):
        body = SetupBody(admin_password="StrongPass123!")
        with mock.patch.object(settings, "app_environment", "production"), \
             mock.patch.object(settings, "setup_init_token", "t" * 16):
            with self.assertRaisesRegex(Exception, "首次初始化需要受控初始化令牌"):
                initialize(body, object(), None)
            with mock.patch("app.routes.setup.initialize_system", return_value={"ok": True}):
                result = initialize(body, object(), "t" * 16)
                self.assertEqual(result, {"ok": True})
    def test_system_admin_boundary(self):
        require_system_admin({'is_system_admin':1})
        with self.assertRaises(PermissionDenied):
            require_system_admin({'is_system_admin':0})

    def test_first_run_setup_is_one_time(self):
        engine=create_engine('sqlite+pysqlite:///:memory:',future=True)
        with engine.begin() as c:
            c.execute(text("CREATE TABLE departments(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE,name TEXT UNIQUE,status TEXT)"))
            c.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT UNIQUE,username TEXT UNIQUE,password_hash TEXT,is_system_admin INTEGER,status TEXT,last_active_time DATETIME)"))
            c.execute(text("CREATE TABLE user_departments(id INTEGER PRIMARY KEY AUTOINCREMENT,user_pk INTEGER,department_id INTEGER,role TEXT,status TEXT)"))
            c.execute(text("INSERT INTO departments(code,name,status) VALUES('B2C','B2C事业部','enabled')"))
        with Session(engine) as db:
            self.assertFalse(setup_status(db)['initialized'])
            result=initialize_system(db,department_code='B2C',department_name='B2C事业部',admin_user_id='SYS0001',admin_username='admin',admin_password='StrongPass123!')
            self.assertTrue(result['ok'])
            self.assertTrue(setup_status(db)['initialized'])
            with self.assertRaises(PermissionError):
                initialize_system(db,department_code='B2C',department_name='B2C事业部',admin_user_id='SYS0002',admin_username='admin2',admin_password='StrongPass123!')

    @unittest.skipUnless((Path(__file__).resolve().parents[2]/'frontend/src/views/SettingsView.vue').exists(), "前端源码不在发布包中，跳过前端一致性检查")
    def test_routes_and_frontend_have_department_audit_setup(self):
        root=Path(__file__).resolve().parents[2]
        admin=(root/'backend/app/routes/admin.py').read_text(encoding='utf-8')
        main=(root/'backend/app/main.py').read_text(encoding='utf-8')
        settings=(root/'frontend/src/views/SettingsView.vue').read_text(encoding='utf-8')
        router=(root/'frontend/src/router/index.js').read_text(encoding='utf-8')
        self.assertIn("/departments",admin)
        self.assertIn("/audit",admin)
        self.assertIn("setup_router",main)
        self.assertIn("部门管理",settings)
        self.assertIn("操作审计",settings)
        self.assertIn("/setup",router)

    @unittest.skipUnless((Path(__file__).resolve().parents[2]/'frontend/src/views/SetupView.vue').exists(), "前端源码不在发布包中，跳过前端一致性检查")
    def test_no_external_wdt_openapi(self):
        root=Path(__file__).resolve().parents[2]
        setup=(root/'frontend/src/views/SetupView.vue').read_text(encoding='utf-8')
        self.assertIn('不会连接旺店通/WMS 外部 OpenAPI',setup)
        self.assertIn('external_wdt_api', (root/'backend/app/routes/health.py').read_text(encoding='utf-8'))

if __name__=='__main__': unittest.main()
