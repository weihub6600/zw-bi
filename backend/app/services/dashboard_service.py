from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from .expiry_service import ExpiryThreshold, is_long_term_expiry, remaining_days, remaining_percent
from .inventory_service import predicted_daily_sales, predicted_stockout_days, shortage_risk_level
from .permission_service import assert_can_view_department


VALID_DAYS = {1, 7, 14, 30}


@dataclass(frozen=True)
class DashboardScope:
    actor_user_id: str
    department_code: str = "B2C"
    days: int = 30
    start_date: date | None = None
    end_date: date | None = None
    shops: tuple[str, ...] = ()
    warehouses: tuple[str, ...] = ()
    product_search: str = ""
    include_name: str = ""
    exclude_name: str = ""
    product_codes: tuple[str, ...] = ()
    product_category_ids: tuple[int, ...] = ()

    @property
    def single_shop(self) -> bool:
        return len(self.shops) == 1


def selected_sales_range(scope: DashboardScope, latest_sales_date: date) -> tuple[date, date, int]:
    """解析销售筛选日期。预设以最新销售日为锚点；自定义区间允许历史查询。"""
    if scope.start_date or scope.end_date:
        end_date = min(scope.end_date or latest_sales_date, latest_sales_date)
        start_date = scope.start_date or end_date
        if start_date > end_date:
            raise ValueError("自定义开始日期不能晚于结束日期/最新销售日期")
        days = (end_date - start_date).days + 1
        if days > 366:
            raise ValueError("自定义日期区间暂最多支持366天")
        return start_date, end_date, days
    days = scope.days if scope.days in VALID_DAYS else 30
    return latest_sales_date - timedelta(days=days - 1), latest_sales_date, days




def _shift_year(value: date, years: int = -1) -> date:
    """按日历年移动日期；2月29日落到目标年的2月28日。"""
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def comparison_periods(scope: DashboardScope, latest_sales_date: date) -> dict[str, tuple[date, date]]:
    """返回当前、环比、同比销售区间。环比=紧邻上一等长区间；同比=去年同期。"""
    current_start, current_end, days = selected_sales_range(scope, latest_sales_date)
    mom_end = current_start - timedelta(days=1)
    mom_start = mom_end - timedelta(days=days - 1)
    yoy_start = _shift_year(current_start, -1)
    yoy_end = _shift_year(current_end, -1)
    return {
        "current": (current_start, current_end),
        "mom": (mom_start, mom_end),
        "yoy": (yoy_start, yoy_end),
    }


