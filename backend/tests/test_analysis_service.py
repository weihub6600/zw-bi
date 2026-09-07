import unittest

from app.services.analysis_service import classify_inventory_health


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


if __name__ == "__main__":
    unittest.main()
