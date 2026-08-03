from __future__ import annotations

from datetime import date, datetime

import pytest

from ecom_market_pulse.reports.builder import build_report_draft
from ecom_market_pulse.reports.weekly_editorial import (
    build_weekly_event_groups,
    select_weekly_featured_articles,
)


_CATEGORIES = (
    "amazon-policy",
    "amazon-fba-fulfillment",
    "fee-margin-tax",
    "ads-traffic",
    "listing-seo-voc",
    "account-compliance-ip",
    "crossborder-logistics",
    "competitor-marketplaces",
    "ai-ops-tools",
    "seller-community-signal",
)


def _article(
    index: int,
    *,
    title: str | None = None,
    summary: str | None = None,
    published_at: str | None = None,
    category: str | None = None,
) -> dict[str, object]:
    return {
        "articleId": f"article-{index}",
        "clusterId": f"event-{index}",
        "titleZh": title or f"平台公布第{index}项独立经营变化",
        "summary": summary or f"这是第{index}项具有独立事实依据的经营变化。",
        "sourceId": "source-a",
        "source": {"name": "示例信源", "sourceClass": "professional-media"},
        "sourceUrl": f"https://example.com/article-{index}",
        "publishedAt": published_at or f"2026-07-{20 + index % 5:02d}T09:00:00+08:00",
        "primaryCategory": category or _CATEGORIES[index % len(_CATEGORIES)],
        "impactDimensions": ["money", "efficiency"],
        "whatHappened": summary or f"平台确认第{index}项独立经营变化。",
        "whyImportant": "该变化可能影响卖家的经营安排。",
        "affectedMarketplaces": ["示例市场"],
        "affectedSellerTypes": ["跨境卖家"],
        "effectiveAt": None,
        "deadlineAt": None,
        "suggestions": ["核对实际适用范围并保留执行记录。"],
        "relevant": True,
    }


def _source() -> dict[str, object]:
    return {
        "id": "source-a",
        "name": "示例信源",
        "sourceClass": "professional-media",
        "homepageUrl": "https://example.com",
        "enabled": True,
    }


def test_cross_day_same_event_is_grouped_without_merging_other_market() -> None:
    us_first = _article(
        1,
        title="TikTok Shop美国美妆报告称短视频贡献68%销售",
        summary="美国站美妆销售额32亿美元，短视频贡献68%，直播贡献20%。",
        published_at="2026-07-27T09:00:00+08:00",
        category="competitor-marketplaces",
    )
    us_second = _article(
        2,
        title="美国TikTok美妆市场内容与套装增长",
        summary="TikTok Shop美国站美妆销售额32亿美元，68%成交来自短视频。",
        published_at="2026-07-28T09:00:00+08:00",
        category="competitor-marketplaces",
    )
    uk_follow_up = _article(
        3,
        title="TikTok Shop英国美妆零售增长60%",
        summary="英国美妆销售同比增长60%，并成为当地重要零售渠道。",
        published_at="2026-07-31T09:00:00+08:00",
        category="competitor-marketplaces",
    )

    groups = build_weekly_event_groups([us_first, us_second, uk_follow_up])

    assert len(groups) == 2
    grouped_ids = [set(group.article_ids) for group in groups]
    assert {"article-1", "article-2"} in grouped_ids
    assert {"article-3"} in grouped_ids


def test_same_tariff_policy_and_carrier_notice_form_one_event() -> None:
    policy = _article(
        1,
        title="美国对中国商品新增12.5%关税",
        summary="原全球10%临时关税到期后，中国商品自7月24日起适用12.5%附加关税。",
        published_at="2026-07-27T09:00:00+08:00",
        category="fee-margin-tax",
    )
    carrier_notice = _article(
        2,
        title="SpeedPAK提示美国进口关税口径调整",
        summary="美国全球10%临时关税到期，中国大陆商品改征12.5%，保证金流程不变。",
        published_at="2026-07-29T09:00:00+08:00",
        category="fee-margin-tax",
    )

    groups = build_weekly_event_groups([policy, carrier_notice])

    assert len(groups) == 1
    assert set(groups[0].article_ids) == {"article-1", "article-2"}


@pytest.mark.parametrize(
    ("first_title", "first_summary", "second_title", "second_summary"),
    [
        (
            "韩国重罚TikTok站外追踪数据合规问题",
            "韩国PIPC处罚TikTok，问题涉及Pixel、Events SDK和个人信息同意机制。",
            "韩国PIPC处罚TikTok数据处理",
            "TikTok因Pixel与Events SDK站外追踪被处罚并要求整改。",
        ),
        (
            "多名Temu商家反馈华南仓合并与欧洲本地仓扩张",
            "Temu整合广东前置仓，并扩大欧洲本地仓和自营仓布局。",
            "Temu调整仓网推进欧洲本土履约",
            "Temu关闭广东部分仓库，同时扩大德国和波兰自营仓布局。",
        ),
        (
            "Meesho披露印度市场增长与AI运营进展",
            "Meesho披露截至6月30日的财务与运营数据，并介绍AI推荐和目录工具。",
            "Meesho称AI深入商家运营",
            "Meesho公布截至6月30日的季度业绩，AI用于目录、需求预测和商家增长。",
        ),
        (
            "FedEx旺季附加费拟上调",
            "FedEx公布旺季附加费方案，多个包裹服务价格上调。",
            "FedEx公布2026旺季附加费方案",
            "FedEx旺季附加费分阶段生效，住宅配送和超规格包裹费用提高。",
        ),
    ],
)
def test_known_cross_day_duplicate_patterns_are_grouped(
    first_title: str,
    first_summary: str,
    second_title: str,
    second_summary: str,
) -> None:
    first = _article(
        1,
        title=first_title,
        summary=first_summary,
        published_at="2026-07-27T09:00:00+08:00",
        category="competitor-marketplaces",
    )
    second = _article(
        2,
        title=second_title,
        summary=second_summary,
        published_at="2026-07-31T09:00:00+08:00",
        category="competitor-marketplaces",
    )

    groups = build_weekly_event_groups([first, second])

    assert len(groups) == 1


