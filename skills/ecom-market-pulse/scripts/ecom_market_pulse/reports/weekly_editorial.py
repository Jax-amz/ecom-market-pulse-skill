"""周报跨日事件归并与重点展示选择。

日报负责保存当天的完整事实；周报需要先跨日识别同一事件，再从候选事件中选择
有限的代表事件。这里提供确定性、可测试的保守实现，Agent 仍可通过
``selectedArticleIds`` 覆盖推荐结果，但不能绕过数量、候选范围和分类覆盖校验。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo


WEEKLY_FEATURED_MIN = 12
WEEKLY_FEATURED_MAX = 20
WEEKLY_EDITORIAL_POLICY_VERSION = "weekly-editorial-v1"

_SOURCE_RANK = {
    "official": 0,
    "professional-media": 1,
    "community": 2,
    "aggregator": 3,
}

_ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "amazon": ("amazon", "亚马逊", "fba", "alexa", "rufus"),
    "tiktok": ("tiktok", "抖音海外"),
    "temu": ("temu",),
    "shopee": ("shopee",),
    "shopify": ("shopify",),
    "ebay": ("ebay",),
    "etsy": ("etsy",),
    "shein": ("shein",),
    "walmart": ("walmart", "walmex", "沃尔玛"),
    "wildberries": ("wildberries", "wb partners"),
    "ozon": ("ozon",),
    "meesho": ("meesho",),
    "lazada": ("lazada",),
    "aliexpress": ("aliexpress", "速卖通"),
    "fedex": ("fedex",),
    "dhl": ("dhl",),
    "usps": ("usps",),
    "speedpak": ("speedpak",),
    "maersk": ("maersk", "马士基"),
    "cainiao": ("cainiao", "菜鸟"),
    "coupang": ("coupang",),
}

_MARKET_ALIASES: dict[str, tuple[str, ...]] = {
    "us": ("美国", "美区", "美国站", "united states", " u.s.", " us "),
    "uk": ("英国", "英国站", " united kingdom", " uk "),
    "korea": ("韩国", " korea"),
    "japan": ("日本", "日本站", " japan"),
    "australia": ("澳大利亚", "澳洲", " australia"),
    "germany": ("德国", "德国站", " germany"),
    "austria": ("奥地利", "奥地利站", " austria"),
    "france": ("法国", "法国站", " france"),
    "russia": ("俄罗斯", "俄罗", " russia"),
    "mexico": ("墨西哥", "墨西哥站", " mexico"),
    "brazil": ("巴西", "巴西站", " brazil"),
    "indonesia": ("印尼", "印度尼西亚", " indonesia"),
    "malaysia": ("马来西亚", " malaysia"),
    "thailand": ("泰国", " thailand"),
    "vietnam": ("越南", " vietnam"),
    "philippines": ("菲律宾", " philippines"),
    "poland": ("波兰", " poland"),
    "turkey": ("土耳其", " turkey"),
    "india": ("印度", " india"),
    "europe": ("欧洲", "欧盟", " europe", " eu "),
}

_TOPIC_MARKERS: dict[str, tuple[str, ...]] = {
    "tariff-customs": ("关税", "海关", "进口商", "原产地", "bond", "报关", "301"),
    "logistics-cost": ("运费", "附加费", "费率", "燃油", "运价", "报价", "物流成本"),
    "fulfillment-network": ("履约", "仓网", "海外仓", "自营仓", "配送中心", "末端网络", "供应链服务"),
    "warehouse-disruption": ("仓库事故", "仓储受袭", "恢复运营", "暂停作业", "赔付", "无人机"),
    "settlement-fee": ("结算", "回款", "佣金", "保证金", "收费", "保险费率", "发票"),
    "advertising": ("广告", "campaigns", "gmv max", "promoted listings", "投放", "获客成本"),
    "paid-membership": ("付费会员", "shop plus", "会员服务", "会员专属"),
    "data-privacy": ("数据合规", "个人信息", "pipc", "pixel", "events sdk", "站外追踪"),
    "market-results": ("财报", "销售额", "gmv", "营收", "市场规模", "同比增长", "份额"),
    "content-commerce": ("内容电商", "短视频", "直播", "美妆", "周榜", "达人"),
    "listing": ("listing", "商品页", "产品库", "尺码字段", "商品合并", "搜索"),
    "account-ip": ("账号", "侵权", "商标", "律师函", "钓鱼", "认证", "资质"),
    "regulation": ("监管", "处罚", "罚款", "反垄断", "合规", "申报", "高风险设备"),
    "ai-tools": (" ai ", "人工智能", "agent", "alexa", "rufus", "自动化"),
    "seasonal-opportunity": ("返校季", "万圣节", "旺季", "选品", "备货"),
}

_CATEGORY_PRIORITY = {
    "amazon-policy": 24,
    "amazon-fba-fulfillment": 18,
    "fee-margin-tax": 26,
    "ads-traffic": 14,
    "listing-seo-voc": 12,
    "account-compliance-ip": 26,
    "crossborder-logistics": 22,
    "competitor-marketplaces": 10,
    "ai-ops-tools": 10,
    "seller-community-signal": 4,
}

_ACTION_TERMS = (
    "生效",
    "截止",
    "必须",
    "要求",
    "上调",
    "下调",
    "处罚",
    "罚款",
    "暂停",
    "恢复",
    "关停",
    "整改",
    "风险",
)

_EVENT_ACTION_MARKERS: dict[str, tuple[str, ...]] = {
    "penalty": ("处罚", "罚款", "重罚", "整改"),
    "tracking": ("站外追踪", "pixel", "events sdk", "events api", "个人信息"),
    "warehouse-close": ("关闭", "关停", "合并", "整合", "收缩"),
    "warehouse-expand": ("扩大", "扩张", "布局", "本地仓", "自营仓"),
    "settlement-change": ("结算周期", "回款", "30个自然日", "30天"),
    "membership-test": ("付费会员", "会员服务", "测试多档", "会员专属"),
    "financial-disclosure": ("财报", "财务与运营数据", "季度业绩", "截至"),
}


@dataclass(frozen=True)
class WeeklyEventGroup:
    """同一周度事实的代表文章和佐证文章。"""

    representative: dict[str, Any]
    corroborating_articles: tuple[dict[str, Any], ...]

    @property
    def article_ids(self) -> tuple[str, ...]:
        return (
            _article_id(self.representative),
            *(_article_id(article) for article in self.corroborating_articles),
        )


@dataclass(frozen=True)
class WeeklyEditorialBrief:
    """供周报 Agent 与测试复用的确定性编辑简报。"""

    event_groups: tuple[WeeklyEventGroup, ...]
    featured_articles: tuple[dict[str, Any], ...]

    @property
    def candidate_count(self) -> int:
        return len(self.event_groups)

    @property
    def featured_article_ids(self) -> tuple[str, ...]:
        return tuple(_article_id(article) for article in self.featured_articles)


def build_weekly_event_groups(articles: Iterable[Mapping[str, Any]]) -> list[WeeklyEventGroup]:
    """跨日期保守归并同一事实，后续进展和同类主题仍保留为独立候选。"""

    candidates = [dict(article) for article in articles]
    candidates.sort(key=_published_sort_key, reverse=True)
    grouped: list[list[dict[str, Any]]] = []
    for article in candidates:
        target = next(
            (
                group
                for group in grouped
                if any(_is_same_weekly_event(article, existing) for existing in group)
            ),
            None,
        )
        if target is None:
            grouped.append([article])
        else:
            target.append(article)

    result: list[WeeklyEventGroup] = []
    for group in grouped:
        ordered = sorted(group, key=_representative_sort_key)
        result.append(
            WeeklyEventGroup(
                representative=ordered[0],
                corroborating_articles=tuple(ordered[1:]),
            )
        )
    return sorted(result, key=lambda group: _published_sort_key(group.representative), reverse=True)


def build_weekly_editorial_brief(
    articles: Iterable[Mapping[str, Any]],
    *,
    selected_article_ids: Sequence[str] | None = None,
    limit: int = WEEKLY_FEATURED_MAX,
) -> WeeklyEditorialBrief:
    """生成跨日候选集和可直接用于周报正文的重点展示集。"""

    groups = build_weekly_event_groups(articles)
    candidates = [group.representative for group in groups]
    featured = select_weekly_featured_articles(
        candidates,
        selected_article_ids=selected_article_ids,
        limit=limit,
    )
    return WeeklyEditorialBrief(tuple(groups), tuple(featured))


def select_weekly_featured_articles(
    candidates: Sequence[Mapping[str, Any]],
    *,
    selected_article_ids: Sequence[str] | None = None,
    limit: int = WEEKLY_FEATURED_MAX,
) -> list[dict[str, Any]]:
    """选择重点展示事件；Agent 指定结果与自动推荐结果使用同一套硬约束。"""

    if limit < 1 or limit > WEEKLY_FEATURED_MAX:
        raise ValueError(f"周报重点展示上限必须在 1～{WEEKLY_FEATURED_MAX} 之间")
    normalized = [dict(article) for article in candidates]
    by_id = {_article_id(article): article for article in normalized}
    if len(by_id) != len(normalized):
        raise ValueError("周报候选集中 articleId 不能重复")
    candidate_categories = {_category(article) for article in normalized if _category(article)}
    if len(candidate_categories) > limit:
        raise ValueError("重点展示上限小于非空候选分类数，无法满足分类覆盖")

    if selected_article_ids is not None:
        requested = [str(article_id) for article_id in selected_article_ids]
        if len(requested) != len(set(requested)):
            raise ValueError("selectedArticleIds 不能重复")
        unknown = sorted(set(requested) - set(by_id))
        if unknown:
            raise ValueError(f"selectedArticleIds 包含非候选文章：{', '.join(unknown)}")
        if len(requested) > limit:
            raise ValueError(f"周报重点展示事件不得超过 {limit} 个")
        if len(normalized) >= WEEKLY_FEATURED_MIN and len(requested) < WEEKLY_FEATURED_MIN:
            raise ValueError(f"候选充足时周报重点展示事件不得少于 {WEEKLY_FEATURED_MIN} 个")
        selected = [by_id[article_id] for article_id in requested]
        _validate_category_coverage(normalized, selected)
        return sorted(selected, key=_published_sort_key, reverse=True)

    if len(normalized) <= limit:
        return sorted(normalized, key=_published_sort_key, reverse=True)

    ranked = sorted(normalized, key=_featured_sort_key)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    categories = sorted(candidate_categories)
    for category in categories:
        winner = next(article for article in ranked if _category(article) == category)
        _append_once(selected, selected_ids, winner)

    family_counts: defaultdict[str, int] = defaultdict(int)
    category_counts: defaultdict[str, int] = defaultdict(int)
    for article in selected:
        family_counts[weekly_topic_family(article)] += 1
        category_counts[_category(article) or "unknown"] += 1
    for article in ranked:
        if len(selected) >= limit:
            break
        family = weekly_topic_family(article)
        category = _category(article) or "unknown"
        if family_counts[family] >= 2:
            continue
        if category_counts[category] >= 3:
            continue
        if _append_once(selected, selected_ids, article):
            family_counts[family] += 1
            category_counts[category] += 1

    # 主题多样性约束不能让展示集低于上限；剩余位置继续按经营价值补齐。
    for article in ranked:
        if len(selected) >= limit:
            break
        _append_once(selected, selected_ids, article)

    _validate_category_coverage(normalized, selected)
    return sorted(selected, key=_published_sort_key, reverse=True)


def weekly_topic_family(article: Mapping[str, Any]) -> str:
    """返回用于限制同类事件铺陈数量的稳定主题族。"""

    text = _article_text(article)
    topics = _topics(text)
    entities = _entities(text)
    category = _category(article) or "unknown"

    for topic in (
        "tariff-customs",
        "logistics-cost",
        "warehouse-disruption",
        "settlement-fee",
    ):
        if topic in topics:
            if topic == "settlement-fee" and entities:
                return f"{topic}:{sorted(entities)[0]}"
            return topic

    entity = sorted(entities)[0] if entities else category
    if "fulfillment-network" in topics:
        return f"{entity}:fulfillment-network"
    if topics & {"advertising", "paid-membership", "ai-tools"}:
        return f"{entity}:growth-tools"
    if topics & {"content-commerce", "market-results"}:
        return f"{entity}:market-intelligence"
    if topics & {"data-privacy", "account-ip", "regulation", "listing"}:
        return f"{entity}:rules-compliance"
    return f"{category}:{entity}"


def build_weekly_theme_suggestions(articles: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把重点展示事件收束为 3～6 个稳定主题，避免退化成分类标题堆砌。"""

    buckets: dict[str, list[str]] = defaultdict(list)
    for article in articles:
        category = _category(article)
        topics = _topics(_article_text(article))
        if topics & {"tariff-customs", "settlement-fee", "regulation", "account-ip", "data-privacy"}:
            bucket = "rules"
        elif topics & {"logistics-cost", "fulfillment-network", "warehouse-disruption"}:
            bucket = "fulfillment"
        elif topics & {"advertising", "paid-membership", "ai-tools", "listing"}:
            bucket = "growth"
        elif topics & {"market-results", "content-commerce", "seasonal-opportunity"}:
            bucket = "market"
        elif category == "seller-community-signal":
            bucket = "signals"
        else:
            bucket = "platform"
        buckets[bucket].append(_article_id(article))

    definitions = (
        ("rules", "规则、税费与合规节点", "合并呈现本周需要核验或执行的平台规则、税费和合规变化。"),
        ("fulfillment", "履约网络与物流成本", "合并呈现仓网、运输价格、配送能力和供应链稳定性变化。"),
        ("growth", "流量入口与运营工具", "合并呈现广告、AI、搜索、会员和商品发现入口的变化。"),
        ("market", "平台竞争与市场信号", "合并呈现区域市场、内容电商、品类和季节性机会信号。"),
        ("platform", "平台经营动作", "合并呈现本周其他具有经营影响的平台动作。"),
        ("signals", "卖家社区重复信号", "汇总跨工作日出现且仍需继续核验的卖家侧信号。"),
    )
    themes = [
        {"title": title, "summary": summary, "articleIds": buckets[key]}
        for key, title, summary in definitions
        if buckets.get(key)
    ]
    if len(themes) >= 3:
        return themes[:6]

    all_ids = [_article_id(article) for article in articles]
    fallbacks = (
        ("本周重点变化", "本主题汇总本周最终入选的重点经营变化。"),
        ("卖家经营影响", "本主题从钱、货、号、流量、效率和竞争维度观察入选事件。"),
        ("下阶段核验重点", "本主题保留需要继续核验生效范围和实际影响的入选事件。"),
    )
    return [
        {"title": title, "summary": summary, "articleIds": all_ids}
        for title, summary in fallbacks
    ]


