from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text

from ..services.import_db_service import import_file, rollback_batch
from ..services.import_parser import ImportValidationError, parse_import_file, parsed_preview


def parse_date(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def cmd_preview(args) -> int:
    try:
        parsed = parse_import_file(args.file, args.type, parse_date(args.business_date))
        print_json(parsed_preview(parsed, args.limit))
        return 0 if not parsed.errors else 2
    except ImportValidationError as exc:
        print_json({"ok": False, "code": exc.code, "message": exc.message})
        return 2


def cmd_import(args) -> int:
    from ..db import SessionLocal
    db = SessionLocal()
    try:
        result = import_file(
            db,
            args.file,
            args.type,
            parse_date(args.business_date),
            args.department_code,
            args.actor_user_id,
        )
        print_json(result)
        return 0 if result["status"] == "success" else 2
    except Exception as exc:
        db.rollback()
        print_json({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 2
    finally:
        db.close()


def date_from_cn_filename(path: Path, year: int) -> date:
    m = re.search(r"(?P<m>\d{1,2})月(?P<d>\d{1,2})", path.stem)
    if not m:
        raise ValueError(f"文件名无法识别日期：{path.name}")
    return date(year, int(m.group("m")), int(m.group("d")))


def cmd_import_daily_dir(args) -> int:
    from ..db import SessionLocal
    directory = Path(args.dir)
    files = sorted([p for p in directory.iterdir() if p.suffix.lower() in {".xlsx", ".csv"}], key=lambda p: date_from_cn_filename(p, args.year))
    if not files:
        print_json({"ok": False, "message": "目录中没有逐日 .xlsx/.csv 文件"})
        return 2
    db = SessionLocal()
    results = []
    try:
        for file_path in files:
            business_date = date_from_cn_filename(file_path, args.year)
            try:
                result = import_file(db, file_path, "sales", business_date, args.department_code, args.actor_user_id)
                results.append(result)
            except Exception as exc:
                db.rollback()
                results.append({"file": file_path.name, "business_date": business_date.isoformat(), "status": "failed", "error": str(exc)})
                if not args.continue_on_error:
                    break
        print_json({"files": len(files), "results": results})
        return 0 if all(r.get("status") == "success" for r in results) else 2
    finally:
        db.close()


def cmd_rollback(args) -> int:
    from ..db import SessionLocal
    db = SessionLocal()
    try:
        result = rollback_batch(db, args.batch_no, args.actor_user_id)
        print_json(result)
        return 0
    except Exception as exc:
        db.rollback()
        print_json({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 2
    finally:
        db.close()


def cmd_bootstrap_admin(args) -> int:
    from ..db import SessionLocal
    db = SessionLocal()
    try:
        existing = db.execute(text("SELECT id FROM users WHERE user_id=:user_id OR username=:username"), {"user_id": args.user_id, "username": args.username}).first()
        if existing:
            print_json({"ok": False, "message": "user_id 或 username 已存在"})
            return 2
        result = db.execute(
            text(
                """
                INSERT INTO users(user_id,username,password_hash,is_system_admin,status)
                VALUES(:user_id,:username,:password_hash,1,'enabled')
                """
            ),
            {"user_id": args.user_id, "username": args.username, "password_hash": args.password_hash},
        )
        db.commit()
        print_json({"ok": True, "user_pk": result.lastrowid, "user_id": args.user_id, "username": args.username, "is_system_admin": True})
        return 0
    except Exception as exc:
        db.rollback()
        print_json({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 2
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="百嘉瑞 BI 真实数据导入 CLI")
    sub = p.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview", help="只解析和校验文件，不写数据库")
    preview.add_argument("--type", choices=["sales", "inventory", "product", "aging"], required=True)
    preview.add_argument("--file", required=True)
    preview.add_argument("--business-date")
    preview.add_argument("--limit", type=int, default=5)
    preview.set_defaults(func=cmd_preview)

    imp = sub.add_parser("import", help="解析并写入 MySQL")
    imp.add_argument("--type", choices=["sales", "inventory", "product", "aging"], required=True)
    imp.add_argument("--file", required=True)
    imp.add_argument("--business-date")
    imp.add_argument("--department-code", default="B2C")
    imp.add_argument("--actor-user-id", required=True)
    imp.set_defaults(func=cmd_import)

    daily = sub.add_parser("import-daily-dir", help="批量导入按 7月20.xlsx / 8月18.xlsx 命名的逐日销量目录")
    daily.add_argument("--dir", required=True)
    daily.add_argument("--year", type=int, required=True)
    daily.add_argument("--department-code", default="B2C")
    daily.add_argument("--actor-user-id", required=True)
    daily.add_argument("--continue-on-error", action="store_true")
    daily.set_defaults(func=cmd_import_daily_dir)

    rollback = sub.add_parser("rollback", help="按导入批次安全回滚")
    rollback.add_argument("--batch-no", required=True)
    rollback.add_argument("--actor-user-id", required=True)
    rollback.set_defaults(func=cmd_rollback)

    bootstrap = sub.add_parser("bootstrap-admin", help="首次部署时创建系统管理员（登录模块完成前可用禁用密码占位）")
    bootstrap.add_argument("--user-id", default="SYS0001")
    bootstrap.add_argument("--username", default="admin")
    bootstrap.add_argument("--password-hash", default="!bootstrap-disabled")
    bootstrap.set_defaults(func=cmd_bootstrap_admin)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
