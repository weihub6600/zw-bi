from datetime import date
from fastapi import APIRouter
from pydantic import BaseModel
from ..services.expiry_service import ExpiryThreshold, remaining_days, remaining_percent, expiry_status
from ..services.inventory_service import predicted_daily_sales, predicted_stockout_days, shortage_risk_level

router = APIRouter(prefix='/rules', tags=['rules'])

class ExpiryRequest(BaseModel):
    production_date: date
    expire_date: date
    snapshot_date: date
    near_days: int = 30
    near_pct: float = 10
    warn_days: int = 90
    warn_pct: float = 25

@router.post('/expiry')
def calculate_expiry(req: ExpiryRequest):
    th = ExpiryThreshold(req.near_days, req.near_pct, req.warn_days, req.warn_pct)
    return {
        "remaining_days": remaining_days(req.snapshot_date, req.expire_date),
        "remaining_percent": round(remaining_percent(req.production_date, req.expire_date, req.snapshot_date), 2),
        "status": expiry_status(req.production_date, req.expire_date, req.snapshot_date, th),
    }

class StockoutRequest(BaseModel):
    stock_qty: float
    sales_7d: float
    sales_14d: float
    sales_30d: float

@router.post('/stockout')
def calculate_stockout(req: StockoutRequest):
    daily = predicted_daily_sales(req.sales_7d, req.sales_14d, req.sales_30d)
    days = predicted_stockout_days(req.stock_qty, daily)
    return {"predicted_daily_sales": daily, "stockout_days": days, "risk": shortage_risk_level(days)}
