from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .permission_service import get_actor
from .auth_service import record_activity


def _json_value(value: Any, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def normalize_string_list(values: list[str] | tuple[str, ...] | None) -> list[str]:
    """去空、去重、保留用户输入顺序。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = str(raw).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def normalize_int_list(values: list[int] | tuple[int, ...] | None) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for raw in values or []:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _public(row: dict[str, Any]) -> dict[str, Any]:
    product_filter = _json_value(row.get("product_filter"), {})
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "shops": normalize_string_list(_json_value(row.get("shop_filter"), [])),
        "warehouses": normalize_string_list(_json_value(row.get("warehouse_filter"), [])),
        "product_codes": normalize_string_list(product_filter.get("merchant_codes", [])),
        "product_category_ids": normalize_int_list(product_filter.get("category_ids", [])),
        "include_name_keywords": normalize_string_list(_json_value(row.get("include_name_keywords"), [])),
        "exclude_name_keywords": normalize_string_list(_json_value(row.get("exclude_name_keywords"), [])),
        "updated_at": str(row.get("updated_at") or ""),
    }


def list_presets(db: Session, actor_user_id: str) -> list[dict[str, Any]]:
    actor = get_actor(db, actor_user_id)
    rows = db.execute(
        text(
            """
            SELECT id,name,shop_filter,warehouse_filter,product_filter,
                   include_name_keywords,exclude_name_keywords,updated_at
            FROM filter_presets
            WHERE user_pk=:user_pk
            ORDER BY updated_at DESC,id DESC
            """
        ),
        {"user_pk": actor["id"]},
    ).mappings().all()
    return [_public(dict(r)) for r in rows]


def save_preset(
    db: Session,
    actor_user_id: str,
    *,
    name: str,
    shops: list[str],
    warehouses: list[str],
    product_codes: list[str],
    product_category_ids: list[int],
    include_name_keywords: list[str],
    exclude_name_keywords: list[str],
    preset_id: int | None = None,
) -> dict[str, Any]:
    actor = get_actor(db, actor_user_id)
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("预设名称不能为空")
    if clean_name == "全部":
        raise ValueError("“全部”是系统固定筛选，不能作为个人预设名称")
    if len(clean_name) > 64:
        raise ValueError("预设名称不能超过64个字符")

    payload = {
        "name": clean_name,
        "shops": json.dumps(normalize_string_list(shops), ensure_ascii=False),
        "warehouses": json.dumps(normalize_string_list(warehouses), ensure_ascii=False),
        "product_filter": json.dumps({
            "merchant_codes": normalize_string_list(product_codes),
            "category_ids": normalize_int_list(product_category_ids),
        }, ensure_ascii=False),
        "include": json.dumps(normalize_string_list(include_name_keywords), ensure_ascii=False),
        "exclude": json.dumps(normalize_string_list(exclude_name_keywords), ensure_ascii=False),
        "user_pk": actor["id"],
    }

    is_create = preset_id is None
    if preset_id is None:
        duplicate = db.execute(
            text("SELECT id FROM filter_presets WHERE user_pk=:user_pk AND name=:name"),
            {"user_pk": actor["id"], "name": clean_name},
        ).scalar_one_or_none()
        if duplicate:
            raise ValueError("该预设名称已存在")
        result = db.execute(
            text(
                """
                INSERT INTO filter_presets(
                  user_pk,name,shop_filter,warehouse_filter,product_filter,
                  include_name_keywords,exclude_name_keywords
                ) VALUES(
                  :user_pk,:name,:shops,:warehouses,:product_filter,:include,:exclude
                )
                """
            ),
            payload,
        )
        preset_id = int(result.lastrowid)
    else:
        owned = db.execute(
            text("SELECT id FROM filter_presets WHERE id=:id AND user_pk=:user_pk"),
            {"id": preset_id, "user_pk": actor["id"]},
        ).scalar_one_or_none()
        if not owned:
            raise LookupError("筛选预设不存在")
        duplicate = db.execute(
            text("SELECT id FROM filter_presets WHERE user_pk=:user_pk AND name=:name AND id<>:id"),
            {"user_pk": actor["id"], "name": clean_name, "id": preset_id},
        ).scalar_one_or_none()
        if duplicate:
            raise ValueError("该预设名称已存在")
        db.execute(
            text(
                """
                UPDATE filter_presets
                SET name=:name,shop_filter=:shops,warehouse_filter=:warehouses,
                    product_filter=:product_filter,include_name_keywords=:include,
                    exclude_name_keywords=:exclude,updated_at=CURRENT_TIMESTAMP
                WHERE id=:id AND user_pk=:user_pk
                """
            ),
            {**payload, "id": preset_id},
        )

    db.commit()
    record_activity(db,int(actor["id"]),"preset_create" if is_create else "preset_update",detail={"preset_id":preset_id,"name":clean_name})
    row = db.execute(
        text(
            """
            SELECT id,name,shop_filter,warehouse_filter,product_filter,
                   include_name_keywords,exclude_name_keywords,updated_at
            FROM filter_presets WHERE id=:id AND user_pk=:user_pk
            """
        ),
        {"id": preset_id, "user_pk": actor["id"]},
    ).mappings().one()
    return _public(dict(row))


def delete_preset(db: Session, actor_user_id: str, preset_id: int) -> dict[str, Any]:
    actor = get_actor(db, actor_user_id)
    row = db.execute(
        text("SELECT id,name FROM filter_presets WHERE id=:id AND user_pk=:user_pk"),
        {"id": preset_id, "user_pk": actor["id"]},
    ).mappings().first()
    if not row:
        raise LookupError("筛选预设不存在")
    db.execute(
        text("DELETE FROM filter_presets WHERE id=:id AND user_pk=:user_pk"),
        {"id": preset_id, "user_pk": actor["id"]},
    )
    db.commit()
    record_activity(db,int(actor["id"]),"preset_delete",detail={"preset_id":int(row["id"]),"name":row["name"]})
    return {"deleted": True, "id": int(row["id"]), "name": row["name"]}