def _pct_change(current: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return _round((current - baseline) / baseline * 100.0, 2)


def sales_period_comparison(
    db: Session,
    department_id: int,
    scope: DashboardScope,
    latest_sales_date: date | None,
    *,
    product_id: int | None = None,
) -> dict[str, Any]:
    """销售环比/同比。历史不足时明确返回 unavailable，绝不伪造。"""
    if not latest_sales_date:
        return {
            "current": {"sales": 0.0, "start_date": None, "end_date": None},
            "mom": {"available": False, "sales": None, "change_pct": None, "note": "历史数据不足"},
            "yoy": {"available": False, "sales": None, "change_pct": None, "note": "历史数据不足"},
        }

    periods = comparison_periods(scope, latest_sales_date)
    earliest = db.execute(
        text("SELECT MIN(business_date) FROM sales_daily WHERE department_id=:department_id"),
        {"department_id": department_id},
    ).scalar_one_or_none()

    def total(start: date, end: date) -> float:
        params: dict[str, Any] = {
            "department_id": department_id,
            "start_date": start,
            "end_date": end,
        }
        product_clause = ""
        if product_id is not None:
            params["product_id"] = product_id
            product_clause = " AND sd.product_id=:product_id"
        filters = _scope_clauses(scope, params, product_alias="p", shop_alias="s", warehouse_alias="w")
        value = db.execute(
            text(
                f"""
                SELECT COALESCE(SUM(sd.sales_qty),0)
                FROM sales_daily sd
                JOIN products p ON p.id=sd.product_id
                JOIN shops s ON s.id=sd.shop_id
                JOIN warehouses w ON w.id=sd.warehouse_id
                WHERE sd.department_id=:department_id
                  AND sd.business_date BETWEEN :start_date AND :end_date
                  {product_clause}
                  {_where(filters)}
                """
            ),
            params,
        ).scalar_one()
        return _round(_number(value), 2) or 0.0

    current_start, current_end = periods["current"]
    current_sales = total(current_start, current_end)

    def baseline_payload(kind: str, label: str) -> dict[str, Any]:
        start, end = periods[kind]
        available = earliest is not None and earliest <= start
        if not available:
            return {
                "available": False,
                "sales": None,
                "change_pct": None,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "note": "历史数据不足",
                "label": label,
            }
        baseline = total(start, end)
        change = _pct_change(current_sales, baseline)
        return {
            "available": True,
            "sales": baseline,
            "change_pct": change,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "note": "基期销量为0，无法计算百分比" if baseline == 0 else None,
            "label": label,
        }

    return {
        "current": {
            "sales": current_sales,
            "start_date": current_start.isoformat(),
            "end_date": current_end.isoformat(),
            "days": (current_end - current_start).days + 1,
        },
        "mom": baseline_payload("mom", "环比"),
        "yoy": baseline_payload("yoy", "同比"),
    }


def parse_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in re.split(r"[,，\s]+", value) if x.strip()]


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _scope_clauses(
    scope: DashboardScope,
    params: dict[str, Any],
    *,
    product_alias: str = "p",
    shop_alias: str | None = None,
    warehouse_alias: str | None = None,
) -> list[str]:
    clauses: list[str] = []

    if scope.product_search.strip():
        params["product_search"] = f"%{scope.product_search.strip().lower()}%"
        clauses.append(
            f"(LOWER({product_alias}.product_name) LIKE :product_search "
            f"OR LOWER({product_alias}.merchant_code) LIKE :product_search)"
        )

    if scope.product_codes:
        placeholders = []
        for i, code in enumerate(scope.product_codes):
            key = f"product_code_{i}"
            params[key] = code
            placeholders.append(f":{key}")
        clauses.append(
            f"{product_alias}.merchant_code IN ({','.join(placeholders)})"
        )

    if scope.product_category_ids:
        placeholders = []
        for i, category_id in enumerate(scope.product_category_ids):
            key = f"product_category_id_{i}"
            params[key] = int(category_id)
            placeholders.append(f":{key}")

        clauses.append(
            "EXISTS ("
            "SELECT 1 FROM product_category_relations pcr "
            f"WHERE pcr.product_id={product_alias}.id "
            f"AND pcr.category_id IN ({','.join(placeholders)})"
            ")"
        )

    includes = [x.lower() for x in parse_keywords(scope.include_name)]
    if includes:
        parts = []
        for i, keyword in enumerate(includes):
            key = f"inc_{i}"
            params[key] = f"%{keyword}%"
            parts.append(f"LOWER({product_alias}.product_name) LIKE :{key}")
        clauses.append("(" + " OR ".join(parts) + ")")

    excludes = [x.lower() for x in parse_keywords(scope.exclude_name)]
    if excludes:
        parts = []
        for i, keyword in enumerate(excludes):
            key = f"exc_{i}"
            params[key] = f"%{keyword}%"
            parts.append(f"LOWER({product_alias}.product_name) LIKE :{key}")
        clauses.append("NOT (" + " OR ".join(parts) + ")")

    if shop_alias and scope.shops:
        placeholders = []
        for i, shop in enumerate(scope.shops):
            key = f"shop_{i}"
            params[key] = shop
            placeholders.append(f":{key}")
        clauses.append(f"{shop_alias}.source_name IN ({','.join(placeholders)})")

    if warehouse_alias and scope.warehouses:
        placeholders = []
        for i, warehouse in enumerate(scope.warehouses):
            key = f"warehouse_{i}"
            params[key] = warehouse
            placeholders.append(f":{key}")
        clauses.append(f"{warehouse_alias}.source_name IN ({','.join(placeholders)})")

    return clauses


def _where(extra: Iterable[str]) -> str:
    parts = [x for x in extra if x]
    return " AND " + " AND ".join(parts) if parts else ""


def _get_latest_sales_date(db: Session, department_id: int) -> date | None:
    return db.execute(
        text("SELECT MAX(business_date) FROM sales_daily WHERE department_id=:department_id"),
        {"department_id": department_id},
    ).scalar_one_or_none()


