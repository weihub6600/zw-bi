from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from app.services.dashboard_service import DashboardScope, comparison_periods


class V154UpdatesTests(unittest.TestCase):
    def test_comparison_periods_for_30_days(self):
        latest = date(2026, 8, 20)
        p = comparison_periods(DashboardScope(actor_user_id='U', days=30), latest)
        self.assertEqual(p['current'], (date(2026, 7, 22), date(2026, 8, 20)))
        self.assertEqual(p['mom'], (date(2026, 6, 22), date(2026, 7, 21)))
        self.assertEqual(p['yoy'], (date(2025, 7, 22), date(2025, 8, 20)))

    @unittest.skipUnless((Path(__file__).resolve().parents[1].parent / 'frontend/src/views/ProductView.vue').exists(), "前端源码不在发布包中，跳过前端一致性检查")
    def test_product_search_and_comparison_are_exposed(self):
        root = Path(__file__).resolve().parents[1]
        service = (root / 'app' / 'services' / 'analysis_service.py').read_text(encoding='utf-8')
        routes = (root / 'app' / 'routes' / 'analysis.py').read_text(encoding='utf-8')
        view = (root.parent / 'frontend' / 'src' / 'views' / 'ProductView.vue').read_text(encoding='utf-8')
        self.assertIn('def search_products(', service)
        self.assertIn('"comparison": comparison', service)
        self.assertIn('@router.get("/products/search")', routes)
        self.assertLess(routes.index('@router.get("/products/search")'), routes.index('@router.get("/products/{merchant_code}")'))
        self.assertIn('输入商家编码或商品名称', view)
        self.assertIn('全部店铺', view)
        self.assertIn('全部仓库', view)
        self.assertIn('同比 · 去年同期', view)
        self.assertIn('环比 · 上一等长区间', view)


if __name__ == '__main__':
    unittest.main()
