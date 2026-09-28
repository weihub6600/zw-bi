from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
import re

from .auth_service import record_activity
from .permission_service import PermissionDenied, assert_can_view_department
from ..core.timezone import today_local


class CostValidationError(ValueError):
    pass


def is_missing_cost_table_error(exc: SQLAlchemyError) -> bool:
    original = getattr(exc, "orig", None)
    message = str(original or exc).lower()
    if "department_product_costs" not in message:
        return False
    code = getattr(original, "args", (None,))[0] if original is not None else None
    return code == 1146 or "no such table" in message or "doesn't exist" in message or "does not exist" in message


def _date_text(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _validate_cost(value: Any) -> Decimal:
    try:
        cost = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise CostValidationError("成本价必须是有效数字") from exc
    if not cost.is_finite() or cost <= 0 or cost >= Decimal("1E+12"):
        raise CostValidationError("成本价必须大于 0 且小于 1000000000000")
    if cost.as_tuple().exponent < -6:
        raise CostValidationError("成本价最多保留 6 位小数")
    return cost


def _validate_currency(value: str) -> str:
    currency = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise CostValidationError("币种请填写 3 位 ISO 代码，例如 CNY")
    return currency


def _assert_cost_maintainer(actor: dict[str, Any]) -> None:
    # The business owner has not yet confirmed a separate department-level
    # cost permission. Keep the safe default: only system admins can write or
    # read cost values until that authorization is explicitly designed.
    if not actor.get("is_system_admin"):
        raise PermissionDenied("当前未授予商品成本查看或维护权限")


def _product(db: Session, merchant_code: str) -> dict[str, Any]:
    row = db.execute(
        text("SELECT id,merchant_code,product_name FROM products WHERE merchant_code=:code"),
        {"code": merchant_code.strip()},
    ).mappings().first()
    if not row:
        raise LookupError(f"商品不存在：{merchant_code}")
    return dict(row)


def _assert_product_visible(db: Session, department_id: int, product_id: int) -> None:
    visible = db.execute(
        text(
            """
            SELECT EXISTS(SELECT 1 FROM sales_daily WHERE department_id=:department_id AND product_id=:product_id)
                OR EXISTS(SELECT 1 FROM inventory_batch WHERE department_id=:department_id AND product_id=:product_id)
                OR EXISTS(SELECT 1 FROM aging_snapshot WHERE department_id=:department_id AND product_id=:product_id)
                OR EXISTS(
                  SELECT 1 FROM products p JOIN import_batches b ON b.id=p.import_batch_id
                  WHERE p.id=:product_id AND b.department_id=:department_id
                )
            """
        ),
        {"department_id": department_id, "product_id": product_id},
    ).scalar()
    if not visible:
        raise LookupError("该商品在所选部门不可见")


def get_cost_as_of(
    db: Session,
    department_id: int,
    product_id: int,
    as_of_date: date,
) -> dict[str, Any] | None:
    """Resolve the department/product cost for a business date.

    The newest version on or before the date wins. If no such version exists,
    the earliest version is used so the first recorded cost covers prior dates.
    """
    row = db.execute(
        text(
            """
            SELECT id,effective_date,unit_cost,currency,unit,source,source_import_batch_id
            FROM department_product_costs
            WHERE department_id=:department_id AND product_id=:product_id
              AND effective_date<=:as_of_date
            ORDER BY effective_date DESC,id DESC LIMIT 1
            """
        ),
        {"department_id": department_id, "product_id": product_id, "as_of_date": as_of_date},
    ).mappings().first()
    if not row:
        row = db.execute(
            text(
                """
                SELECT id,effective_date,unit_cost,currency,unit,source,source_import_batch_id
                FROM department_product_costs
                WHERE department_id=:department_id AND product_id=:product_id
                ORDER BY effective_date ASC,id ASC LIMIT 1
                """
            ),
            {"department_id": department_id, "product_id": product_id},
        ).mappings().first()
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "unit_cost": str(row["unit_cost"]),
        "currency": row["currency"],
        "unit": row["unit"],
        "source": row["source"],
        "effective_date": _date_text(row["effective_date"]),
        "source_import_batch_id": row["source_import_batch_id"],
    }


def costs_as_of(
    db: Session,
    department_id: int,
    product_ids: list[int],
    as_of_date: date,
) -> dict[int, dict[str, Any]]:
    """Resolve visible product costs in one query for list-style analysis views."""
    ids = list(dict.fromkeys(int(value) for value in product_ids))
    if not ids:
        return {}
    placeholders = ",".join(f":cost_product_{i}" for i in range(len(ids)))
    params = {"department_id": department_id, "as_of_date": as_of_date}
    params.update({f"cost_product_{i}": value for i, value in enumerate(ids)})
    rows = db.execute(
        text(
            f"""
            SELECT product_id,effective_date,unit_cost,currency,unit,source
            FROM department_product_costs
            WHERE department_id=:department_id AND product_id IN ({placeholders})
            ORDER BY product_id,effective_date DESC,id DESC
            """
        ),
        params,
    ).mappings().all()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["product_id"]), []).append(dict(row))
    result: dict[int, dict[str, Any]] = {}
    for product_id, versions in grouped.items():
        selected = next(
            (row for row in versions if _date_text(row["effective_date"])[:10] <= as_of_date.isoformat()),
            versions[-1],
        )
        result[product_id] = {
            "unit_cost": str(selected["unit_cost"]),
            "currency": selected["currency"],
            "unit": selected["unit"],
            "source": selected["source"],
            "effective_date": _date_text(selected["effective_date"]),
        }
    return result


