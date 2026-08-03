from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from ecom_market_pulse.exporters.report_exporter import export_passed_report
from ecom_market_pulse.models import validate_report
from ecom_market_pulse.reports import (
    apply_gate_result,
    build_report_draft,
    monthly_business_dates,
)


def _monthly_draft(*, daily_reports: int = 23) -> dict[str, object]:
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
        report_type="monthly",
        business_date=date(2026, 7, 31),
        run_id="monthly-2026-07",
        articles=[article],
        sources=[source],
        stats={"dailyReports": daily_reports},
        generated_at=datetime.fromisoformat("2026-07-31T16:30:00+08:00"),
    )


def _pass_monthly_report(report: dict[str, object], *, validated_at: str = "2026-07-31T17:00:00+08:00") -> None:
    report["gate"] = {
        "status": "passed",
        "issues": [],
        "validatedAt": validated_at,
        "promptVersion": "monthly-report-gate-v1",
    }


def test_monthly_period_uses_last_day_business_cutoff() -> None:
    report = _monthly_draft()

    assert report["reportId"] == "monthly-2026-07-01"
    assert report["date"] == "2026-07-01"
    assert report["windowStart"] == "2026-07-01T00:00:00+08:00"
    assert report["windowEnd"] == "2026-07-31T16:00:00+08:00"
    assert report["period"] == {
        "month": "2026-07",
        "startDate": "2026-07-01",
        "endDate": "2026-07-31",
    }


def test_monthly_contract_rejects_legacy_report_schema() -> None:
    report = _monthly_draft()
    report["schemaVersion"] = "1.1.0"
    report["build"]["schemaVersion"] = "1.1.0"

    with pytest.raises(ValidationError):
        validate_report(report)


@pytest.mark.parametrize(
    ("business_date", "period_start", "period_end", "window_end"),
    [
        (date(2028, 2, 29), "2028-02-01", "2028-02-29", "2028-02-29T16:00:00+08:00"),
        (date(2026, 12, 31), "2026-12-01", "2026-12-31", "2026-12-31T16:00:00+08:00"),
    ],
)
def test_monthly_period_handles_leap_year_and_year_boundary(
    business_date: date, period_start: str, period_end: str, window_end: str
) -> None:
    report = _monthly_draft()
    article = next(item for section in report["sections"] for item in section["items"])
    source = report["sourceDirectory"][0]
    rebuilt = build_report_draft(
        report_type="monthly",
        business_date=business_date,
        run_id=f"monthly-{business_date:%Y-%m}",
        articles=[
            {
                **article,
                "sourceId": source["id"],
                "source": {
                    "name": source["name"],
                    "sourceClass": source["sourceClass"],
                },
                "relevant": True,
            }
        ],
        sources=[
            {
                **source,
                "enabled": True,
            }
        ],
    )

    assert rebuilt["period"]["startDate"] == period_start
    assert rebuilt["period"]["endDate"] == period_end
    assert rebuilt["windowEnd"] == window_end


def test_monthly_business_dates_cover_weekdays_only() -> None:
    business_dates = monthly_business_dates(date(2026, 7, 31))

    assert len(business_dates) == 23
    assert business_dates[0] == date(2026, 7, 1)
    assert business_dates[-1] == date(2026, 7, 31)
    assert all(value.isoweekday() <= 5 for value in business_dates)


def test_monthly_contract_rejects_partial_calendar_month() -> None:
    report = deepcopy(_monthly_draft())
    report["period"]["endDate"] = "2026-07-30"
    report["windowEnd"] = "2026-07-31T00:00:00+08:00"

    with pytest.raises(ValidationError, match="period.endDate 必须是同一自然月最后一天"):
        validate_report(report)


def test_passed_monthly_report_requires_all_business_day_reports() -> None:
    report = _monthly_draft(daily_reports=22)
    _pass_monthly_report(report)

    with pytest.raises(ValidationError, match="必须汇总 23 份工作日日报"):
        validate_report(report)


def test_monthly_report_cannot_pass_before_month_end_cutoff() -> None:
    report = _monthly_draft()
    _pass_monthly_report(report, validated_at="2026-07-31T15:59:59+08:00")

    with pytest.raises(ValidationError, match="月末 16:00"):
        validate_report(report)


def test_monthly_report_rejects_naive_gate_timestamp() -> None:
    report = _monthly_draft()
    _pass_monthly_report(report, validated_at="2026-07-31T17:00:00")

    with pytest.raises(ValidationError, match="月末 16:00"):
        validate_report(report)


def test_apply_gate_result_rechecks_monthly_contract() -> None:
    report = _monthly_draft()

    gated = apply_gate_result(
        report,
        {
            "reportId": report["reportId"],
            "status": "passed",
            "issues": [],
            "validatedAt": "2026-07-31T17:00:00+08:00",
        },
    )

    assert gated["gate"]["status"] == "passed"


def test_export_rechecks_monthly_contract_and_uses_month_key(tmp_path) -> None:
    report = _monthly_draft()
    _pass_monthly_report(report)

    exported = export_passed_report(report, tmp_path)

    assert exported["json"] == (tmp_path / "exports/monthly/2026-07.json").resolve()
    assert exported["latest_json"] == (tmp_path / "exports/monthly/latest.json").resolve()


def test_monthly_extension_references_must_point_to_selected_articles() -> None:
    report = _monthly_draft()
    report["trendEvidence"][0]["articleIds"] = ["missing-article"]

    with pytest.raises(ValidationError, match="引用了未入选文章"):
        validate_report(report)


def test_monthly_next_month_calendar_accepts_selected_article_reference() -> None:
    report = _monthly_draft()
    report["nextMonthCalendar"] = [
        {
            "date": "2026-08-12",
            "dateType": "effective",
            "articleId": "article-1",
            "event": "欧盟包装法规进入实施节点",
        }
    ]

    validated = validate_report(report)

    assert validated.next_month_calendar[0].article_id == "article-1"


def test_monthly_next_month_calendar_rejects_unselected_article_reference() -> None:
    report = _monthly_draft()
    report["nextMonthCalendar"] = [
        {
            "date": "2026-08-12",
            "dateType": "effective",
            "articleId": "missing-article",
            "event": "欧盟包装法规进入实施节点",
        }
    ]

    with pytest.raises(ValidationError, match="引用了未入选文章"):
        validate_report(report)
