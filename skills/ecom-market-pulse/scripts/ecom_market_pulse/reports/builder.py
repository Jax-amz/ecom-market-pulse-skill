"""不依赖外部模型接口的报告草稿聚合。

子 Agent 解读只提供已校验的文章结论；文章引用、栏目、日期、统计和报告窗口始终
由本模块确定，以便在关门验证前保持可解释与可重复。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from ..models import REPORT_SCHEMA_VERSION
from ..periods import BUSINESS_TIMEZONE, REPORT_CUTOFF_TIME, calendar_month_window
from .title_policy import validate_report_editorial_title
from .weekly_editorial import (
    WEEKLY_EDITORIAL_POLICY_VERSION,
    WEEKLY_FEATURED_MAX,
    build_weekly_editorial_brief,
    build_weekly_theme_suggestions,
)


WEEKLY_BUSINESS_DAYS = 5
CATEGORY_ORDER = (
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
CATEGORY_LABELS = {
    "amazon-policy": "Amazon 官方政策与卖家公告",
    "amazon-fba-fulfillment": "FBA、仓储、配送与退货",
    "fee-margin-tax": "平台费用、利润、税务与关税",
    "ads-traffic": "广告与流量",
    "listing-seo-voc": "Listing、SEO、评论与 VOC",
    "account-compliance-ip": "账号健康、合规与知识产权",
    "crossborder-logistics": "跨境物流、供应链与海关",
    "competitor-marketplaces": "竞品平台动态",
    "ai-ops-tools": "AI 工具与运营自动化",
    "seller-community-signal": "卖家社区与异常信号",
}


def select_representative_articles(articles: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """只保留每个事件的代表文章；官方来源优先，避免日报重复列举同一事件。"""

    candidates = [dict(article) for article in articles if _is_relevant(article)]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for article in candidates:
        key = str(
            _value(article, "clusterId", "cluster_id", "eventKey", "event_key", "articleId", "article_id", "id")
        )
        groups[key].append(article)
    selected: list[dict[str, Any]] = []
    for group in groups.values():
        selected.append(min(group, key=_representative_sort_key))
    return sorted(selected, key=_published_sort_key, reverse=True)


def weekly_archive_number(period_start: date) -> int:
    """按周一在所属月份中的位置计算用户可见周序。"""

    if period_start.isoweekday() != 1:
        raise ValueError("周报归档日期必须是周一")
    return (period_start.day - 1) // 7 + 1


def weekly_archive_label(period_start: date) -> str:
    """返回“第X周”；例如 2026-07-20 为 7 月第3周。"""

    return f"第{weekly_archive_number(period_start)}周"


def build_report_draft(
    *,
    report_type: str,
    business_date: date,
    run_id: str,
    articles: Iterable[Mapping[str, Any]],
    sources: Iterable[Any],
    stats: Mapping[str, int] | None = None,
    taxonomy_version: str = "1.0.0",
    prompt_version: str = "article-analysis-v1",
    gate_prompt_version: str = "report-gate-v1",
    report_prompt_version: str | None = None,
    schema_version: str = REPORT_SCHEMA_VERSION,
    narrative: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """构建未验证的报告草稿；仅支持 daily、weekly、monthly。"""

    if report_type not in {"daily", "weekly", "monthly"}:
        raise ValueError("report_type 仅支持 daily、weekly 或 monthly")
    if report_type == "weekly" and report_prompt_version is None:
        report_prompt_version = WEEKLY_EDITORIAL_POLICY_VERSION
    tz = ZoneInfo(BUSINESS_TIMEZONE)
    generated_at = (generated_at or datetime.now(tz)).astimezone(tz)
    start, end = _period_window(report_type, business_date, tz)
    article_candidates = [dict(article) for article in articles if _is_relevant(article)]
    weekly_candidate_count: int | None = None
    if report_type == "weekly":
        selected_article_ids = _weekly_selected_article_ids(narrative)
        editorial_brief = build_weekly_editorial_brief(
            article_candidates,
            selected_article_ids=selected_article_ids,
            limit=WEEKLY_FEATURED_MAX,
        )
        representative = list(editorial_brief.featured_articles)
        weekly_candidate_count = editorial_brief.candidate_count
    else:
        representative = select_representative_articles(article_candidates)
    sections = _build_sections(representative)
    source_directory = _build_source_directory(sources, representative)
    report_date = start.date() if report_type in {"weekly", "monthly"} else business_date
    report_id = f"{report_type}-{report_date.isoformat()}"
    effective_stats = _build_stats(
        report_type,
        stats,
        representative,
        candidate_count=weekly_candidate_count,
    )
    report: dict[str, Any] = {
        "schemaVersion": schema_version,
        "reportId": report_id,
        "reportType": report_type,
        "date": report_date.isoformat(),
        "timezone": BUSINESS_TIMEZONE,
        "generatedAt": generated_at.isoformat(),
        "windowStart": start.isoformat(),
        "windowEnd": end.isoformat(),
        "lead": _build_lead(
            report_type,
            len(representative),
            narrative,
            candidate_count=weekly_candidate_count,
        ),
        "stats": effective_stats,
        "sourceDirectory": source_directory,
        "sections": sections,
        "keyDates": _build_key_dates(sections),
        "gate": {
            "status": "pending",
            "issues": [],
            "validatedAt": None,
            "promptVersion": None,
        },
        "build": {
            "runId": run_id,
            "promptVersion": prompt_version,
            "gatePromptVersion": gate_prompt_version,
            "reportPromptVersion": report_prompt_version,
            "taxonomyVersion": taxonomy_version,
            "schemaVersion": schema_version,
            "dataCutoffAt": end.isoformat(),
        },
    }
    if report_type == "weekly":
        report.update(_weekly_extensions(start, end, representative, narrative))
    elif report_type == "monthly":
        report.update(_monthly_extensions(start, end, representative, narrative))
    _validate_report_references(report)
    # Pydantic 合同是 Schema 的唯一事实来源；以 JSON 模式返回可直接写入 DuckDB
    # 或导出的字典，避免 Enum/datetime 在不同边界层漂移。
    from ..models import validate_report

    return validate_report(report).model_dump(mode="json", by_alias=True)


def apply_gate_result(report: Mapping[str, Any], gate_result: Mapping[str, Any]) -> dict[str, Any]:
    """将不可变的关门结论合入草稿，返回新对象，不修改文章分析。"""

    status = gate_result.get("status")
    if status not in {"passed", "rejected"}:
        raise ValueError("关门验证结果 status 必须是 passed 或 rejected")
    result = deepcopy(dict(report))
    if gate_result.get("reportId") and gate_result["reportId"] != result.get("reportId"):
        raise ValueError("关门验证结果的 reportId 与报告草稿不一致")
    if status == "passed":
        validate_report_editorial_title(report)
    result["gate"] = {
        "status": status,
        "issues": list(gate_result.get("issues") or []),
        "validatedAt": gate_result.get("validatedAt"),
        "promptVersion": result["build"]["gatePromptVersion"],
    }
    if result.get("reportType") in {"weekly", "monthly"}:
        from ..models import validate_report

        return validate_report(result).model_dump(mode="json", by_alias=True)
    return result


def collect_evidence(articles: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """整理关门验证所需的文章 URL、结构化分析和证据，不传入无关全文。"""

    result: list[dict[str, Any]] = []
    for article in select_representative_articles(articles):
        analysis = _mapping_value(article, "analysis")
        result.append(
            {
                "articleId": _value(article, "articleId", "article_id", "id"),
                "clusterId": _value(article, "clusterId", "cluster_id", "eventKey", "event_key"),
                "sourceUrl": _value(article, "sourceUrl", "source_url", "canonicalUrl", "canonical_url"),
                "source": _value(article, "source", default={}),
                "originalTitle": _value(article, "originalTitle", "original_title", "title"),
                "publishedAt": _value(article, "publishedAt", "published_at"),
                "analysis": analysis or _analysis_fields(article),
                "evidence": _value(article, "evidence", default=[]),
                "conflicts": _value(article, "conflicts", default=[]),
            }
        )
    return result


def _build_sections(articles: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {category: [] for category in CATEGORY_ORDER}
    for article in articles:
        category = _value(article, "primaryCategory", "primary_category")
        if category not in buckets:
            continue
        buckets[category].append(_to_report_item(article))
    for items in buckets.values():
        items.sort(key=lambda item: _parse_datetime(item.get("publishedAt")) or datetime.min.replace(tzinfo=ZoneInfo("UTC")), reverse=True)
    return [
        {"category": category, "label": CATEGORY_LABELS[category], "items": buckets[category]}
        for category in CATEGORY_ORDER
    ]


def _build_source_directory(sources: Iterable[Any], representative: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """以启用的信源配置生成完整目录，并按最终纳入报告的文章计数。"""

    directories: list[dict[str, Any]] = []
    configured_ids: set[str] = set()
    for source in sources:
        if not _configured_value(source, "enabled"):
            continue
        source_id = _configured_value(source, "id")
        name = _configured_value(source, "name")
        source_class = _configured_value(source, "sourceClass", "source_class")
        homepage_url = _configured_value(source, "homepageUrl", "homepage_url")
        if not all(isinstance(value, str) and value.strip() for value in (source_id, name, source_class, homepage_url)):
            raise ValueError("已启用信源必须提供 id、name、sourceClass 和 homepageUrl")
        if source_id in configured_ids:
            raise ValueError(f"已启用信源 id 重复：{source_id}")
        configured_ids.add(source_id)
        directories.append(
            {
                "id": source_id,
                "name": name,
                "sourceClass": source_class,
                "homepageUrl": homepage_url,
                "articleCount": 0,
            }
        )

    article_counts = Counter()
    for article in representative:
        source_id = _source_id(article)
        if not source_id:
            raise ValueError("纳入报告的文章缺少 sourceId，无法生成完整信源目录")
        article_counts[source_id] += 1
    unconfigured_ids = sorted(set(article_counts) - configured_ids)
    if unconfigured_ids:
        raise ValueError(f"纳入报告的文章引用了未启用或未配置的信源：{', '.join(unconfigured_ids)}")
    for entry in directories:
        entry["articleCount"] = article_counts[entry["id"]]
    return directories


def _to_report_item(article: Mapping[str, Any]) -> dict[str, Any]:
    analysis = _mapping_value(article, "analysis")
    fields = _analysis_fields(article)
    if analysis:
        fields = {**fields, **analysis}
    return {
        "articleId": _value(article, "articleId", "article_id", "id"),
        "clusterId": _value(article, "clusterId", "cluster_id", "eventKey", "event_key"),
        "title": _value(article, "titleZh", "title_zh", "title"),
        "summary": _value(article, "summary"),
        "source": _normalise_source(_value(article, "source", default={}), article),
        "sourceUrl": _value(article, "sourceUrl", "source_url", "canonicalUrl", "canonical_url"),
        "publishedAt": _value(article, "publishedAt", "published_at"),
        "primaryCategory": _value(article, "primaryCategory", "primary_category"),
        "impactDimensions": _value(article, "impactDimensions", "impact_dimensions", default=[]),
        "whatHappened": _value(fields, "whatHappened", "what_happened"),
        "whyImportant": _value(fields, "whyImportant", "why_important"),
        "affectedMarketplaces": _value(article, "affectedMarketplaces", "affected_marketplaces", default=[]),
        "affectedSellerTypes": _value(article, "affectedSellerTypes", "affected_seller_types", default=[]),
        "effectiveAt": _value(fields, "effectiveAt", "effective_at"),
        "deadlineAt": _value(fields, "deadlineAt", "deadline_at"),
        "suggestions": _value(fields, "suggestions", default=[]),
    }


def _build_key_dates(sections: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    dates: list[dict[str, Any]] = []
    for section in sections:
        for item in section["items"]:
            for date_type, field in (("effective", "effectiveAt"), ("deadline", "deadlineAt")):
                value = item.get(field)
                parsed = _parse_datetime(value)
                if parsed:
                    dates.append(
                        {
                            "date": parsed.date().isoformat(),
                            "dateType": date_type,
                            "articleId": item["articleId"],
                            "event": item["title"],
                        }
                    )
    return sorted(dates, key=lambda item: (item["date"], item["dateType"], item["articleId"] or ""))


def _build_stats(
    report_type: str,
    stats: Mapping[str, int] | None,
    representative: list[dict[str, Any]],
    *,
    candidate_count: int | None = None,
) -> dict[str, int]:
    if report_type == "daily":
        defaults = {
            "discovered": 0,
            "fetched": 0,
            "uniqueEvents": len(representative),
            "analyzed": 0,
            "included": len(representative),
        }
    elif report_type == "weekly":
        defaults = {
            "uniqueEvents": candidate_count if candidate_count is not None else len(representative),
            "sources": len({_source_id(article) for article in representative if _source_id(article)}),
            "officialSources": len(
                {_source_id(article) for article in representative if _source_class(article) == "official"}
            ),
            "dailyReports": 0,
        }
    else:
        defaults = {
            "uniqueEvents": len(representative),
            "sources": len({_source_id(article) for article in representative if _source_id(article)}),
            "officialSources": len(
                {_source_id(article) for article in representative if _source_class(article) == "official"}
            ),
            "dailyReports": 0,
        }
    if stats:
        for key in defaults:
            if report_type == "weekly" and key == "uniqueEvents":
                continue
            if isinstance(stats.get(key), int):
                defaults[key] = stats[key]
    return defaults


def _build_lead(
    report_type: str,
    included: int,
    narrative: Mapping[str, Any] | None,
    *,
    candidate_count: int | None = None,
) -> dict[str, str]:
    if narrative and isinstance(narrative.get("lead"), Mapping):
        lead = narrative["lead"]
        return {"title": str(lead.get("title") or _report_title(report_type)), "summary": str(lead.get("summary") or "")[:200]}
    if report_type == "weekly" and candidate_count is not None:
        return {
            "title": _report_title(report_type),
            "summary": f"本周跨日去重后确认 {candidate_count} 个候选事件，精选 {included} 个重点事件展示。",
        }
    return {
        "title": _report_title(report_type),
        "summary": f"本期经去重并完成单篇分析后，纳入 {included} 个与跨境电商卖家经营相关的独立事件。",
    }


def _weekly_extensions(
    start: datetime, end: datetime, articles: list[dict[str, Any]], narrative: Mapping[str, Any] | None
) -> dict[str, Any]:
    iso_year, iso_week, _ = start.isocalendar()
    article_ids = [_article_id(article) for article in articles]
    if not article_ids:
        raise ValueError("没有已确认文章时不能生成周报")
    themes = list((narrative or {}).get("themes") or [])
    if not themes:
        themes = build_weekly_theme_suggestions(articles)
    important = [article for article in articles if _source_class(article) == "official"]
    recurring_signals = list((narrative or {}).get("recurringSignals") or [])
    if not recurring_signals:
        recurring_signals = _recurring_signal_items(articles)
    important_changes = list((narrative or {}).get("importantChanges") or [])
    if not important_changes:
        important_changes = _important_change_items(important)
    return {
        "period": {
            "isoWeek": f"{iso_year}-W{iso_week:02d}",
            "startDate": start.date().isoformat(),
            "endDate": end.date().isoformat(),
        },
        "themes": themes,
        "recurringSignals": recurring_signals,
        "importantChanges": important_changes,
        "nextWeekWatchlist": list((narrative or {}).get("nextWeekWatchlist") or []),
    }


def _monthly_extensions(
    start: datetime, end: datetime, articles: list[dict[str, Any]], narrative: Mapping[str, Any] | None
) -> dict[str, Any]:
    if not articles:
        raise ValueError("没有已确认文章时不能生成月报")
    all_ids = [_article_id(article) for article in articles]
    return {
        "period": {
            "month": start.strftime("%Y-%m"),
            "startDate": start.date().isoformat(),
            "endDate": end.date().isoformat(),
        },
        "monthLead": (narrative or {}).get("monthLead") or _build_lead("monthly", len(articles), None),
        "platformMatrix": (narrative or {}).get("platformMatrix") or _platform_matrix(articles),
        "costAndRisk": (narrative or {}).get("costAndRisk")
        or _narrative_section("费用、物流、税务和合规风险", _category_article_ids(articles, "fee-margin-tax", "account-compliance-ip", "crossborder-logistics")),
        "trafficAndConversion": (narrative or {}).get("trafficAndConversion")
        or _narrative_section("广告、搜索、Listing、评论和转化变化", _category_article_ids(articles, "ads-traffic", "listing-seo-voc")),
        "opportunities": (narrative or {}).get("opportunities")
        or _narrative_section("平台扩张、工具与自动化机会", _category_article_ids(articles, "competitor-marketplaces", "ai-ops-tools")),
        "trendEvidence": (narrative or {}).get("trendEvidence")
        or [{"trend": "本月已确认跨境电商卖家经营事件", "articleIds": all_ids, "eventCount": len(articles)}],
        "nextMonthCalendar": list((narrative or {}).get("nextMonthCalendar") or []),
    }


def _platform_matrix(articles: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    platform_names = ("Amazon", "Walmart", "Shopify", "TikTok Shop", "Temu", "eBay")
    result = []
    for name in platform_names:
        matches = [article for article in articles if name.lower() in json_string(article).lower()]
        result.append(
            {
                "platform": name,
                "summary": f"本期确认 {len(matches)} 个与 {name} 直接相关的事件。",
                "articleIds": [_article_id(article) for article in matches],
            }
        )
    return result


def _category_article_ids(articles: Iterable[Mapping[str, Any]], *categories: str) -> list[str]:
    return [_article_id(article) for article in articles if _value(article, "primaryCategory", "primary_category") in categories]


def _narrative_section(summary: str, article_ids: list[str]) -> dict[str, Any]:
    return {"summary": summary, "articleIds": article_ids}


def _fallback_themes(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    article_ids = [_article_id(article) for article in articles]
    groups = [
        ("本周确认事件概览", article_ids),
        ("经营影响与关键变化", article_ids),
        ("关键日期与后续观察", article_ids),
    ]
    return [
        {"title": title, "summary": f"本主题基于本周已确认的 {len(ids)} 个事件聚合。", "articleIds": ids}
        for title, ids in groups
    ]


def _recurring_signal_items(articles: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ids = _category_article_ids(articles, "seller-community-signal")
    return [{"summary": "本期卖家社区的可追溯异常信号。", "articleIds": ids}] if ids else []


def _important_change_items(articles: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ids = [_article_id(article) for article in articles]
    return [{"summary": "本期已确认的官方政策、费用或规则变化。", "articleIds": ids}] if ids else []


def _validate_report_references(report: Mapping[str, Any]) -> None:
    seen: set[str] = set()
    for section in report.get("sections", []):
        for item in section.get("items", []):
            article_id = item.get("articleId")
            if not article_id:
                raise ValueError("报告条目缺少 articleId")
            if article_id in seen:
                raise ValueError(f"报告中重复引用了文章 {article_id}")
            seen.add(article_id)
    if report.get("reportType") != "weekly":
        return

    reference_groups = [
        *(item.get("articleIds", []) for item in report.get("themes", [])),
        *(item.get("articleIds", []) for item in report.get("recurringSignals", [])),
        *(item.get("articleIds", []) for item in report.get("importantChanges", [])),
        *(item.get("articleIds", []) for item in report.get("nextWeekWatchlist", [])),
    ]
    unknown = sorted(
        {
            str(article_id)
            for article_ids in reference_groups
            for article_id in article_ids
            if article_id not in seen
        }
    )
    if unknown:
        raise ValueError(f"周报扩展字段引用了未入选文章：{', '.join(unknown)}")


def _weekly_selected_article_ids(narrative: Mapping[str, Any] | None) -> list[str] | None:
    if not narrative or "selectedArticleIds" not in narrative:
        return None
    value = narrative.get("selectedArticleIds")
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(article_id, str) and article_id for article_id in value):
        raise ValueError("weekly narrative.selectedArticleIds 必须是非空字符串数组")
    return list(value)


def _period_window(report_type: str, business_date: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    end_time = time.min
    if report_type == "daily":
        start_date = business_date
        end_date = business_date + timedelta(days=1)
    elif report_type == "weekly":
        start_date = business_date - timedelta(days=business_date.isoweekday() - 1)
        # 周五 16:00 执行截止补采后立即汇总，周末资讯归入下一业务周期。
        end_date = start_date + timedelta(days=WEEKLY_BUSINESS_DAYS - 1)
        end_time = REPORT_CUTOFF_TIME
    else:
        start_date, next_month = calendar_month_window(business_date)
        end_date = next_month - timedelta(days=1)
        end_time = REPORT_CUTOFF_TIME
    return datetime.combine(start_date, time.min, tzinfo=tz), datetime.combine(end_date, end_time, tzinfo=tz)


def _is_relevant(article: Mapping[str, Any]) -> bool:
    return _value(article, "relevant", default=True) is True and _value(article, "primaryCategory", "primary_category") in CATEGORY_LABELS


def _representative_sort_key(article: Mapping[str, Any]) -> tuple[int, int, float]:
    source = _value(article, "source", default={})
    source_class = _value(article, "sourceClass", "source_class", default=_value(source, "sourceClass", "source_class"))
    source_rank = {"official": 0, "professional-media": 1, "community": 2, "aggregator": 3}.get(source_class, 4)
    representative_rank = 0 if _value(article, "isRepresentative", "is_representative", default=True) else 1
    parsed = _parse_datetime(_value(article, "publishedAt", "published_at"))
    timestamp = -(parsed.timestamp() if parsed else 0)
    return representative_rank, source_rank, timestamp


def _published_sort_key(article: Mapping[str, Any]) -> datetime:
    return _parse_datetime(_value(article, "publishedAt", "published_at")) or datetime.min.replace(tzinfo=ZoneInfo("UTC"))


def _normalise_source(source: Any, article: Mapping[str, Any]) -> dict[str, Any]:
    mapping = source if isinstance(source, Mapping) else {}
    return {
        "name": _value(mapping, "name", default=_value(article, "sourceName", "source_name", default="未知来源")),
        "sourceClass": _value(mapping, "sourceClass", "source_class", default=_value(article, "sourceClass", "source_class")),
    }


def _analysis_fields(article: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "whatHappened": _value(article, "whatHappened", "what_happened"),
        "whyImportant": _value(article, "whyImportant", "why_important"),
        "effectiveAt": _value(article, "effectiveAt", "effective_at"),
        "deadlineAt": _value(article, "deadlineAt", "deadline_at"),
        "suggestions": _value(article, "suggestions", "suggestions_json", default=[]),
    }


def _mapping_value(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    candidate = value.get(name)
    return dict(candidate) if isinstance(candidate, Mapping) else {}


def _value(source: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in source and source[name] is not None:
            return source[name]
    return default


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=ZoneInfo("UTC"))
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("UTC"))


def _report_title(report_type: str) -> str:
    return {"daily": "跨境电商资讯日报", "weekly": "跨境电商资讯周报", "monthly": "跨境电商资讯月报"}[report_type]


def json_string(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _article_id(article: Mapping[str, Any]) -> str:
    value = _value(article, "articleId", "article_id", "id")
    if not value:
        raise ValueError("报告候选文章缺少 articleId")
    return str(value)


def _source_id(article: Mapping[str, Any]) -> str | None:
    source = _value(article, "source", default={})
    return _value(article, "sourceId", "source_id", default=_value(source, "id"))


def _configured_value(source: Any, *names: str, default: Any = None) -> Any:
    """同时支持 YAML 映射与 Pydantic SourceConfig，避免报告构建层绑定配置实现。"""

    if isinstance(source, Mapping):
        return _value(source, *names, default=default)
    for name in names:
        if hasattr(source, name):
            value = getattr(source, name)
            if value is not None:
                return value
    return default


def _source_class(article: Mapping[str, Any]) -> str | None:
    source = _value(article, "source", default={})
    return _value(article, "sourceClass", "source_class", default=_value(source, "sourceClass", "source_class"))