def _get_latest_inventory_date(db: Session, department_id: int) -> date | None:
    return db.execute(
        text("SELECT MAX(snapshot_date) FROM inventory_batch WHERE department_id=:department_id"),
        {"department_id": department_id},
    ).scalar_one_or_none()


def _sales_rows(
    db: Session,
    department_id: int,
    scope: DashboardScope,
    latest_sales_date: date,
) -> tuple[list[dict[str, Any]], date | None]:
    d7 = latest_sales_date - timedelta(days=6)
    d14 = latest_sales_date - timedelta(days=13)
    d30 = latest_sales_date - timedelta(days=29)
    prev7_start = latest_sales_date - timedelta(days=13)
    prev7_end = latest_sales_date - timedelta(days=7)
    selected_start, selected_end, _selected_days = selected_sales_range(scope, latest_sales_date)
    query_start = min(d30, selected_start)

    params: dict[str, Any] = {
        "department_id": department_id,
        "end_date": latest_sales_date,
        "query_start": query_start,
        "d7": d7,
        "d14": d14,
        "d30": d30,
        "prev7_start": prev7_start,
        "prev7_end": prev7_end,
        "selected_start": selected_start,
        "selected_end": selected_end,
    }
    filters = _scope_clauses(scope, params, product_alias="p", shop_alias="s", warehouse_alias="w")

    sql = text(
        f"""
        SELECT
          p.id AS product_id,
          p.merchant_code,
          p.product_name,
          SUM(CASE WHEN sd.business_date >= :d7 THEN sd.sales_qty ELSE 0 END) AS sales7,
          SUM(CASE WHEN sd.business_date >= :d14 THEN sd.sales_qty ELSE 0 END) AS sales14,
          SUM(CASE WHEN sd.business_date >= :d30 THEN sd.sales_qty ELSE 0 END) AS sales30,
          SUM(CASE WHEN sd.business_date BETWEEN :prev7_start AND :prev7_end THEN sd.sales_qty ELSE 0 END) AS prior7,
          SUM(CASE WHEN sd.business_date BETWEEN :selected_start AND :selected_end THEN sd.sales_qty ELSE 0 END) AS selected_sales,
          SUM(CASE WHEN sd.business_date BETWEEN :selected_start AND :selected_end AND sd.sales_qty > 0 AND sd.avg_price > 0
                   THEN sd.sales_qty * sd.avg_price ELSE 0 END) AS selected_revenue,
          SUM(CASE WHEN sd.business_date BETWEEN :selected_start AND :selected_end AND sd.sales_qty > 0 AND sd.avg_price > 0
                   THEN sd.sales_qty ELSE 0 END) AS selected_priced_qty
        FROM sales_daily sd
        JOIN products p ON p.id=sd.product_id
        JOIN shops s ON s.id=sd.shop_id
        JOIN warehouses w ON w.id=sd.warehouse_id
        WHERE sd.department_id=:department_id
          AND sd.business_date BETWEEN :query_start AND :end_date
          {_where(filters)}
        GROUP BY p.id,p.merchant_code,p.product_name
        """
    )
    rows = [dict(r) for r in db.execute(sql, params).mappings().all()]

    min_params: dict[str, Any] = {"department_id": department_id, "end_date": latest_sales_date}
    min_filters = _scope_clauses(scope, min_params, product_alias="p", shop_alias="s", warehouse_alias="w")
    min_date = db.execute(
        text(
            f"""
            SELECT MIN(sd.business_date)
            FROM sales_daily sd
            JOIN products p ON p.id=sd.product_id
            JOIN shops s ON s.id=sd.shop_id
            JOIN warehouses w ON w.id=sd.warehouse_id
            WHERE sd.department_id=:department_id AND sd.business_date <= :end_date
            {_where(min_filters)}
            """
        ),
        min_params,
    ).scalar_one_or_none()
    return rows, min_date


def _inventory_rows(
    db: Session,
    department_id: int,
    scope: DashboardScope,
    latest_inventory_date: date | None,
) -> list[dict[str, Any]]:
    if not latest_inventory_date:
        return []
    params: dict[str, Any] = {
        "department_id": department_id,
        "snapshot_date": latest_inventory_date,
    }
    filters = _scope_clauses(scope, params, product_alias="p", warehouse_alias="w")
    sql = text(
        f"""
        SELECT
          p.id AS product_id,
          p.merchant_code,
          p.product_name,
          SUM(ib.stock_qty) AS stock_qty
        FROM inventory_batch ib
        JOIN products p ON p.id=ib.product_id
        JOIN warehouses w ON w.id=ib.warehouse_id
        WHERE ib.department_id=:department_id
          AND ib.snapshot_date=:snapshot_date
          {_where(filters)}
        GROUP BY p.id,p.merchant_code,p.product_name
        """
    )
    return [dict(r) for r in db.execute(sql, params).mappings().all()]


