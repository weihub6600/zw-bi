"""兼容入口。

V14.1 的真实导入实现已经拆分为：
- import_parser.py：Excel/CSV 解析与校验
- import_db_service.py：MySQL upsert / 批次 / 回滚

旧代码若仍引用 import_service，可从这里继续拿到核心函数。
"""

from .import_parser import ImportValidationError, ParsedImport, parse_import_file, parsed_preview
from .import_db_service import import_file, recent_batches, rollback_batch, latest_business_date, import_batch_detail, import_batch_issues

__all__ = [
    "ImportValidationError",
    "ParsedImport",
    "parse_import_file",
    "parsed_preview",
    "import_file",
    "recent_batches",
    "rollback_batch",
    "latest_business_date",
    "import_batch_detail",
    "import_batch_issues",
]
