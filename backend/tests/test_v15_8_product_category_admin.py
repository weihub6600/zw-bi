import json
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.admin_service import list_product_category_admin, set_product_categories
from app.services.permission_service import PermissionDenied


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as db:
        db.execute(text("CREATE TABLE departments(id INTEGER PRIMARY KEY,code TEXT,name TEXT,status TEXT)"))
        db.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,user_id TEXT,username TEXT,is_system_admin INTEGER,status TEXT)"))
        db.execute(text("CREATE TABLE user_departments(user_pk INTEGER,department_id INTEGER,role TEXT,status TEXT)"))
        db.execute(text("CREATE TABLE products(id INTEGER PRIMARY KEY,merchant_code TEXT,product_name TEXT,spec TEXT,brand TEXT,category TEXT,import_batch_id INTEGER,updated_at DATETIME)"))
        db.execute(text("CREATE TABLE product_categories(id INTEGER PRIMARY KEY AUTOINCREMENT,category_name TEXT UNIQUE)"))
        db.execute(text("CREATE TABLE product_category_relations(id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER,category_id INTEGER,UNIQUE(product_id,category_id))"))
        for table in ("sales_daily", "inventory_batch", "aging_snapshot"):
            db.execute(text(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY,department_id INTEGER,product_id INTEGER)"))
        db.execute(text("CREATE TABLE import_batches(id INTEGER PRIMARY KEY,department_id INTEGER)"))
        db.execute(text("CREATE TABLE activity_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_pk INTEGER,department_id INTEGER,action_type TEXT,action_detail TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO departments VALUES(1,'B2C','B2C','enabled'),(2,'B2B','B2B','enabled')"))
        db.execute(text("INSERT INTO users VALUES(10,'DEP','部门管理员',0,'enabled')"))
        db.execute(text("INSERT INTO user_departments VALUES(10,1,'dept_admin','enabled')"))
        db.execute(text("INSERT INTO products(id,merchant_code,product_name) VALUES(1,'A001','可乐'),(2,'B001','饼干')"))
        db.execute(text("INSERT INTO sales_daily VALUES(1,1,1),(2,2,2)"))
        db.execute(text("INSERT INTO product_categories(id,category_name) VALUES(1,'饮料'),(2,'零食')"))
    return engine


class V158ProductCategoryAdminTests(unittest.TestCase):
    actor = {"user_pk": 10, "user_id": "DEP", "username": "部门管理员", "is_system_admin": False, "status": "enabled"}

    def test_department_admin_is_scoped_to_managed_department(self):
        with Session(_engine()) as db:
            result = list_product_category_admin(db, self.actor, "B2C")
            self.assertEqual([row["product_id"] for row in result["items"]], [1])
            with self.assertRaises(PermissionDenied):
                set_product_categories(db, self.actor, "B2C", [2], [1])

    def test_assignment_replaces_categories_and_legacy_column(self):
        with Session(_engine()) as db:
            set_product_categories(db, self.actor, "B2C", [1], [1, 2])
            names = db.execute(text("SELECT category_name FROM product_categories pc JOIN product_category_relations pcr ON pcr.category_id=pc.id WHERE pcr.product_id=1 ORDER BY category_name")).scalars().all()
            self.assertEqual(names, sorted(["饮料", "零食"]))
            self.assertEqual(json.loads(db.execute(text("SELECT category FROM products WHERE id=1")).scalar_one()), sorted(["饮料", "零食"]))
            set_product_categories(db, self.actor, "B2C", [1], [2])
            self.assertEqual(db.execute(text("SELECT COUNT(*) FROM product_category_relations WHERE product_id=1")).scalar_one(), 1)
            self.assertEqual(json.loads(db.execute(text("SELECT category FROM products WHERE id=1")).scalar_one()), ["零食"])


if __name__ == "__main__":
    unittest.main()
