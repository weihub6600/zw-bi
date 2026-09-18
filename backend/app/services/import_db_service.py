from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from .import_parser import ParsedImport, RowError, json_safe, parse_import_file, sha256_file
from .product_category_codec import parse_category_names, serialize_category_names
from .permission_service import assert_can_import, assert_can_view_department
from ..core.timezone import now_local, today_local


class DuplicateImportError(RuntimeError):
    pass


class ImportExecutionError(RuntimeError):
    pass


class RollbackConflictError(RuntimeError):
    pass


class SystemImportError(RuntimeError):
    """系统级导入错误（数据库结构缺失、连接异常等），应立即终止整批导入并回滚。"""

    def __init__(self, message: str, *, error_code: str = "DATABASE_SCHEMA_MISSING", detail: str = ""):
        super().__init__(message)
        self.error_code = error_code
        self.detail = detail


_SYSTEM_ERROR_CODES = {1146, 1054, 1142, 1143, 1044, 1045, 1049, 2013, 2006, 0}


def _is_system_level_error(exc: Exception) -> bool:
    """判断异常是否为系统级错误（表/列缺失、连接异常、schema 不一致）。

    这类错误不允许按行级数据错误继续处理，应立即终止整批导入。
    """
    # 数据库驱动底层错误码
    orig = getattr(exc, "orig", None)
    if orig is not None:
        code = None
        try:
            code = int(orig.args[0])
        except (TypeError, ValueError, IndexError, AttributeError):
            code = None
        if code in _SYSTEM_ERROR_CODES:
            return True
    # SQLAlchemy 已包装的错误类别
    class_name = type(exc).__name__
    if class_name in {"ProgrammingError", "OperationalError", "InternalError"}:
        return True
    if class_name in {"OperationalError", "InterfaceError", "DatabaseError"}:
        return True
    # 信息性提示：schema 不一致
    msg = str(exc)
    if "doesn't exist" in msg or "Unknown column" in msg or "Unknown table" in msg:
        return True
    if "syntax error" in msg.lower() and "sql" in msg.lower():
        return True
    return False


def _batch_no(data_type: str, business_date: date | None) -> str:
    day = (business_date or today_local()).strftime("%Y%m%d")
    stamp = now_local().strftime("%H%M%S%f")
    return f"IMP-{day}-{data_type.upper()}-{stamp}"


def _json_dump(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False)


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def _record_change(db: Session, batch_id: int, table_name: str, row_pk: int, action: str, before_data: dict | None) -> None:
    db.execute(
        text(
            """
            INSERT INTO import_changes(import_batch_id,table_name,row_pk,action,before_data)
            VALUES(:batch_id,:table_name,:row_pk,:action,CAST(:before_data AS JSON))
            """
        ),
        {
            "batch_id": batch_id,
            "table_name": table_name,
            "row_pk": row_pk,
            "action": action,
            "before_data": _json_dump(before_data) if before_data is not None else None,
        },
    )


def _product_category_ids(db: Session, product_id: int) -> list[int]:
    try:
        rows = db.execute(
            text(
                "SELECT category_id FROM product_category_relations "
                "WHERE product_id=:product_id ORDER BY category_id"
            ),
            {"product_id": product_id},
        ).scalars().all()
    except Exception:
        return []
    return [int(value) for value in rows]


def _find_or_create_named_dimension(db: Session, table_name: str, name: str) -> int:
    if table_name not in {"shops", "warehouses"}:
        raise ValueError("invalid dimension")
    cache = db.info.setdefault("import_dimension_ids", {})
    cache_key = (table_name, name)
    if cache_key in cache:
        return int(cache[cache_key])
    row = db.execute(text(f"SELECT id FROM {table_name} WHERE source_name=:name ORDER BY id LIMIT 1"), {"name": name}).first()
    if row:
        cache[cache_key] = int(row[0])
        return int(row[0])
    result = db.execute(text(f"INSERT INTO {table_name}(source_name) VALUES(:name)"), {"name": name})
    cache[cache_key] = int(result.lastrowid)
    return int(result.lastrowid)

def _sync_product_categories(
    db: Session,
    product_id: int,
    category_text: str | None,
):
    category_ids = db.info.get("import_category_ids")
    if category_ids is None:
        rows = db.execute(text("SELECT id,category_name FROM product_categories")).all()
        category_ids = {str(name): int(category_id) for category_id, name in rows}
        db.info["import_category_ids"] = category_ids
    names = parse_category_names(category_text, known_names=category_ids)

    # 商品资料是分类关系的唯一来源：重导时同步新增、删除和清空。
    db.execute(
        text("DELETE FROM product_category_relations WHERE product_id=:product_id"),
        {"product_id": product_id},
    )

    for name in names:
        category_id = category_ids.get(name)
        if category_id is None:
            # The unique category name is the concurrency boundary. INSERT
            # IGNORE/OR IGNORE lets concurrent imports converge on one row;
            # the follow-up SELECT retrieves the winner's ID.
            insert_sql = "INSERT OR IGNORE" if db.get_bind().dialect.name == "sqlite" else "INSERT IGNORE"
            db.execute(
                text(f"{insert_sql} INTO product_categories(category_name) VALUES(:name)"),
                {"name": name},
            )
            category_id = db.execute(
                text("SELECT id FROM product_categories WHERE category_name=:name"),
                {"name": name},
            ).scalar_one()
            category_ids[name] = int(category_id)

        insert_ignore = "INSERT OR IGNORE" if db.get_bind().dialect.name == "sqlite" else "INSERT IGNORE"
        db.execute(
            text(f"""
                {insert_ignore} INTO product_category_relations
                (product_id, category_id)
                VALUES(:product_id,:category_id)
            """),
            {
                "product_id": product_id,
                "category_id": category_id,
            },
        )
    return names