def cost_reference(
    db: Session,
    department_id: int,
    product_id: int,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    current = get_cost_as_of(db, department_id, product_id, end_date)
    changes = db.execute(
        text(
            """
            SELECT COUNT(*) FROM department_product_costs
            WHERE department_id=:department_id AND product_id=:product_id
              AND effective_date>:start_date AND effective_date<=:end_date
            """
        ),
        {"department_id": department_id, "product_id": product_id, "start_date": start_date, "end_date": end_date},
    ).scalar() or 0
    return {
        "unit_cost": current["unit_cost"] if current else None,
        "currency": current["currency"] if current else None,
        "unit": current["unit"] if current else None,
        "cost_effective_date": current["effective_date"] if current else None,
        "as_of_date": end_date.isoformat(),
        "cost_changed_in_period": int(changes) > 0,
        "cost_change_count_in_period": int(changes),
    }


def save_manual_cost(
    db: Session,
    actor: dict[str, Any],
    department_code: str,
    merchant_code: str,
    unit_cost: Any,
    effective_date: date,
    currency: str = "CNY",
    unit: str = "件",
) -> dict[str, Any]:
    actor_pk = int(actor.get("id", actor.get("user_pk")))
    _assert_cost_maintainer(actor)
    _, department = assert_can_view_department(db, actor["user_id"], department_code)
    product = _product(db, merchant_code)
    _assert_product_visible(db, int(department["id"]), int(product["id"]))
    cost = _validate_cost(unit_cost)
    currency = _validate_currency(currency)
    unit = str(unit or "").strip()
    if not unit or len(unit) > 32:
        raise CostValidationError("请填写币种代码和商品销售计量单位")
    if effective_date != today_local():
        raise CostValidationError("生效日期暂仅支持业务当天；历史补录和未来生效需受控确认流程")
    existing = db.execute(
        text(
            "SELECT id FROM department_product_costs WHERE department_id=:department_id AND product_id=:product_id AND effective_date=:effective_date"
        ),
        {"department_id": department["id"], "product_id": product["id"], "effective_date": effective_date},
    ).first()
    if existing:
        raise CostValidationError("该部门该商品在生效日已有成本版本；如需纠错请走受控修正流程")
    try:
        result = db.execute(
            text(
                """
                INSERT INTO department_product_costs(
                  department_id,product_id,effective_date,unit_cost,currency,unit,created_by
                ) VALUES(:department_id,:product_id,:effective_date,:unit_cost,:currency,:unit,:created_by)
                """
            ),
            {"department_id": department["id"], "product_id": product["id"], "effective_date": effective_date, "unit_cost": cost, "currency": currency, "unit": unit, "created_by": actor_pk},
        )
    except IntegrityError as exc:
        raise CostValidationError("该部门该商品在生效日已有成本版本，请刷新后重试") from exc
    record_activity(
        db,
        actor_pk,
        "product_cost_create",
        department_id=int(department["id"]),
        detail={"sku": product["merchant_code"], "effective_date": effective_date.isoformat()},
    )
    db.commit()
    return {"saved": True, "id": int(result.lastrowid), "sku": product["merchant_code"], "effective_date": effective_date.isoformat(), "unit_cost": str(cost), "currency": currency, "unit": unit}


def list_cost_history(db: Session, actor: dict[str, Any], department_code: str, merchant_code: str) -> dict[str, Any]:
    _assert_cost_maintainer(actor)
    _, department = assert_can_view_department(db, actor["user_id"], department_code)
    product = _product(db, merchant_code)
    _assert_product_visible(db, int(department["id"]), int(product["id"]))
    rows = db.execute(
        text(
            """
            SELECT effective_date,unit_cost,currency,unit,source,created_at
            FROM department_product_costs
            WHERE department_id=:department_id AND product_id=:product_id
            ORDER BY effective_date ASC,id ASC
            """
        ),
        {"department_id": department["id"], "product_id": product["id"]},
    ).mappings().all()
    return {"sku": product["merchant_code"], "items": [dict(row) for row in rows]}


def search_department_products(db: Session, actor: dict[str, Any], department_code: str, query: str) -> dict[str, Any]:
    _assert_cost_maintainer(actor)
    _, department = assert_can_view_department(db, actor["user_id"], department_code)
    query = str(query or "").strip()
    if len(query) < 2:
        return {"items": []}
    pattern = f"%{query.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
    rows = db.execute(
        text(
            """
            SELECT p.id AS product_id,p.merchant_code,p.product_name,p.spec,p.brand
            FROM products p
            WHERE (p.merchant_code LIKE :query ESCAPE '!' OR p.product_name LIKE :query ESCAPE '!')
              AND (
                EXISTS(SELECT 1 FROM sales_daily s WHERE s.department_id=:department_id AND s.product_id=p.id)
                OR EXISTS(SELECT 1 FROM inventory_batch i WHERE i.department_id=:department_id AND i.product_id=p.id)
                OR EXISTS(SELECT 1 FROM aging_snapshot a WHERE a.department_id=:department_id AND a.product_id=p.id)
                OR EXISTS(SELECT 1 FROM import_batches b WHERE b.id=p.import_batch_id AND b.department_id=:department_id)
              )
            ORDER BY p.merchant_code LIMIT 30
            """
        ),
        {"query": pattern, "department_id": department["id"]},
    ).mappings().all()
    return {"items": [dict(row) for row in rows]}
