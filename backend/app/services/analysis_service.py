from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .dashboard_service import (
    DashboardScope,
    _get_latest_inventory_date,
    _get_latest_sales_date,
    _inventory_rows,
    _load_expiry_rules,
    _merge_products,
    _number,
    _round,
    _safe_expiry_status,
    _sales_rows,
    _scope_clauses,
    parse_keywords,
    _where,
    selected_sales_range,
    sales_period_comparison,
)
from .expiry_service import is_long_term_expiry, total_shelf_days
from .permission_service import assert_can_view_department
from .auth_service import record_activity
from ..core.timezone import today_local


# 这两个阈值目前作为可配置默认值使用，不作为不可变业务规则锁死。
DEFAULT_HIGH_COVER_DAYS = 90
DEFAULT_STAGNANT_AGING_DAYS = 180
DEFAULT_STAGNANT_COVER_DAYS = 180

CATEGORY_LABELS = {
    "healthy": "健康库存",
    "high": "高库存",
    "stagnant": "呆滞库存",
    "no_sales": "无销量库存",
    "stockout": "缺货动销",
}


def _product_category_names_by_product(db: Session, product_ids: list[int]) -> dict[int, str]:
    if not product_ids:
        return {}
    placeholders = ",".join(f":product_category_product_{i}" for i in range(len(product_ids)))
    params = {f"product_category_product_{i}": product_id for i, product_id in enumerate(product_ids)}

    def split_names(value: Any) -> list[str]:
        if value is None:
            return []
        raw = str(value).strip()
        if not raw:
            return []
        raw = raw.replace(r"\r\n", "\n").replace(r"\n", "\n").replace(r"\r", "\r")
        # Some historical imports stored a JSON array in the category column.
        if raw.startswith("[") and raw.endswith("]"):
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, list):
                    return [str(item).strip() for item in decoded if str(item).strip()]
            except (TypeError, ValueError):
                pass
        return [part.strip() for part in re.split(r"[,，、;；|\r\n]+", raw) if part.strip()]

    # Always load the legacy column first. This keeps categories visible even
    # when the relation tables are empty after a database restore.
    product_rows = db.execute(
        text(f"SELECT id AS product_id, category FROM products WHERE id IN ({placeholders})"),
        params,
    ).mappings().all()
    result: dict[int, str] = {
        int(row["product_id"]): "、".join(dict.fromkeys(split_names(row["category"])))
        for row in product_rows
    }

    # New multi-category relations are authoritative when present. Older
    # restored databases without relation rows continue using the legacy field.
    try:
        relation_rows = db.execute(
            text(
                f"""
                SELECT pcr.product_id, pc.category_name
                FROM product_category_relations pcr
                JOIN product_categories pc ON pc.id=pcr.category_id
                WHERE pcr.product_id IN ({placeholders})
                ORDER BY pcr.product_id, pc.category_name
                """
            ),
            params,
        ).mappings().all()
    except SQLAlchemyError:
        relation_rows = []

    relation_names: dict[int, list[str]] = {}
    for row in relation_rows:
        name = str(row["category_name"] or "").strip()
        if name:
            relation_names.setdefault(int(row["product_id"]), []).append(name)
    for product_id, names in relation_names.items():
        result[product_id] = "、".join(dict.fromkeys(names))

    return {product_id: result.get(product_id, "") for product_id in product_ids}


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _aging_by_product(
    db: Session,
    department_id: int,
    scope: DashboardScope,
) -> tuple[date | None, dict[int, dict[str, float]]]:
    latest = db.execute(
        text("SELECT MAX(snapshot_date) FROM aging_snapshot WHERE department_id=:department_id"),
        {"department_id": department_id},
    ).scalar_one_or_none()
    if not latest:
        return None, {}

    params: dict[str, Any] = {"department_id": department_id, "snapshot_date": latest}
    filters = _scope_clauses(scope, params, product_alias="p", warehouse_alias="w")
    rows = db.execute(
        text(
            f"""
            SELECT a.product_id,
                   SUM(a.stock_qty) AS aging_stock_qty,
                   SUM(a.stock_qty * a.aging_days) / NULLIF(SUM(a.stock_qty),0) AS weighted_aging_days,
                   MAX(a.aging_days) AS max_aging_days
            FROM aging_snapshot a
            JOIN products p ON p.id=a.product_id
            JOIN warehouses w ON w.id=a.warehouse_id
            WHERE a.department_id=:department_id
              AND a.snapshot_date=:snapshot_date
              {_where(filters)}
            GROUP BY a.product_id
            """
        ),
        params,
    ).mappings().all()
    result = {
        int(r["product_id"]): {
            "aging_stock_qty": _number(r["aging_stock_qty"]),
            "weighted_aging_days": _number(r["weighted_aging_days"]),
            "max_aging_days": _number(r["max_aging_days"]),
        }
        for r in rows
    }
    return latest, result


