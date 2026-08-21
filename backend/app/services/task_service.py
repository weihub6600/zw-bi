from datetime import date, timedelta


def task_start_date(assign_date: date) -> date:
    return assign_date + timedelta(days=1)


def can_self_approve_delete(requester_user_id: str, approver_user_id: str) -> bool:
    # 自己的删除申请不能自己审批。
    return requester_user_id != approver_user_id


def completion_percent(actual_qty: float, target_qty: float) -> float:
    if target_qty <= 0:
        return 0.0
    return actual_qty / target_qty * 100.0
