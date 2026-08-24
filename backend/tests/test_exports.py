from __future__ import annotations

import io
import unittest
from datetime import date

from openpyxl import load_workbook
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.export_service import export_aging, export_inventory, export_product, export_sales
from app.services.permission_service import PermissionDenied


def _build_schema_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE departments(id INTEGER PRIMARY KEY,code TEXT UNIQUE,name TEXT,status TEXT)"))
        conn.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,user_id TEXT UNIQUE,username TEXT,password_hash TEXT,is_system_admin INTEGER,status TEXT)"))
        conn.execute(text("CREATE TABLE user_departments(id INTEGER PRIMARY KEY,user_pk INTEGER,department_id INTEGER,role TEXT,status TEXT)"))
        conn.execute(text("CREATE TABLE products(id INTEGER PRIMARY KEY,merchant_code TEXT UNIQUE,product_name TEXT,spec TEXT,brand TEXT,category TEXT,barcode TEXT,import_batch_id INTEGER)"))
        conn.execute(text("CREATE TABLE shops(id INTEGER PRIMARY KEY,source_code TEXT,source_name TEXT)"))
        conn.execute(text("CREATE TABLE warehouses(id INTEGER PRIMARY KEY,source_code TEXT,source_name TEXT)"))
        conn.execute(text("CREATE TABLE sales_daily(id INTEGER PRIMARY KEY,department_id INTEGER,business_date DATE,shop_id INTEGER,warehouse_id INTEGER,product_id INTEGER,sales_qty DECIMAL,avg_price DECIMAL,import_batch_id INTEGER)"))
        conn.execute(text("CREATE TABLE inventory_batch(id INTEGER PRIMARY KEY,department_id INTEGER,snapshot_date DATE,warehouse_id INTEGER,product_id INTEGER,stock_qty DECIMAL,production_date DATE,expire_date DATE,import_batch_id INTEGER)"))
        conn.execute(text("CREATE TABLE aging_snapshot(id INTEGER PRIMARY KEY,department_id INTEGER,snapshot_date DATE,warehouse_id INTEGER,product_id INTEGER,stock_qty DECIMAL,aging_days INTEGER,import_batch_id INTEGER)"))
        conn.execute(text("CREATE TABLE import_batches(id INTEGER PRIMARY KEY,batch_no TEXT,department_id INTEGER,data_type TEXT,business_date DATE,status TEXT)"))
        conn.execute(text("CREATE TABLE activity_logs(id INTEGER PRIMARY KEY,user_pk INTEGER,department_id INTEGER,action_type TEXT,action_detail TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO departments(id,code,name,status) VALUES(1,'B2C','B2C','enabled')"))
        conn.execute(text("INSERT INTO departments(id,code,name,status) VALUES(2,'XJB','XJB','enabled')"))
        conn.execute(text("INSERT INTO users(id,user_id,username,is_system_admin,status) VALUES(1,'SYS','sys',1,'enabled')"))
        conn.execute(text("INSERT INTO users(id,user_id,username,is_system_admin,status) VALUES(2,'DEP','dep',0,'enabled')"))
        conn.execute(text("INSERT INTO users(id,user_id,username,is_system_admin,status) VALUES(3,'MEM','mem',0,'enabled')"))
        conn.execute(text("INSERT INTO user_departments(user_pk,department_id,role,status) VALUES(2,1,'dept_admin','enabled')"))
        conn.execute(text("INSERT INTO user_departments(user_pk,department_id,role,status) VALUES(3,1,'member','enabled')"))
        conn.execute(text("INSERT INTO shops(id,source_name) VALUES(1,'主店')"))
        conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(1,'主仓')"))
        conn.execute(text("INSERT INTO products(id,merchant_code,product_name,import_batch_id) VALUES(101,'A','A',1)"))
        conn.execute(text("INSERT INTO products(id,merchant_code,product_name,import_batch_id) VALUES(102,'B','B',1)"))
        conn.execute(text("INSERT INTO products(id,merchant_code,product_name,import_batch_id) VALUES(103,'C','C',2)"))
        conn.execute(text("INSERT INTO import_batches(id,batch_no,department_id,data_type,business_date,status) VALUES(1,'B1','1','product','2026-08-01','success')"))
        conn.execute(text("INSERT INTO import_batches(id,batch_no,department_id,data_type,business_date,status) VALUES(2,'B2','2','product','2026-08-01','success')"))
        conn.execute(text("INSERT INTO sales_daily(department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price) VALUES(1,'2026-08-01',1,1,101,10,5.5)"))
        conn.execute(text("INSERT INTO sales_daily(department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price) VALUES(1,'2026-08-02',1,1,102,20,6.0)"))
        conn.execute(text("INSERT INTO sales_daily(department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price) VALUES(2,'2026-08-01',1,1,103,99,9.9)"))
        conn.execute(text("INSERT INTO inventory_batch(department_id,snapshot_date,warehouse_id,product_id,stock_qty,production_date,expire_date) VALUES(1,'2026-07-01',1,101,5,'2026-06-01','2027-06-01')"))
        conn.execute(text("INSERT INTO inventory_batch(department_id,snapshot_date,warehouse_id,product_id,stock_qty,production_date,expire_date) VALUES(1,'2026-08-10',1,101,7,'2026-07-01','2027-07-01')"))
        conn.execute(text("INSERT INTO inventory_batch(department_id,snapshot_date,warehouse_id,product_id,stock_qty,production_date,expire_date) VALUES(2,'2026-08-10',1,103,3,'2026-07-01','2027-07-01')"))
        conn.execute(text("INSERT INTO aging_snapshot(department_id,snapshot_date,warehouse_id,product_id,stock_qty,aging_days) VALUES(1,'2026-07-01',1,101,5,30)"))
        conn.execute(text("INSERT INTO aging_snapshot(department_id,snapshot_date,warehouse_id,product_id,stock_qty,aging_days) VALUES(1,'2026-08-10',1,101,7,40)"))
        conn.execute(text("INSERT INTO aging_snapshot(department_id,snapshot_date,warehouse_id,product_id,stock_qty,aging_days) VALUES(2,'2026-08-10',1,103,3,50)"))
    return engine


