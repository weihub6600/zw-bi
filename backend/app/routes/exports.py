from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.auth import require_actor
from ..db import get_db
from ..services.export_service import (
    ExportError,
    export_aging,
    export_expiry_batches,
    export_inventory,
    export_inventory_analysis,
    export_product,
    export_sales,
)
from ..services.permission_service import PermissionDenied

router = APIRouter(prefix="/exports", tags=["exports"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _handle(exc: Exception):
    if isinstance(exc, PermissionDenied):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ExportError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise exc


def _xlsx_response(content: bytes, filename: str, row_count: int | None = None, ascii_filename: str = "export.xlsx"):
    from urllib.parse import quote

    from fastapi.responses import Response

    # RFC 6266/5987：ASCII 文件名兜底 + filename* 携带 UTF-8 中文真实名，
    # 避免中文文件名触发 latin-1 编码失败（UnicodeEncodeError → HTTP 500）。
    safe_name = ascii_filename or "export.xlsx"
    encoded_name = quote(filename, safe="")
    content_disposition = f"attachment; filename=\"{safe_name}\"; filename*=UTF-8''{encoded_name}"
    headers = {"Content-Disposition": content_disposition}
    if row_count is not None:
        headers["X-Export-Row-Count"] = str(row_count)
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers=headers,
    )


@router.get("/product")
def download_product(department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        result = export_product(db, actor["user_id"], department_code)
        return _xlsx_response(result["content"], result["filename"], ascii_filename=result.get("ascii_filename", "export.xlsx"))
    except Exception as exc:
        _handle(exc)


@router.get("/sales")
def download_sales(
    department_code: str = "B2C",
    start_date: date | None = None,
    end_date: date | None = None,
    days: int = 30,
    shops: str = "",
    warehouses: str = "",
    product_search: str = "",
    include_name: str = "",
    exclude_name: str = "",
    product_codes: str = "",
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    """下载当前筛选结果对应的全部销量明细（不分页）。

    筛选条件（日期预设/店铺/仓库/商品名/商家编码等）与列表页一致，全部由后端
    基于登录用户权限范围过滤，跨部门一律 403。
    """
    try:
        result = export_sales(
            db,
            actor["user_id"],
            department_code,
            start_date=start_date,
            end_date=end_date,
            days=days,
            shops=_split_csv(shops),
            warehouses=_split_csv(warehouses),
            product_search=product_search,
            include_name=include_name,
            exclude_name=exclude_name,
            product_codes=_split_csv(product_codes),
        )
        return _xlsx_response(result["content"], result["filename"], row_count=result["row_count"], ascii_filename=result.get("ascii_filename", "export.xlsx"))
    except Exception as exc:
        _handle(exc)


def _split_csv(value: str) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


@router.get("/inventory")
def download_inventory(department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        result = export_inventory(db, actor["user_id"], department_code)
        return _xlsx_response(result["content"], result["filename"], ascii_filename=result.get("ascii_filename", "export.xlsx"))
    except Exception as exc:
        _handle(exc)


@router.get("/aging")
def download_aging(department_code: str = "B2C", actor: dict = Depends(require_actor), db: Session = Depends(get_db)):
    try:
        result = export_aging(db, actor["user_id"], department_code)
        return _xlsx_response(result["content"], result["filename"], ascii_filename=result.get("ascii_filename", "export.xlsx"))
    except Exception as exc:
        _handle(exc)


@router.get("/inventory-analysis")
def download_inventory_analysis(
    department_code: str = "B2C",
    shops: str = "",
    warehouses: str = "",
    days: int = 30,
    product_search: str = "",
    include_name: str = "",
    exclude_name: str = "",
    product_codes: str = "",
    category: str = "",
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    """下载库存明细（库存视图的 SKU 级库存健康度），复用列表相同筛选与权限。"""
    try:
        result = export_inventory_analysis(
            db,
            actor["user_id"],
            department_code,
            shops=_split_csv(shops),
            warehouses=_split_csv(warehouses),
            days=days,
            product_search=product_search,
            include_name=include_name,
            exclude_name=exclude_name,
            product_codes=_split_csv(product_codes),
            category=category or None,
        )
        return _xlsx_response(result["content"], result["filename"], row_count=result["row_count"], ascii_filename=result.get("ascii_filename", "export.xlsx"))
    except Exception as exc:
        _handle(exc)


@router.get("/expiry-batches")
def download_expiry_batches(
    department_code: str = "B2C",
    warehouses: str = "",
    product_search: str = "",
    include_name: str = "",
    exclude_name: str = "",
    product_codes: str = "",
    statuses: str = "",
    remaining_days_min: int | None = None,
    remaining_days_max: int | None = None,
    remaining_pct_min: float | None = None,
    remaining_pct_max: float | None = None,
    merchant_code: str = "",
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    """下载效期批次明细（效期视图），复用列表相同筛选与权限。"""
    try:
        result = export_expiry_batches(
            db,
            actor["user_id"],
            department_code,
            warehouses=_split_csv(warehouses),
            product_search=product_search,
            include_name=include_name,
            exclude_name=exclude_name,
            product_codes=_split_csv(product_codes),
            statuses=_split_csv(statuses),
            remaining_days_min=remaining_days_min,
            remaining_days_max=remaining_days_max,
            remaining_pct_min=remaining_pct_min,
            remaining_pct_max=remaining_pct_max,
            merchant_code=merchant_code or None,
        )
        return _xlsx_response(result["content"], result["filename"], row_count=result["row_count"], ascii_filename=result.get("ascii_filename", "export.xlsx"))
    except Exception as exc:
        _handle(exc)
