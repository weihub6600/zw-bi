from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.admin_service import delete_product_category, set_product_categories
from app.services.export_service import _product_rows
from app.services.import_db_service import _get_or_create_product, _restore_update, _sync_product_categories
from app.services.product_category_codec import parse_category_names, serialize_category_names


def _category_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as db:
        db.execute(text("CREATE TABLE product_categories(id INTEGER PRIMARY KEY AUTOINCREMENT,category_name TEXT UNIQUE)"))
        db.execute(text("CREATE TABLE product_category_relations(id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER,category_id INTEGER,UNIQUE(product_id,category_id))"))
        db.execute(text("CREATE TABLE products(id INTEGER PRIMARY KEY,merchant_code TEXT UNIQUE,product_name TEXT,spec TEXT,brand TEXT,category TEXT,barcode TEXT,import_batch_id INTEGER)"))
        db.execute(text("CREATE TABLE sales_daily(id INTEGER PRIMARY KEY,department_id INTEGER,product_id INTEGER)"))
        db.execute(text("CREATE TABLE inventory_batch(id INTEGER PRIMARY KEY,department_id INTEGER,product_id INTEGER)"))
        db.execute(text("CREATE TABLE aging_snapshot(id INTEGER PRIMARY KEY,department_id INTEGER,product_id INTEGER)"))
        db.execute(text("CREATE TABLE import_batches(id INTEGER PRIMARY KEY,department_id INTEGER)"))
    return engine


class ProductCategoryCodecTests(unittest.TestCase):
    def test_json_round_trip_and_legacy_special_punctuation(self):
        names = ["饮料", "进口食品", "礼盒、套装", "A,B"]
        encoded = serialize_category_names(names)
        self.assertEqual(parse_category_names(encoded), names)
        self.assertEqual(parse_category_names("礼盒、套装", known_names=["礼盒、套装"]), ["礼盒、套装"])
        self.assertEqual(parse_category_names("饮料、进口食品", known_names=["饮料", "进口食品"]), ["饮料", "进口食品"])

    def test_empty_category_serializes_to_null(self):
        self.assertIsNone(serialize_category_names([]))
        self.assertEqual(parse_category_names(None), [])

    def test_integrity_migration_adds_both_foreign_keys_without_editing_0157(self):
        root = Path(__file__).resolve().parents[1]
        migration = (root / "sql" / "migrations" / "0158_product_category_foreign_keys.sql").read_text(encoding="utf-8")
        self.assertIn("fk_product_category_product", migration)
        self.assertIn("fk_product_category_category", migration)
        self.assertIn("ON DELETE CASCADE", migration)


