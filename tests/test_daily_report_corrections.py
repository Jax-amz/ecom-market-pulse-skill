from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from ecom_market_pulse.reports.builder import build_report_draft


def _article(article_id: str, cluster_id: str, *, relevant: bool = True) -> dict:
    return {
        "articleId": article_id,
        "clusterId": cluster_id,
        "titleZh": "亚马逊更新商品合规资料要求",
        "summary": "平台公布新的商品合规要求。",
        "sourceId": "source-a",
        "source": {"name": "示例信源", "sourceClass": "professional-media"},
        "sourceUrl": f"https://example.com/{article_id}",
        "publishedAt": "2026-10-12T09:00:00+08:00",
        "primaryCategory": "account-compliance-ip",
        "impactDimensions": ["account"],
        "whatHappened": "平台公布新的商品合规要求。",
        "whyImportant": "卖家需要按新要求复核现有商品资料。",
        "suggestions": ["逐项核对商品资料并保留平台通知与提交记录。"],
        "relevant": relevant,
    }


def _draft(articles: list[dict], *, summary: str = "本期经事件去重后纳入合格资讯。") -> dict:
    return build_report_draft(
        report_type="daily",
        business_date=date(2026, 10, 12),
        run_id="daily-correction-test",
        articles=articles,
        sources=[{
            "id": "source-a",
            "name": "示例信源",
            "sourceClass": "professional-media",
            "homepageUrl": "https://example.com",
            "enabled": True,
        }],
        stats={"discovered": 75, "fetched": 75, "uniqueEvents": 66, "analyzed": 66, "included": 66},
        narrative={"lead": {"title": "亚马逊更新商品合规资料，卖家需补充认证", "summary": summary}},
        generated_at=datetime.fromisoformat("2026-10-12T10:00:00+08:00"),
    )


def test_daily_counts_qualified_events_instead_of_raw_versions() -> None:
    report = _draft([
        _article("first", "same-event"),
        _article("second-version", "same-event"),
        _article("excluded", "unrelated-event", relevant=False),
    ])

    assert report["stats"] == {
        "discovered": 75, "fetched": 75, "uniqueEvents": 1, "analyzed": 66, "included": 1,
    }
    assert sum(len(section["items"]) for section in report["sections"]) == 1


def test_daily_excluded_articles_do_not_become_public_events() -> None:
    report = _draft([_article("excluded", "unrelated-event", relevant=False)])

    assert report["stats"]["uniqueEvents"] == report["stats"]["included"] == 0


def test_overlong_summary_is_rejected_instead_of_silently_truncated() -> None:
    summary = "甲" * 200 + "。"
    with pytest.raises(ValidationError) as error:
        _draft([_article("first", "event")], summary=summary)

    assert any(issue["loc"][-2:] == ("lead", "summary") for issue in error.value.errors())


def test_summary_at_limit_keeps_its_final_sentence() -> None:
    summary = "甲" * 199 + "。"
    report = _draft([_article("first", "event")], summary=summary)

    assert report["lead"]["summary"] == summary
