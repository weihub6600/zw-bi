from __future__ import annotations

import unittest
from pathlib import Path

from app.services.dashboard_service import DashboardScope, _scope_clauses
from app.services.analysis_service import _product_category_names_by_product
from app.services.import_db_service import _sync_product_categories
from app.services.preset_service import normalize_int_list
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


class ProductCategoryCompletionTests(unittest.TestCase):
    def test_category_scope_clause_is_parameterized(self):
        params = {}
        clauses = _scope_clauses(
            DashboardScope(actor_user_id="U1", product_category_ids=(3, 9)),
            params,
        )
        self.assertEqual(params["product_category_id_0"], 3)
        self.assertEqual(params["product_category_id_1"], 9)
        self.assertEqual(len(clauses), 1)
        self.assertIn("product_category_relations", clauses[0])
        self.assertIn("pcr.category_id IN", clauses[0])

    def test_preset_category_ids_are_cleaned(self):
        self.assertEqual(normalize_int_list([2, "2", 0, -1, "x", 7]), [2, 7])

    def test_product_category_sync_replaces_and_clears_relations(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE product_categories(id INTEGER PRIMARY KEY,category_name TEXT UNIQUE)"))
            conn.execute(text("CREATE TABLE product_category_relations(product_id INTEGER,category_id INTEGER,UNIQUE(product_id,category_id))"))
        with Session(engine) as db:
            _sync_product_categories(db, 8, "冷藏，饮品")
            self.assertEqual(db.execute(text("SELECT COUNT(*) FROM product_category_relations WHERE product_id=8")).scalar_one(), 2)
            _sync_product_categories(db, 8, None)
            self.assertEqual(db.execute(text("SELECT COUNT(*) FROM product_category_relations WHERE product_id=8")).scalar_one(), 0)

    def test_inventory_category_names_fall_back_to_legacy_product_field(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE products(id INTEGER PRIMARY KEY,category TEXT)"))
            conn.execute(text("CREATE TABLE product_categories(id INTEGER PRIMARY KEY,category_name TEXT UNIQUE)"))
            conn.execute(text("CREATE TABLE product_category_relations(product_id INTEGER,category_id INTEGER)"))
            conn.execute(text("INSERT INTO products(id,category) VALUES(1,'饮料，碳酸'),(2,'旧分类')"))
            conn.execute(text("INSERT INTO product_categories(id,category_name) VALUES(9,'新分类')"))
            conn.execute(text("INSERT INTO product_category_relations(product_id,category_id) VALUES(2,9)"))
        with Session(engine) as db:
            categories = _product_category_names_by_product(db, [1, 2])
        self.assertEqual(categories[1], "饮料、碳酸")
        self.assertEqual(categories[2], "新分类")

    def test_inventory_category_names_work_when_relation_tables_are_missing(self):
        """Restored older databases may have products.category but no 0157 tables yet."""
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE products(id INTEGER PRIMARY KEY,category TEXT)"))
            conn.execute(text("INSERT INTO products(id,category) VALUES(7,'饮品|无糖\\n碳酸')"))
        with Session(engine) as db:
            categories = _product_category_names_by_product(db, [7])
        self.assertEqual(categories[7], "饮品、无糖、碳酸")

    def test_category_migration_backfills_and_schema_has_tables(self):
        root = Path(__file__).resolve().parents[1]
        migration = (root / "sql" / "migrations" / "0157_product_categories.sql").read_text(encoding="utf-8")
        schema = (root / "sql" / "schema_tables.sql").read_text(encoding="utf-8")
        self.assertIn("INSERT IGNORE INTO product_categories", migration)
        self.assertIn("INSERT IGNORE INTO product_category_relations", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS product_categories", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS product_category_relations", schema)

    def test_inventory_detail_and_frontend_filter_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        analysis = (root / "app" / "services" / "analysis_service.py").read_text(encoding="utf-8")
        inventory = (root.parent / "frontend" / "src" / "views" / "InventoryView.vue").read_text(encoding="utf-8")
        filter_bar = (root.parent / "frontend" / "src" / "components" / "FilterBar.vue").read_text(encoding="utf-8")
        self.assertIn("def _inventory_by_product_warehouse", analysis)
        self.assertIn("detail_warehouses", analysis)
        self.assertIn("warehouse_stocks", analysis)
        self.assertIn("detailWarehouses", inventory)
        self.assertIn("productCategoryIds", filter_bar)

    def test_product_shop_selection_and_yesterday_sales_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        analysis = (root / "app" / "services" / "analysis_service.py").read_text(encoding="utf-8")
        product = (root.parent / "frontend" / "src" / "views" / "ProductView.vue").read_text(encoding="utf-8")
        self.assertIn("AS sales_yesterday", analysis)
        self.assertIn('"shop_sales_options": shop_sales_options', analysis)
        self.assertIn("toggleShop(r.shop,$event)", product)
        self.assertIn("applyShopSelection", product)
        self.assertIn("yesterday_sales_available", analysis)
        self.assertIn("v-if=\"showYesterdaySales\"", product)
        self.assertIn("昨日销量", product)

    def test_migrations_use_legacy_utf8mb4_collation_for_json_values(self):
        root = Path(__file__).resolve().parents[1]
        release_tool = (root.parent / "scripts" / "release_tool.py").read_text(encoding="utf-8")
        self.assertIn("SET NAMES utf8mb4 COLLATE utf8mb4_general_ci", release_tool)

    def test_baota_upgrade_uses_supervisor_when_configured(self):
        root = Path(__file__).resolve().parents[1]
        update_script = (root.parent / "deploy" / "baota" / "update.sh").read_text(encoding="utf-8")
        self.assertIn("SUPERVISOR_PROGRAM", update_script)
        self.assertIn("supervisorctl stop", update_script)
        self.assertIn("supervisorctl start", update_script)


if __name__ == "__main__":
    unittest.main()
