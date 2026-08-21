from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class ExpiryThreshold:
    near_days: int = 30
    near_pct: float = 10.0
    warn_days: int = 90
    warn_pct: float = 25.0


def total_shelf_days(production_date: date, expire_date: date) -> int:
    return max(0, (expire_date - production_date).days)


def remaining_days(snapshot_date: date, expire_date: date) -> int:
    # 过期日当天不算有效期，因此 -1。
    return (expire_date - snapshot_date).days - 1


def remaining_percent(production_date: date, expire_date: date, snapshot_date: date) -> float:
    total = total_shelf_days(production_date, expire_date)
    if total <= 0:
        return 0.0
    remaining = remaining_days(snapshot_date, expire_date)
    return max(0.0, min(100.0, remaining / total * 100.0))


def is_long_term_expiry(expire_date: date) -> bool:
    # 项目约定：明显异常的超长期日期不进入效期预警。
    return expire_date.year >= 2100


def expiry_status(
    production_date: date,
    expire_date: date,
    snapshot_date: date,
    threshold: ExpiryThreshold,
) -> str:
    if is_long_term_expiry(expire_date):
        return "正常"

    days = remaining_days(snapshot_date, expire_date)
    pct = remaining_percent(production_date, expire_date, snapshot_date)

    if days <= 0:
        return "过期"
    if days <= threshold.near_days or pct <= threshold.near_pct:
        return "临期"
    if days <= threshold.warn_days or pct <= threshold.warn_pct:
        return "预警"
    return "正常"
