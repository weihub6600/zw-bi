import os
import unittest
from pathlib import Path

import pymysql
from sqlalchemy import create_engine, text

from app.core.config import settings


@unittest.skipUnless(os.getenv("RUN_MYSQL_INTEGRATION") == "1", "需要 RUN_MYSQL_INTEGRATION=1 的隔离 MySQL")
class MySQLIntegrationTests(unittest.TestCase):
    def test_connection_schema_and_foreign_keys(self):
        engine = create_engine(settings.effective_database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar_one()
            self.assertTrue(str(version).lower().find("mariadb") < 0, version)
            self.assertEqual(conn.execute(text("SELECT DATABASE()")).scalar_one(), settings.mysql_database)
            tables = {
                row[0]
                for row in conn.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()")
                )
            }
            self.assertIn("products", tables)
            self.assertIn("product_category_relations", tables)
            fks = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT constraint_name FROM information_schema.table_constraints "
                        "WHERE table_schema=DATABASE() AND table_name='product_category_relations' "
                        "AND constraint_type='FOREIGN KEY'"
                    )
                )
            }
            self.assertTrue({"fk_product_category_product", "fk_product_category_category"} <= fks)

    def test_product_category_fk_migration_is_executable_on_mysql(self):
        from scripts.release_tool import apply_sql, connect

        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE product_category_relations DROP FOREIGN KEY fk_product_category_product")
                cursor.execute("ALTER TABLE product_category_relations DROP FOREIGN KEY fk_product_category_category")
            migration = Path("backend/sql/migrations/0158_product_category_foreign_keys.sql").read_text(encoding="utf-8")
            apply_sql(connection, migration)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.table_constraints "
                    "WHERE table_schema=DATABASE() AND table_name='product_category_relations' "
                    "AND constraint_type='FOREIGN KEY'"
                )
                self.assertEqual(cursor.fetchone()[0], 2)
        finally:
            connection.close()

    def test_mysql_unique_and_foreign_key_behavior(self):
        from scripts.release_tool import connect

        connection = connect()
        connection.autocommit(True)
        try:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM product_categories WHERE category_name='__ci_unique_category__'")
                cursor.execute("INSERT INTO product_categories(category_name) VALUES('__ci_unique_category__')")
                with self.assertRaises(pymysql.err.IntegrityError):
                    cursor.execute("INSERT INTO product_categories(category_name) VALUES('__ci_unique_category__')")
                cursor.execute("SELECT id FROM product_categories WHERE category_name='__ci_unique_category__'")
                category_id = cursor.fetchone()[0]
                with self.assertRaises(pymysql.err.IntegrityError):
                    cursor.execute(
                        "INSERT INTO product_category_relations(product_id,category_id) VALUES(%s,%s)",
                        (9_999_999_999, category_id),
                    )
                cursor.execute("DELETE FROM product_categories WHERE id=%s", (category_id,))
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
