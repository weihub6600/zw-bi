from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class Round1SecurityRegressionTests(unittest.TestCase):
    def test_ci_runs_tests_from_repo_root_with_backend_path(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("PYTHONPATH: backend", ci)
        self.assertIn('python -m unittest discover -s backend/tests -p "test_*.py"', ci)
        self.assertIn('python -m unittest discover -s backend/tests -p "test_mysql_integration.py" -v', ci)

    def test_product_tooltip_escapes_imported_shop_text(self):
        source = (ROOT / "frontend" / "src" / "views" / "ProductView.vue").read_text(encoding="utf-8")
        self.assertIn("function escapeTooltipText", source)
        self.assertIn("escapeTooltipText(row.shop)", source)
        self.assertNotIn("return `${row.shop||''}", source)

    def test_service_boundaries_are_present(self):
        admin = (ROOT / "backend" / "app" / "services" / "admin_service.py").read_text(encoding="utf-8")
        analysis = (ROOT / "backend" / "app" / "services" / "analysis_service.py").read_text(encoding="utf-8")
        self.assertIn("department_id=:did", admin)
        self.assertIn("def _product_visible_in_department", analysis)
        self.assertIn("_product_visible_in_department(db, actor", analysis)


if __name__ == "__main__":
    unittest.main()