def _open_xlsx(content: bytes):
    return load_workbook(io.BytesIO(content))


def _rows_of(wb):
    ws = wb.active
    data = list(ws.values)
    return data[0], data[1:]


class ExportPermissionTests(unittest.TestCase):
    def _db(self):
        return Session(_build_schema_engine())

    def test_member_can_export_own_department(self):
        db = self._db()
        result = export_product(db, 'MEM', 'B2C')
        self.assertTrue(result['content'])
        headers, body = _rows_of(_open_xlsx(result['content']))
        self.assertEqual(headers[0], '商家编码')
        codes = {row[0] for row in body}
        self.assertIn('A', codes)
        self.assertIn('B', codes)
        db.close()

    def test_member_cross_department_raises(self):
        db = self._db()
        with self.assertRaises(PermissionDenied):
            export_product(db, 'MEM', 'XJB')
        db.close()

    def test_dept_admin_can_export_own_department(self):
        db = self._db()
        result = export_inventory(db, 'DEP', 'B2C')
        self.assertTrue(result['content'])
        db.close()

    def test_dept_admin_cross_department_raises(self):
        db = self._db()
        with self.assertRaises(PermissionDenied):
            export_sales(db, 'DEP', 'XJB', start_date=date(2026, 8, 1), end_date=date(2026, 8, 2))
        db.close()

    def test_system_admin_can_export_any_department(self):
        db = self._db()
        r1 = export_product(db, 'SYS', 'B2C')
        r2 = export_product(db, 'SYS', 'XJB')
        self.assertTrue(r1['content'] and r2['content'])
        _, body = _rows_of(_open_xlsx(r2['content']))
        codes = {row[0] for row in body}
        self.assertIn('C', codes)
        self.assertNotIn('A', codes)
        db.close()


