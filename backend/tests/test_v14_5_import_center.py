from __future__ import annotations

import unittest
from datetime import date

from pathlib import Path
from app.services.import_parser import ParsedImport, RowError, preview_commit_policy


class V145ImportCenterTests(unittest.TestCase):
    def test_preview_allows_valid_rows(self):
        parsed = ParsedImport(data_type="sales", source_file="8月19.xlsx", business_date=date(2026, 8, 19))
        parsed.rows.append({"row_no": 2, "merchant_code": "A001"})
        self.assertEqual(preview_commit_policy(parsed), {"commit_allowed": True, "partial_import": False})

    def test_preview_marks_partial_import_when_errors_exist(self):
        parsed = ParsedImport(data_type="sales", source_file="8月19.xlsx", business_date=date(2026, 8, 19))
        parsed.rows.append({"row_no": 2, "merchant_code": "A001"})
        parsed.errors.append(RowError(row_no=3, code="INVALID_NUMBER", message="销量不是数字"))
        self.assertEqual(preview_commit_policy(parsed), {"commit_allowed": True, "partial_import": True})

    def test_preview_blocks_commit_when_no_valid_rows(self):
        parsed = ParsedImport(data_type="inventory", source_file="库存.xlsx", business_date=date(2026, 8, 19))
        parsed.errors.append(RowError(row_no=2, code="EMPTY_MERCHANT_CODE", message="商家编码不能为空"))
        self.assertEqual(preview_commit_policy(parsed), {"commit_allowed": False, "partial_import": False})

    def test_import_center_routes_are_declared(self):
        source = (Path(__file__).resolve().parents[1] / "app" / "routes" / "imports.py").read_text(encoding="utf-8")
        expected = [
            '@router.post("/preview")',
            '@router.post("/commit")',
            '@router.get("/recent")',
            '@router.get("/latest-business-date")',
            '@router.get("/{batch_no}")',
            '@router.get("/{batch_no}/issues")',
            '@router.post("/{batch_no}/rollback")',
        ]
        for declaration in expected:
            self.assertIn(declaration, source)


if __name__ == "__main__":
    unittest.main()