def _touch_product_alias(
    db: Session,
    product_id: int,
    alias_name: str,
    *,
    status: str,
    actor_user_pk: int | None = None,
) -> bool:
    """记录商品名称别名。返回该别名当前是否仍待管理员确认。"""
    alias_name = str(alias_name or "").strip()
    if not alias_name:
        return False
    existing = db.execute(
        text("SELECT id,status FROM product_name_aliases WHERE product_id=:product_id AND alias_name=:alias_name"),
        {"product_id": product_id, "alias_name": alias_name},
    ).mappings().first()
    if existing:
        next_status = "accepted" if existing["status"] == "accepted" or status == "accepted" else "pending"
        db.execute(
            text(
                """
                UPDATE product_name_aliases
                SET last_seen_at=NOW(),seen_count=seen_count+1,status=:status,
                    resolved_at=CASE WHEN :status='accepted' THEN COALESCE(resolved_at,NOW()) ELSE resolved_at END,
                    resolved_by=CASE WHEN :status='accepted' THEN COALESCE(resolved_by,:actor) ELSE resolved_by END
                WHERE id=:id
                """
            ),
            {"status": next_status, "actor": actor_user_pk, "id": existing["id"]},
        )
        return next_status == "pending"
    db.execute(
        text(
            """
            INSERT INTO product_name_aliases(
              product_id,alias_name,status,first_seen_at,last_seen_at,seen_count,resolved_at,resolved_by
            ) VALUES(
              :product_id,:alias_name,:status,NOW(),NOW(),1,
              CASE WHEN :status='accepted' THEN NOW() ELSE NULL END,
              CASE WHEN :status='accepted' THEN :actor ELSE NULL END
            )
            """
        ),
        {"product_id": product_id, "alias_name": alias_name, "status": status, "actor": actor_user_pk},
    )
    return status == "pending"


def _snapshot_table(data_type: str) -> str:
    if data_type == "inventory":
        return "inventory_batch"
    if data_type == "aging":
        return "aging_snapshot"
    raise ValueError("not a snapshot type")


def _ensure_schema_tables(db: Session) -> None:
    """系统级 schema 自检：导入流程依赖的核心表若缺失，立即终止，避免逐行产生重复系统错误。

    表缺失属于数据库结构版本不完整（migration 未执行），不应被当作几百条行级数据错误。
    """
    required = {
        "import_changes": "回滚变更表",
        "import_errors": "导入错误明细表",
        "import_batches": "导入批次表",
    }
    for table, label in required.items():
        dialect = db.get_bind().dialect.name if db.get_bind() else "mysql"
        if dialect == "sqlite":
            sql = text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:t")
        else:
            sql = text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=:t")
        exists = db.execute(sql, {"t": table}).scalar()
        if not exists:
            raise SystemImportError(
                "数据库结构版本不完整，请联系管理员升级数据库。本次导入已终止。",
                error_code="DATABASE_SCHEMA_MISSING",
                detail=f"缺少表 {table}（{label}）。请执行数据库迁移：python scripts/release_tool.py migrate",
            )


def _prepare_sales_date_replace(
    db: Session, batch_id: int, department_id: int, business_date: date
) -> int:
    """销量按“部门 + 业务日期”整日覆盖：最后一次成功上传为准。

    覆盖前把旧行登记到 import_changes，既避免同日重复叠加，也保留当前最新
    覆盖批次的一层安全回滚能力。
    """
    existing_rows = db.execute(
        text(
            """
            SELECT * FROM sales_daily
            WHERE department_id=:department_id AND business_date=:business_date
            ORDER BY id
            """
        ),
        {"department_id": department_id, "business_date": business_date},
    ).mappings().all()
    for existing in existing_rows:
        _record_change(db, batch_id, "sales_daily", int(existing["id"]), "deleted", dict(existing))
    if existing_rows:
        db.execute(
            text("DELETE FROM sales_daily WHERE department_id=:department_id AND business_date=:business_date"),
            {"department_id": department_id, "business_date": business_date},
        )
    return len(existing_rows)


def _prepare_latest_snapshot(
    db: Session, batch_id: int, department_id: int, data_type: str, snapshot_date: date
) -> int:
    """库存效期/库龄仅保留当前部门最新整表快照。旧事实行登记到回滚日志后删除。"""
    table_name = _snapshot_table(data_type)
    latest = db.execute(
        text(f"SELECT MAX(snapshot_date) FROM {table_name} WHERE department_id=:department_id"),
        {"department_id": department_id},
    ).scalar()
    if latest and snapshot_date < latest:
        raise ImportExecutionError(
            f"{data_type} 只保留最新快照；当前最新日期为 {latest}，不能用较早日期 {snapshot_date} 覆盖"
        )
    existing_rows = db.execute(
        text(f"SELECT * FROM {table_name} WHERE department_id=:department_id ORDER BY id"),
        {"department_id": department_id},
    ).mappings().all()
    for existing in existing_rows:
        before = dict(existing)
        _record_change(db, batch_id, table_name, int(existing["id"]), "deleted", before)
    if existing_rows:
        db.execute(
            text(f"DELETE FROM {table_name} WHERE department_id=:department_id"),
            {"department_id": department_id},
        )
    return len(existing_rows)


def _get_or_create_product(db: Session, batch_id: int, row: dict[str, Any], data_type: str, warnings: list[RowError], product_cache: dict[str, dict[str, Any]] | None = None) -> int:
    code = str(row["merchant_code"])
    existing = product_cache.get(code) if product_cache is not None else None
    if existing is None:
        fetched = db.execute(
            text("SELECT * FROM products WHERE merchant_code=:code"),
            {"code": code},
        ).mappings().first()
        existing = dict(fetched) if fetched else None
        if existing is not None and product_cache is not None:
            product_cache[code] = existing
    if existing:
        if data_type == "product":
            before = {
                **{k: existing[k] for k in ("product_name", "spec", "brand", "category", "barcode", "import_batch_id")},
                "category_ids": _product_category_ids(db, int(existing["id"])),
            }
            category_names = _sync_product_categories(db, int(existing["id"]), row.get("category"))
            update_fields = {k: row.get(k) for k in ("product_name", "spec", "brand", "category", "barcode")}
            update_fields["category"] = serialize_category_names(category_names)
            relation_changed = before["category_ids"] != _product_category_ids(db, int(existing["id"]))
            changed = any(update_fields[k] != existing[k] for k in update_fields) or relation_changed
            if changed:
                _record_change(db, batch_id, "products", int(existing["id"]), "updated", before)
                db.execute(
                    text(
                        """
                        UPDATE products
                        SET product_name=:product_name,spec=:spec,brand=:brand,category=:category,barcode=:barcode,import_batch_id=:batch_id
                        WHERE id=:id
                        """
                    ),
                    {**update_fields, "batch_id": batch_id, "id": existing["id"]},
                )
        product_id = int(existing["id"])
        if product_cache is not None:
            product_cache[code] = {
                **existing,
                **(update_fields if data_type == "product" else {}),
                "import_batch_id": batch_id if data_type == "product" and changed else existing.get("import_batch_id"),
            }
        return product_id

    result = db.execute(
        text(
            """
            INSERT INTO products(merchant_code,product_name,spec,brand,category,barcode,import_batch_id)
            VALUES(:merchant_code,:product_name,:spec,:brand,:category,:barcode,:batch_id)
            """
        ),
        {
            "merchant_code": row["merchant_code"],
            "product_name": row["product_name"],
            "spec": row.get("spec"),
            "brand": row.get("brand"),
            "category": row.get("category"),
            "barcode": row.get("barcode"),
            "batch_id": batch_id,
        },
    )
    product_id = int(result.lastrowid)
    stored_category = row.get("category")
    if data_type == "product":
        category_names = _sync_product_categories(db, product_id, row.get("category"))
        stored_category = serialize_category_names(category_names)
        db.execute(
            text("UPDATE products SET category=:category WHERE id=:product_id"),
            {"category": stored_category, "product_id": product_id},
        )
    _record_change(db, batch_id, "products", product_id, "inserted", None)
    if product_cache is not None:
        product_cache[code] = {
            "id": product_id,
            "merchant_code": code,
            "product_name": row["product_name"],
            "spec": row.get("spec"),
            "brand": row.get("brand"),
            "category": stored_category,
            "barcode": row.get("barcode"),
            "import_batch_id": batch_id,
        }
    return product_id


