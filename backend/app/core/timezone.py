"""Application time helpers for the China Standard Time deployment."""

from datetime import date, datetime, timedelta, timezone


LOCAL_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_local() -> datetime:
    """Return local business time as a naive datetime for DATETIME columns."""

    return datetime.now(LOCAL_TZ).replace(tzinfo=None, microsecond=0)


def today_local() -> date:
    """Return today's date in the application timezone."""

    return datetime.now(LOCAL_TZ).date()
