import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.analysis_service import _product_visible_in_department, classify_inventory_health


class InventoryClassificationTests(unittest.TestCase):
    def test_no_sales_has_priority(self):
        self.assertEqual(
            classify_inventory_health(stock=100, sales30=0, cover_days=None, weighted_aging_days=300),
            "no_sales",
        )

    def test_stagnant_by_aging(self):
        self.assertEqual(
            classify_inventory_health(stock=100, sales30=50, cover_days=60, weighted_aging_days=180),
            "stagnant",
        )

    def test_stagnant_by_cover(self):
        self.assertEqual(
            classify_inventory_health(stock=100, sales30=50, cover_days=181, weighted_aging_days=20),
            "stagnant",
        )

    def test_high_stock_by_cover(self):
        self.assertEqual(
            classify_inventory_health(stock=100, sales30=50, cover_days=100, weighted_aging_days=20),
            "high",
        )

    def test_healthy(self):
        self.assertEqual(
            classify_inventory_health(stock=100, sales30=50, cover_days=50, weighted_aging_days=20),
            "healthy",
        )

    def test_zero_stock_is_not_mixed_into_health_classifier(self):
        # get_inventory_analysis assigns the dedicated stockout class before
        # calling this positive-stock health classifier.
        self.assertEqual(
            classify_inventory_health(stock=0, sales30=20, cover_days=None, weighted_aging_days=None),
            "healthy",
        )


class ProductVisibilityTests(unittest.TestCase):
    def test_direct_product_visibility_is_scoped_to_department(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE products(id INTEGER PRIMARY KEY,import_batch_id INTEGER)"))
            conn.execute(text("CREATE TABLE import_batches(id INTEGER PRIMARY KEY,department_id INTEGER)"))
            conn.execute(text("CREATE TABLE sales_daily(id INTEGER PRIMARY KEY,department_id INTEGER,product_id INTEGER)"))
            conn.execute(text("CREATE TABLE inventory_batch(id INTEGER PRIMARY KEY,department_id INTEGER,product_id INTEGER)"))
            conn.execute(text("CREATE TABLE aging_snapshot(id INTEGER PRIMARY KEY,department_id INTEGER,product_id INTEGER)"))
            conn.execute(text("INSERT INTO products(id,import_batch_id) VALUES(1,NULL),(2,NULL),(3,10)"))
            conn.execute(text("INSERT INTO sales_daily VALUES(1,1,1),(2,2,2)"))
            conn.execute(text("INSERT INTO import_batches VALUES(10,1)"))
        member = {"is_system_admin": False}
        system = {"is_system_admin": True}
        with Session(engine) as db:
            self.assertTrue(_product_visible_in_department(db, member, 1, 1))
            self.assertFalse(_product_visible_in_department(db, member, 1, 2))
            self.assertTrue(_product_visible_in_department(db, member, 1, 3))
            self.assertTrue(_product_visible_in_department(db, system, 1, 2))


if __name__ == "__main__":
    unittest.main()
