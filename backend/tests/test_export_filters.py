# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import unittest
from datetime import date

from openpyxl import load_workbook
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.export_service import export_sales
from app.services.permission_service import PermissionDenied


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE departments(id INTEGER PRIMARY KEY,code TEXT UNIQUE,name TEXT,status TEXT)"))
        conn.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,user_id TEXT UNIQUE,username TEXT,password_hash TEXT,is_system_admin INTEGER,status TEXT)"))
        conn.execute(text("CREATE TABLE user_departments(id INTEGER PRIMARY KEY,user_pk INTEGER,department_id INTEGER,role TEXT,status TEXT)"))
        conn.execute(text("CREATE TABLE products(id INTEGER PRIMARY KEY,merchant_code TEXT UNIQUE,product_name TEXT,spec TEXT,brand TEXT,category TEXT,barcode TEXT,import_batch_id INTEGER)"))
        conn.execute(text("CREATE TABLE shops(id INTEGER PRIMARY KEY,source_code TEXT,source_name TEXT)"))
        conn.execute(text("CREATE TABLE warehouses(id INTEGER PRIMARY KEY,source_code TEXT,source_name TEXT)"))
        conn.execute(text("CREATE TABLE sales_daily(id INTEGER PRIMARY KEY,department_id INTEGER,business_date DATE,shop_id INTEGER,warehouse_id INTEGER,product_id INTEGER,sales_qty DECIMAL,avg_price DECIMAL,import_batch_id INTEGER)"))
        conn.execute(text("CREATE TABLE activity_logs(id INTEGER PRIMARY KEY,user_pk INTEGER,department_id INTEGER,action_type TEXT,action_detail TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
        conn.execute(text("CREATE TABLE import_batches(id INTEGER PRIMARY KEY,batch_no TEXT,department_id INTEGER,data_type TEXT,business_date DATE,status TEXT)"))
        conn.execute(text("INSERT INTO departments(id,code,name,status) VALUES(1,'B2C','B2C','enabled')"))
        conn.execute(text("INSERT INTO departments(id,code,name,status) VALUES(2,'XJB','XJB','enabled')"))
        conn.execute(text("INSERT INTO users(id,user_id,username,is_system_admin,status) VALUES(1,'SYS','sys',1,'enabled')"))
        conn.execute(text("INSERT INTO users(id,user_id,username,is_system_admin,status) VALUES(2,'DEP','dep',0,'enabled')"))
        conn.execute(text("INSERT INTO users(id,user_id,username,is_system_admin,status) VALUES(3,'MEM','mem',0,'enabled')"))
        conn.execute(text("INSERT INTO user_departments(user_pk,department_id,role,status) VALUES(2,1,'dept_admin','enabled')"))
        conn.execute(text("INSERT INTO user_departments(user_pk,department_id,role,status) VALUES(3,1,'member','enabled')"))
        # 店铺 / 仓库
        conn.execute(text("INSERT INTO shops(id,source_name) VALUES(1,'\u4e3b\u5e97')"))    # 主店
        conn.execute(text("INSERT INTO shops(id,source_name) VALUES(2,'\u5206\u5e97')"))    # 分店
        conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(1,'\u4e3b\u4ed3')"))  # 主仓
        conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(2,'\u5907\u4ed3')"))  # 备仓
        # 商品 A/B 属于 B2C，C 属于 XJB
        conn.execute(text("INSERT INTO products(id,merchant_code,product_name,import_batch_id) VALUES(101,'A','\u5546\u54c1A',1)"))  # 商品A
        conn.execute(text("INSERT INTO products(id,merchant_code,product_name,import_batch_id) VALUES(102,'B','\u5546\u54c1B',1)"))  # 商品B
        conn.execute(text("INSERT INTO products(id,merchant_code,product_name,import_batch_id) VALUES(103,'C','\u5546\u54c1C',2)"))  # 商品C
        conn.execute(text("INSERT INTO import_batches(id,batch_no,department_id,data_type,business_date,status) VALUES(1,'B1','1','product','2026-08-01','success')"))
        conn.execute(text("INSERT INTO import_batches(id,batch_no,department_id,data_type,business_date,status) VALUES(2,'B2','2','product','2026-08-01','success')"))
        # B2C 销量：A 在 主店/主仓 08-01；A 在 分店/主仓 08-02；B 在 主店/备仓 08-02；A 在 主店/备仓 08-03
        conn.execute(text("INSERT INTO sales_daily(department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price) VALUES(1,'2026-08-01',1,1,101,10,5.0)"))
        conn.execute(text("INSERT INTO sales_daily(department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price) VALUES(1,'2026-08-02',2,1,101,8,6.0)"))
        conn.execute(text("INSERT INTO sales_daily(department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price) VALUES(1,'2026-08-02',1,2,102,20,7.0)"))
        conn.execute(text("INSERT INTO sales_daily(department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price) VALUES(1,'2026-08-03',1,2,101,12,6.5)"))
        # XJB 销量（不应被 B2C 用户导出）
        conn.execute(text("INSERT INTO sales_daily(department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price) VALUES(2,'2026-08-02',1,1,103,99,9.9)"))
    return engine


def _open(content):
    return load_workbook(io.BytesIO(content))


def _rows(content):
    ws = _open(content).active
    data = list(ws.values)
    return data[0], data[1:]


class ExportFilterConsistencyTests(unittest.TestCase):
    def _db(self):
        return Session(_engine())

    def _codes(self, result):
        _, body = _rows(result["content"])
        return [r[3] for r in body]  # 第4列=商家编码

    def _dates(self, result):
        _, body = _rows(result["content"])
        return [str(r[0]) for r in body]

    def test_no_filter_exports_all_in_scope(self):
        db = self._db()
        result = export_sales(db, "MEM", "B2C", start_date=date(2026, 8, 1), end_date=date(2026, 8, 3))
        self.assertEqual(result["row_count"], 4)
        codes = self._codes(result)
        self.assertEqual(sorted(codes), ["A", "A", "A", "B"])
        db.close()

    def test_date_filter(self):
        db = self._db()
        result = export_sales(db, "MEM", "B2C", start_date=date(2026, 8, 2), end_date=date(2026, 8, 2))
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(sorted(self._dates(result)), ["2026-08-02", "2026-08-02"])
        db.close()

    def test_shop_filter(self):
        db = self._db()
        result = export_sales(db, "MEM", "B2C", start_date=date(2026, 8, 1), end_date=date(2026, 8, 3), shops=("\u4e3b\u5e97",))
        # 主店：08-01 A(主仓)、08-02 B(备仓)、08-03 A(备仓) = 3 条
        self.assertEqual(result["row_count"], 3)
        db.close()

    def test_warehouse_filter(self):
        db = self._db()
        result = export_sales(db, "MEM", "B2C", start_date=date(2026, 8, 1), end_date=date(2026, 8, 3), warehouses=("\u5907\u4ed3",))
        # 备仓：08-02 B、08-03 A = 2 条
        self.assertEqual(result["row_count"], 2)
        db.close()

    def test_merchant_code_filter(self):
        db = self._db()
        result = export_sales(db, "MEM", "B2C", start_date=date(2026, 8, 1), end_date=date(2026, 8, 3), product_codes=("A",))
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(set(self._codes(result)), {"A"})
        db.close()

    def test_product_name_filter(self):
        db = self._db()
        result = export_sales(db, "MEM", "B2C", start_date=date(2026, 8, 1), end_date=date(2026, 8, 3), product_search="\u5546\u54c1B")
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(self._codes(result), ["B"])
        db.close()

    def test_combined_filters(self):
        db = self._db()
        result = export_sales(
            db, "MEM", "B2C",
            start_date=date(2026, 8, 1), end_date=date(2026, 8, 3),
            shops=("\u4e3b\u5e97",), product_codes=("A",),
        )
        # 主店 + 商品A：08-01 A(主仓)、08-03 A(备仓) = 2 条
        self.assertEqual(result["row_count"], 2)
        db.close()

    def test_export_includes_all_rows_not_page(self):
        # 模拟"筛选 total=137，分页 50/页"的场景：导出必须返回全部，而不是一页。
        db = self._db()
        result = export_sales(db, "MEM", "B2C", start_date=date(2026, 8, 1), end_date=date(2026, 8, 3))
        # 无分页参数传入，导出全部 4 条；若传了 page/page_size 才是 50。
        self.assertEqual(result["row_count"], 4)
        db.close()

    def test_dept_admin_cannot_export_other_department(self):
        db = self._db()
        with self.assertRaises(PermissionDenied):
            export_sales(db, "DEP", "XJB", start_date=date(2026, 8, 1), end_date=date(2026, 8, 3))
        db.close()

    def test_empty_result_returns_header_only_xlsx(self):
        db = self._db()
        result = export_sales(db, "MEM", "B2C", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        self.assertEqual(result["row_count"], 0)
        headers, body = _rows(result["content"])
        self.assertEqual(headers[0], "\u4e1a\u52a1\u65e5\u671f")  # 业务日期
        self.assertEqual(len(body), 0)
        db.close()


if __name__ == "__main__":
    unittest.main()
