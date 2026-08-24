# -*- coding: utf-8 -*-
from __future__ import annotations

import pathlib
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.exports import ExportError, _xlsx_response
from app.services.export_service import _make_workbook
from app.services.task_crud_service import _dimension_ids_in_department, _is_duplicate_key, _next_task_no


class FreshInstallSchemaTests(unittest.TestCase):
    """验证全新数据库执行 init-schema（schema_tables.sql）后，0152/0153 所需表全部存在。"""

    def _schema_sql(self):
        return (pathlib.Path(__file__).resolve().parents[1] / "sql" / "schema_tables.sql").read_text(encoding="utf-8")

    def test_schema_tables_contains_task_dimension_tables(self):
        sql = self._schema_sql()
        self.assertIn("CREATE TABLE IF NOT EXISTS task_shops", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS task_warehouses", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS product_name_aliases", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS release_history", sql)

    def test_schema_tables_has_foreign_keys(self):
        sql = self._schema_sql()
        self.assertIn("fk_task_shops_task", sql)
        self.assertIn("fk_task_shops_shop", sql)
        self.assertIn("fk_task_warehouses_task", sql)
        self.assertIn("fk_task_warehouses_warehouse", sql)


class EmptyExportTests(unittest.TestCase):
    def test_empty_result_raises_business_error(self):
        body = _make_workbook(["\u5546\u5bb6\u7f16\u7801"], [], set())  # 商家编码
        with self.assertRaises(ExportError) as ctx:
            _xlsx_response(body, "B2C_sales.xlsx", row_count=0, ascii_filename="B2C_sales.xlsx")
        self.assertIn("\u6682\u65e0\u53ef\u5bfc\u51fa", str(ctx.exception))  # 暂无


class DimensionCandidateTests(unittest.TestCase):
    def _engine(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE warehouses(id INTEGER PRIMARY KEY,source_name TEXT)"))
            conn.execute(text("CREATE TABLE sales_daily(id INTEGER PRIMARY KEY,department_id INTEGER,warehouse_id INTEGER)"))
            conn.execute(text("CREATE TABLE inventory_batch(id INTEGER PRIMARY KEY,department_id INTEGER,warehouse_id INTEGER)"))
            conn.execute(text("CREATE TABLE aging_snapshot(id INTEGER PRIMARY KEY,department_id INTEGER,warehouse_id INTEGER)"))
            conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(1,'\u4e3b\u4ed3')"))   # 主仓
            conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(2,'\u5e93\u5b58\u4ed3')"))  # 库存仓
            conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(3,'\u5e93\u9f84\u4ed3')"))  # 库龄仓
            conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(9,'\u5176\u4ed6\u4ed3')"))  # 其他仓
            # warehouse 1 只出现在 sales_daily
            conn.execute(text("INSERT INTO sales_daily(department_id,warehouse_id) VALUES(1,1)"))
            # warehouse 2 只出现在 inventory_batch
            conn.execute(text("INSERT INTO inventory_batch(department_id,warehouse_id) VALUES(1,2)"))
            # warehouse 3 只出现在 aging_snapshot
            conn.execute(text("INSERT INTO aging_snapshot(department_id,warehouse_id) VALUES(1,3)"))
            # warehouse 9 不属于本部门任何表
        return engine

    def test_warehouse_candidates_cover_all_three_tables(self):
        db = Session(self._engine())
        result = _dimension_ids_in_department(db, 1, "warehouses", [1, 2, 3, 9])
        self.assertEqual(result, {1, 2, 3})
        self.assertNotIn(9, result)
        db.close()


class TaskNoRetryTests(unittest.TestCase):
    def test_next_task_no_offset(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE todo_tasks(id INTEGER PRIMARY KEY,task_no TEXT UNIQUE)"))
            conn.execute(text("INSERT INTO todo_tasks(task_no) VALUES('TD20260825-001')"))
        from datetime import date
        db = Session(engine)
        self.assertEqual(_next_task_no(db, date(2026, 8, 25)), "TD20260825-002")
        self.assertEqual(_next_task_no(db, date(2026, 8, 25), offset=1), "TD20260825-003")
        db.close()

    def test_is_duplicate_key_detects_1062(self):
        class Orig:
            args = (1062, "Duplicate entry 'TD-001' for key 'task_no'")
            def __str__(self):
                return "(1062, \"Duplicate entry 'TD-001' for key 'task_no'\")"
        err = IntegrityError("stmt", {}, Orig())
        self.assertTrue(_is_duplicate_key(err))

    def test_is_duplicate_key_false_for_other(self):
        self.assertFalse(_is_duplicate_key(ValueError("x")))


if __name__ == "__main__":
    unittest.main()