class ExportContentTests(unittest.TestCase):
    def _db(self):
        return Session(_build_schema_engine())

    def test_product_export_does_not_leak_other_department(self):
        db = self._db()
        result = export_product(db, 'MEM', 'B2C')
        _, body = _rows_of(_open_xlsx(result['content']))
        codes = {row[0] for row in body}
        self.assertIn('A', codes)
        self.assertIn('B', codes)
        self.assertNotIn('C', codes)
        db.close()

    def test_sales_date_range(self):
        db = self._db()
        result = export_sales(db, 'MEM', 'B2C', start_date=date(2026, 8, 2), end_date=date(2026, 8, 2))
        _, body = _rows_of(_open_xlsx(result['content']))
        self.assertEqual(len(body), 1)
        self.assertEqual(str(body[0][0]), '2026-08-02')
        db.close()

    def test_sales_date_range_reversed_raises(self):
        from app.services.export_service import ExportError
        db = self._db()
        with self.assertRaises(ExportError):
            export_sales(db, 'MEM', 'B2C', start_date=date(2026, 8, 2), end_date=date(2026, 8, 1))
        db.close()

    def test_inventory_exports_only_latest_snapshot(self):
        db = self._db()
        result = export_inventory(db, 'MEM', 'B2C')
        _, body = _rows_of(_open_xlsx(result['content']))
        self.assertTrue(body)
        for row in body:
            self.assertEqual(str(row[0]), '2026-08-10')
        self.assertEqual(len(body), 1)
        db.close()

    def test_aging_exports_only_latest_snapshot(self):
        db = self._db()
        result = export_aging(db, 'MEM', 'B2C')
        _, body = _rows_of(_open_xlsx(result['content']))
        self.assertTrue(body)
        for row in body:
            self.assertEqual(str(row[0]), '2026-08-10')
        self.assertEqual(len(body), 1)
        db.close()

    def test_xlsx_reopenable_and_has_filter(self):
        db = self._db()
        result = export_sales(db, 'MEM', 'B2C', start_date=date(2026, 8, 1), end_date=date(2026, 8, 2))
        wb = _open_xlsx(result['content'])
        ws = wb.active
        self.assertEqual(ws.freeze_panes, 'A2')
        self.assertIsNotNone(ws.auto_filter.ref)
        db.close()


class CapabilityTests(unittest.TestCase):
    """验证 can_download_data capability 规则：系统管理员恒 true；普通用户只要有 enabled membership 即为 true；且 can_import 保持不放宽。"""

    def _profile_for(self, engine, actor):
        from app.routes.auth import _profile
        with Session(engine) as db:
            return _profile(db, actor)

    def test_system_admin_can_download(self):
        engine = _build_schema_engine()
        actor = {"user_pk": 1, "user_id": "SYS", "username": "sys", "is_system_admin": True, "status": "enabled"}
        cap = self._profile_for(engine, actor)["capabilities"]
        self.assertTrue(cap["can_download_data"])
        self.assertTrue(cap["can_import"])

    def test_member_can_download_but_not_import(self):
        engine = _build_schema_engine()
        actor = {"user_pk": 3, "user_id": "MEM", "username": "mem", "is_system_admin": False, "status": "enabled"}
        cap = self._profile_for(engine, actor)["capabilities"]
        self.assertTrue(cap["can_download_data"])
        self.assertFalse(cap["can_import"])

    def test_dept_admin_can_download(self):
        engine = _build_schema_engine()
        actor = {"user_pk": 2, "user_id": "DEP", "username": "dep", "is_system_admin": False, "status": "enabled"}
        cap = self._profile_for(engine, actor)["capabilities"]
        self.assertTrue(cap["can_download_data"])
        self.assertTrue(cap["can_import"])

    def test_user_without_membership_cannot_download(self):
        engine = _build_schema_engine()
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users(id,user_id,username,is_system_admin,status) VALUES(4,'NO','no',0,'enabled')"))
        actor = {"user_pk": 4, "user_id": "NO", "username": "no", "is_system_admin": False, "status": "enabled"}
        cap = self._profile_for(engine, actor)["capabilities"]
        self.assertFalse(cap["can_download_data"])
        self.assertFalse(cap["can_import"])


class ExportAuditTests(unittest.TestCase):
    def _db(self):
        return Session(_build_schema_engine())

    def test_data_export_writes_activity_log(self):
        db = self._db()
        export_sales(db, 'MEM', 'B2C', start_date=date(2026, 8, 1), end_date=date(2026, 8, 2))
        log = db.execute(text("SELECT action_type,action_detail FROM activity_logs WHERE action_type='data_export'")).mappings().all()
        self.assertEqual(len(log), 1)
        self.assertIn('sales', log[0]['action_detail'])
        self.assertIn('B2C', log[0]['action_detail'])
        db.close()


if __name__ == '__main__':
    unittest.main()