def classify_inventory_health(
    *,
    stock: float,
    sales30: float,
    cover_days: float | None,
    weighted_aging_days: float | None,
    high_cover_days: int = DEFAULT_HIGH_COVER_DAYS,
    stagnant_aging_days: int = DEFAULT_STAGNANT_AGING_DAYS,
    stagnant_cover_days: int = DEFAULT_STAGNANT_COVER_DAYS,
) -> str:
    if stock <= 0:
        return "healthy"
    if sales30 <= 0:
        return "no_sales"
    if weighted_aging_days is not None and weighted_aging_days >= stagnant_aging_days:
        return "stagnant"
    if cover_days is not None and cover_days > stagnant_cover_days:
        return "stagnant"
    if cover_days is not None and cover_days > high_cover_days:
        return "high"
    return "healthy"


def get_inventory_analysis(
    db: Session,
    scope: DashboardScope,
    *,
    category: str | None = None,
    high_cover_days: int = DEFAULT_HIGH_COVER_DAYS,
    stagnant_aging_days: int = DEFAULT_STAGNANT_AGING_DAYS,
    stagnant_cover_days: int = DEFAULT_STAGNANT_COVER_DAYS,
    detail_warehouses: bool = False,
    detail_product_categories: bool = False,
) -> dict[str, Any]:
    actor, department = assert_can_view_department(db, scope.actor_user_id, scope.department_code)
    department_id = int(department["id"])
    latest_sales_date = _get_latest_sales_date(db, department_id)
    latest_inventory_date = _get_latest_inventory_date(db, department_id)

    sales_rows = []
    if latest_sales_date:
        sales_rows, _ = _sales_rows(db, department_id, scope, latest_sales_date)
    inventory_rows = _inventory_rows(db, department_id, scope, latest_inventory_date)
    products = _merge_products(sales_rows, inventory_rows)
    latest_aging_date, aging = _aging_by_product(db, department_id, scope)

    categories = {
        key: {"key": key, "label": label, "sku_count": 0, "stock_qty": 0.0, "sales30_qty": 0.0}
        for key, label in CATEGORY_LABELS.items()
    }
    rows: list[dict[str, Any]] = []
    for p in products:
        stock = _number(p.get("stock"))
        sales30 = _number(p.get("sales30"))
        # Keep zero-stock products with recent sales as a separate replenishment class.
        if stock <= 0 and sales30 <= 0:
            continue
        age = aging.get(int(p["product_id"]), {})
        weighted_age = age.get("weighted_aging_days")
        cat = "stockout" if stock <= 0 else classify_inventory_health(
            stock=stock,
            sales30=sales30,
            cover_days=p.get("cover_days"),
            weighted_aging_days=weighted_age,
            high_cover_days=high_cover_days,
            stagnant_aging_days=stagnant_aging_days,
            stagnant_cover_days=stagnant_cover_days,
        )
        categories[cat]["sku_count"] += 1
        categories[cat]["stock_qty"] += stock
        categories[cat]["sales30_qty"] += sales30
        rows.append(
            {
                "product_id": p["product_id"],
                "sku": p["sku"],
                "name": p["name"],
                "category": cat,
                "category_label": CATEGORY_LABELS[cat],
                "stock_qty": _round(stock, 2),
                "sales_yesterday": _round(_number(p.get("sales_yesterday")), 2),
                "sales7": _round(_number(p.get("sales7")), 2),
                "sales14": _round(_number(p.get("sales14")), 2),
                "sales30": _round(_number(p.get("sales30")), 2),
                "sales_last_month": _round(_number(p.get("sales_last_month")), 2),
                "predicted_daily": _round(_number(p.get("predicted_daily")), 2),
                "cover_days": _round(p.get("cover_days"), 1),
                "weighted_aging_days": _round(weighted_age, 1) if weighted_age is not None else None,
                "max_aging_days": _round(age.get("max_aging_days"), 0) if age else None,
            }
        )

    for info in categories.values():
        info["stock_qty"] = _round(info["stock_qty"], 2)

    severity = {"stockout": 4, "no_sales": 3, "stagnant": 2, "high": 1, "healthy": 0}
    rows.sort(
        key=lambda r: (
            severity[r["category"]],
            r["cover_days"] if r["cover_days"] is not None else 10**9,
            r["stock_qty"],
        ),
        reverse=True,
    )
    if category in CATEGORY_LABELS:
        rows = [r for r in rows if r["category"] == category]

    if detail_product_categories and rows:
        product_ids = sorted({int(row["product_id"]) for row in rows})
        product_categories = _product_category_names_by_product(db, product_ids)
        for row in rows:
            row["product_category_names"] = product_categories.get(int(row["product_id"]), "")

    warehouse_columns: list[str] = []
    if detail_warehouses and latest_inventory_date:
        warehouse_rows = _inventory_by_product_warehouse(
            db, department_id, scope, latest_inventory_date
        )
        by_product: dict[int, dict[str, float]] = {}
        for warehouse_row in warehouse_rows:
            product_id = int(warehouse_row["product_id"])
            warehouse = str(warehouse_row["warehouse"])
            by_product.setdefault(product_id, {})[warehouse] = _round(
                _number(warehouse_row["stock_qty"]), 2
            ) or 0.0
        warehouse_columns = sorted({name for values in by_product.values() for name in values})
        for row in rows:
            stock_by_warehouse = by_product.get(int(row["product_id"]), {})
            row["warehouse_stocks"] = {
                warehouse: stock_by_warehouse.get(warehouse, 0.0)
                for warehouse in warehouse_columns
            }

    total_stock = sum(_number(r["stock_qty"]) for r in rows)
    return {
        "meta": {
            "department": {"code": department["code"], "name": department["name"]},
            "actor": {"user_id": actor["user_id"], "username": actor["username"]},
            "latest_sales_date": _date_text(latest_sales_date),
            "latest_inventory_date": _date_text(latest_inventory_date),
            "latest_aging_date": _date_text(latest_aging_date),
            "inventory_dimension_note": "库存只按部门/仓库/商品筛选；店铺筛选只影响销量和周转判断。",
            "classification_rule_status": "当前为可配置默认阈值，未锁死为不可变业务规则。",
            "thresholds": {
                "high_cover_days": high_cover_days,
                "stagnant_aging_days": stagnant_aging_days,
                "stagnant_cover_days": stagnant_cover_days,
            },
            "warehouse_columns": warehouse_columns,
            "detail_warehouses": detail_warehouses,
            "detail_product_categories": detail_product_categories,
        },
        "categories": categories,
        "selected_category": category if category in CATEGORY_LABELS else None,
        "rows": rows,
        "totals": {"sku_count": len(rows), "stock_qty": _round(total_stock, 2)},
    }


