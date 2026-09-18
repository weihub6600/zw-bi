from __future__ import annotations

import os
import tempfile
import re
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..core.auth import require_actor
from ..core.config import settings
from ..services.import_db_service import (
    DuplicateImportError,
    ImportExecutionError,
    RollbackConflictError,
    SystemImportError,
    import_batch_detail,
    import_batch_issues,
    import_file,
    latest_business_date,
    recent_batches,
    rollback_batch,
)
from ..services.import_parser import ImportValidationError, parse_import_file, parsed_preview, sha256_file
from ..services.permission_service import ActorNotFound, PermissionDenied, assert_can_import

router = APIRouter(prefix="/imports", tags=["imports"])
DataType = Literal["sales", "inventory", "product", "aging"]



def _save_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "upload.xlsx").suffix.lower()
    if suffix not in {".xlsx", ".csv", ".xls"}:
        raise HTTPException(status_code=400, detail="只支持 .xlsx / .csv（.xls 请另存为 .xlsx）")
    safe_stem = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", Path(upload.filename or "upload").stem)[:80]
    fd, path = tempfile.mkstemp(prefix=f"bjr_import_{safe_stem}_", suffix=suffix)
    try:
        total_bytes = 0
        with os.fdopen(fd, "wb") as f:
            while chunk := upload.file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"上传文件超过 {settings.max_upload_bytes // (1024 * 1024)}MB 上限",
                    )
                f.write(chunk)
        return path
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def _handle_error(exc: Exception) -> None:
    if isinstance(exc, (PermissionDenied, ActorNotFound)):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, SystemImportError):
        # 系统级错误（如数据库缺表）：返回友好信息与错误码，不逐行重复展示底层 traceback。
        raise HTTPException(
            status_code=500,
            detail={
                "code": exc.error_code,
                "message": "销量导入失败：数据库结构版本不完整，请联系管理员升级数据库。本次导入已终止。",
                "detail": exc.detail or str(exc),
            },
        )
    if isinstance(exc, ImportValidationError):
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})
    if isinstance(exc, DuplicateImportError):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, RollbackConflictError):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ImportExecutionError):
        status = 404 if "不存在" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc))
    raise exc


@router.post("/preview")
def preview_import(
    data_type: DataType = Form(...),
    department_code: str = Form("B2C"),
    business_date: date | None = Form(None),
    file: UploadFile = File(...),
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    temp_path = _save_upload(file)
    try:
        _, department = assert_can_import(db, actor["user_id"], department_code)
        parsed = parse_import_file(temp_path, data_type, business_date)
        result = parsed_preview(parsed, limit=10)
        file_hash = sha256_file(temp_path)
        result["original_filename"] = file.filename
        result["file_sha256"] = file_hash
        duplicate = db.execute(
            text(
                """
                SELECT batch_no,status,created_at
                FROM import_batches
                WHERE department_id=:department_id AND data_type=:data_type
                  AND (business_date <=> :business_date) AND file_sha256=:file_hash
                  AND status='success'
                ORDER BY id DESC LIMIT 1
                """
            ),
            {
                "department_id": department["id"],
                "data_type": data_type,
                "business_date": business_date,
                "file_hash": file_hash,
            },
        ).mappings().first()
        if duplicate:
            result["duplicate"] = {
                "batch_no": duplicate["batch_no"],
                "status": duplicate["status"],
                "created_at": duplicate["created_at"].isoformat(sep=" ") if duplicate["created_at"] else None,
            }
            # 销量采用“同部门 + 同业务日期整日覆盖，最后一次上传为准”。
            # 即使 SHA256 完全相同，也允许重新提交；结果只是用当前文件重新生成该日事实数据。
            if data_type != "sales":
                result["commit_allowed"] = False
        else:
            result["duplicate"] = None

        result["replace_existing"] = None
        if data_type == "sales" and business_date is not None:
            existing_rows = int(
                db.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM sales_daily
                        WHERE department_id=:department_id AND business_date=:business_date
                        """
                    ),
                    {"department_id": department["id"], "business_date": business_date},
                ).scalar() or 0
            )
            previous = db.execute(
                text(
                    """
                    SELECT batch_no,created_at,original_filename
                    FROM import_batches
                    WHERE department_id=:department_id AND data_type='sales'
                      AND business_date=:business_date AND status='success'
                    ORDER BY id DESC LIMIT 1
                    """
                ),
                {"department_id": department["id"], "business_date": business_date},
            ).mappings().first()
            if existing_rows or previous:
                result["replace_existing"] = {
                    "business_date": business_date.isoformat(),
                    "existing_rows": existing_rows,
                    "previous_batch_no": previous["batch_no"] if previous else None,
                    "previous_filename": previous["original_filename"] if previous else None,
                    "previous_created_at": previous["created_at"].isoformat(sep=" ") if previous and previous["created_at"] else None,
                    "same_file": bool(duplicate),
                }
                if existing_rows > 0 and parsed.error_rows > 0:
                    result["commit_allowed"] = False
                    result["partial_import"] = False
                    result["sales_replace_blocked"] = True
                    result["replace_block_reason"] = (
                        f"该日期已有 {existing_rows} 条销量，纠正文件仍有 {parsed.error_rows} 条错误；"
                        "整日覆盖必须先修正所有错误，旧数据暂不删除。"
                    )
        return result
    except Exception as exc:
        _handle_error(exc)
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


@router.post("/commit")
def commit_import(
    data_type: DataType = Form(...),
    department_code: str = Form("B2C"),
    business_date: date | None = Form(None),
    file: UploadFile = File(...),
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    temp_path = _save_upload(file)
    try:
        # import_file 内部再次强制权限校验；普通用户无法绕过 preview 直接 commit。
        result = import_file(db, temp_path, data_type, business_date, department_code, actor["user_id"], original_filename=file.filename)
        result["original_filename"] = file.filename
        return result
    except Exception as exc:
        db.rollback()
        _handle_error(exc)
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass




@router.get("/latest-business-date")
def get_latest_business_date(
    department_code: str = "B2C",
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return latest_business_date(db, department_code, actor["user_id"])
    except Exception as exc:
        _handle_error(exc)


@router.get("/recent")
def list_recent_imports(
    department_code: str = "B2C",
    limit: int = 50,
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return {"items": recent_batches(db, department_code, actor["user_id"], min(max(limit, 1), 200))}
    except Exception as exc:
        _handle_error(exc)


@router.get("/{batch_no}")
def get_import_batch(
    batch_no: str,
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return import_batch_detail(db, batch_no, actor["user_id"])
    except Exception as exc:
        _handle_error(exc)


@router.get("/{batch_no}/issues")
def get_import_batch_issues(
    batch_no: str,
    severity: Literal["error", "warning"] | None = None,
    limit: int = 100,
    offset: int = 0,
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return import_batch_issues(
            db, batch_no, actor["user_id"], severity=severity, limit=limit, offset=offset
        )
    except Exception as exc:
        _handle_error(exc)


@router.post("/{batch_no}/rollback")
def rollback_import(
    batch_no: str,
    actor: dict = Depends(require_actor),
    db: Session = Depends(get_db),
):
    try:
        return rollback_batch(db, batch_no, actor["user_id"])
    except Exception as exc:
        db.rollback()
        _handle_error(exc)
