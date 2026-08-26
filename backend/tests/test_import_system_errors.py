# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from datetime import datetime

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.services.import_db_service import (
    SystemImportError,
    _ensure_schema_tables,
    _get_or_create_product,
    _is_system_level_error,
    _touch_product_alias,
)


def _schema_sql(include_aliases: bool) -> list[str]:
    tables = [
        "CREATE TABLE products(id INTEGER PRIMARY KEY,merchant_code TEXT UNIQUE,product_name TEXT,spec TEXT,brand TEXT,category TEXT,barcode TEXT,import_batch_id INTEGER)",
        "CREATE TABLE import_changes(id INTEGER PRIMARY KEY,import_batch_id INTEGER,table_name TEXT,row_pk INTEGER,action TEXT,before_data TEXT)",
        "CREATE TABLE import_errors(id INTEGER PRIMARY KEY,import_batch_id INTEGER,row_no INTEGER,severity TEXT,error_code TEXT,error_message TEXT,raw_data TEXT)",
        "CREATE TABLE import_batches(id INTEGER PRIMARY KEY,batch_no TEXT,department_id INTEGER,data_type TEXT,business_date DATE,original_filename TEXT,file_sha256 TEXT,imported_by INTEGER,total_rows INTEGER,success_rows INTEGER,error_rows INTEGER,warning_rows INTEGER,status TEXT)",
    ]
    if include_aliases:
        tables.append("CREATE TABLE product_name_aliases(id INTEGER PRIMARY KEY,product_id INTEGER,alias_name TEXT,status TEXT,first_seen_at DATETIME,last_seen_at DATETIME,seen_count INTEGER,resolved_at DATETIME,resolved_by INTEGER)")
    return tables


def _make_engine(include_aliases=True):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _sqlite_now(dbapi_conn, _record):
        # SQLite 没有 NOW()；注册为当前时间，便于运行 MySQL 语义的 SQL。
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    with engine.begin() as conn:
        for sql in _schema_sql(include_aliases):
            conn.execute(text(sql))
    return engine


class SchemaCheckTests(unittest.TestCase):
    def test_missing_legacy_alias_table_does_not_block_imports(self):
        engine = _make_engine(include_aliases=False)
        with Session(engine) as db:
            _ensure_schema_tables(db)
            db.close()

    def test_all_tables_present_passes(self):
        engine = _make_engine(include_aliases=True)
        with Session(engine) as db:
            _ensure_schema_tables(db)
            db.close()

    def test_is_system_level_error_classifies_1146(self):
        from sqlalchemy.exc import ProgrammingError
        class Orig:
            args = (1146, "Table 'x.product_name_aliases' doesn't exist")
        err = ProgrammingError("stmt", {}, Orig())
        self.assertTrue(_is_system_level_error(err))

    def test_is_system_level_error_false_for_data(self):
        self.assertFalse(_is_system_level_error(ValueError("bad sales qty")))

    def test_is_system_level_error_false_for_rule_error(self):
        from app.services.import_db_service import ImportExecutionError
        self.assertFalse(_is_system_level_error(ImportExecutionError("\u5546\u5bb6\u65e0\u6cd5\u8bc6\u522b")))


class ProductCreateTests(unittest.TestCase):
    def test_same_merchant_multiple_rows_do_not_repeat_create(self):
        engine = _make_engine(include_aliases=True)
        with Session(engine) as db:
            warnings = []
            row1 = {"merchant_code": "A001", "product_name": "\u5546\u54c1A"}
            row2 = {"merchant_code": "A001", "product_name": "\u5546\u54c1A"}
            pid1 = _get_or_create_product(db, 1, row1, "sales", warnings)
            pid2 = _get_or_create_product(db, 1, row2, "sales", warnings)
            self.assertEqual(pid1, pid2)
            n = db.execute(text("SELECT COUNT(*) FROM products")).scalar()
            self.assertEqual(n, 1)
            db.close()

    def test_alias_inserted_when_missing(self):
        engine = _make_engine(include_aliases=True)
        with Session(engine) as db:
            db.execute(text("INSERT INTO products(id,merchant_code,product_name) VALUES(1,'A001','\u5546\u54c1A')"))
            pending = _touch_product_alias(db, 1, "\u5546\u54c1A", status="accepted")
            self.assertFalse(pending)
            n = db.execute(text("SELECT COUNT(*) FROM product_name_aliases")).scalar()
            self.assertEqual(n, 1)
            db.close()

    def test_alias_updated_when_exists(self):
        engine = _make_engine(include_aliases=True)
        with Session(engine) as db:
            db.execute(text("INSERT INTO product_name_aliases(product_id,alias_name,status,seen_count) VALUES(1,'\u5546\u54c1A','accepted',1)"))
            pending = _touch_product_alias(db, 1, "\u5546\u54c1A", status="accepted")
            self.assertFalse(pending)
            seen = db.execute(text("SELECT seen_count FROM product_name_aliases WHERE product_id=1")).scalar()
            self.assertEqual(seen, 2)
            db.close()


if __name__ == "__main__":
    unittest.main()
