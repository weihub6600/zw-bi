from fastapi import APIRouter
from ..version import APP_VERSION

router = APIRouter()


@router.get('/health')
def health():
    return {
        "ok": True,
        "app": "百嘉瑞BI",
        "version": APP_VERSION,
        "external_wdt_api": False,
    }