def _inventory_by_product_warehouse(
    db: Session,
    department_id: int,
    scope: DashboardScope,
    snapshot_date: date,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "department_id": department_id,
        "snapshot_date": snapshot_date,
    }
    filters = _scope_clauses(scope, params, product_alias="p", warehouse_alias="w")
    rows = db.execute(
        text(
            f"""
            SELECT ib.product_id,w.source_name AS warehouse,SUM(ib.stock_qty) AS stock_qty
            FROM inventory_batch ib
            JOIN products p ON p.id=ib.product_id
            JOIN warehouses w ON w.id=ib.warehouse_id
            WHERE ib.department_id=:department_id
              AND ib.snapshot_date=:snapshot_date
              {_where(filters)}
            GROUP BY ib.product_id,w.source_name
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _expiry_rows_for_scope(
    db: Session,
    department_id: int,
    scope: DashboardScope,
    snapshot_date: date,
    *,
    merchant_code: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"department_id": department_id, "snapshot_date": snapshot_date}
    filters = _scope_clauses(scope, params, product_alias="p", warehouse_alias="w")
    if merchant_code:
        params["merchant_code"] = merchant_code
        filters.append("p.merchant_code=:merchant_code")
    rows = db.execute(
        text(
            f"""
            SELECT ib.id AS batch_id,ib.product_id,p.merchant_code,p.product_name,
                   w.source_name AS warehouse,ib.stock_qty,ib.production_date,ib.expire_date
            FROM inventory_batch ib
            JOIN products p ON p.id=ib.product_id
            JOIN warehouses w ON w.id=ib.warehouse_id
            WHERE ib.department_id=:department_id
              AND ib.snapshot_date=:snapshot_date
              AND ib.stock_qty > 0
              {_where(filters)}
            ORDER BY p.product_name,w.source_name,ib.expire_date,ib.production_date
            """
        ),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


def _expiry_public_rows(
    db: Session,
    department_id: int,
    snapshot_date: date,
    raw_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    global_rule, department_rule, product_rules = _load_expiry_rules(db, department_id)
    result: list[dict[str, Any]] = []
    for row in raw_rows:
        pid = int(row["product_id"])
        if pid in product_rules:
            threshold = product_rules[pid]
            rule_source = "product"
        elif department_rule:
            threshold = department_rule
            rule_source = "department"
        else:
            threshold = global_rule
            rule_source = "global"
        long_term = bool(row["expire_date"] and is_long_term_expiry(row["expire_date"]))
        status, days, pct = _safe_expiry_status(
            row["production_date"], row["expire_date"], snapshot_date, threshold
        )
        total_days = None
        if row["production_date"] and row["expire_date"] and not long_term:
            total_days = total_shelf_days(row["production_date"], row["expire_date"])
        result.append(
            {
                "batch_id": int(row["batch_id"]),
                "product_id": pid,
                "sku": row["merchant_code"],
                "name": row["product_name"],
                "warehouse": row["warehouse"],
                "stock_qty": _round(_number(row["stock_qty"]), 2),
                "production_date": _date_text(row["production_date"]),
                "expire_date": _date_text(row["expire_date"]),
                "total_shelf_days": total_days,
                "remaining_days": days,
                "remaining_pct": _round(pct, 2),
                "status": status,
                "long_term": long_term,
                "rule_source": rule_source,
            }
        )
    return result


def get_expiry_batches(
    db: Session,
    scope: DashboardScope,
    *,
    statuses: tuple[str, ...] = (),
    remaining_days_min: int | None = None,
    remaining_days_max: int | None = None,
    remaining_pct_min: float | None = None,
    remaining_pct_max: float | None = None,
    merchant_code: str | None = None,
    limit: int | None = 1000,
) -> dict[str, Any]:
    actor, department = assert_can_view_department(db, scope.actor_user_id, scope.department_code)
    department_id = int(department["id"])
    snapshot_date = _get_latest_inventory_date(db, department_id)
    if not snapshot_date:
        return {
            "meta": {
                "department": {"code": department["code"], "name": department["name"]},
                "actor": {"user_id": actor["user_id"], "username": actor["username"]},
                "latest_inventory_date": None,
            },
            "summary": {"正常": 0, "预警": 0, "临期": 0, "过期": 0},
            "filtered_count": 0,
            "rows": [],
        }

    raw = _expiry_rows_for_scope(db, department_id, scope, snapshot_date, merchant_code=merchant_code)
    rows = _expiry_public_rows(db, department_id, snapshot_date, raw)
    summary = {"正常": 0, "预警": 0, "临期": 0, "过期": 0}
    for row in rows:
        summary[row["status"]] += 1

    allowed_statuses = {"正常", "预警", "临期", "过期"}
    status_set = {s for s in statuses if s in allowed_statuses}

    def keep(row: dict[str, Any]) -> bool:
        if status_set and row["status"] not in status_set:
            return False
        days = row["remaining_days"]
        pct = row["remaining_pct"]
        if remaining_days_min is not None and (days is None or days < remaining_days_min):
            return False
        if remaining_days_max is not None and (days is None or days > remaining_days_max):
            return False
        if remaining_pct_min is not None and (pct is None or pct < remaining_pct_min):
            return False
        if remaining_pct_max is not None and (pct is None or pct > remaining_pct_max):
            return False
        return True

    filtered = [r for r in rows if keep(r)]
    severity = {"过期": 3, "临期": 2, "预警": 1, "正常": 0}
    filtered.sort(
        key=lambda r: (
            severity[r["status"]],
            -(r["remaining_days"] if r["remaining_days"] is not None else 10**9),
            r["stock_qty"],
        ),
        reverse=True,
    )
    return {
        "meta": {
            "department": {"code": department["code"], "name": department["name"]},
            "actor": {"user_id": actor["user_id"], "username": actor["username"]},
            "latest_inventory_date": snapshot_date.isoformat(),
            "long_term_note": "明显超长期日期（>=2100年）不进入效期预警，剩余天数/百分比显示为空。",
        },
        "summary": summary,
        "filtered_count": len(filtered),
        "rows": filtered if limit is None else filtered[: max(1, min(limit, 5000))],
    }


def search_products(
    db: Session,
    scope: DashboardScope,
    query: str,
    *,
    limit: int = 20,
    category_id: int | None = None,
) -> dict[str, Any]:
    """按商品名、规格、品牌或商家编码搜索；分类可单独用于浏览商品。"""
    actor, department = assert_can_view_department(db, scope.actor_user_id, scope.department_code)
    q = query.strip()
    if not q and category_id is None:
        return {"rows": [], "query": "", "department": {"code": department["code"], "name": department["name"]}}
    department_id = int(department["id"])
    cap = max(1, min(int(limit), 30))
    keywords = [x.lower() for x in parse_keywords(q)]
    # 多个空格分隔的关键词按 AND 处理：每个关键词都必须命中商品名或商家编码。
    search_clauses = []
    params: dict[str, Any] = {
        "department_id": department_id,
        "exact": q.lower(),
        "prefix": f"{q.lower()}%",
        "query_empty": 1 if not q else 0,
        "category_id": category_id,
    }
    for i, keyword in enumerate(keywords):
        key = f"search_{i}"
        params[key] = f"%{keyword}%"
        search_clauses.append(
            f"(LOWER(p.merchant_code) LIKE :{key} OR LOWER(p.product_name) LIKE :{key} "
            f"OR LOWER(COALESCE(p.spec,'')) LIKE :{key} OR LOWER(COALESCE(p.brand,'')) LIKE :{key})"
        )
    search_sql = " AND ".join(search_clauses) if search_clauses else "1=1"
    rows = db.execute(
        text(
            f"""
            SELECT p.id,p.merchant_code,p.product_name,p.spec,p.brand,
                   MAX(CASE
                     WHEN LOWER(p.merchant_code)=:exact THEN 100
                     WHEN LOWER(p.product_name)=:exact THEN 90
                     WHEN LOWER(p.merchant_code) LIKE :prefix THEN 80
                     WHEN LOWER(p.product_name) LIKE :prefix THEN 70
                     ELSE 50 END) AS score
            FROM products p
            WHERE (
                   :query_empty=1
                   OR ({search_sql})
                   )
              AND (
                EXISTS(SELECT 1 FROM sales_daily sd WHERE sd.department_id=:department_id AND sd.product_id=p.id)
                OR EXISTS(SELECT 1 FROM inventory_batch ib WHERE ib.department_id=:department_id AND ib.product_id=p.id)
                OR EXISTS(SELECT 1 FROM aging_snapshot ag WHERE ag.department_id=:department_id AND ag.product_id=p.id)
              )

              AND (
                  :category_id IS NULL
                  OR EXISTS(
                      SELECT 1
                      FROM product_category_relations pcr
                      WHERE pcr.product_id=p.id
                        AND pcr.category_id=:category_id
                  )
              )
            GROUP BY p.id,p.merchant_code,p.product_name,p.spec,p.brand
            ORDER BY score DESC,p.product_name,p.merchant_code
            LIMIT {cap}
            """
        ),
params
    ).mappings().all()
    return {
        "query": q,
        "department": {"code": department["code"], "name": department["name"]},
        "rows": [
            {
                "product_id": int(r["id"]),
                "sku": r["merchant_code"],
                "name": r["product_name"],
                "spec": r["spec"],
                "brand": r["brand"],
                "matched_aliases": "",
            }
            for r in rows
        ],
    }


def _resolve_product(db: Session, merchant_code: str) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT id,merchant_code,product_name,spec,brand,category,barcode
            FROM products WHERE merchant_code=:merchant_code
            """
        ),
        {"merchant_code": merchant_code},
    ).mappings().first()
    return dict(row) if row else None