def _is_same_weekly_event(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if _article_id(left) == _article_id(right):
        return True

    left_url = _canonical_identity_url(left)
    right_url = _canonical_identity_url(right)
    if left_url and left_url == right_url:
        return True

    left_hash = _value(left, "contentHash", "content_hash")
    right_hash = _value(right, "contentHash", "content_hash")
    if left_hash and left_hash == right_hash:
        return True

    left_cluster = _value(left, "clusterId", "cluster_id", "eventKey", "event_key")
    right_cluster = _value(right, "clusterId", "cluster_id", "eventKey", "event_key")
    if left_cluster and left_cluster == right_cluster:
        return True

    left_title = _title(left)
    right_title = _title(right)
    left_text = _article_text(left)
    right_text = _article_text(right)
    left_entities = _entities(left_text)
    right_entities = _entities(right_text)
    left_markets = _markets(left_text)
    right_markets = _markets(right_text)
    left_topics = _topics(left_text)
    right_topics = _topics(right_text)
    shared_entities = left_entities & right_entities
    shared_topics = left_topics & right_topics
    shared_numbers = _numbers(left_text) & _numbers(right_text)
    shared_actions = _event_actions(left_text) & _event_actions(right_text)
    title_similarity = _jaccard(_character_ngrams(left_title), _character_ngrams(right_title))
    text_similarity = _jaccard(_text_features(left_text), _text_features(right_text))

    if left_markets and right_markets and not left_markets & right_markets:
        return False
    if shared_entities and shared_topics:
        if title_similarity >= 0.50:
            return True
        if left_markets & right_markets and len(shared_actions) >= 2:
            return True
        if (
            "financial-disclosure" in shared_actions
            and shared_numbers
            and text_similarity >= 0.08
        ):
            return True
        if len(shared_topics) >= 2 and text_similarity >= 0.20:
            return True
        if len(shared_topics) >= 2 and shared_numbers and text_similarity >= 0.08:
            return True
        if len(shared_numbers) >= 2 and text_similarity >= 0.10:
            return True
        if shared_numbers and title_similarity >= 0.30 and text_similarity >= 0.12:
            return True
        if text_similarity >= 0.38:
            return True
    if shared_topics and left_markets & right_markets:
        distinctive_percentages = {
            number for number in shared_numbers if number.endswith("%") and number not in {"100%"}
        }
        if distinctive_percentages and "tariff-customs" in shared_topics:
            return True
        if len(shared_numbers) >= 2:
            return text_similarity >= 0.12
    return False


def _validate_category_coverage(
    candidates: Sequence[Mapping[str, Any]], selected: Sequence[Mapping[str, Any]]
) -> None:
    candidate_categories = {_category(article) for article in candidates if _category(article)}
    selected_categories = {_category(article) for article in selected if _category(article)}
    missing = sorted(candidate_categories - selected_categories)
    if missing:
        raise ValueError(f"周报重点展示集缺少非空分类代表事件：{', '.join(missing)}")


def _append_once(
    selected: list[dict[str, Any]], selected_ids: set[str], article: Mapping[str, Any]
) -> bool:
    article_id = _article_id(article)
    if article_id in selected_ids:
        return False
    selected.append(dict(article))
    selected_ids.add(article_id)
    return True


def _featured_sort_key(article: Mapping[str, Any]) -> tuple[int, float, str]:
    score = _editorial_score(article)
    published = _published_sort_key(article).timestamp()
    return -score, -published, _article_id(article)


def _editorial_score(article: Mapping[str, Any]) -> int:
    source_class = _source_class(article)
    score = {0: 60, 1: 35, 2: 10, 3: 0}.get(_SOURCE_RANK.get(source_class, 4), 0)
    score += _CATEGORY_PRIORITY.get(_category(article) or "", 0)
    score += len(set(_value(article, "impactDimensions", "impact_dimensions", default=[]) or [])) * 6
    if _value(article, "effectiveAt", "effective_at"):
        score += 18
    if _value(article, "deadlineAt", "deadline_at"):
        score += 18
    evidence = _value(article, "evidence", default=[]) or []
    conflicts = _value(article, "conflicts", default=[]) or []
    score += min(len(evidence), 3) * 3
    score += min(len(conflicts), 2) * 4
    text = _article_text(article)
    score += min(sum(term in text for term in _ACTION_TERMS), 3) * 4
    if _value(article, "whyImportant", "why_important"):
        score += 4
    if _value(article, "suggestions", default=[]):
        score += 4
    return score


def _representative_sort_key(article: Mapping[str, Any]) -> tuple[int, int, float, str]:
    source_rank = _SOURCE_RANK.get(_source_class(article), 4)
    completeness = _completeness_score(article)
    published = _published_sort_key(article).timestamp()
    return source_rank, -completeness, -published, _article_id(article)


def _completeness_score(article: Mapping[str, Any]) -> int:
    score = 0
    for field_names in (
        ("summary",),
        ("whatHappened", "what_happened"),
        ("whyImportant", "why_important"),
        ("affectedMarketplaces", "affected_marketplaces"),
        ("suggestions",),
        ("evidence",),
    ):
        value = _value(article, *field_names)
        if value:
            score += len(value) if isinstance(value, (list, tuple)) else min(len(str(value)) // 40 + 1, 5)
    score += min(len(_numbers(_article_text(article))), 6)
    return score


def _entities(text: str) -> set[str]:
    padded = f" {text.lower()} "
    return {
        name
        for name, aliases in _ENTITY_ALIASES.items()
        if any(alias.lower() in padded for alias in aliases)
    }


def _markets(text: str) -> set[str]:
    padded = f" {text.lower()} "
    return {
        name
        for name, aliases in _MARKET_ALIASES.items()
        if any(alias.lower() in padded for alias in aliases)
    }


def _topics(text: str) -> set[str]:
    padded = f" {text.lower()} "
    topics = {
        topic
        for topic, markers in _TOPIC_MARKERS.items()
        if any(marker.lower() in padded for marker in markers)
    }
    if re.search(r"(?<![a-z])ai(?![a-z])|ai运营|ai目录|genai", padded):
        topics.add("ai-tools")
    return topics


def _event_actions(text: str) -> set[str]:
    padded = f" {text.lower()} "
    return {
        action
        for action, markers in _EVENT_ACTION_MARKERS.items()
        if any(marker.lower() in padded for marker in markers)
    }


def _numbers(text: str) -> set[str]:
    result: set[str] = set()
    for match in re.findall(r"(?<![a-z0-9])\d+(?:\.\d+)?%?", text):
        number = match.rstrip("%")
        if number.isdigit() and 2020 <= int(number) <= 2035:
            continue
        if number.isdigit() and len(number) == 1 and not match.endswith("%"):
            continue
        if "." in number:
            number = number.rstrip("0").rstrip(".")
        if match.endswith("%"):
            number += "%"
        if number:
            result.add(number)
    return result


def _character_ngrams(value: str, size: int = 2) -> set[str]:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", _normalize(value))
    if len(normalized) <= size:
        return {normalized} if normalized else set()
    return {normalized[index : index + size] for index in range(len(normalized) - size + 1)}


def _text_features(value: str) -> set[str]:
    normalized = _normalize(value)
    latin = {
        token
        for token in re.findall(r"[a-z][a-z0-9.+-]{2,}", normalized)
        if token not in {"reported", "report", "according", "platform"}
    }
    chinese_segments = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    chinese = {
        segment[index : index + 2]
        for segment in chinese_segments
        for index in range(len(segment) - 1)
    }
    return latin | chinese


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _article_text(article: Mapping[str, Any]) -> str:
    analysis = _value(article, "analysis", default={})
    analysis_mapping = analysis if isinstance(analysis, Mapping) else {}
    values = (
        _title(article),
        _value(article, "summary", default=""),
        _value(article, "whatHappened", "what_happened", default=""),
        _value(analysis_mapping, "whatHappened", "what_happened", default=""),
    )
    return _normalize(" ".join(str(value) for value in values if value))


def _title(article: Mapping[str, Any]) -> str:
    return str(_value(article, "titleZh", "title_zh", "title", default=""))


def _canonical_identity_url(article: Mapping[str, Any]) -> str | None:
    value = _value(article, "canonicalUrl", "canonical_url", "sourceUrl", "source_url")
    if not isinstance(value, str) or not value:
        return None
    parts = urlsplit(value.strip())
    if not parts.scheme or not parts.netloc:
        return None
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"\s+", " ", normalized).strip()


def _published_sort_key(article: Mapping[str, Any]) -> datetime:
    value = _value(article, "publishedAt", "published_at")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=ZoneInfo("UTC"))
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("UTC"))
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=ZoneInfo("UTC"))


def _article_id(article: Mapping[str, Any]) -> str:
    value = _value(article, "articleId", "article_id", "id")
    if not value:
        raise ValueError("周报候选文章缺少 articleId")
    return str(value)


def _category(article: Mapping[str, Any]) -> str | None:
    value = _value(article, "primaryCategory", "primary_category")
    return str(value) if value else None


def _source_class(article: Mapping[str, Any]) -> str | None:
    source = _value(article, "source", default={})
    source_mapping = source if isinstance(source, Mapping) else {}
    value = _value(
        article,
        "sourceClass",
        "source_class",
        default=_value(source_mapping, "sourceClass", "source_class"),
    )
    return str(value) if value else None


def _value(source: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in source and source[name] is not None:
            return source[name]
    return default


__all__ = [
    "WEEKLY_FEATURED_MAX",
    "WEEKLY_FEATURED_MIN",
    "WEEKLY_EDITORIAL_POLICY_VERSION",
    "WeeklyEditorialBrief",
    "WeeklyEventGroup",
    "build_weekly_editorial_brief",
    "build_weekly_event_groups",
    "build_weekly_theme_suggestions",
    "select_weekly_featured_articles",
    "weekly_topic_family",
]
