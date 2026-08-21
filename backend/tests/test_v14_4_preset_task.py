from datetime import date
import unittest

from app.services.dashboard_service import DashboardScope, _scope_clauses
from app.services.preset_service import normalize_string_list
from app.services.task_crud_service import task_window_complete, task_window_end
from app.services.task_service import task_start_date


class V144RulesTests(unittest.TestCase):
    def test_personal_preset_lists_keep_order_and_deduplicate(self):
        self.assertEqual(normalize_string_list(["主仓", " 主仓 ", "华东仓", ""]), ["主仓", "华东仓"])

    def test_specific_product_codes_become_scope_filter(self):
        params = {}
        clauses = _scope_clauses(
            DashboardScope(actor_user_id="U1", product_codes=("SKU-A", "SKU-B")),
            params,
        )
        self.assertTrue(any("merchant_code IN" in x for x in clauses))
        self.assertEqual(params["product_code_0"], "SKU-A")
        self.assertEqual(params["product_code_1"], "SKU-B")

    def test_task_starts_day_after_assign(self):
        self.assertEqual(task_start_date(date(2026, 8, 20)), date(2026, 8, 21))

    def test_task_window_completion_is_explicit(self):
        start = date(2026, 8, 21)
        self.assertEqual(task_window_end(start, 7), date(2026, 8, 27))
        self.assertFalse(task_window_complete(start, 7, date(2026, 8, 26)))
        self.assertTrue(task_window_complete(start, 7, date(2026, 8, 27)))


if __name__ == "__main__":
    unittest.main()