def _prefetch_products(db: Session, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    codes = list(dict.fromkeys(str(row["merchant_code"]) for row in rows if row.get("merchant_code")))
    if not codes:
        return {}
    query = text("SELECT * FROM products WHERE merchant_code IN :codes").bindparams(bindparam("codes", expanding=True))
    return {
        str(row["merchant_code"]): dict(row)
        for row in db.execute(query, {"codes": codes}).mappings().all()
    }


def _merge_weighted_price(old_qty: Any, old_price: Any, new_qty: Any, new_price: Any) -> Decimal | None:
    oq = Decimal(str(old_qty or 0))
    nq = Decimal(str(new_qty or 0))
    op = Decimal(str(old_price)) if old_price is not None else None
    np = Decimal(str(new_price)) if new_price is not None else None
    numerator = Decimal("0")
    denominator = Decimal("0")
    if oq > 0 and op is not None and op > 0:
        numerator += oq * op
        denominator += oq
    if nq > 0 and np is not None and np > 0:
        numerator += nq * np
        denominator += nq
    if denominator > 0:
        return numerator / denominator
    return np if np is not None else op


def _upsert_sales(db: Session, batch_id: int, department_id: int, product_id: int, row: dict[str, Any]) -> None:
    shop_id = _find_or_create_named_dimension(db, "shops", row["shop_name"])
    warehouse_id = _find_or_create_named_dimension(db, "warehouses", row["warehouse_name"])
    existing = db.execute(
        text(
            """
            SELECT * FROM sales_daily
            WHERE department_id=:department_id AND business_date=:business_date
              AND shop_id=:shop_id AND warehouse_id=:warehouse_id AND product_id=:product_id
            """
        ),
        {
            "department_id": department_id,
            "business_date": row["business_date"],
            "shop_id": shop_id,
            "warehouse_id": warehouse_id,
            "product_id": product_id,
        },
    ).mappings().first()
    if existing:
        same_batch = int(existing.get("import_batch_id") or 0) == int(batch_id)
        if same_batch:
            # 同一文件内同一商家编码可能因商品改名出现多行；按业务维度聚合，不能让后一行覆盖前一行。
            sales_qty = Decimal(str(existing["sales_qty"] or 0)) + Decimal(str(row["sales_qty"] or 0))
            avg_price = _merge_weighted_price(existing["sales_qty"], existing["avg_price"], row["sales_qty"], row["avg_price"])
        else:
            before = {k: existing[k] for k in ("sales_qty", "avg_price", "import_batch_id")}
            _record_change(db, batch_id, "sales_daily", int(existing["id"]), "updated", before)
            sales_qty = row["sales_qty"]
            avg_price = row["avg_price"]
        db.execute(
            text(
                """
                UPDATE sales_daily SET sales_qty=:sales_qty,avg_price=:avg_price,import_batch_id=:batch_id
                WHERE id=:id
                """
            ),
            {"sales_qty": sales_qty, "avg_price": avg_price, "batch_id": batch_id, "id": existing["id"]},
        )
    else:
        result = db.execute(
            text(
                """
                INSERT INTO sales_daily(
                  department_id,business_date,shop_id,warehouse_id,product_id,sales_qty,avg_price,import_batch_id
                ) VALUES(
                  :department_id,:business_date,:shop_id,:warehouse_id,:product_id,:sales_qty,:avg_price,:batch_id
                )
                """
            ),
            {
                "department_id": department_id,
                "business_date": row["business_date"],
                "shop_id": shop_id,
                "warehouse_id": warehouse_id,
                "product_id": product_id,
                "sales_qty": row["sales_qty"],
                "avg_price": row["avg_price"],
                "batch_id": batch_id,
            },
        )
        _record_change(db, batch_id, "sales_daily", int(result.lastrowid), "inserted", None)


def _upsert_inventory(db: Session, batch_id: int, department_id: int, product_id: int, row: dict[str, Any]) -> None:
    warehouse_id = _find_or_create_named_dimension(db, "warehouses", row["warehouse_name"])
    params = {
        "department_id": department_id,
        "snapshot_date": row["snapshot_date"],
        "warehouse_id": warehouse_id,
        "product_id": product_id,
        "production_date": row["production_date"],
        "expire_date": row["expire_date"],
    }
    existing = db.execute(
        text(
            """
            SELECT * FROM inventory_batch
            WHERE department_id=:department_id AND snapshot_date=:snapshot_date AND warehouse_id=:warehouse_id
              AND product_id=:product_id AND production_date <=> :production_date AND expire_date <=> :expire_date
            """
        ), params,
    ).mappings().first()
    if existing:
        same_batch = int(existing.get("import_batch_id") or 0) == int(batch_id)
        if same_batch:
            stock_qty = Decimal(str(existing["stock_qty"] or 0)) + Decimal(str(row["stock_qty"] or 0))
        else:
            before = {k: existing[k] for k in ("stock_qty", "import_batch_id")}
            _record_change(db, batch_id, "inventory_batch", int(existing["id"]), "updated", before)
            stock_qty = row["stock_qty"]
        db.execute(
            text("UPDATE inventory_batch SET stock_qty=:stock_qty,import_batch_id=:batch_id WHERE id=:id"),
            {"stock_qty": stock_qty, "batch_id": batch_id, "id": existing["id"]},
        )
    else:
        result = db.execute(
            text(
                """
                INSERT INTO inventory_batch(
                  department_id,snapshot_date,warehouse_id,product_id,stock_qty,production_date,expire_date,import_batch_id
                ) VALUES(
                  :department_id,:snapshot_date,:warehouse_id,:product_id,:stock_qty,:production_date,:expire_date,:batch_id
                )
                """
            ),
            {**params, "stock_qty": row["stock_qty"], "batch_id": batch_id},
        )
        _record_change(db, batch_id, "inventory_batch", int(result.lastrowid), "inserted", None)


def _upsert_aging(db: Session, batch_id: int, department_id: int, product_id: int, row: dict[str, Any]) -> None:
    warehouse_id = _find_or_create_named_dimension(db, "warehouses", row["warehouse_name"])
    params = {
        "department_id": department_id,
        "snapshot_date": row["snapshot_date"],
        "warehouse_id": warehouse_id,
        "product_id": product_id,
        "aging_days": row["aging_days"],
    }
    existing = db.execute(
        text(
            """
            SELECT * FROM aging_snapshot
            WHERE department_id=:department_id AND snapshot_date=:snapshot_date AND warehouse_id=:warehouse_id
              AND product_id=:product_id AND aging_days=:aging_days
            """
        ), params,
    ).mappings().first()
    if existing:
        same_batch = int(existing.get("import_batch_id") or 0) == int(batch_id)
        if same_batch:
            stock_qty = Decimal(str(existing["stock_qty"] or 0)) + Decimal(str(row["stock_qty"] or 0))
        else:
            before = {k: existing[k] for k in ("stock_qty", "import_batch_id")}
            _record_change(db, batch_id, "aging_snapshot", int(existing["id"]), "updated", before)
            stock_qty = row["stock_qty"]
        db.execute(
            text("UPDATE aging_snapshot SET stock_qty=:stock_qty,import_batch_id=:batch_id WHERE id=:id"),
            {"stock_qty": stock_qty, "batch_id": batch_id, "id": existing["id"]},
        )
    else:
        result = db.execute(
            text(
                """
                INSERT INTO aging_snapshot(
                  department_id,snapshot_date,warehouse_id,product_id,stock_qty,aging_days,import_batch_id
                ) VALUES(
                  :department_id,:snapshot_date,:warehouse_id,:product_id,:stock_qty,:aging_days,:batch_id
                )
                """
            ),
            {**params, "stock_qty": row["stock_qty"], "batch_id": batch_id},
        )
        _record_change(db, batch_id, "aging_snapshot", int(result.lastrowid), "inserted", None)


def _purge_older_snapshot_rollback_logs(
    db: Session, department_id: int, data_type: str, current_batch_id: int
) -> None:
    """快照事实只保留最新；回滚日志也只保留“当前快照 -> 上一快照”这一层。"""
    if data_type not in {"inventory", "aging"}:
        return
    db.execute(
        text(
            """
            DELETE ic FROM import_changes ic
            JOIN import_batches b ON b.id=ic.import_batch_id
            WHERE b.department_id=:department_id AND b.data_type=:data_type
              AND b.id<>:current_batch_id
            """
        ),
        {"department_id": department_id, "data_type": data_type, "current_batch_id": current_batch_id},
    )


def import_parsed(
    db: Session,
    parsed: ParsedImport,
    file_path: str | Path,
    department_code: str,
    actor_user_id: str,
    original_filename: str | None = None,
) -> dict[str, Any]:
    actor, department = assert_can_import(db, actor_user_id, department_code)
    file_hash = sha256_file(file_path)

    duplicate = db.execute(
        text(
            """
            SELECT batch_no,status FROM import_batches
            WHERE department_id=:department_id AND data_type=:data_type
              AND (business_date <=> :business_date) AND file_sha256=:file_hash
              AND status IN ('preview','success')
            ORDER BY id DESC LIMIT 1
            """
        ),
        {
            "department_id": department["id"],
            "data_type": parsed.data_type,
            "business_date": parsed.business_date,
            "file_hash": file_hash,
        },
    ).mappings().first()
    if duplicate and parsed.data_type != "sales":
        raise DuplicateImportError(f"相同文件已导入：{duplicate['batch_no']} ({duplicate['status']})")

    if parsed.data_type in {"inventory", "aging"} and parsed.errors:
        raise ImportExecutionError(
            "库存效期/库龄是整表最新快照；存在错误行时禁止覆盖当前快照，请先修正错误后再导入"
        )

    # 销量允许首次导入时保留既有“有效行 + 错误行”的兼容行为；
    # 但一旦是同业务日期覆盖，必须整批可解析，避免先清掉旧日数据后只写入半份纠正文件。
    if parsed.data_type == "sales" and parsed.business_date is not None and parsed.errors:
        existing_sales_rows = int(
            db.execute(
                text(
                    """
                    SELECT COUNT(*) FROM sales_daily
                    WHERE department_id=:department_id AND business_date=:business_date
                    """
                ),
                {"department_id": department["id"], "business_date": parsed.business_date},
            ).scalar() or 0
        )
        if existing_sales_rows > 0:
            raise ImportExecutionError(
                f"销售 {parsed.business_date} 采用整日覆盖；当前纠正文件仍有 {len(parsed.errors)} 条错误，"
                "为保护旧日数据已禁止覆盖，请先修正错误后再提交"
            )

    batch_no = _batch_no(parsed.data_type, parsed.business_date)
    result = db.execute(
        text(
            """
            INSERT INTO import_batches(
              batch_no,department_id,data_type,business_date,original_filename,file_sha256,imported_by,
              total_rows,success_rows,error_rows,warning_rows,status
            ) VALUES(
              :batch_no,:department_id,:data_type,:business_date,:filename,:file_hash,:imported_by,
              :total_rows,0,:error_rows,:warning_rows,'preview'
            )
            """
        ),
        {
            "batch_no": batch_no,
            "department_id": department["id"],
            "data_type": parsed.data_type,
            "business_date": parsed.business_date,
            "filename": original_filename or Path(file_path).name,
            "file_hash": file_hash,
            "imported_by": actor["id"],
            "total_rows": parsed.source_row_count,
            "error_rows": len(parsed.errors),
            "warning_rows": len(parsed.warnings),
        },
    )
    batch_id = int(result.lastrowid)

    replaced_rows = 0
    if parsed.data_type == "sales":
        if parsed.business_date is None:
            raise ImportExecutionError("销售业务日期不能为空")
        replaced_rows = _prepare_sales_date_replace(
            db, batch_id, int(department["id"]), parsed.business_date
        )

    if parsed.data_type in {"inventory", "aging"}:
        if parsed.business_date is None:
            raise ImportExecutionError("快照日期不能为空")
        _prepare_latest_snapshot(db, batch_id, int(department["id"]), parsed.data_type, parsed.business_date)

    errors = list(parsed.errors)
    warnings = list(parsed.warnings)
    success_rows = 0
    db.info.pop("import_dimension_ids", None)
    db.info.pop("import_category_ids", None)
    # 系统级 schema 自检：核心依赖表缺失时立即终止，避免逐行产生重复系统错误。
    _ensure_schema_tables(db)
    for offset in range(0, len(parsed.rows), 1000):
        chunk = parsed.rows[offset:offset + 1000]
        product_cache = _prefetch_products(db, chunk)
        for row in chunk:
            try:
                # 每一行使用 SAVEPOINT。某一行失败时只回滚该行，不污染整个导入批次。
                with db.begin_nested():
                    product_id = _get_or_create_product(db, batch_id, row, parsed.data_type, warnings, product_cache)
                    if parsed.data_type == "sales":
                        _upsert_sales(db, batch_id, department["id"], product_id, row)
                    elif parsed.data_type == "inventory":
                        _upsert_inventory(db, batch_id, department["id"], product_id, row)
                    elif parsed.data_type == "aging":
                        _upsert_aging(db, batch_id, department["id"], product_id, row)
                success_rows += 1
            except ImportExecutionError as exc:
                # SAVEPOINT 已回滚；清掉可能指向该行临时记录的缓存。
                product_cache.pop(str(row.get("merchant_code") or ""), None)
                db.info.pop("import_dimension_ids", None)
                db.info.pop("import_category_ids", None)
                errors.append(RowError(row_no=row.get("row_no"), code="ROW_IMPORT_RULE_FAILED", message=str(exc), raw_data=row))
            except SystemImportError:
                # 系统级错误：立即终止整批导入，交由外层回滚。
                raise
            except Exception as exc:
                product_cache.pop(str(row.get("merchant_code") or ""), None)
                db.info.pop("import_dimension_ids", None)
                db.info.pop("import_category_ids", None)
                if _is_system_level_error(exc):
                    # 数据库结构缺失/连接异常/schema 不一致：系统级错误，立即终止。
                    raise SystemImportError(
                        f"数据库结构版本不完整，请联系管理员升级数据库。本次导入已终止。{exc}",
                        error_code="DATABASE_SCHEMA_MISSING",
                        detail=str(exc),
                    ) from exc
                # 其他未知行级错误：记录并继续。
                errors.append(RowError(row_no=row.get("row_no"), code="ROW_IMPORT_FAILED", message=str(exc), raw_data=row))

    if parsed.data_type in {"inventory", "aging"} and errors:
        # 快照必须整批成功；否则由路由层 rollback 整个事务，保留旧快照。
        raise ImportExecutionError(
            f"{parsed.data_type} 快照写入过程中出现 {len(errors)} 条错误，已取消整批覆盖；旧快照保持不变"
        )

    if parsed.data_type == "sales" and replaced_rows > 0 and errors:
        # 同日纠正是“整日替换”事务：任何运行期行错误都取消整个覆盖，旧日数据由外层 rollback 恢复。
        raise ImportExecutionError(
            f"销售 {parsed.business_date} 覆盖写入过程中出现 {len(errors)} 条错误，已取消整日覆盖；旧日数据保持不变"
        )

    for severity, issues in (("error", errors), ("warning", warnings)):
        for err in issues:
            db.execute(
                text(
                    """
                    INSERT INTO import_errors(import_batch_id,row_no,severity,error_code,error_message,raw_data)
                    VALUES(:batch_id,:row_no,:severity,:code,:message,CAST(:raw_data AS JSON))
                    """
                ),
                {
                    "batch_id": batch_id,
                    "row_no": err.row_no,
                    "severity": severity,
                    "code": err.code,
                    "message": err.message[:1000],
                    "raw_data": _json_dump(err.raw_data) if err.raw_data is not None else None,
                },
            )

    status = "success" if success_rows > 0 else "failed"
    db.execute(
        text(
            """
            UPDATE import_batches
            SET success_rows=:success_rows,error_rows=:error_rows,warning_rows=:warning_rows,status=:status
            WHERE id=:batch_id
            """
        ),
        {"success_rows": success_rows, "error_rows": len(errors), "warning_rows": len(warnings), "status": status, "batch_id": batch_id},
    )
    _purge_older_snapshot_rollback_logs(db, int(department["id"]), parsed.data_type, batch_id)
    db.execute(
        text("INSERT INTO activity_logs(user_pk,department_id,action_type,action_detail) VALUES(:u,:d,'import_commit',JSON_OBJECT('batch_no',:batch_no,'data_type',:data_type,'status',:status,'replaced_rows',:replaced_rows))"),
        {"u":actor["id"],"d":department["id"],"batch_no":batch_no,"data_type":parsed.data_type,"status":status,"replaced_rows":replaced_rows},
    )
    db.commit()
    return {
        "batch_no": batch_no,
        "data_type": parsed.data_type,
        "business_date": parsed.business_date.isoformat() if parsed.business_date else None,
        "total_rows": parsed.source_row_count,
        "success_rows": success_rows,
        "error_rows": len(errors),
        "warning_rows": len(warnings),
        "replaced_rows": replaced_rows,
        "status": status,
    }


def import_file(
    db: Session,
    file_path: str | Path,
    data_type: str,
    business_date: date | None,
    department_code: str,
    actor_user_id: str,
    original_filename: str | None = None,
) -> dict[str, Any]:
    parsed = parse_import_file(file_path, data_type, business_date)
    return import_parsed(db, parsed, file_path, department_code, actor_user_id, original_filename=original_filename)


def _restore_update(db: Session, table_name: str, row_pk: int, before: dict[str, Any]) -> None:
    allowed = {
        "sales_daily": {"sales_qty", "avg_price", "import_batch_id"},
        "inventory_batch": {"stock_qty", "import_batch_id"},
        "aging_snapshot": {"stock_qty", "import_batch_id"},
        "products": {"product_name", "spec", "brand", "category", "barcode", "import_batch_id"},
    }
    fields = allowed[table_name]
    payload = {k: before.get(k) for k in fields}
    assignments = ",".join(f"{k}=:{k}" for k in fields)
    payload["row_pk"] = row_pk
    db.execute(text(f"UPDATE {table_name} SET {assignments} WHERE id=:row_pk"), payload)
    if table_name == "products":
        db.execute(
            text("DELETE FROM product_category_relations WHERE product_id=:product_id"),
            {"product_id": row_pk},
        )
        category_ids = before.get("category_ids")
        if category_ids is None:
            _sync_product_categories(db, row_pk, payload.get("category"))
        else:
            insert_sql = "INSERT OR IGNORE" if db.get_bind().dialect.name == "sqlite" else "INSERT IGNORE"
            for category_id in dict.fromkeys(int(value) for value in category_ids):
                exists = db.execute(
                    text("SELECT id FROM product_categories WHERE id=:category_id"),
                    {"category_id": category_id},
                ).scalar()
                if exists is None:
                    raise RollbackConflictError(f"回滚所需商品分类不存在：{category_id}")
                db.execute(
                    text(
                        f"{insert_sql} INTO product_category_relations(product_id,category_id) "
                        "VALUES(:product_id,:category_id)"
                    ),
                    {"product_id": row_pk, "category_id": category_id},
                )


def _restore_deleted(db: Session, table_name: str, before: dict[str, Any]) -> None:
    fields_map = {
        "sales_daily": ("id","department_id","business_date","shop_id","warehouse_id","product_id","sales_qty","avg_price","import_batch_id","created_at","updated_at"),
        "inventory_batch": ("id","department_id","snapshot_date","warehouse_id","product_id","stock_qty","production_date","expire_date","import_batch_id","created_at"),
        "aging_snapshot": ("id","department_id","snapshot_date","warehouse_id","product_id","stock_qty","aging_days","import_batch_id","created_at"),
    }
    fields = fields_map.get(table_name)
    if not fields:
        raise RollbackConflictError(f"{table_name} 不支持 deleted 回滚")
    payload = {k: before.get(k) for k in fields}
    cols = ",".join(fields)
    vals = ",".join(f":{k}" for k in fields)
    db.execute(text(f"INSERT INTO {table_name}({cols}) VALUES({vals})"), payload)


def _assert_product_not_referenced(db: Session, product_id: int, batch_id: int) -> None:
    checks = [
        ("sales_daily", "import_batch_id"),
        ("inventory_batch", "import_batch_id"),
        ("aging_snapshot", "import_batch_id"),
        ("todo_tasks", None),
    ]
    for table_name, batch_col in checks:
        if batch_col:
            row = db.execute(
                text(f"SELECT id FROM {table_name} WHERE product_id=:product_id AND (import_batch_id IS NULL OR import_batch_id<>:batch_id) LIMIT 1"),
                {"product_id": product_id, "batch_id": batch_id},
            ).first()
        else:
            row = db.execute(text(f"SELECT id FROM {table_name} WHERE product_id=:product_id LIMIT 1"), {"product_id": product_id}).first()
        if row:
            raise RollbackConflictError(f"商品 {product_id} 已被后续数据引用，不能安全回滚删除")


def rollback_batch(db: Session, batch_no: str, actor_user_id: str) -> dict[str, Any]:
    batch = db.execute(text("SELECT * FROM import_batches WHERE batch_no=:batch_no"), {"batch_no": batch_no}).mappings().first()
    if not batch:
        raise RollbackConflictError(f"导入批次不存在：{batch_no}")
    if batch["status"] != "success":
        raise RollbackConflictError(f"批次当前状态不可回滚：{batch['status']}")
    if batch["data_type"] in {"inventory", "aging"}:
        latest_snapshot_batch = db.execute(
            text(
                """
                SELECT id FROM import_batches
                WHERE department_id=:department_id AND data_type=:data_type AND status='success'
                ORDER BY id DESC LIMIT 1
                """
            ),
            {"department_id": batch["department_id"], "data_type": batch["data_type"]},
        ).scalar()
        if int(latest_snapshot_batch or 0) != int(batch["id"]):
            raise RollbackConflictError("库存效期/库龄仅允许回滚当前最新快照批次")

    if batch["data_type"] == "sales" and batch["business_date"] is not None:
        latest_sales_batch = db.execute(
            text(
                """
                SELECT id FROM import_batches
                WHERE department_id=:department_id AND data_type='sales'
                  AND business_date=:business_date AND status='success'
                ORDER BY id DESC LIMIT 1
                """
            ),
            {"department_id": batch["department_id"], "business_date": batch["business_date"]},
        ).scalar()
        if int(latest_sales_batch or 0) != int(batch["id"]):
            raise RollbackConflictError("销量按日期覆盖后，仅允许回滚该日期当前最新成功批次")

    department = db.execute(text("SELECT code FROM departments WHERE id=:id"), {"id": batch["department_id"]}).first()
    assert_can_import(db, actor_user_id, department[0])

    changes = db.execute(
        text("SELECT * FROM import_changes WHERE import_batch_id=:batch_id ORDER BY id DESC"),
        {"batch_id": batch["id"]},
    ).mappings().all()
    if batch["data_type"] in {"inventory", "aging"} and not changes:
        raise RollbackConflictError("该快照批次的上一层回滚数据已按最新快照保留策略清理，不能继续向前回滚")

    for change in changes:
        table_name = change["table_name"]
        if table_name not in {"sales_daily", "inventory_batch", "aging_snapshot", "products"}:
            raise RollbackConflictError(f"未知回滚表：{table_name}")
        row_pk = int(change["row_pk"])
        action = change["action"]
        if action == "inserted":
            if table_name == "products":
                _assert_product_not_referenced(db, row_pk, int(batch["id"]))
            db.execute(text(f"DELETE FROM {table_name} WHERE id=:id"), {"id": row_pk})
        elif action == "deleted":
            before = change["before_data"]
            if isinstance(before, str):
                before = json.loads(before)
            _restore_deleted(db, table_name, before or {})
        elif action == "updated":
            current = db.execute(text(f"SELECT import_batch_id FROM {table_name} WHERE id=:id"), {"id": row_pk}).first()
            if not current:
                raise RollbackConflictError(f"回滚目标行已不存在：{table_name}#{row_pk}")
            if current[0] != batch["id"]:
                raise RollbackConflictError(f"{table_name}#{row_pk} 已被后续批次修改，拒绝覆盖回滚")
            before = change["before_data"]
            if isinstance(before, str):
                before = json.loads(before)
            _restore_update(db, table_name, row_pk, before or {})

    db.execute(
        text("UPDATE import_batches SET status='rolled_back',rolled_back_at=NOW() WHERE id=:id"),
        {"id": batch["id"]},
    )
    actor,_=assert_can_import(db,actor_user_id,department[0])
    db.execute(text("INSERT INTO activity_logs(user_pk,department_id,action_type,action_detail) VALUES(:u,:d,'import_rollback',JSON_OBJECT('batch_no',:batch_no,'changes',:changes))"),{"u":actor["id"],"d":batch["department_id"],"batch_no":batch_no,"changes":len(changes)})
    if batch["data_type"] in {"inventory", "aging"}:
        db.execute(text("DELETE FROM import_changes WHERE import_batch_id=:batch_id"), {"batch_id": batch["id"]})
    db.commit()
    return {"batch_no": batch_no, "status": "rolled_back", "changes_reverted": len(changes)}


def recent_batches(db: Session, department_code: str, actor_user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    actor, department = assert_can_import(db, actor_user_id, department_code)
    rows = db.execute(
        text(
            """
            SELECT b.batch_no,b.data_type,b.business_date,b.original_filename,b.total_rows,b.success_rows,b.error_rows,b.warning_rows,
                   b.status,b.created_at,u.user_id,u.username,
                   EXISTS(SELECT 1 FROM import_changes ic WHERE ic.import_batch_id=b.id LIMIT 1) AS has_changes
            FROM import_batches b
            LEFT JOIN users u ON u.id=b.imported_by
            WHERE b.department_id=:department_id
            ORDER BY b.id DESC LIMIT :limit
            """
        ),
        {"department_id": department["id"], "limit": limit},
    ).mappings().all()
    items = [json_safe(dict(r)) for r in rows]
    seen_snapshot_type: set[str] = set()
    seen_sales_dates: set[str] = set()
    for item in items:
        if item.get("status") != "success":
            item["can_rollback"] = False
        elif item.get("data_type") in {"inventory", "aging"}:
            dt = str(item["data_type"])
            item["can_rollback"] = dt not in seen_snapshot_type and bool(item.get("has_changes"))
            seen_snapshot_type.add(dt)
        elif item.get("data_type") == "sales":
            day = str(item.get("business_date") or "")
            item["can_rollback"] = day not in seen_sales_dates and bool(item.get("has_changes"))
            seen_sales_dates.add(day)
        else:
            item["can_rollback"] = bool(item.get("has_changes"))
    return items


def product_name_aliases(
    db: Session, department_code: str, actor_user_id: str, *, pending_only: bool = False
) -> dict[str, Any]:
    actor, department = assert_can_import(db, actor_user_id, department_code)
    status_where = "AND a.status='pending'" if pending_only else ""
    rows = db.execute(
        text(
            f"""
            SELECT p.id AS product_id,p.merchant_code,p.product_name AS canonical_name,
                   a.id AS alias_id,a.alias_name,a.status,a.first_seen_at,a.last_seen_at,a.seen_count
            FROM products p
            JOIN product_name_aliases a ON a.product_id=p.id
            WHERE (
              EXISTS(SELECT 1 FROM sales_daily s WHERE s.department_id=:department_id AND s.product_id=p.id) OR
              EXISTS(SELECT 1 FROM inventory_batch i WHERE i.department_id=:department_id AND i.product_id=p.id) OR
              EXISTS(SELECT 1 FROM aging_snapshot g WHERE g.department_id=:department_id AND g.product_id=p.id) OR
              EXISTS(SELECT 1 FROM import_batches b WHERE b.id=p.import_batch_id AND b.department_id=:department_id)
            ) {status_where}
            ORDER BY (a.status='pending') DESC,a.last_seen_at DESC,p.merchant_code,a.alias_name
            """
        ),
        {"department_id": department["id"]},
    ).mappings().all()
    grouped: dict[int, dict[str, Any]] = {}
    for r in rows:
        pid = int(r["product_id"])
        item = grouped.setdefault(
            pid,
            {
                "product_id": pid,
                "merchant_code": r["merchant_code"],
                "canonical_name": r["canonical_name"],
                "aliases": [],
                "pending_count": 0,
            },
        )
        alias = json_safe({k: r[k] for k in ("alias_id","alias_name","status","first_seen_at","last_seen_at","seen_count")})
        item["aliases"].append(alias)
        if r["status"] == "pending":
            item["pending_count"] += 1
    items = list(grouped.values())
    return {
        "department_code": department_code,
        "items": items,
        "pending_products": sum(1 for x in items if x["pending_count"] > 0),
        "pending_aliases": sum(x["pending_count"] for x in items),
    }


def resolve_product_name_alias(
    db: Session,
    department_code: str,
    actor_user_id: str,
    product_id: int,
    canonical_name: str,
) -> dict[str, Any]:
    actor, department = assert_can_import(db, actor_user_id, department_code)
    canonical_name = str(canonical_name or "").strip()
    if not canonical_name:
        raise ImportExecutionError("规范商品名称不能为空")
    product = db.execute(
        text("SELECT id,merchant_code,product_name FROM products WHERE id=:id"), {"id": product_id}
    ).mappings().first()
    if not product:
        raise ImportExecutionError("商品不存在")
    if not actor["is_system_admin"]:
        related = db.execute(
            text(
                """
                SELECT 1 WHERE
                  EXISTS(SELECT 1 FROM sales_daily s WHERE s.department_id=:d AND s.product_id=:p) OR
                  EXISTS(SELECT 1 FROM inventory_batch i WHERE i.department_id=:d AND i.product_id=:p) OR
                  EXISTS(SELECT 1 FROM aging_snapshot g WHERE g.department_id=:d AND g.product_id=:p) OR
                  EXISTS(SELECT 1 FROM import_batches b WHERE b.id=(SELECT import_batch_id FROM products WHERE id=:p) AND b.department_id=:d)
                """
            ),
            {"d": department["id"], "p": product_id},
        ).first()
        if not related:
            raise ImportExecutionError("该商品不属于当前管理部门的数据范围")
    old_name = str(product["product_name"])
    _touch_product_alias(db, product_id, old_name, status="accepted", actor_user_pk=int(actor["id"]))
    _touch_product_alias(db, product_id, canonical_name, status="accepted", actor_user_pk=int(actor["id"]))
    db.execute(
        text("UPDATE products SET product_name=:name WHERE id=:id"),
        {"name": canonical_name, "id": product_id},
    )
    db.execute(
        text(
            """
            UPDATE product_name_aliases
            SET status='accepted',resolved_at=NOW(),resolved_by=:actor
            WHERE product_id=:product_id
            """
        ),
        {"actor": actor["id"], "product_id": product_id},
    )
    db.execute(
        text(
            """
            INSERT INTO activity_logs(user_pk,department_id,action_type,action_detail)
            VALUES(:u,:d,'product_name_resolve',JSON_OBJECT('product_id',:p,'merchant_code',:code,'old_name',:old,'canonical_name',:new))
            """
        ),
        {"u": actor["id"], "d": department["id"], "p": product_id, "code": product["merchant_code"], "old": old_name, "new": canonical_name},
    )
    db.commit()
    return {
        "product_id": product_id,
        "merchant_code": product["merchant_code"],
        "canonical_name": canonical_name,
        "status": "resolved",
    }


def latest_business_date(db: Session, department_code: str, actor_user_id: str) -> dict[str, Any]:
    _, department = assert_can_view_department(db, actor_user_id, department_code)
    value = db.execute(
        text(
            """
            SELECT MAX(business_date)
            FROM import_batches
            WHERE department_id=:department_id AND status='success' AND business_date IS NOT NULL
            """
        ),
        {"department_id": department["id"]},
    ).scalar()
    return {
        "department_code": department_code,
        "latest_business_date": value.isoformat() if value else None,
    }


def _authorized_import_batch(db: Session, batch_no: str, actor_user_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    batch = db.execute(
        text(
            """
            SELECT b.*,d.code AS department_code,d.name AS department_name,
                   u.user_id AS imported_by_user_id,u.username AS imported_by_username
            FROM import_batches b
            JOIN departments d ON d.id=b.department_id
            LEFT JOIN users u ON u.id=b.imported_by
            WHERE b.batch_no=:batch_no
            """
        ),
        {"batch_no": batch_no},
    ).mappings().first()
    if not batch:
        raise ImportExecutionError(f"导入批次不存在：{batch_no}")
    actor, _ = assert_can_import(db, actor_user_id, batch["department_code"])
    return dict(batch), actor


def import_batch_detail(db: Session, batch_no: str, actor_user_id: str) -> dict[str, Any]:
    """数据中心导入记录详情。仅系统管理员/目标部门部门管理员可查看。"""
    batch, _ = _authorized_import_batch(db, batch_no, actor_user_id)
    change_count = int(
        db.execute(
            text("SELECT COUNT(*) FROM import_changes WHERE import_batch_id=:batch_id"),
            {"batch_id": batch["id"]},
        ).scalar()
        or 0
    )
    issue_counts = db.execute(
        text(
            """
            SELECT
              SUM(CASE WHEN severity='error' THEN 1 ELSE 0 END) AS errors,
              SUM(CASE WHEN severity='warning' THEN 1 ELSE 0 END) AS warnings
            FROM import_errors
            WHERE import_batch_id=:batch_id
            """
        ),
        {"batch_id": batch["id"]},
    ).mappings().first() or {}
    can_rollback = batch["status"] == "success"
    if can_rollback and batch["data_type"] in {"inventory", "aging"}:
        latest_id = db.execute(
            text(
                """SELECT id FROM import_batches
                   WHERE department_id=:department_id AND data_type=:data_type AND status='success'
                   ORDER BY id DESC LIMIT 1"""
            ),
            {"department_id": batch["department_id"], "data_type": batch["data_type"]},
        ).scalar()
        can_rollback = int(latest_id or 0) == int(batch["id"]) and change_count > 0
    return {
        **json_safe(batch),
        "changes_count": change_count,
        "issue_counts": {
            "error": int(issue_counts.get("errors") or 0),
            "warning": int(issue_counts.get("warnings") or 0),
        },
        "can_rollback": can_rollback,
    }


def import_batch_issues(
    db: Session,
    batch_no: str,
    actor_user_id: str,
    *,
    severity: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """分页读取批次错误/警告明细，供数据质量页面使用。"""
    if severity not in {None, "", "error", "warning"}:
        raise ImportExecutionError("severity 只支持 error / warning")
    batch, _ = _authorized_import_batch(db, batch_no, actor_user_id)
    where = "import_batch_id=:batch_id"
    params: dict[str, Any] = {"batch_id": batch["id"]}
    if severity:
        where += " AND severity=:severity"
        params["severity"] = severity
    total = int(db.execute(text(f"SELECT COUNT(*) FROM import_errors WHERE {where}"), params).scalar() or 0)
    safe_limit = min(max(int(limit), 1), 500)
    safe_offset = max(int(offset), 0)
    rows = db.execute(
        text(
            f"""
            SELECT id,row_no,severity,error_code,error_message,raw_data,created_at
            FROM import_errors
            WHERE {where}
            ORDER BY id ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        {**params, "limit": safe_limit, "offset": safe_offset},
    ).mappings().all()
    return {
        "batch_no": batch_no,
        "data_type": batch["data_type"],
        "business_date": json_safe(batch["business_date"]),
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "items": [json_safe(dict(r)) for r in rows],
    }
