from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.routes.admin import _handle_cost_error
from app.services.cost_service import CostValidationError, _validate_cost, get_cost_as_of, is_missing_cost_table_error, save_manual_cost
from app.services.import_db_service import (
    RollbackConflictError,
    _assert_product_not_referenced,
    _redact_product_cost_raw_data,
)
from app.services.import_parser import parse_import_file
from app.core.timezone import today_local


class ProductCostTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        with self.engine.begin() as db:
            db.execute(text("""
                CREATE TABLE department_product_costs(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  department_id INTEGER NOT NULL,
                  product_id INTEGER NOT NULL,
                  effective_date DATE NOT NULL,
                  unit_cost NUMERIC NOT NULL,
                  currency TEXT NOT NULL DEFAULT 'CNY',
                  unit TEXT NOT NULL DEFAULT '件',
                  source TEXT NOT NULL DEFAULT 'manual',
                  source_import_batch_id INTEGER,
                  created_by INTEGER NOT NULL
                )
            """))

    def test_first_cost_covers_prior_dates_and_later_cost_starts_on_effective_date(self):
        with self.engine.begin() as db:
            db.execute(text("INSERT INTO department_product_costs(department_id,product_id,effective_date,unit_cost,created_by) VALUES (1,10,'2026-09-15',20,1),(1,10,'2026-09-25',23,1)"))
        with Session(self.engine) as db:
            self.assertEqual(get_cost_as_of(db, 1, 10, date(2026, 9, 1))["unit_cost"], "20")
            self.assertEqual(get_cost_as_of(db, 1, 10, date(2026, 9, 24))["unit_cost"], "20")
            self.assertEqual(get_cost_as_of(db, 1, 10, date(2026, 9, 25))["unit_cost"], "23")
            self.assertIsNone(get_cost_as_of(db, 2, 10, date(2026, 9, 25)))

    def test_cost_validation_rejects_non_finite_non_positive_and_excess_precision(self):
        for value in ("NaN", "Infinity", "-1", "0", "1.1234567"):
            with self.assertRaises(CostValidationError):
                _validate_cost(value)
        self.assertEqual(_validate_cost("12.50"), _validate_cost("12.5"))

    def test_manual_cost_write_rolls_back_when_activity_log_write_fails(self):
        with self.engine.begin() as db:
            db.execute(text("CREATE TABLE departments(id INTEGER PRIMARY KEY,code TEXT,name TEXT,status TEXT)"))
            db.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,user_id TEXT,username TEXT,is_system_admin INTEGER,status TEXT)"))
            db.execute(text("CREATE TABLE user_departments(user_pk INTEGER,department_id INTEGER,role TEXT,status TEXT)"))
            db.execute(text("CREATE TABLE products(id INTEGER PRIMARY KEY,merchant_code TEXT,product_name TEXT,import_batch_id INTEGER)"))
            db.execute(text("CREATE TABLE sales_daily(id INTEGER PRIMARY KEY,department_id INTEGER,product_id INTEGER)"))
            db.execute(text("CREATE TABLE inventory_batch(id INTEGER PRIMARY KEY,department_id INTEGER,product_id INTEGER)"))
            db.execute(text("CREATE TABLE aging_snapshot(id INTEGER PRIMARY KEY,department_id INTEGER,product_id INTEGER)"))
            db.execute(text("CREATE TABLE import_batches(id INTEGER PRIMARY KEY,department_id INTEGER)"))
            db.execute(text("CREATE TABLE activity_logs(id INTEGER PRIMARY KEY,user_pk INTEGER,department_id INTEGER,action_type TEXT,action_detail TEXT)"))
            db.execute(text("INSERT INTO departments VALUES (1,'B2C','B2C','enabled')"))
            db.execute(text("INSERT INTO users VALUES (1,'admin','Admin',1,'enabled')"))
            db.execute(text("INSERT INTO products VALUES (10,'SKU-1','Test',NULL)"))
            db.execute(text("INSERT INTO sales_daily VALUES (1,1,10)"))
            db.execute(text("INSERT INTO department_product_costs(department_id,product_id,effective_date,unit_cost,created_by) VALUES (1,10,:today,1,1)"), {"today": date(2026, 9, 25)})
        with Session(self.engine) as db:
            with self.assertRaises(ProgrammingError):
                save_manual_cost(
                    db,
                    {"user_id": "admin", "id": 1, "is_system_admin": True},
                    "B2C",
                    "SKU-1",
                    "12.50",
                    today_local(),
                    "CNY",
                    "件",
                )
            self.assertEqual(db.execute(text("SELECT COUNT(*) FROM department_product_costs")).scalar(), 1)

    def test_missing_cost_migration_returns_actionable_service_unavailable(self):
        error = ProgrammingError(
            "SELECT * FROM department_product_costs",
            {},
            Exception("Table 'local_bi.department_product_costs' doesn't exist"),
        )
        self.assertTrue(is_missing_cost_table_error(error))
        with self.assertRaises(HTTPException) as raised:
            _handle_cost_error(error)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("0159_department_product_costs", raised.exception.detail)

    def test_unrelated_sql_error_is_not_converted_to_migration_message(self):
        error = OperationalError("SELECT 1", {}, Exception("database connection lost"))
        self.assertFalse(is_missing_cost_table_error(error))
        with self.assertRaises(OperationalError):
            _handle_cost_error(error)

    def test_new_migration_and_schema_declare_department_scoped_unique_versions(self):
        root = Path(__file__).resolve().parents[1]
        migration = (root / "sql" / "migrations" / "0159_department_product_costs.sql").read_text(encoding="utf-8")
        schema = (root / "sql" / "schema_tables.sql").read_text(encoding="utf-8")
        for content in (migration, schema):
            self.assertIn("department_product_costs", content)
            self.assertIn("UNIQUE KEY uk_department_product_cost_date", content)
            self.assertIn("DECIMAL(18,6)", content)

    def test_product_template_cost_columns_are_recognized_by_import_parser(self):
        root = Path(__file__).resolve().parents[2]
        for filename in ("product_master.xlsx", "商品资料模板.xlsx"):
            parsed = parse_import_file(root / "frontend" / "public" / "templates" / filename, "product", None)
            self.assertIn("unit_cost", parsed.header_mapping)
            self.assertIn("cost_currency", parsed.header_mapping)
            self.assertIn("cost_unit", parsed.header_mapping)
            self.assertFalse(parsed.contains_cost_values)

    def test_product_rollback_reference_check_uses_cost_source_batch_column(self):
        with self.engine.begin() as db:
            for table in ("sales_daily", "inventory_batch", "aging_snapshot"):
                db.execute(text(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY,product_id INTEGER,import_batch_id INTEGER)"))
            db.execute(text("CREATE TABLE todo_tasks(id INTEGER PRIMARY KEY,product_id INTEGER)"))
            db.execute(text("INSERT INTO department_product_costs(department_id,product_id,effective_date,unit_cost,source_import_batch_id,created_by) VALUES (1,10,'2026-09-25',2,7,1)"))
        with Session(self.engine) as db:
            _assert_product_not_referenced(db, product_id=10, batch_id=7)

    def test_product_rollback_refuses_cost_reference_from_other_or_manual_source(self):
        with self.engine.begin() as db:
            for table in ("sales_daily", "inventory_batch", "aging_snapshot"):
                db.execute(text(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY,product_id INTEGER,import_batch_id INTEGER)"))
            db.execute(text("CREATE TABLE todo_tasks(id INTEGER PRIMARY KEY,product_id INTEGER)"))
            db.execute(text("INSERT INTO department_product_costs(department_id,product_id,effective_date,unit_cost,source_import_batch_id,created_by) VALUES (1,10,'2026-09-25',2,8,1)"))
        with Session(self.engine) as db:
            with self.assertRaises(RollbackConflictError):
                _assert_product_not_referenced(db, product_id=10, batch_id=7)
        with self.engine.begin() as db:
            db.execute(text("DELETE FROM department_product_costs"))
            db.execute(text("INSERT INTO department_product_costs(department_id,product_id,effective_date,unit_cost,source_import_batch_id,created_by) VALUES (1,10,'2026-09-25',2,NULL,1)"))
        with Session(self.engine) as db:
            with self.assertRaises(RollbackConflictError):
                _assert_product_not_referenced(db, product_id=10, batch_id=7)

    def test_department_issue_view_redacts_cost_headers_but_keeps_error_context(self):
        raw = {
            "商家编码": "SKU-1",
            "货品名称": "测试商品",
            "成本价": "88.50",
            "成本币种": "CNY",
            "成本单位": "箱",
        }
        self.assertEqual(
            _redact_product_cost_raw_data(raw),
            {"商家编码": "SKU-1", "货品名称": "测试商品"},
        )
        self.assertEqual(
            _redact_product_cost_raw_data('{"merchant_code":"SKU-1","unit_cost":"88.50"}'),
            {"merchant_code": "SKU-1"},
        )


if __name__ == "__main__":
    unittest.main()
