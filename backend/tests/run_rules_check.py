from datetime import date
from app.services.expiry_service import ExpiryThreshold, remaining_days, remaining_percent, expiry_status
from app.services.inventory_service import predicted_daily_sales, predicted_stockout_days, high_velocity_low_stock_candidate
from app.services.task_service import task_start_date, can_self_approve_delete

assert remaining_days(date(2026,8,20), date(2026,8,29)) == 8
pct = remaining_percent(date(2026,1,1), date(2027,1,1), date(2026,8,20))
assert 36 < pct < 37
assert expiry_status(date(2025,1,1), date(2026,8,20), date(2026,8,20), ExpiryThreshold()) == '过期'
daily = predicted_daily_sales(700,1400,3000)
assert predicted_stockout_days(0,daily) is None
assert not high_velocity_low_stock_candidate(0,3000,None)
assert task_start_date(date(2026,8,20)) == date(2026,8,21)
assert not can_self_approve_delete('U1','U1')
print('business rules check: OK')