def _product_sales_metrics(
    db: Session,
    department_id: int,
    scope: DashboardScope,
    product_id: int,
    latest_sales_date: date | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not latest_sales_date:
        return {
            "sales7": 0.0, "sales14": 0.0, "sales30": 0.0,
            "avg_price7": None, "avg_price14": None, "avg_price30": None,
        }, []

    d7 = latest_sales_date - timedelta(days=6)
    d14 = latest_sales_date - timedelta(days=13)
    d30 = latest_sales_date - timedelta(days=29)
    trend_start, trend_end, trend_days = selected_sales_range(scope, latest_sales_date)
    query_start = min(d30, trend_start)
    params: dict[str, Any] = {
        "department_id": department_id,
        "product_id": product_id,
        "d7": d7,
        "d14": d14,
        "d30": d30,
        "end_date": latest_sales_date,
        "query_start": query_start,
        "trend_start": trend_start,
        "trend_end": trend_end,
    }
    filters = _scope_clauses(scope, params, product_alias="p", shop_alias="s", warehouse_alias="w")
    agg = db.execute(
        text(
            f"""
            SELECT
              SUM(CASE WHEN sd.business_date>=:d7 THEN sd.sales_qty ELSE 0 END) AS sales7,
              SUM(CASE WHEN sd.business_date>=:d14 THEN sd.sales_qty ELSE 0 END) AS sales14,
              SUM(sd.sales_qty) AS sales30,
              SUM(CASE WHEN sd.business_date>=:d7 AND sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty*sd.avg_price ELSE 0 END) AS rev7,
              SUM(CASE WHEN sd.business_date>=:d7 AND sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty ELSE 0 END) AS qty7,
              SUM(CASE WHEN sd.business_date>=:d14 AND sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty*sd.avg_price ELSE 0 END) AS rev14,
              SUM(CASE WHEN sd.business_date>=:d14 AND sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty ELSE 0 END) AS qty14,
              SUM(CASE WHEN sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty*sd.avg_price ELSE 0 END) AS rev30,
              SUM(CASE WHEN sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty ELSE 0 END) AS qty30
            FROM sales_daily sd
            JOIN products p ON p.id=sd.product_id
            JOIN shops s ON s.id=sd.shop_id
            JOIN warehouses w ON w.id=sd.warehouse_id
            WHERE sd.department_id=:department_id
              AND sd.product_id=:product_id
              AND sd.business_date BETWEEN :d30 AND :end_date
              {_where(filters)}
            """
        ),
        params,
    ).mappings().one()

    def price(rev: Any, qty: Any) -> float | None:
        q = _number(qty)
        return _round(_number(rev) / q, 2) if scope.single_shop and q > 0 else None

    metrics = {
        "sales7": _round(_number(agg["sales7"]), 2),
        "sales14": _round(_number(agg["sales14"]), 2),
        "sales30": _round(_number(agg["sales30"]), 2),
        "avg_price7": price(agg["rev7"], agg["qty7"]),
        "avg_price14": price(agg["rev14"], agg["qty14"]),
        "avg_price30": price(agg["rev30"], agg["qty30"]),
    }

    trend_rows = db.execute(
        text(
            f"""
            SELECT sd.business_date,
                   SUM(sd.sales_qty) AS sales_qty,
                   SUM(CASE WHEN sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty*sd.avg_price ELSE 0 END) AS revenue,
                   SUM(CASE WHEN sd.sales_qty>0 AND sd.avg_price>0 THEN sd.sales_qty ELSE 0 END) AS priced_qty
            FROM sales_daily sd
            JOIN products p ON p.id=sd.product_id
            JOIN shops s ON s.id=sd.shop_id
            JOIN warehouses w ON w.id=sd.warehouse_id
            WHERE sd.department_id=:department_id
              AND sd.product_id=:product_id
              AND sd.business_date BETWEEN :trend_start AND :trend_end
              {_where(filters)}
            GROUP BY sd.business_date ORDER BY sd.business_date
            """
        ),
        params,
    ).mappings().all()
    by_date = {r["business_date"]: r for r in trend_rows}
    trend: list[dict[str, Any]] = []
    for i in range(trend_days):
        d = trend_start + timedelta(days=i)
        r = by_date.get(d)
        qty = _number(r["sales_qty"]) if r else 0.0
        rev = _number(r["revenue"]) if r else 0.0
        priced = _number(r["priced_qty"]) if r else 0.0
        trend.append(
            {
                "date": d.isoformat(),
                "sales_qty": _round(qty, 2),
                "avg_price": _round(rev / priced, 2) if scope.single_shop and priced > 0 else None,
            }
        )
    return metrics, trend

def list_product_categories(
    db: Session,
    scope: DashboardScope,
) -> list[dict[str, Any]]:
    _, department = assert_can_view_department(db, scope.actor_user_id, scope.department_code)
    department_id = int(department["id"])
    rows = db.execute(
        text("""
            SELECT DISTINCT pc.id, pc.category_name
            FROM product_categories pc
            JOIN product_category_relations pcr ON pcr.category_id=pc.id
            WHERE EXISTS(
                SELECT 1 FROM sales_daily sd
                WHERE sd.department_id=:department_id AND sd.product_id=pcr.product_id
            )
            OR EXISTS(
                SELECT 1 FROM inventory_batch ib
                WHERE ib.department_id=:department_id AND ib.product_id=pcr.product_id
            )
            OR EXISTS(
                SELECT 1 FROM aging_snapshot ag
                WHERE ag.department_id=:department_id AND ag.product_id=pcr.product_id
            )
            ORDER BY pc.category_name
        """),
        {"department_id": department_id},
    ).mappings().all()

    return [
        {
            "id": int(r["id"]),
            "name": r["category_name"],
        }
        for r in rows
    ]


def _product_categories(
    db: Session,
    product_id: int,
) -> list[str]:
    rows = db.execute(
        text("""
            SELECT pc.category_name
            FROM product_category_relations pcr
            JOIN product_categories pc
              ON pc.id=pcr.category_id
            WHERE pcr.product_id=:product_id
            ORDER BY pc.category_name
        """),
        {
            "product_id": product_id,
        },
    ).scalars().all()

    return [str(x) for x in rows]


def _has_sales_on_date(db: Session, department_id: int, business_date: date) -> bool:
    return db.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM sales_daily
                WHERE department_id=:department_id AND business_date=:business_date
            )
            """
        ),
        {"department_id": department_id, "business_date": business_date},
    ).scalar_one() == 1

def _product_shop_sales(
    db: Session,
    department_id: int,
    scope: DashboardScope,
    product_id: int,
    latest_sales_date: date | None,
) -> list[dict[str, Any]]:
    if not latest_sales_date:
        return []
    d7 = latest_sales_date - timedelta(days=6)
    d14 = latest_sales_date - timedelta(days=13)
    d30 = latest_sales_date - timedelta(days=29)
    params: dict[str, Any] = {
        "department_id": department_id,
        "product_id": product_id,
        "d7": d7,
        "d14": d14,
        "d30": d30,
        "end_date": latest_sales_date,
    }
    # 店铺维度本身是分组项；若用户筛选了店铺则只显示被选中的店铺。
    filters = _scope_clauses(scope, params, product_alias="p", shop_alias="s", warehouse_alias="w")
    rows = db.execute(
        text(
            f"""
            SELECT
                s.id AS shop_id,
                s.source_name AS shop,
                SUM(CASE WHEN sd.business_date=:end_date THEN sd.sales_qty ELSE 0 END) AS sales_yesterday,
                SUM(CASE WHEN sd.business_date>=:d7 THEN sd.sales_qty ELSE 0 END) AS sales7,
                   SUM(CASE WHEN sd.business_date>=:d14 THEN sd.sales_qty ELSE 0 END) AS sales14,
                   SUM(sd.sales_qty) AS sales30
            FROM sales_daily sd
            JOIN products p ON p.id=sd.product_id
            JOIN shops s ON s.id=sd.shop_id
            JOIN warehouses w ON w.id=sd.warehouse_id
            WHERE sd.department_id=:department_id
              AND sd.product_id=:product_id
              AND sd.business_date BETWEEN :d30 AND :end_date
              {_where(filters)}
            GROUP BY s.id,s.source_name
            ORDER BY sales30 DESC,s.source_name
            """
        ),
        params,
    ).mappings().all()
    total30 = sum(_number(r["sales30"]) for r in rows)
    return [
        {
            "shop_id": r["shop_id"],
            "shop": r["shop"],
            "sales_yesterday": _round(_number(r["sales_yesterday"]), 2),
            "sales7": _round(_number(r["sales7"]), 2),
            "sales14": _round(_number(r["sales14"]), 2),
            "sales30": _round(_number(r["sales30"]), 2),
            "share30_pct": _round((_number(r["sales30"]) / total30 * 100.0) if total30 > 0 else 0.0, 1),
        }
        for r in rows
    ]


def _product_warehouse_stock(
    db: Session,
    department_id: int,
    scope: DashboardScope,
    product_id: int,
    snapshot_date: date | None,
) -> list[dict[str, Any]]:
    if not snapshot_date:
        return []
    params: dict[str, Any] = {
        "department_id": department_id,
        "product_id": product_id,
        "snapshot_date": snapshot_date,
    }
    filters = _scope_clauses(scope, params, product_alias="p", warehouse_alias="w")
    rows = db.execute(
        text(
            f"""
            SELECT w.source_name AS warehouse,SUM(ib.stock_qty) AS stock_qty
            FROM inventory_batch ib
            JOIN products p ON p.id=ib.product_id
            JOIN warehouses w ON w.id=ib.warehouse_id
            WHERE ib.department_id=:department_id
              AND ib.product_id=:product_id
              AND ib.snapshot_date=:snapshot_date
              {_where(filters)}
            GROUP BY w.id,w.source_name ORDER BY stock_qty DESC,w.source_name
            """
        ),
        params,
    ).mappings().all()
    return [{"warehouse": r["warehouse"], "stock_qty": _round(_number(r["stock_qty"]), 2)} for r in rows]


def _actor_department_role(db: Session, actor: dict[str, Any], department_id: int) -> str:
    if actor.get("is_system_admin"):
        return "system_admin"
    role = db.execute(
        text(
            """
            SELECT role FROM user_departments
            WHERE user_pk=:user_pk AND department_id=:department_id AND status='enabled'
            """
        ),
        {"user_pk": actor["id"], "department_id": department_id},
    ).scalar_one_or_none()
    return str(role or "member")


def _product_tasks(
    db: Session,
    actor: dict[str, Any],
    department_id: int,
    product_id: int,
) -> list[dict[str, Any]]:
    role = _actor_department_role(db, actor, department_id)
    params: dict[str, Any] = {"department_id": department_id, "product_id": product_id, "actor_pk": actor["id"]}
    owner_clause = "" if role in {"system_admin", "dept_admin"} else " AND t.owner_user_pk=:actor_pk"
    rows = db.execute(
        text(
            f"""
            SELECT t.task_no,t.target_qty,t.assign_date,t.start_date,t.manager_note,t.owner_note,t.status,
                   u.username AS owner_name,c.username AS creator_name
            FROM todo_tasks t
            JOIN users u ON u.id=t.owner_user_pk
            JOIN users c ON c.id=t.creator_user_pk
            WHERE t.department_id=:department_id AND t.product_id=:product_id
              {owner_clause}
            ORDER BY t.created_at DESC LIMIT 50
            """
        ),
        params,
    ).mappings().all()
    return [
        {
            "task_no": r["task_no"],
            "owner_name": r["owner_name"],
            "creator_name": r["creator_name"],
            "target_qty": _round(_number(r["target_qty"]), 2) if r["target_qty"] is not None else None,
            "assign_date": _date_text(r["assign_date"]),
            "start_date": _date_text(r["start_date"]),
            "manager_note": r["manager_note"],
            "owner_note": r["owner_note"],
            "status": r["status"],
        }
        for r in rows
    ]


def get_product_detail(db: Session, scope: DashboardScope, merchant_code: str) -> dict[str, Any]:
    actor, department = assert_can_view_department(db, scope.actor_user_id, scope.department_code)
    department_id = int(department["id"])
    product = _resolve_product(db, merchant_code)
    if not product:
        raise LookupError(f"商品不存在：{merchant_code}")

    categories = _product_categories(
        db,
        int(product["id"]),
    )

    latest_sales_date = _get_latest_sales_date(db, department_id)
    latest_inventory_date = _get_latest_inventory_date(db, department_id)
    yesterday_sales_date = today_local() - timedelta(days=1)
    yesterday_sales_available = _has_sales_on_date(db, department_id, yesterday_sales_date)
    metrics, trend = _product_sales_metrics(db, department_id, scope, int(product["id"]), latest_sales_date)
    comparison = sales_period_comparison(db, department_id, scope, latest_sales_date, product_id=int(product["id"]))
    shop_sales = _product_shop_sales(db, department_id, scope, int(product["id"]), latest_sales_date)
    shop_selection_scope = DashboardScope(
        actor_user_id=scope.actor_user_id,
        department_code=scope.department_code,
        days=scope.days,
        warehouses=scope.warehouses,
    )
    shop_sales_options = _product_shop_sales(
        db,
        department_id,
        shop_selection_scope,
        int(product["id"]),
        latest_sales_date,
    )
    warehouse_stock = _product_warehouse_stock(db, department_id, scope, int(product["id"]), latest_inventory_date)
    stock_total = sum(_number(x["stock_qty"]) for x in warehouse_stock)

    product_scope = DashboardScope(
        actor_user_id=scope.actor_user_id,
        department_code=scope.department_code,
        days=scope.days,
        shops=scope.shops,
        warehouses=scope.warehouses,
        product_search="",
        include_name="",
        exclude_name="",
        product_codes=(),
    )
    expiry = get_expiry_batches(db, product_scope, merchant_code=merchant_code, limit=500)
    batches = expiry["rows"]
    severity = {"正常": 0, "预警": 1, "临期": 2, "过期": 3}
    worst = "正常"
    min_pct: float | None = None
    for batch in batches:
        if severity[batch["status"]] > severity[worst]:
            worst = batch["status"]
        pct = batch["remaining_pct"]
        if pct is not None:
            min_pct = pct if min_pct is None else min(min_pct, pct)

    sales_rows = [{
        "product_id": int(product["id"]),
        "merchant_code": product["merchant_code"],
        "product_name": product["product_name"],
        "sales7": metrics["sales7"],
        "sales14": metrics["sales14"],
        "sales30": metrics["sales30"],
        "prior7": 0,
        "selected_sales": metrics["sales30"],
        "selected_revenue": 0,
        "selected_priced_qty": 0,
    }]
    inv_rows = [{
        "product_id": int(product["id"]),
        "merchant_code": product["merchant_code"],
        "product_name": product["product_name"],
        "stock_qty": stock_total,
    }]
    merged = _merge_products(sales_rows, inv_rows)[0]
    latest_aging_date, aging_map = _aging_by_product(db, department_id, product_scope)
    age = aging_map.get(int(product["id"]), {})
    health = classify_inventory_health(
        stock=stock_total,
        sales30=_number(metrics["sales30"]),
        cover_days=merged.get("cover_days"),
        weighted_aging_days=age.get("weighted_aging_days"),
    )

    note = db.execute(
        text("SELECT note,updated_at FROM product_notes WHERE user_pk=:user_pk AND product_id=:product_id"),
        {"user_pk": actor["id"], "product_id": product["id"]},
    ).mappings().first()

    return {
        "meta": {
            "department": {"code": department["code"], "name": department["name"]},
            "actor": {"user_id": actor["user_id"], "username": actor["username"]},
            "single_shop": scope.single_shop,
            "price_visible": scope.single_shop,
            "latest_sales_date": _date_text(latest_sales_date),
            "yesterday_sales_date": _date_text(yesterday_sales_date),
            "yesterday_sales_available": yesterday_sales_available,
            "selected_start_date": _date_text(selected_sales_range(scope, latest_sales_date)[0]) if latest_sales_date else None,
            "selected_end_date": _date_text(selected_sales_range(scope, latest_sales_date)[1]) if latest_sales_date else None,
            "selected_days": selected_sales_range(scope, latest_sales_date)[2] if latest_sales_date else scope.days,
            "latest_inventory_date": _date_text(latest_inventory_date),
            "latest_aging_date": _date_text(latest_aging_date),
            "inventory_dimension_note": "库存不按店铺拆分。当前店铺筛选只影响销量/均价；仓库筛选同时影响销量和库存。",
        },
        "product": {
            "product_id": int(product["id"]),
            "sku": product["merchant_code"],
            "name": product["product_name"],
            "spec": product["spec"],
            "brand": product["brand"],
            "category": product["category"],
            "categories": categories,
            "barcode": product["barcode"],
            "inventory_category": health,
            "inventory_category_label": CATEGORY_LABELS[health],
            "expiry_status": worst,
            "lowest_remaining_pct": _round(min_pct, 2),
        },
        "sales": metrics,
        "comparison": comparison,
        "trend": trend,
        "shop_sales": shop_sales,
        "shop_sales_options": shop_sales_options,
        "inventory": {
            "stock_qty": _round(stock_total, 2),
            "predicted_daily": _round(_number(merged.get("predicted_daily")), 2),
            "cover_days": _round(merged.get("cover_days"), 1),
            "weighted_aging_days": _round(age.get("weighted_aging_days"), 1) if age else None,
            "warehouses": warehouse_stock,
        },
        "expiry_batches": batches,
        "personal_note": {"note": note["note"] if note else "", "updated_at": str(note["updated_at"]) if note else None},
        "tasks": _product_tasks(db, actor, department_id, int(product["id"])),
    }


def save_product_note(
    db: Session,
    scope: DashboardScope,
    merchant_code: str,
    note: str,
) -> dict[str, Any]:
    actor, department = assert_can_view_department(db, scope.actor_user_id, scope.department_code)
    product = _resolve_product(db, merchant_code)
    if not product:
        raise LookupError(f"商品不存在：{merchant_code}")

    db.execute(
        text(
            """
            INSERT INTO product_notes(user_pk,product_id,note)
            VALUES(:user_pk,:product_id,:note)
            ON DUPLICATE KEY UPDATE note=VALUES(note),updated_at=CURRENT_TIMESTAMP
            """
        ),
        {"user_pk": actor["id"], "product_id": product["id"], "note": note},
    )
    db.commit()
    record_activity(db,int(actor["id"]),"product_note_update",department_id=int(department["id"]),detail={"sku":product["merchant_code"]})
    return {
        "saved": True,
        "department": {"code": department["code"], "name": department["name"]},
        "sku": product["merchant_code"],
        "note": note,
    }