def _load_expiry_rules(db: Session, department_id: int) -> tuple[ExpiryThreshold, ExpiryThreshold | None, dict[int, ExpiryThreshold]]:
    rows = db.execute(
        text(
            """
            SELECT scope_type,department_id,product_id,near_days,near_pct,warn_days,warn_pct,updated_at
            FROM expiry_rules
            WHERE scope_type='global'
               OR (scope_type='department' AND department_id=:department_id)
               OR (scope_type='product' AND (department_id=:department_id OR department_id IS NULL))
            ORDER BY updated_at DESC
            """
        ),
        {"department_id": department_id},
    ).mappings().all()

    global_rule: ExpiryThreshold | None = None
    department_rule: ExpiryThreshold | None = None
    product_rules: dict[int, ExpiryThreshold] = {}
    for row in rows:
        rule = ExpiryThreshold(
            near_days=int(row["near_days"]),
            near_pct=_number(row["near_pct"]),
            warn_days=int(row["warn_days"]),
            warn_pct=_number(row["warn_pct"]),
        )
        if row["scope_type"] == "global" and global_rule is None:
            global_rule = rule
        elif row["scope_type"] == "department" and department_rule is None:
            department_rule = rule
        elif row["scope_type"] == "product" and row["product_id"] is not None:
            product_rules.setdefault(int(row["product_id"]), rule)
    return global_rule or ExpiryThreshold(), department_rule, product_rules


def _safe_expiry_status(
    production_date: date | None,
    expire_date: date | None,
    snapshot_date: date,
    threshold: ExpiryThreshold,
) -> tuple[str, int | None, float | None]:
    if not expire_date or is_long_term_expiry(expire_date):
        return "正常", None, None
    days = remaining_days(snapshot_date, expire_date)
    pct: float | None = None
    if production_date:
        pct = remaining_percent(production_date, expire_date, snapshot_date)
    if days <= 0:
        return "过期", days, pct
    if days <= threshold.near_days or (pct is not None and pct <= threshold.near_pct):
        return "临期", days, pct
    if days <= threshold.warn_days or (pct is not None and pct <= threshold.warn_pct):
        return "预警", days, pct
    return "正常", days, pct


def _expiry_summary(
    db: Session,
    department_id: int,
    scope: DashboardScope,
    latest_inventory_date: date | None,
) -> dict[str, Any]:
    empty = {"正常": 0, "预警": 0, "临期": 0, "过期": 0}
    if not latest_inventory_date:
        return {"risk_products": 0, "categories": empty}

    params: dict[str, Any] = {
        "department_id": department_id,
        "snapshot_date": latest_inventory_date,
    }
    filters = _scope_clauses(scope, params, product_alias="p", warehouse_alias="w")
    rows = db.execute(
        text(
            f"""
            SELECT ib.product_id,p.product_name,p.merchant_code,ib.stock_qty,
                   ib.production_date,ib.expire_date
            FROM inventory_batch ib
            JOIN products p ON p.id=ib.product_id
            JOIN warehouses w ON w.id=ib.warehouse_id
            WHERE ib.department_id=:department_id
              AND ib.snapshot_date=:snapshot_date
              AND ib.stock_qty > 0
              {_where(filters)}
            """
        ),
        params,
    ).mappings().all()

    global_rule, department_rule, product_rules = _load_expiry_rules(db, department_id)
    category_products: dict[str, set[int]] = {k: set() for k in empty}
    severity = {"正常": 0, "预警": 1, "临期": 2, "过期": 3}
    product_worst: dict[int, str] = {}

    for row in rows:
        pid = int(row["product_id"])
        threshold = product_rules.get(pid) or department_rule or global_rule
        status, _, _ = _safe_expiry_status(row["production_date"], row["expire_date"], latest_inventory_date, threshold)
        old = product_worst.get(pid, "正常")
        if severity[status] > severity[old]:
            product_worst[pid] = status
        else:
            product_worst.setdefault(pid, old)

    for pid, status in product_worst.items():
        category_products[status].add(pid)

    categories = {k: len(v) for k, v in category_products.items()}
    risk_products = categories["预警"] + categories["临期"] + categories["过期"]
    return {"risk_products": risk_products, "categories": categories}


