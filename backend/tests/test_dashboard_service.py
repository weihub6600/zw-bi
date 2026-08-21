from __future__ import annotations

import unittest

from app.services.dashboard_service import build_rankings, parse_keywords


class DashboardServiceTests(unittest.TestCase):
    def test_parse_keywords_supports_chinese_comma_and_spaces(self):
        self.assertEqual(parse_keywords("泡菜，海苔 赠品"), ["泡菜", "海苔", "赠品"])

    def test_shortage_top_excludes_zero_stock(self):
        products = [
            {"product_id": 1, "sku": "A", "name": "A", "selected_sales": 1000, "selected_revenue": 10000, "sales30": 3000, "stock": 0, "predicted_daily": 100, "cover_days": None, "risk_level": "不适用"},
            {"product_id": 2, "sku": "B", "name": "B", "selected_sales": 900, "selected_revenue": 9000, "sales30": 2700, "stock": 500, "predicted_daily": 120, "cover_days": 4.2, "risk_level": "紧急"},
            {"product_id": 3, "sku": "C", "name": "C", "selected_sales": 100, "selected_revenue": 1000, "sales30": 300, "stock": 100, "predicted_daily": 10, "cover_days": 10, "risk_level": "紧急"},
        ]
        result = build_rankings(products, 30, False)
        ids = [x["product_id"] for x in result["shortage"]]
        self.assertNotIn(1, ids)
        self.assertIn(2, ids)

    def test_sales_amount_ranking_only_single_shop(self):
        products = [
            {"product_id": 1, "sku": "A", "name": "A", "selected_sales": 10, "selected_revenue": 200, "sales30": 10, "stock": 10, "predicted_daily": 1, "cover_days": 10, "risk_level": "紧急"},
        ]
        self.assertEqual(build_rankings(products, 30, False)["sales_amount"], [])
        single = build_rankings(products, 30, True)["sales_amount"]
        self.assertEqual(len(single), 1)
        self.assertEqual(single[0]["sales_amount"], 200.0)

    def test_slow_ranking_includes_no_sales_stock(self):
        products = [
            {"product_id": 1, "sku": "A", "name": "A", "selected_sales": 0, "selected_revenue": 0, "sales30": 0, "stock": 500, "predicted_daily": 0, "cover_days": None, "risk_level": "不适用"},
            {"product_id": 2, "sku": "B", "name": "B", "selected_sales": 100, "selected_revenue": 1000, "sales30": 300, "stock": 200, "predicted_daily": 10, "cover_days": 20, "risk_level": "高风险"},
        ]
        result = build_rankings(products, 30, False)["slow"]
        self.assertEqual(result[0]["product_id"], 1)
        self.assertEqual(result[0]["risk_level"], "无销量库存")
        self.assertIsNone(result[0]["turnover_days"])


if __name__ == "__main__":
    unittest.main()