class ProductCategoryImportRollbackTests(unittest.TestCase):
    def test_export_then_import_keeps_two_categories_independent(self):
        engine = _category_engine()
        with engine.begin() as db:
            db.execute(text("INSERT INTO products(id,merchant_code,product_name) VALUES(1,'SKU-A','商品A')"))
            db.execute(text("INSERT INTO sales_daily(id,department_id,product_id) VALUES(1,1,1)"))
        with Session(engine) as db:
            encoded = serialize_category_names(["饮料", "进口食品"])
            _sync_product_categories(db, 1, encoded)
            db.execute(text("UPDATE products SET category=:category WHERE id=1"), {"category": encoded})
            db.commit()
            exported = _product_rows(db, 1)[0][4]
            self.assertEqual(set(json.loads(exported)), {"饮料", "进口食品"})
            _sync_product_categories(db, 1, exported)
            ids = db.execute(text("SELECT category_id FROM product_category_relations WHERE product_id=1 ORDER BY category_id")).scalars().all()
            names = db.execute(text("SELECT category_name FROM product_categories WHERE id IN (1,2) ORDER BY id")).scalars().all()
        self.assertEqual(len(ids), 2)
        self.assertEqual(set(names), {"饮料", "进口食品"})

    def test_rollback_restores_relation_ids_not_just_display_text(self):
        engine = _category_engine()
        with engine.begin() as db:
            db.execute(text("INSERT INTO products(id,merchant_code,product_name,category) VALUES(1,'SKU-A','商品A','新的分类')"))
            db.execute(text("INSERT INTO product_categories(id,category_name) VALUES(1,'饮料'),(2,'进口食品'),(3,'新的分类')"))
            db.execute(text("INSERT INTO product_category_relations(product_id,category_id) VALUES(1,3)"))
        with Session(engine) as db:
            _restore_update(
                db,
                "products",
                1,
                {"product_name": "商品A", "spec": None, "brand": None, "category": serialize_category_names(["饮料", "进口食品"]), "barcode": None, "import_batch_id": None, "category_ids": [1, 2]},
            )
            ids = db.execute(text("SELECT category_id FROM product_category_relations WHERE product_id=1 ORDER BY category_id")).scalars().all()
        self.assertEqual(ids, [1, 2])

    def test_relation_only_change_is_recorded_for_rollback(self):
        engine = _category_engine()
        encoded = serialize_category_names(["饮料", "进口食品"])
        with engine.begin() as db:
            db.execute(
                text("INSERT INTO products(id,merchant_code,product_name,category) VALUES(1,'SKU-A','商品A',:category)"),
                {"category": encoded},
            )
            db.execute(text("INSERT INTO product_categories(id,category_name) VALUES(1,'饮料'),(2,'进口食品')"))
            db.execute(text("INSERT INTO product_category_relations(product_id,category_id) VALUES(1,1)"))
        with Session(engine) as db, mock.patch("app.services.import_db_service._record_change") as record_change:
            _get_or_create_product(
                db,
                99,
                {"merchant_code": "SKU-A", "product_name": "商品A", "spec": None, "brand": None, "category": encoded, "barcode": None},
                "product",
                [],
            )
            before = record_change.call_args.args[5]
            self.assertEqual(before["category_ids"], [1])
            ids = db.execute(text("SELECT category_id FROM product_category_relations WHERE product_id=1 ORDER BY category_id")).scalars().all()
        self.assertEqual(ids, [1, 2])


class ProductCategoryBoundaryTests(unittest.TestCase):
    def test_shared_sku_category_assignment_is_global_current_behavior(self):
        # This documents the existing global product-master model; it is not
        # changed without a business decision about department-owned labels.
        from backend.tests.test_v15_8_product_category_admin import _engine

        engine = _engine()
        with engine.begin() as db:
            db.execute(text("INSERT INTO sales_daily VALUES(3,2,1)"))
            db.execute(text("INSERT INTO product_categories(id,category_name) VALUES(3,'进口食品')"))
        actor = {"user_pk": 10, "user_id": "DEP", "username": "部门管理员", "is_system_admin": False, "status": "enabled"}
        with Session(engine) as db:
            set_product_categories(db, actor, "B2C", [1], [3])
            self.assertEqual(db.execute(text("SELECT category_id FROM product_category_relations WHERE product_id=1")).scalar_one(), 3)

    def test_invalid_category_id_is_rejected_and_linked_category_cannot_delete(self):
        from backend.tests.test_v15_8_product_category_admin import _engine

        engine = _engine()
        actor = {"user_pk": 10, "user_id": "DEP", "username": "部门管理员", "is_system_admin": False, "status": "enabled"}
        with Session(engine) as db:
            with self.assertRaises(ValueError):
                set_product_categories(db, actor, "B2C", [1], [999])
        system_actor = {"user_pk": 1, "user_id": "SYS", "username": "系统管理员", "is_system_admin": True, "status": "enabled"}
        with engine.begin() as db:
            db.execute(text("INSERT INTO product_category_relations(product_id,category_id) VALUES(1,1)"))
        with Session(engine) as db:
            with self.assertRaises(ValueError):
                delete_product_category(db, system_actor, "B2C", 1)


if __name__ == "__main__":
    unittest.main()
