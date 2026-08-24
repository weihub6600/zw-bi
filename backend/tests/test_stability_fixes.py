# -*- coding: utf-8 -*-
from __future__ import annotations

import pathlib
import unittest
from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.routes.exports import ExportError, _xlsx_response
from app.services.export_service import ExportError as SvcExportError
from app.services.export_service import _build_xlsx, _make_workbook
from app.services.task_crud_service import _allocate_task_no, _dimension_ids_in_department


class FreshInstallSchemaTests(unittest.TestCase):
    def _schema_sql(self):
        return (pathlib.Path(__file__).resolve().parents[1] / "sql" / "schema_tables.sql").read_text(encoding="utf-8")

    def test_schema_tables_contains_task_dimension_tables(self):
        sql = self._schema_sql()
        for t in ["task_shops", "task_warehouses", "task_no_sequences", "product_name_aliases", "release_history"]:
            self.assertIn("CREATE TABLE IF NOT EXISTS " + t, sql)

    def test_schema_tables_has_foreign_keys(self):
        sql = self._schema_sql()
        for fk in ["fk_task_shops_task", "fk_task_shops_shop", "fk_task_warehouses_task", "fk_task_warehouses_warehouse"]:
            self.assertIn(fk, sql)


class EmptyExportTests(unittest.TestCase):
    def test_xlsx_response_empty_raises(self):
        with self.assertRaises(ExportError) as ctx:
            _xlsx_response(b"", "B2C_sales.xlsx", row_count=0, ascii_filename="B2C_sales.xlsx")
        self.assertIn("\u6682\u65e0\u53ef\u5bfc\u51fa", str(ctx.exception))

    def test_build_xlsx_empty_raises_before_generation(self):
        with self.assertRaises(SvcExportError):
            _build_xlsx("sales", [], "B2C")


class DimensionCandidateTests(unittest.TestCase):
    def _engine(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE warehouses(id INTEGER PRIMARY KEY,source_name TEXT)"))
            conn.execute(text("CREATE TABLE sales_daily(id INTEGER PRIMARY KEY,department_id INTEGER,warehouse_id INTEGER)"))
            conn.execute(text("CREATE TABLE inventory_batch(id INTEGER PRIMARY KEY,department_id INTEGER,warehouse_id INTEGER)"))
            conn.execute(text("CREATE TABLE aging_snapshot(id INTEGER PRIMARY KEY,department_id INTEGER,warehouse_id INTEGER)"))
            conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(1,'w1')"))
            conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(2,'w2')"))
            conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(3,'w3')"))
            conn.execute(text("INSERT INTO warehouses(id,source_name) VALUES(9,'w9')"))
            conn.execute(text("INSERT INTO sales_daily(department_id,warehouse_id) VALUES(1,1)"))
            conn.execute(text("INSERT INTO inventory_batch(department_id,warehouse_id) VALUES(1,2)"))
            conn.execute(text("INSERT INTO aging_snapshot(department_id,warehouse_id) VALUES(1,3)"))
        return engine

    def test_warehouse_candidates_cover_all_three_tables(self):
        db = Session(self._engine())
        result = _dimension_ids_in_department(db, 1, "warehouses", [1, 2, 3, 9])
        self.assertEqual(result, {1, 2, 3})
        self.assertNotIn(9, result)
        db.close()


class TaskNoSequenceTests(unittest.TestCase):
    def _engine(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE task_no_sequences(assign_date DATE PRIMARY KEY,last_seq INT NOT NULL DEFAULT 0)"))
            conn.execute(text("CREATE TABLE todo_tasks(id INTEGER PRIMARY KEY,task_no TEXT UNIQUE)"))
        return engine

    def test_increments_sequentially(self):
        db = Session(self._engine())
        self.assertEqual(_allocate_task_no(db, date(2026, 8, 25)), "TD20260825-001")
        self.assertEqual(_allocate_task_no(db, date(2026, 8, 25)), "TD20260825-002")
        self.assertEqual(_allocate_task_no(db, date(2026, 8, 25)), "TD20260825-003")
        db.close()

    def test_delete_does_not_reuse_or_rewind(self):
        db = Session(self._engine())
        a = _allocate_task_no(db, date(2026, 8, 25))
        b = _allocate_task_no(db, date(2026, 8, 25))
        # 模拟删除任务 b（真正 DELETE），编号不应回退
        db.execute(text("DELETE FROM todo_tasks WHERE task_no=:t"), {"t": b})
        db.commit()
        c = _allocate_task_no(db, date(2026, 8, 25))
        self.assertEqual(a, "TD20260825-001")
        self.assertEqual(c, "TD20260825-003")  # 不复用 002
        db.close()

    def test_different_dates_isolated(self):
        db = Session(self._engine())
        self.assertEqual(_allocate_task_no(db, date(2026, 8, 25)), "TD20260825-001")
        self.assertEqual(_allocate_task_no(db, date(2026, 8, 26)), "TD20260826-001")
        db.close()

    def test_backfill_from_historical_tasks_when_sequence_missing(self):
        # 历史任务 001~018 存在，但 sequence 表为空，allocator 应得到 019 而非复用 001。
        db = Session(self._engine())
        for i in range(1, 19):
            db.execute(
                text("INSERT INTO todo_tasks(id, task_no) VALUES(:id, :t)"),
                {"id": i, "t": f"TD20260825-{i:03d}"},
            )
        db.commit()
        self.assertEqual(_allocate_task_no(db, date(2026, 8, 25)), "TD20260825-019")
        db.close()

    def test_delete_latest_then_allocate_does_not_reuse(self):
        # 历史 001~018 + sequence 空：先 allocator 初始化到 019；
        # 再删除 018（历史最大），allocator 仍得 020，不复用 018/019。
        db = Session(self._engine())
        for i in range(1, 19):
            db.execute(
                text("INSERT INTO todo_tasks(id, task_no) VALUES(:id, :t)"),
                {"id": i, "t": f"TD20260825-{i:03d}"},
            )
        db.commit()
        self.assertEqual(_allocate_task_no(db, date(2026, 8, 25)), "TD20260825-019")
        # 删除最新的历史任务 018
        db.execute(text("DELETE FROM todo_tasks WHERE task_no='TD20260825-018'"))
        db.commit()
        self.assertEqual(_allocate_task_no(db, date(2026, 8, 25)), "TD20260825-020")
        db.close()


class MigrationSha256Tests(unittest.TestCase):
    """migration checksum 跨平台：CRLF/CR 标准化为 LF，LF 与 CRLF 内容不 drift。"""

    def _import_mod(self):
        import importlib.util
        import sys
        scripts_dir = pathlib.Path(__file__).resolve().parents[2] / "scripts"
        spec = importlib.util.spec_from_file_location("release_tool_mod", scripts_dir / "release_tool.py")
        mod = importlib.util.module_from_spec(spec)
        backend_dir = str(pathlib.Path(__file__).resolve().parents[1])
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        spec.loader.exec_module(mod)
        return mod

    def test_lf_and_crlf_same_checksum(self):
        import tempfile
        mod = self._import_mod()
        content = "CREATE TABLE t(id INT);\nINSERT INTO t VALUES(1);\n"
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td)
            lf = p / "lf.sql"
            crlf = p / "crlf.sql"
            lf.write_text(content, encoding="utf-8", newline="\n")
            crlf.write_text(content, encoding="utf-8", newline="\r\n")
            self.assertEqual(mod.migration_sha256(lf), mod.migration_sha256(crlf))

    def test_cr_also_normalized(self):
        import tempfile
        mod = self._import_mod()
        content = "CREATE TABLE t(id INT);\n"
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td)
            lf = p / "lf.sql"
            cr = p / "cr.sql"
            lf.write_text(content, encoding="utf-8", newline="\n")
            cr.write_bytes(content.replace("\n", "\r").encode("utf-8"))
            self.assertEqual(mod.migration_sha256(lf), mod.migration_sha256(cr))

    def test_legacy_crlf_checksum_accepted(self):
        # 旧 Windows 存 raw CRLF checksum，新 checkout 为 LF，应判定合法（不 drift）。
        import tempfile
        mod = self._import_mod()
        content = "CREATE TABLE t(id INT);\nINSERT INTO t VALUES(1);\n"
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td)
            lf = p / "lf.sql"
            crlf = p / "crlf.sql"
            lf.write_text(content, encoding="utf-8", newline="\n")
            crlf.write_text(content, encoding="utf-8", newline="\r\n")
            # recorded = 旧 raw CRLF checksum（sha256(crlf bytes)）
            recorded = mod.sha256(crlf)
            # 当前 path 用 LF，accepted 应包含 legacy_crlf_sha256（= raw CRLF）
            accepted = {mod.migration_sha256(lf), mod.sha256(lf), mod.legacy_crlf_sha256(lf)}
            self.assertIn(recorded, accepted)


