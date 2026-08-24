# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services import export_service
from app.services.export_service import export_expiry_batches, export_inventory_analysis
from app.services.permission_service import PermissionDenied


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE departments(id INTEGER PRIMARY KEY,code TEXT UNIQUE,name TEXT,status TEXT)"))
        conn.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,user_id TEXT UNIQUE,username TEXT,password_hash TEXT,is_system_admin INTEGER,status TEXT)"))
        conn.execute(text("CREATE TABLE user_departments(id INTEGER PRIMARY KEY,user_pk INTEGER,department_id INTEGER,role TEXT,status TEXT)"))
        conn.execute(text("CREATE TABLE activity_logs(id INTEGER PRIMARY KEY,user_pk INTEGER,department_id INTEGER,action_type TEXT,action_detail TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO departments(id,code,name,status) VALUES(1,'B2C','B2C','enabled')"))
        conn.execute(text("INSERT INTO departments(id,code,name,status) VALUES(2,'XJB','XJB','enabled')"))
        conn.execute(text("INSERT INTO users(id,user_id,username,is_system_admin,status) VALUES(1,'SYS','sys',1,'enabled')"))
        conn.execute(text("INSERT INTO users(id,user_id,username,is_system_admin,status) VALUES(3,'MEM','mem',0,'enabled')"))
        conn.execute(text("INSERT INTO user_departments(user_pk,department_id,role,status) VALUES(3,1,'member','enabled')"))
    return engine


def _db():
    return Session(_engine())


class ExportPermissionTests(unittest.TestCase):
    def test_inventory_analysis_cross_department_raises(self):
        db = _db()
        with self.assertRaises(PermissionDenied):
            export_inventory_analysis(db, "MEM", "XJB")
        db.close()

    def test_expiry_batches_cross_department_raises(self):
        db = _db()
        with self.assertRaises(PermissionDenied):
            export_expiry_batches(db, "MEM", "XJB")
        db.close()


class ExportReuseTests(unittest.TestCase):
    """验证导出函数复用 analysis_service 的公开查询（列表==导出），筛选参数正确传递。"""

    def test_inventory_analysis_reuses_get_inventory_analysis(self):
        db = _db()
        fake_rows = [{"sku": "A", "name": "\u5546\u54c1A", "category_label": "\u5065\u5eb7", "stock_qty": 5.0,
                      "sales7": 1, "sales14": 2, "sales30": 3, "predicted_daily": 0.5,
                      "cover_days": 10.0, "weighted_aging_days": 12.0, "max_aging_days": 30}]
        with mock.patch.object(export_service, "get_inventory_analysis") as m:
            m.return_value = {"rows": fake_rows}
            result = export_inventory_analysis(
                db, "MEM", "B2C", warehouses=("\u4e3b\u4ed3",), product_search="\u5546\u54c1",
                include_name="x", exclude_name="y", product_codes=("A",), category=None,
            )
            # 验证调用了一次，且传入了正确的 scope 筛选
            self.assertEqual(m.call_count, 1)
            scope = m.call_args.args[1]
            self.assertEqual(scope.department_code, "B2C")
            self.assertEqual(scope.product_search, "\u5546\u54c1")
            self.assertEqual(scope.product_codes, ("A",))
            self.assertEqual(scope.warehouses, ("\u4e3b\u4ed3",))
            self.assertEqual(result["row_count"], 1)
            db.close()

    def test_expiry_batches_reuses_get_expiry_batches(self):
        db = _db()
        fake_rows = [{"warehouse": "\u4e3b\u4ed3", "sku": "A", "name": "\u5546\u54c1A", "stock_qty": 5.0,
                      "production_date": "2026-07-01", "expire_date": "2027-07-01", "total_shelf_days": 365,
                      "remaining_days": 300, "remaining_pct": 82.0, "status": "\u6b63\u5e38", "rule_source": "global"}]
        with mock.patch.object(export_service, "get_expiry_batches") as m:
            m.return_value = {"rows": fake_rows}
            result = export_expiry_batches(
                db, "MEM", "B2C", warehouses=("\u4e3b\u4ed3",), statuses=("\u6b63\u5e38",),
                remaining_days_min=10, remaining_days_max=400,
                remaining_pct_min=1.0, remaining_pct_max=99.0,
            )
            self.assertEqual(m.call_count, 1)
            self.assertEqual(m.call_args.kwargs["statuses"], ("\u6b63\u5e38",))
            self.assertEqual(m.call_args.kwargs["remaining_days_min"], 10)
            self.assertEqual(result["row_count"], 1)
            db.close()


if __name__ == "__main__":
    unittest.main()
