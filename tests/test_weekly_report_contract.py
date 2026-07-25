from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from ecom_market_pulse.exporters.report_exporter import export_passed_report
from ecom_market_pulse.models import validate_report
from ecom_market_pulse.reports.builder import (
    build_report_draft,
    weekly_archive_label,
    weekly_archive_number,
)


def _weekly_draft(*, daily_reports: int = 5) -> dict[str, object]:
    article = {
        "articleId": "article-1",
        "clusterId": "event-1",
        "titleZh": "亚马逊更新卖家合规要求",
        "summary": "平台公布新的商品合规要求。",
        "sourceId": "source-a",
        "source": {"name": "示例信源", "sourceClass": "professional-media"},
        "sourceUrl": "https://example.com/article-1",
        "publishedAt": "2026-07-24T09:00:00+08:00",
        "primaryCategory": "amazon-policy",
        "impactDimensions": ["account"],
        "whatHappened": "平台公布新的商品合规要求。",
        "whyImportant": "卖家需要按新要求复核现有商品资料。",
        "affectedMarketplaces": ["US"],
        "affectedSellerTypes": ["跨境卖家"],
        "effectiveAt": None,
        "deadlineAt": None,
        "suggestions": ["逐项核对商品资料并保留平台通知与提交记录。"],
        "relevant": True,
    }
    source = {
        "id": "source-a",
        "name": "示例信源",
        "sourceClass": "professional-media",
        "homepageUrl": "https://example.com",
        "enabled": True,
    }
    return build_report_draft(
        report_type="weekly",
        business_date=date(2026, 7, 24),
        run_id="weekly-2026-W30",
        articles=[article],
        sources=[source],
        stats={"dailyReports": daily_reports},
    )


def test_weekly_period_is_monday_to_friday() -> None:
    report = _weekly_draft()

    assert report["date"] == "2026-07-20"
    assert report["windowStart"] == "2026-07-20T00:00:00+08:00"
    assert report["windowEnd"] == "2026-07-25T00:00:00+08:00"
    assert report["period"] == {
        "isoWeek": "2026-W30",
        "startDate": "2026-07-20",
        "endDate": "2026-07-24",
    }


def test_weekly_contract_rejects_natural_week_end() -> None:
    report = deepcopy(_weekly_draft())
    report["period"]["endDate"] = "2026-07-26"
    report["windowEnd"] = "2026-07-27T00:00:00+08:00"
    report["build"]["dataCutoffAt"] = "2026-07-27T00:00:00+08:00"

    with pytest.raises(ValidationError, match="period.endDate 必须是同一工作周的周五"):
        validate_report(report)


def test_passed_weekly_report_requires_five_daily_reports() -> None:
    report = _weekly_draft(daily_reports=4)
    report["gate"] = {
        "status": "passed",
        "issues": [],
        "validatedAt": "2026-07-25T08:30:00+08:00",
        "promptVersion": "weekly-report-gate-v1",
    }

    with pytest.raises(ValidationError, match="必须汇总 5 份工作日日报"):
        validate_report(report)


def test_export_rechecks_weekly_workday_contract(tmp_path) -> None:
    report = _weekly_draft(daily_reports=4)
    report["gate"] = {
        "status": "passed",
        "issues": [],
        "validatedAt": "2026-07-25T08:30:00+08:00",
        "promptVersion": "weekly-report-gate-v1",
    }

    with pytest.raises(ValidationError, match="必须汇总 5 份工作日日报"):
        export_passed_report(report, tmp_path)


def test_weekly_period_contains_exactly_five_business_dates() -> None:
    report = _weekly_draft()
    start = date.fromisoformat(report["period"]["startDate"])
    end = date.fromisoformat(report["period"]["endDate"])
    business_dates = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]

    assert len(business_dates) == 5
    assert [business_date.isoweekday() for business_date in business_dates] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize(
    ("period_start", "number", "label"),
    [
        (date(2026, 7, 6), 1, "第1周"),
        (date(2026, 7, 13), 2, "第2周"),
        (date(2026, 7, 20), 3, "第3周"),
        (date(2026, 7, 27), 4, "第4周"),
        (date(2026, 6, 29), 5, "第5周"),
    ],
)
def test_weekly_archive_label_uses_monday_position_in_month(
    period_start: date, number: int, label: str
) -> None:
    assert weekly_archive_number(period_start) == number
    assert weekly_archive_label(period_start) == label
