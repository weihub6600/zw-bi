from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from app.services.dashboard_service import DashboardScope, selected_sales_range


class V153UpdatesTests(unittest.TestCase):
    def test_date_presets_anchor_to_latest_sales_date(self):
        latest = date(2026, 8, 20)
        start, end, days = selected_sales_range(DashboardScope(actor_user_id="U", days=1), latest)
        self.assertEqual((start, end, days), (date(2026, 8, 20), date(2026, 8, 20), 1))
        start, end, days = selected_sales_range(DashboardScope(actor_user_id="U", days=14), latest)
        self.assertEqual((start, end, days), (date(2026, 8, 7), date(2026, 8, 20), 14))

    def test_custom_date_range(self):
        latest = date(2026, 8, 20)
        scope = DashboardScope(actor_user_id="U", start_date=date(2026, 7, 25), end_date=date(2026, 8, 5))
        start, end, days = selected_sales_range(scope, latest)
        self.assertEqual(start, date(2026, 7, 25))
        self.assertEqual(end, date(2026, 8, 5))
        self.assertEqual(days, 12)

    def test_sales_import_is_date_replace_not_duplicate_block(self):
        root = Path(__file__).resolve().parents[1]
        service = (root / "app" / "services" / "import_db_service.py").read_text(encoding="utf-8")
        routes = (root / "app" / "routes" / "imports.py").read_text(encoding="utf-8")
        self.assertIn("_prepare_sales_date_replace", service)
        self.assertIn('duplicate and parsed.data_type != "sales"', service)
        self.assertIn('result["replace_existing"]', routes)

    def test_product_shop_sales_is_exposed(self):
        root = Path(__file__).resolve().parents[1]
        service = (root / "app" / "services" / "analysis_service.py").read_text(encoding="utf-8")
        self.assertIn("def _product_shop_sales", service)
        self.assertIn('"shop_sales": shop_sales', service)


if __name__ == "__main__":
    unittest.main()