def test_auto_selection_caps_at_twenty_and_preserves_non_empty_categories() -> None:
    candidates = [_article(index) for index in range(30)]

    selected = select_weekly_featured_articles(candidates)

    assert len(selected) == 20
    assert {article["primaryCategory"] for article in selected} == set(_CATEGORIES)


def test_manual_selection_must_respect_minimum_and_candidate_scope() -> None:
    candidates = [_article(index) for index in range(25)]

    with pytest.raises(ValueError, match="不得少于 12"):
        select_weekly_featured_articles(
            candidates,
            selected_article_ids=[f"article-{index}" for index in range(11)],
        )
    with pytest.raises(ValueError, match="非候选文章"):
        select_weekly_featured_articles(
            candidates,
            selected_article_ids=[*(f"article-{index}" for index in range(19)), "missing"],
        )


def test_weekly_report_keeps_candidate_count_but_only_displays_twenty() -> None:
    articles = [_article(index) for index in range(25)]

    report = build_report_draft(
        report_type="weekly",
        business_date=date(2026, 7, 24),
        run_id="weekly-2026-W30",
        articles=articles,
        sources=[_source()],
        stats={"dailyReports": 5, "uniqueEvents": 999},
        generated_at=datetime.fromisoformat("2026-07-24T16:10:00+08:00"),
    )

    selected_ids = {
        item["articleId"]
        for section in report["sections"]
        for item in section["items"]
    }
    assert report["stats"]["uniqueEvents"] == 25
    assert len(selected_ids) == 20
    assert sum(source["articleCount"] for source in report["sourceDirectory"]) == 20
    assert report["build"]["reportPromptVersion"] == "weekly-editorial-v1"
    assert {
        article_id
        for theme in report["themes"]
        for article_id in theme["articleIds"]
    } <= selected_ids


def test_candidate_set_below_limit_is_fully_displayed() -> None:
    articles = [_article(index) for index in range(8)]

    report = build_report_draft(
        report_type="weekly",
        business_date=date(2026, 7, 24),
        run_id="weekly-2026-W30",
        articles=articles,
        sources=[_source()],
        stats={"dailyReports": 5},
        generated_at=datetime.fromisoformat("2026-07-24T16:10:00+08:00"),
    )

    selected_ids = {
        item["articleId"]
        for section in report["sections"]
        for item in section["items"]
    }
    assert report["stats"]["uniqueEvents"] == 8
    assert len(selected_ids) == 8


def test_weekly_narrative_cannot_reference_unselected_article() -> None:
    articles = [_article(index) for index in range(25)]
    selected_ids = [f"article-{index}" for index in range(20)]
    narrative = {
        "selectedArticleIds": selected_ids,
        "themes": [
            {
                "title": "主题一",
                "summary": "引用未进入重点展示集的文章。",
                "articleIds": ["article-24"],
            },
            {
                "title": "主题二",
                "summary": "第二个主题。",
                "articleIds": ["article-1"],
            },
            {
                "title": "主题三",
                "summary": "第三个主题。",
                "articleIds": ["article-2"],
            },
        ],
    }

    with pytest.raises(ValueError, match="引用了未入选文章"):
        build_report_draft(
            report_type="weekly",
            business_date=date(2026, 7, 24),
            run_id="weekly-2026-W30",
            articles=articles,
            sources=[_source()],
            stats={"dailyReports": 5},
            narrative=narrative,
            generated_at=datetime.fromisoformat("2026-07-24T16:10:00+08:00"),
        )


def test_weekly_narrative_extensions_are_preserved() -> None:
    articles = [_article(index) for index in range(12)]
    narrative = {
        "recurringSignals": [
            {"summary": "跨工作日重复出现的履约信号。", "articleIds": ["article-1", "article-2"]}
        ],
        "importantChanges": [
            {"summary": "本周需要执行的重要变化。", "articleIds": ["article-3"]}
        ],
        "nextWeekWatchlist": [
            {"item": "核对下周生效范围。", "date": "2026-07-27", "articleIds": ["article-4"]}
        ],
    }

    report = build_report_draft(
        report_type="weekly",
        business_date=date(2026, 7, 24),
        run_id="weekly-2026-W30",
        articles=articles,
        sources=[_source()],
        stats={"dailyReports": 5},
        narrative=narrative,
        generated_at=datetime.fromisoformat("2026-07-24T16:10:00+08:00"),
    )

    assert report["recurringSignals"] == narrative["recurringSignals"]
    assert report["importantChanges"] == narrative["importantChanges"]
    assert report["nextWeekWatchlist"] == narrative["nextWeekWatchlist"]
