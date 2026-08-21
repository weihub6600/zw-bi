from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from app.services.import_parser import ImportValidationError, parse_import_file


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", default="/mnt/data")
    args = p.parse_args()
    root = Path(args.data_root)
    checks = [
        ("inventory", root / "仓库编码货品批次库存.xlsx", date(2026, 8, 18)),
        ("aging", root / "5仓库龄表.xlsx", date(2026, 8, 18)),
    ]
    results = []
    for data_type, path, business_date in checks:
        parsed = parse_import_file(path, data_type, business_date)
        results.append(parsed.summary())
    aggregate = root / "5仓所有店铺30天销量.xlsx"
    try:
        parse_import_file(aggregate, "sales", date(2026, 8, 18))
        results.append({"file": aggregate.name, "unexpected": "aggregate was accepted"})
    except ImportValidationError as exc:
        results.append({"file": aggregate.name, "expected_rejection": exc.code, "message": exc.message})
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
