from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from openpyxl import Workbook

from app.services.import_parser import ImportValidationError, parse_import_file


class ImportParserTests(unittest.TestCase):
    def make_xlsx(self, filename: str, rows: list[list]):
        td = tempfile.TemporaryDirectory()
        path = Path(td.name) / filename
        wb = Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)
        wb.save(path)
        wb.close()
        self.addCleanup(td.cleanup)
        return path

    def test_sales_aliases_and_total_row(self):
        path = self.make_xlsx(
            "8月19.xlsx",
            [
                ["店铺", "仓库", "商家编码", "货品名称", "实际销售量", "均价"],
                ["天猫", "主仓", "A001", "商品A", 10, 19.9],
                ["合计:", "NA", "NA", "NA", 10, 19.9],
            ],
        )
        parsed = parse_import_file(path, "sales", date(2026, 8, 19))
        self.assertEqual(parsed.valid_rows, 1)
        self.assertEqual(parsed.skipped_rows, 1)
        self.assertEqual(parsed.rows[0]["sales_qty"], 10)

    def test_inventory_legacy_headers_use_selected_snapshot_date(self):
        path = self.make_xlsx(
            "库存.xlsx",
            [
                ["库存日期", "仓库", "商家编码", "货品名称", "生产日期", "过期日期", "正常库存"],
                ["2026-08-18", "主仓", "A001", "商品A", "2026-01-01", "2027-01-01", 20],
            ],
        )
        parsed = parse_import_file(path, "inventory", date(2026, 8, 19))
        self.assertEqual(parsed.rows[0]["snapshot_date"], date(2026, 8, 19))

    def test_aging_total_row_is_skipped(self):
        path = self.make_xlsx(
            "库龄.xlsx",
            [
                ["仓库", "商家编码", "货品名称", "数量", "库龄[天]"],
                ["主仓", "A001", "商品A", 20, 30],
                ["合计:", "NA", "NA", "NA", "NA"],
            ],
        )
        parsed = parse_import_file(path, "aging", date(2026, 8, 19))
        self.assertEqual(parsed.valid_rows, 1)
        self.assertEqual(parsed.rows[0]["aging_days"], 30)

    def test_product_name_variant_in_file_is_warning_and_keeps_rows(self):
        path = self.make_xlsx(
            "商品资料.xlsx",
            [
                ["商家编码", "货品名称"],
                ["A001", "商品A"],
                ["A001", "商品A新名称"],
            ],
        )
        parsed = parse_import_file(path, "product")
        self.assertEqual(parsed.valid_rows, 2)
        self.assertEqual(parsed.error_rows, 0)
        self.assertEqual(parsed.warning_rows, 1)
        self.assertEqual(parsed.warnings[0].code, "PRODUCT_NAME_VARIANT_IN_FILE")

    def test_aggregate_sales_file_is_rejected(self):
        path = self.make_xlsx(
            "5仓所有店铺30天销量.xlsx",
            [["店铺", "仓库", "商家编码", "货品名称", "实际销售量", "均价"], ["天猫", "主仓", "A001", "商品A", 100, 20]],
        )
        with self.assertRaises(ImportValidationError) as ctx:
            parse_import_file(path, "sales", date(2026, 8, 19))
        self.assertEqual(ctx.exception.code, "AGGREGATE_SALES_NOT_DAILY")

    def test_sales_requires_business_date(self):
        path = self.make_xlsx(
            "8月19.xlsx",
            [["店铺", "仓库", "商家编码", "货品名称", "实际销售量", "均价"], ["天猫", "主仓", "A001", "商品A", 10, 20]],
        )
        with self.assertRaises(ImportValidationError) as ctx:
            parse_import_file(path, "sales", None)
        self.assertEqual(ctx.exception.code, "BUSINESS_DATE_REQUIRED")


if __name__ == "__main__":
    unittest.main()