def _trend_rows(
    db: Session,
    department_id: int,
    scope: DashboardScope,
    latest_sales_date: date,
) -> list[dict[str, Any]]:
    start_date, end_date, selected_days = selected_sales_range(scope, latest_sales_date)
    params: dict[str, Any] = {
        "department_id": department_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    filters = _scope_clauses(scope, params, product_alias="p", shop_alias="s", warehouse_alias="w")
    rows = db.execute(
        text(
            f"""
            SELECT
              sd.business_date,
              SUM(sd.sales_qty) AS sales_qty,
              SUM(CASE WHEN sd.sales_qty > 0 AND sd.avg_price > 0 THEN sd.sales_qty * sd.avg_price ELSE 0 END) AS revenue,
              SUM(CASE WHEN sd.sales_qty > 0 AND sd.avg_price > 0 THEN sd.sales_qty ELSE 0 END) AS priced_qty
            FROM sales_daily sd
            JOIN products p ON p.id=sd.product_id
            JOIN shops s ON s.id=sd.shop_id
            JOIN warehouses w ON w.id=sd.warehouse_id
            WHERE sd.department_id=:department_id
              AND sd.business_date BETWEEN :start_date AND :end_date
              {_where(filters)}
            GROUP BY sd.business_date
            ORDER BY sd.business_date
            """
        ),
        params,
    ).mappings().all()
    by_date = {r["business_date"]: r for r in rows}
    result = []
    for offset in range(selected_days):
        d = start_date + timedelta(days=offset)
        r = by_date.get(d)
        qty = _number(r["sales_qty"]) if r else 0.0
        revenue = _number(r["revenue"]) if r else 0.0
        priced_qty = _number(r["priced_qty"]) if r else 0.0
        avg_price = revenue / priced_qty if scope.single_shop and priced_qty > 0 else None
        result.append(
            {
                "date": d.isoformat(),
                "sales_qty": _round(qty, 2),
                "avg_price": _round(avg_price, 2),
                "sales_amount": _round(revenue, 2) if scope.single_shop else None,
            }
        )
    return result


def _high_velocity_threshold(values: list[float]) -> float | None:
    values = sorted(v for v in values if v > 0)
    if not values:
        return None
    idx = max(0, math.ceil(len(values) * 0.8) - 1)
    return values[idx]


def build_rankings(products: list[dict[str, Any]], selected_days: int, single_shop: bool) -> dict[str, list[dict[str, Any]]]:
    threshold = _high_velocity_threshold([_number(p.get("predicted_daily")) for p in products])

    def public(p: dict[str, Any]) -> dict[str, Any]:
        return {
            "product_id": p["product_id"],
            "sku": p["sku"],
            "name": p["name"],
            "sales_qty": _round(_number(p.get("selected_sales")), 2),
            "sales30": _round(_number(p.get("sales30")), 2),
            "sales_amount": _round(_number(p.get("selected_revenue")), 2) if single_shop else None,
            "stock": _round(_number(p.get("stock")), 2),
            "predicted_daily": _round(_number(p.get("predicted_daily")), 2),
            "cover_days": _round(p.get("cover_days"), 1),
            "risk_level": p.get("risk_level", "不适用"),
            "turnover_days": _round(p.get("cover_days"), 1),
            "selected_days": selected_days,
        }

    sales = sorted(products, key=lambda p: (_number(p.get("selected_sales")), _number(p.get("sales30"))), reverse=True)
    sales = [public(p) for p in sales if _number(p.get("selected_sales")) > 0][:30]

    amount: list[dict[str, Any]] = []
    if single_shop:
        amount = sorted(products, key=lambda p: _number(p.get("selected_revenue")), reverse=True)
        amount = [public(p) for p in amount if _number(p.get("selected_revenue")) > 0][:30]

    shortage_candidates = []
    if threshold is not None:
        for p in products:
            stock = _number(p.get("stock"))
            sales30 = _number(p.get("sales30"))
            cover = p.get("cover_days")
            predicted = _number(p.get("predicted_daily"))
            if stock > 0 and sales30 > 0 and cover is not None and cover <= 45 and predicted >= threshold:
                shortage_candidates.append(p)
    shortage_candidates.sort(key=lambda p: (p.get("cover_days") if p.get("cover_days") is not None else 10**9, -_number(p.get("sales30"))))
    shortage = [public(p) for p in shortage_candidates[:30]]
    shortage_total = len(shortage_candidates)
    urgent_shortage_total = sum(1 for p in shortage_candidates if p.get("cover_days") is not None and p.get("cover_days") <= 10)

    slow_candidates = [p for p in products if _number(p.get("stock")) > 0]
    slow_candidates.sort(
        key=lambda p: (
            1 if _number(p.get("sales30")) <= 0 else 0,
            p.get("cover_days") if p.get("cover_days") is not None else 10**9,
            _number(p.get("stock")),
        ),
        reverse=True,
    )
    slow = [public(p) for p in slow_candidates[:30]]
    for item, p in zip(slow, slow_candidates[:30]):
        if _number(p.get("sales30")) <= 0:
            item["risk_level"] = "无销量库存"
            item["turnover_days"] = None

    return {
        "sales": sales,
        "sales_amount": amount,
        "shortage": shortage,
        "slow": slow,
        "high_velocity_threshold": _round(threshold, 2),
        "shortage_total": shortage_total,
        "urgent_shortage_total": urgent_shortage_total,
    }


def _merge_products(sales_rows: list[dict[str, Any]], inventory_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for row in sales_rows:
        pid = int(row["product_id"])
        priced_qty = _number(row.get("selected_priced_qty"))
        revenue = _number(row.get("selected_revenue"))
        merged[pid] = {
            "product_id": pid,
            "sku": row["merchant_code"],
            "name": row["product_name"],
            "sales7": _number(row.get("sales7")),
            "sales14": _number(row.get("sales14")),
            "sales30": _number(row.get("sales30")),
            "prior7": _number(row.get("prior7")),
            "selected_sales": _number(row.get("selected_sales")),
            "selected_revenue": revenue,
            "selected_avg_price": revenue / priced_qty if priced_qty > 0 else None,
            "stock": 0.0,
        }
    for row in inventory_rows:
        pid = int(row["product_id"])
        item = merged.setdefault(
            pid,
            {
                "product_id": pid,
                "sku": row["merchant_code"],
                "name": row["product_name"],
                "sales7": 0.0,
                "sales14": 0.0,
                "sales30": 0.0,
                "prior7": 0.0,
                "selected_sales": 0.0,
                "selected_revenue": 0.0,
                "selected_avg_price": None,
                "stock": 0.0,
            },
        )
        item["stock"] = _number(row.get("stock_qty"))

    for item in merged.values():
        predicted = predicted_daily_sales(item["sales7"], item["sales14"], item["sales30"])
        cover = predicted_stockout_days(item["stock"], predicted)
        item["predicted_daily"] = predicted
        item["cover_days"] = cover
        item["risk_level"] = shortage_risk_level(cover)
    return list(merged.values())


def _sales_history_available(db: Session, department_id: int, latest_sales_date: date) -> bool:
    start = latest_sales_date - timedelta(days=13)
    count = db.execute(
        text(
            """
            SELECT COUNT(DISTINCT business_date)
            FROM import_batches
            WHERE department_id=:department_id
              AND data_type='sales'
              AND status='success'
              AND business_date BETWEEN :start_date AND :end_date
            """
        ),
        {"department_id": department_id, "start_date": start, "end_date": latest_sales_date},
    ).scalar_one()
    return int(count or 0) >= 14


def get_filter_options(db: Session, scope: DashboardScope) -> dict[str, Any]:
    _, department = assert_can_view_department(db, scope.actor_user_id, scope.department_code)
    department_id = int(department["id"])
    shops = [
        r[0]
        for r in db.execute(
            text(
                """
                SELECT DISTINCT s.source_name
                FROM sales_daily sd JOIN shops s ON s.id=sd.shop_id
                WHERE sd.department_id=:department_id
                ORDER BY s.source_name
                """
            ),
            {"department_id": department_id},
        ).all()
    ]
    warehouses = [
        r[0]
        for r in db.execute(
            text(
                """
                SELECT source_name FROM (
                  SELECT DISTINCT w.source_name AS source_name
                  FROM sales_daily sd JOIN warehouses w ON w.id=sd.warehouse_id
                  WHERE sd.department_id=:department_id
                  UNION
                  SELECT DISTINCT w.source_name AS source_name
                  FROM inventory_batch ib JOIN warehouses w ON w.id=ib.warehouse_id
                  WHERE ib.department_id=:department_id
                ) x ORDER BY source_name
                """
            ),
            {"department_id": department_id},
        ).all()
    ]
    product_categories = [
        {
            "id": int(r["id"]),
            "name": r["category_name"],
        }
        for r in db.execute(
            text(
                """
                SELECT DISTINCT pc.id, pc.category_name
                FROM product_categories pc
                JOIN product_category_relations pcr
                  ON pcr.category_id=pc.id
                WHERE
                  EXISTS(
                    SELECT 1
                    FROM sales_daily sd
                    WHERE sd.department_id=:department_id
                      AND sd.product_id=pcr.product_id
                  )
                  OR EXISTS(
                    SELECT 1
                    FROM inventory_batch ib
                    WHERE ib.department_id=:department_id
                      AND ib.product_id=pcr.product_id
                  )
                  OR EXISTS(
                    SELECT 1
                    FROM aging_snapshot ag
                    WHERE ag.department_id=:department_id
                      AND ag.product_id=pcr.product_id
                  )
                  OR EXISTS(
                    SELECT 1
                    FROM products p
                    JOIN import_batches b ON b.id=p.import_batch_id
                    WHERE p.id=pcr.product_id
                      AND b.department_id=:department_id
                  )
                ORDER BY pc.category_name
                """
            ),
            {"department_id": department_id},
        ).mappings().all()
    ]

    return {
        "department": {"code": department["code"], "name": department["name"]},
        "shops": shops,
        "warehouses": warehouses,
        "product_categories": product_categories,
    }


def get_dashboard(db: Session, scope: DashboardScope) -> dict[str, Any]:
    days = scope.days if scope.days in VALID_DAYS else 30
    scope = DashboardScope(
        actor_user_id=scope.actor_user_id,
        department_code=scope.department_code,
        days=days,
        start_date=scope.start_date,
        end_date=scope.end_date,
        shops=tuple(scope.shops),
        warehouses=tuple(scope.warehouses),
        product_search=scope.product_search,
        include_name=scope.include_name,
        exclude_name=scope.exclude_name,
        product_codes=tuple(scope.product_codes),
    )
    actor, department = assert_can_view_department(db, scope.actor_user_id, scope.department_code)
    department_id = int(department["id"])
    latest_sales_date = _get_latest_sales_date(db, department_id)
    latest_inventory_date = _get_latest_inventory_date(db, department_id)
    selected_start = selected_end = None
    selected_days = days
    if latest_sales_date:
        selected_start, selected_end, selected_days = selected_sales_range(scope, latest_sales_date)

    empty_response = {
        "meta": {
            "department": {"code": department["code"], "name": department["name"]},
            "actor": {"user_id": actor["user_id"], "username": actor["username"]},
            "selected_days": selected_days,
            "selected_start_date": _date_text(selected_start),
            "selected_end_date": _date_text(selected_end),
            "single_shop": scope.single_shop,
            "sales_amount_visible": scope.single_shop,
            "price_visible": scope.single_shop,
            "latest_sales_date": _date_text(latest_sales_date),
            "latest_inventory_date": _date_text(latest_inventory_date),
            "inventory_dimension_note": "库存只按部门/仓库/商品筛选，不按店铺拆分。",
        },
        "kpis": {
            "sales_qty": 0,
            "sales_amount": None,
            "active_sku": 0,
            "stock_qty": 0,
            "turnover_days": None,
            "shortage_risk": 0,
            "expiry_risk": 0,
        },
        "risks": {
            "urgent_shortage": 0,
            "slow_moving": 0,
            "declining_sales": None,
            "comparison_available": False,
            "recent7_sales": 0,
            "prior7_sales": 0,
            "seven_day_change_pct": None,
        },
        "comparison": {
            "current": {"sales": 0.0, "start_date": None, "end_date": None},
            "mom": {"available": False, "sales": None, "change_pct": None, "note": "历史数据不足"},
            "yoy": {"available": False, "sales": None, "change_pct": None, "note": "历史数据不足"},
        },
        "trend": [],
        "rankings": {"sales": [], "sales_amount": [], "shortage": [], "slow": [], "high_velocity_threshold": None, "shortage_total": 0, "urgent_shortage_total": 0},
        "expiry_categories": {"正常": 0, "预警": 0, "临期": 0, "过期": 0},
    }
    if not latest_sales_date:
        if latest_inventory_date:
            inventory = _inventory_rows(db, department_id, scope, latest_inventory_date)
            expiry = _expiry_summary(db, department_id, scope, latest_inventory_date)
            empty_response["kpis"]["stock_qty"] = _round(sum(_number(r["stock_qty"]) for r in inventory), 2)
            empty_response["kpis"]["expiry_risk"] = expiry["risk_products"]
            empty_response["expiry_categories"] = expiry["categories"]
        return empty_response

    sales_rows, _min_sales_date = _sales_rows(db, department_id, scope, latest_sales_date)
    inventory_rows = _inventory_rows(db, department_id, scope, latest_inventory_date)
    products = _merge_products(sales_rows, inventory_rows)
    rankings = build_rankings(products, selected_days, scope.single_shop)
    expiry = _expiry_summary(db, department_id, scope, latest_inventory_date)
    trend = _trend_rows(db, department_id, scope, latest_sales_date)
    comparison = sales_period_comparison(db, department_id, scope, latest_sales_date)

    selected_sales = sum(_number(p["selected_sales"]) for p in products)
    selected_revenue = sum(_number(p["selected_revenue"]) for p in products)
    total_sales30 = sum(_number(p["sales30"]) for p in products)
    total_stock = sum(_number(p["stock"]) for p in products)
    active_sku = sum(1 for p in products if _number(p["selected_sales"]) > 0)
    turnover_days = total_stock / (total_sales30 / 30.0) if total_sales30 > 0 else None

    shortage_candidates = rankings["shortage"]
    urgent_shortage = int(rankings["urgent_shortage_total"])
    slow_moving = sum(
        1
        for p in products
        if _number(p["stock"]) > 0 and (_number(p["sales30"]) <= 0 or (p["cover_days"] is not None and p["cover_days"] > 90))
    )

    comparison_available = _sales_history_available(db, department_id, latest_sales_date)
    recent7 = sum(_number(p["sales7"]) for p in products)
    prior7 = sum(_number(p["prior7"]) for p in products)
    change_pct = ((recent7 - prior7) / prior7 * 100.0) if comparison_available and prior7 > 0 else None
    declining_sales = None
    if comparison_available:
        declining_sales = sum(
            1
            for p in products
            if _number(p["prior7"]) > 0 and _number(p["sales7"]) < _number(p["prior7"]) * 0.8
        )

    return {
        "meta": {
            "department": {"code": department["code"], "name": department["name"]},
            "actor": {"user_id": actor["user_id"], "username": actor["username"]},
            "selected_days": selected_days,
            "selected_start_date": _date_text(selected_start),
            "selected_end_date": _date_text(selected_end),
            "single_shop": scope.single_shop,
            "sales_amount_visible": scope.single_shop,
            "price_visible": scope.single_shop,
            "latest_sales_date": _date_text(latest_sales_date),
            "latest_inventory_date": _date_text(latest_inventory_date),
            "inventory_dimension_note": "库存只按部门/仓库/商品筛选，不按店铺拆分。",
        },
        "kpis": {
            "sales_qty": _round(selected_sales, 2),
            "sales_amount": _round(selected_revenue, 2) if scope.single_shop else None,
            "active_sku": active_sku,
            "stock_qty": _round(total_stock, 2),
            "turnover_days": _round(turnover_days, 1),
            "shortage_risk": int(rankings["shortage_total"]),
            "expiry_risk": expiry["risk_products"],
        },
        "risks": {
            "urgent_shortage": urgent_shortage,
            "slow_moving": slow_moving,
            "declining_sales": declining_sales,
            "comparison_available": comparison_available,
            "recent7_sales": _round(recent7, 2),
            "prior7_sales": _round(prior7, 2),
            "seven_day_change_pct": _round(change_pct, 2),
        },
        "comparison": comparison,
        "trend": trend,
        "rankings": rankings,
        "expiry_categories": expiry["categories"],
    }
