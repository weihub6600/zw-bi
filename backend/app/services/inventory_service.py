from typing import Optional


def predicted_daily_sales(sales_7d: float, sales_14d: float, sales_30d: float) -> float:
    avg7 = sales_7d / 7.0
    avg14 = sales_14d / 14.0
    avg30 = sales_30d / 30.0
    return avg7 * 0.50 + avg14 * 0.30 + avg30 * 0.20


def predicted_stockout_days(stock_qty: float, predicted_daily: float) -> Optional[float]:
    if stock_qty <= 0 or predicted_daily <= 0:
        return None
    return stock_qty / predicted_daily


def shortage_risk_level(days: Optional[float]) -> str:
    if days is None:
        return "不适用"
    if days <= 10:
        return "紧急"
    if days <= 30:
        return "高风险"
    if days <= 45:
        return "预警"
    return "正常"


def high_velocity_low_stock_candidate(stock_qty: float, sales_30d: float, stockout_days: Optional[float]) -> bool:
    # 已确认：0 库存不进入“高动销低库存 TOP30”。
    return stock_qty > 0 and sales_30d > 0 and stockout_days is not None and stockout_days <= 45
