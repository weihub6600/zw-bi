# -*- coding: utf-8 -*-
from __future__ import annotations

import pathlib
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.task_crud_service import (
    _dimension_names,
    _dimension_ids_in_department,
    _task_dimensions,
    _validate_task_dimensions,
    _write_task_dimensions,
    list_task_dimensions,
)
from app.services.permission_service import PermissionDenied


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE departments(id INTEGER PRIMARY KEY,code TEXT UNIQUE,name TEXT,status TEXT)"))
        conn.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,user_id TEXT UNIQUE,username TEXT,password_hash TEXT,is_system_admin INTEGER,status TEXT)"))
        conn.execute(text("CREATE TABLE user_departments(id INTEGER PRIMARY KEY,user_pk INTEGER,department_id INTEGER,role TEXT,status TEXT)"))
        conn.execute(text("CREATE TABLE todo_tasks(id INTEGER PRIMARY KEY,task_no TEXT,department_id INTEGER,product_id INTEGER,owner_user_pk INTEGER,creator_user_pk INTEGER,warehouse_id INTEGER,shop_id INTEGER,target_qty DECIMAL,assign_date DATE,start_date DATE,manager_note TEXT,owner_note TEXT,status TEXT)"))
        conn.execute(text("CREATE TABLE task_shops(id INTEGER PRIMARY KEY,task_id INTEGER,shop_id INTEGER)"))
        conn.execute(text("CREATE TABLE task_warehouses(id INTEGER PRIMARY KEY,task_id INTEGER,warehouse_id INTEGER)"))
        conn.execute(text("CREATE TABLE products(id INTEGER PRIMARY KEY,merchant_code TEXT,product_name TEXT)"))
        conn.execute(text("CREATE TABLE shops(id INTEGER PRIMARY KEY,source_code TEXT,source_name TEXT)"))
        conn.execute(text("CREATE TABLE warehouses(id INTEGER PRIMARY KEY,source_code TEXT,source_name TEXT)"))
        conn.execute(text("CREATE TABLE sales_daily(id INTEGER PRIMARY KEY,department_id INTEGER,business_date DATE,shop_id INTEGER,warehouse_id INTEGER,product_id INTEGER,sales_qty DECIMAL,avg_price DECIMAL,import_batch_id INTEGER)"))
        conn.execute(text("CREATE TABLE inventory_batch(id INTEGER PRIMARY KEY,department_id INTEGER,snapshot_date DATE,warehouse_id INTEGER,product_id INTEGER,stock_qty DECIMAL,production_date DATE,expire_date DATE,import_batch_id INTEGER)"))
        conn.execute(text("CREATE TABLE aging_snapshot(id INTEGER PRIMARY KEY,department_id INTEGER,snapshot_date DATE,warehouse_id INTEGER,product_id INTEGER,stock_qty DECIMAL,aging_days INTEGER,import_batch_id INTEGER)"))
        conn.execute(text("CREATE TABLE activity_logs(id INTEGER PRIMARY KEY,user_pk INTEGER,department_id INTEGER,action_type TEXT,action_detail TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO departments(id,code,name,status) VALUES(1,'B2C','B2C','enabled')"))
        conn.execute(text("INSERT INTO departments(id,code,name,status) VALUES(2,'XJB','XJB','enabled')"))
        conn.execute(text("INSERT INTO users(id,user_id,username,is_system_admin,status) VALUES(1,'SYS','sys',1,'enabled')"))
        conn.execute(text("INSERT INTO users(id,user_id,username,is_system_admin,status) VALUES(3,'MEM','mem',0,'enabled')"))
        conn.execute(text("INSERT INTO user_departments(user_pk,department_id,role,status) VALUES(3,1,'member','enabled')"))
        conn.execute(text("INSERT INTO shops(id,source_name) VALUES(11,'\u6dd8\u5b9d\u5e97')"))   # 淘宝店
        conn.execute(text("INSERT INTO shops(id,source_name) VALUES(12,'\u4eac\u4e1c\u5e97')"))   # 京东店
        conn.execute(text("INSERT INTO shops(id,source_name) VALUES(21,'\u62fc\u591a\u591a\u5e97')"))  # 拼多多店(XJB)
        conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(31,'\u5feb\u9012\u4ed3')"))  # 快递仓
        conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(32,'\u4e0a\u6d77\u4ed3')"))  # 上海仓
        conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(41,'\u5e7f\u5dde\u4ed3')"))  # 广州仓(XJB)
        # B2C 可见店铺：11,12；可见仓库：31,32
        conn.execute(text("INSERT INTO sales_daily(department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price) VALUES(1,'2026-08-01',11,31,101,5,10)"))
        conn.execute(text("INSERT INTO sales_daily(department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price) VALUES(1,'2026-08-02',12,32,101,6,11)"))
        # XJB 可见：21,41
        conn.execute(text("INSERT INTO sales_daily(department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price) VALUES(2,'2026-08-01',21,41,102,9,9)"))
    return engine