class BootstrapMigrationTableTests(unittest.TestCase):
    """bootstrap_migration_table 的 legacy baseline 只应标记 0141~0147，不含 0151 及之后。"""

    def _import_mod(self):
        import importlib.util
        import sys
        scripts_dir = pathlib.Path(__file__).resolve().parents[2] / "scripts"
        spec = importlib.util.spec_from_file_location("release_tool_mod2", scripts_dir / "release_tool.py")
        mod = importlib.util.module_from_spec(spec)
        backend_dir = str(pathlib.Path(__file__).resolve().parents[1])
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        spec.loader.exec_module(mod)
        return mod

    def test_legacy_baseline_only_0141_to_0147(self):
        from unittest import mock
        mod = self._import_mod()

        executed = []

        class FakeCursor:
            def __init__(self):
                self._calls = []
            def execute(self, sql, args=None):
                self._calls.append((sql, args))
            def fetchone(self):
                sql = self._calls[-1][0] if self._calls else ""
                if "COUNT(*)" in sql:
                    return (0,)  # schema_migrations 空
                if "SHOW TABLES" in sql:
                    return ("users",)  # 旧库有 users 表
                return None
            def executemany(self, sql, seq):
                executed.extend(row[0] for row in seq)
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        conn = mock.MagicMock()
        conn.cursor.return_value = FakeCursor()
        mod.bootstrap_migration_table(conn)

        # 只 baseline 0141~0147
        self.assertEqual(sorted(executed), sorted([
            "0141_import_pipeline", "0142_dashboard_indexes", "0145_import_center_indexes",
            "0146_auth_sessions", "0147_audit_indexes",
        ]))
        # 0151~0155 不在 baseline
        for mid in ["0151_release_chain", "0152_product_alias_latest_snapshot",
                    "0153_task_multi_dimensions", "0154_task_no_sequences",
                    "0155_task_no_sequence_backfill"]:
            self.assertNotIn(mid, executed)


if __name__ == "__main__":
    unittest.main()
