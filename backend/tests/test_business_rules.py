from datetime import date
from app.services.expiry_service import ExpiryThreshold, remaining_days, remaining_percent, expiry_status
from app.services.inventory_service import predicted_daily_sales, predicted_stockout_days, high_velocity_low_stock_candidate
from app.services.task_service import task_start_date, can_self_approve_delete


def test_expiry_days_excludes_expire_day():
    assert remaining_days(date(2026, 8, 20), date(2026, 8, 29)) == 8


def test_remaining_pct():
    pct = remaining_percent(date(2026, 1, 1), date(2027, 1, 1), date(2026, 8, 20))
    assert 36 < pct < 37


def test_expired_precedence():
    th = ExpiryThreshold()
    assert expiry_status(date(2025, 1, 1), date(2026, 8, 20), date(2026, 8, 20), th) == "过期"


def test_high_velocity_zero_stock_excluded():
    daily = predicted_daily_sales(700, 1400, 3000)
    assert predicted_stockout_days(0, daily) is None
    assert not high_velocity_low_stock_candidate(0, 3000, None)


def test_task_starts_next_day():
    assert task_start_date(date(2026, 8, 20)) == date(2026, 8, 21)


def test_self_approval_forbidden():
    assert can_self_approve_delete("U1", "U1") is False
    assert can_self_approve_delete("U1", "U2") is True