def _db():
    return Session(_engine())


class DimensionPermissionTests(unittest.TestCase):
    def test_valid_shops_warehouses_allowed(self):
        db = _db()
        shops, whs = _validate_task_dimensions(db, 1, shop_ids=[11, 12], warehouse_ids=[31, 32])
        self.assertEqual(shops, [11, 12])
        self.assertEqual(whs, [31, 32])
        db.close()

    def test_unauthorized_shop_rejected(self):
        db = _db()
        with self.assertRaises(PermissionDenied):
            _validate_task_dimensions(db, 1, shop_ids=[21], warehouse_ids=[])
        db.close()

    def test_unauthorized_warehouse_rejected(self):
        db = _db()
        with self.assertRaises(PermissionDenied):
            _validate_task_dimensions(db, 1, shop_ids=[11], warehouse_ids=[41])
        db.close()

    def test_combined_multi_shop_multi_warehouse(self):
        db = _db()
        shops, whs = _validate_task_dimensions(db, 1, shop_ids=[11, 12], warehouse_ids=[31, 32])
        self.assertEqual(shops, [11, 12])
        self.assertEqual(whs, [31, 32])
        db.close()


class DimensionRelationTests(unittest.TestCase):
    def test_write_and_read_relations(self):
        db = _db()
        _write_task_dimensions(db, 100, [11, 12], [31, 32])
        shop_map, wh_map = _task_dimensions(db, [100])
        self.assertEqual(sorted(shop_map.get(100, [])), [11, 12])
        self.assertEqual(sorted(wh_map.get(100, [])), [31, 32])
        db.close()

    def test_dimension_names(self):
        db = _db()
        names = _dimension_names(db, "shops", [11, 12])
        self.assertEqual(names[11], "\u6dd8\u5b9d\u5e97")
        self.assertEqual(names[12], "\u4eac\u4e1c\u5e97")
        db.close()

    def test_legacy_single_dimension_fallback(self):
        # 旧单选任务：todo_tasks.shop_id/warehouse_id 有值但关联表为空。
        db = _db()
        db.execute(text("INSERT INTO todo_tasks(id,task_no,department_id,product_id,owner_user_pk,creator_user_pk,shop_id,warehouse_id,assign_date,start_date,status) VALUES(1,'T1',1,101,3,1,11,31,'2026-08-01','2026-08-02','running')"))
        db.commit()
        shop_map, wh_map = _task_dimensions(db, [1])
        # 关联表为空时 _task_dimensions 返回空；前端/上层用 _task_base_rows 做旧字段回退。
        self.assertEqual(shop_map.get(1, []), [])
        db.close()

    def test_dimension_ids_in_department(self):
        db = _db()
        self.assertEqual(_dimension_ids_in_department(db, 1, "shops", [11, 12, 21]), {11, 12})
        self.assertEqual(_dimension_ids_in_department(db, 1, "warehouses", [31, 32, 41]), {31, 32})
        db.close()


class TaskOptionsTests(unittest.TestCase):
    def test_list_task_dimensions_returns_id_and_name(self):
        db = _db()
        result = list_task_dimensions(db, "MEM", "B2C")
        shop_ids = sorted(s["id"] for s in result["shops"])
        self.assertEqual(shop_ids, [11, 12])
        self.assertTrue(all("name" in s and "id" in s for s in result["shops"]))
        wh_ids = sorted(w["id"] for w in result["warehouses"])
        self.assertEqual(wh_ids, [31, 32])
        db.close()

    def test_list_task_dimensions_scoped_by_department(self):
        db = _db()
        result = list_task_dimensions(db, "MEM", "B2C")
        self.assertNotIn(21, [s["id"] for s in result["shops"]])
        self.assertNotIn(41, [w["id"] for w in result["warehouses"]])
        db.close()


class MigrationTests(unittest.TestCase):
    def test_migration_creates_relation_tables_and_migrates_legacy(self):
        sql_path = pathlib.Path(__file__).resolve().parents[1] / "sql" / "migrations" / "0153_task_multi_dimensions.sql"
        sql = sql_path.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS task_shops", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS task_warehouses", sql)
        self.assertIn("INSERT IGNORE INTO task_shops", sql)
        self.assertIn("INSERT IGNORE INTO task_warehouses", sql)
        self.assertIn("SELECT id, shop_id FROM todo_tasks WHERE shop_id IS NOT NULL", sql)
        self.assertIn("SELECT id, warehouse_id FROM todo_tasks WHERE warehouse_id IS NOT NULL", sql)


if __name__ == "__main__":
    unittest.main()
