"""日报、周报和月报共享的确定性周期计算。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE = "Asia/Shanghai"
REPORT_CUTOFF_TIME = time(hour=16)


def calendar_month_window(value: date) -> tuple[date, date]:
    """返回目标自然月的月初和下月月初，右边界不包含。"""

    start_date = value.replace(day=1)
    next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start_date, next_month


def monthly_business_dates(value: date) -> tuple[date, ...]:
    """返回目标自然月内全部周一至周五日期，不处理法定调休。"""

    start_date, next_month = calendar_month_window(value)
    return tuple(
        start_date + timedelta(days=offset)
        for offset in range((next_month - start_date).days)
        if (start_date + timedelta(days=offset)).isoweekday() <= 5
    )


def report_cutoff_at(value: date) -> datetime:
    """返回报告业务日期当天 16:00 的上海时区截止点。"""

    return datetime.combine(value, REPORT_CUTOFF_TIME, tzinfo=ZoneInfo(BUSINESS_TIMEZONE))


__all__ = [
    "BUSINESS_TIMEZONE",
    "REPORT_CUTOFF_TIME",
    "calendar_month_window",
    "monthly_business_dates",
    "report_cutoff_at",
]
