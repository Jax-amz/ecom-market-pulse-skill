"""URL、正文和事件层面的可解释去重辅助函数。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import re
from typing import Any, Iterable, Sequence

from .normalization import content_sha256, normalize_text, normalize_url


_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "at", "by", "for", "from", "in", "is", "of", "on", "the", "to", "with",
    "about", "after", "announces", "announcement", "new", "update", "updates", "发布", "公告", "更新", "最新", "关于", "以及", "的", "了", "和", "与", "在", "对",
})


@dataclass(frozen=True, slots=True)
class SimilarityCandidate:
    """近似标题候选，供事件聚类或人工复核使用，绝不代表自动删除。"""

    item: Any
    distance: int
    similarity: float


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    kind: str  # canonical_url | content_sha256
    existing: Any


@dataclass(slots=True)
class EventCluster:
    """保留代表来源和所有佐证来源的同事件分组。"""

    event_key: str
    representative: Any
    corroborating_sources: list[Any] = field(default_factory=list)
    conflicts: list[Any] = field(default_factory=list)


class Deduplicator:
    """进程内的确定性重复索引；数据库层负责跨运行查询与持久化。"""

    def __init__(self, simhash_threshold: int = 3) -> None:
        self.simhash_threshold = simhash_threshold
        self._by_url: dict[str, Any] = {}
        self._by_content: dict[str, Any] = {}
        self._title_fingerprints: list[tuple[int, Any]] = []

    def find_exact_duplicate(self, article: Any) -> DuplicateMatch | None:
        canonical = normalize_url(_article_value(article, "canonical_url", "canonicalUrl"))
        if canonical and canonical in self._by_url:
            return DuplicateMatch("canonical_url", self._by_url[canonical])
        text_hash = _article_content_hash(article)
        if text_hash and text_hash in self._by_content:
            return DuplicateMatch("content_sha256", self._by_content[text_hash])
        return None

    def find_near_duplicate_candidates(self, title: str | None, threshold: int | None = None) -> list[SimilarityCandidate]:
        fingerprint = simhash(title)
        limit = self.simhash_threshold if threshold is None else threshold
        candidates = [
            SimilarityCandidate(item=item, distance=hamming_distance(fingerprint, existing), similarity=1 - distance / 64)
            for existing, item in self._title_fingerprints
            if (distance := hamming_distance(fingerprint, existing)) <= limit
        ]
        return sorted(candidates, key=lambda candidate: (candidate.distance, _article_value(candidate.item, "canonical_url", "canonicalUrl") or ""))

    def register(self, article: Any) -> None:
        """在调用方确认应保留该文章后登记；近似候选不会阻止登记。"""
        canonical = normalize_url(_article_value(article, "canonical_url", "canonicalUrl"))
        if canonical:
            self._by_url.setdefault(canonical, article)
        text_hash = _article_content_hash(article)
        if text_hash:
            self._by_content.setdefault(text_hash, article)
        self._title_fingerprints.append((simhash(_article_value(article, "title") or ""), article))


def simhash(text: str | None) -> int:
    """基于标题 token 的 64 位 SimHash，作为候选召回而非重复判定。"""
    tokens = _tokens(text)
    if not tokens:
        return 0
    weights = [0] * 64
    for token in tokens:
        digest = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")
        for index in range(64):
            weights[index] += 1 if digest & (1 << index) else -1
    return sum(1 << index for index, weight in enumerate(weights) if weight >= 0)


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def build_event_key(
    title: str | None,
    published_at: datetime | None,
    *,
    entities: Iterable[str] | None = None,
    topic: str | None = None,
) -> str:
    """为同事件聚类提供稳定键，不会引入任何业务分类。

    调用方可传入来自原文的实体和中性主题词；未传时仅从标题确定性提取。
    """
    entity_values = sorted(set(normalize_text(value).lower() for value in (entities or extract_entities(title)) if normalize_text(value)))
    title_terms = _tokens(title)[:8]
    date_part = "unknown"
    if published_at:
        value = published_at.astimezone(UTC) if published_at.tzinfo else published_at.replace(tzinfo=UTC)
        date_part = value.date().isoformat()
    payload = "|".join((normalize_text(topic).lower(), date_part, ",".join(entity_values), ",".join(title_terms)))
    return "evt_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def extract_entities(title: str | None) -> list[str]:
    """仅提取标题中的显式专名/缩写，不依赖或产生业务标签。"""
    text = normalize_text(title)
    candidates = re.findall(r"\b[A-Z][A-Za-z0-9&.-]{1,}(?:\s+[A-Z][A-Za-z0-9&.-]{1,})*\b|\b[A-Z]{2,}[A-Z0-9-]*\b", text)
    return sorted(set(candidate.casefold() for candidate in candidates))


def cluster_events(articles: Sequence[Any], simhash_threshold: int = 3) -> list[EventCluster]:
    """按精确事件键优先，再以日期、实体和标题候选作保守合并。

    相近标题不会单独触发合并：还必须在同一自然日且共享实体或有较高 token 重叠。
    """
    clusters: list[EventCluster] = []
    for article in articles:
        key = build_event_key(
            _article_value(article, "title"),
            _article_datetime(article, "published_at", "publishedAt"),
            entities=_article_value(article, "entities"),
            topic=_article_value(article, "topic"),
        )
        target = next((cluster for cluster in clusters if cluster.event_key == key), None)
        if target is None:
            target = _matching_cluster(article, clusters, simhash_threshold)
        if target is None:
            clusters.append(EventCluster(key, article))
        else:
            _add_to_cluster(target, article)
    return clusters


def choose_representative(articles: Sequence[Any]) -> Any:
    """官方源优先，其余按发布时间和 canonical URL 产生稳定结果。"""
    if not articles:
        raise ValueError("至少需要一篇文章才能选择代表来源。")
    return min(articles, key=_representative_sort_key)


def _matching_cluster(article: Any, clusters: Sequence[EventCluster], threshold: int) -> EventCluster | None:
    title_hash = simhash(_article_value(article, "title") or "")
    article_date = _article_datetime(article, "published_at", "publishedAt")
    article_entities = set(_article_value(article, "entities") or extract_entities(_article_value(article, "title")))
    article_tokens = set(_tokens(_article_value(article, "title")))
    for cluster in clusters:
        representative = cluster.representative
        rep_date = _article_datetime(representative, "published_at", "publishedAt")
        if not _same_day(article_date, rep_date):
            continue
        distance = hamming_distance(title_hash, simhash(_article_value(representative, "title") or ""))
        if distance > threshold:
            continue
        rep_entities = set(_article_value(representative, "entities") or extract_entities(_article_value(representative, "title")))
        rep_tokens = set(_tokens(_article_value(representative, "title")))
        token_overlap = len(article_tokens & rep_tokens) / max(1, len(article_tokens | rep_tokens))
        if article_entities & rep_entities or token_overlap >= 0.6:
            return cluster
    return None


def _add_to_cluster(cluster: EventCluster, article: Any) -> None:
    candidates = [cluster.representative, *cluster.corroborating_sources, article]
    representative = choose_representative(candidates)
    cluster.corroborating_sources = [candidate for candidate in candidates if candidate is not representative]
    cluster.representative = representative


def _representative_sort_key(article: Any) -> tuple[int, str, str]:
    source_class = str(_article_value(article, "source_class", "sourceClass") or _nested_source_class(article) or "aggregator")
    priority = {"official": 0, "professional-media": 1, "community": 2, "aggregator": 3}.get(source_class, 4)
    published = _article_datetime(article, "published_at", "publishedAt")
    published_key = published.isoformat() if published else "9999-12-31T00:00:00+00:00"
    url = str(_article_value(article, "canonical_url", "canonicalUrl") or "")
    return priority, published_key, url


def _nested_source_class(article: Any) -> Any:
    source = _article_value(article, "source")
    return _article_value(source, "source_class", "sourceClass") if source is not None else None


def _article_content_hash(article: Any) -> str:
    existing = _article_value(article, "content_sha256", "contentHash")
    return str(existing) if existing else content_sha256(_article_value(article, "extracted_text", "text", "content") or "")


def _article_value(article: Any, *names: str) -> Any:
    for name in names:
        if isinstance(article, dict) and name in article:
            return article[name]
        value = getattr(article, name, None)
        if value is not None:
            return value
    return None


def _article_datetime(article: Any, *names: str) -> datetime | None:
    value = _article_value(article, *names)
    return value if isinstance(value, datetime) else None


def _same_day(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return False
    left_utc = left.astimezone(UTC) if left.tzinfo else left.replace(tzinfo=UTC)
    right_utc = right.astimezone(UTC) if right.tzinfo else right.replace(tzinfo=UTC)
    return left_utc.date() == right_utc.date()


def _tokens(value: str | None) -> list[str]:
    normalized = normalize_text(value).lower()
    parts = re.findall(r"[a-z0-9][a-z0-9+&.-]*|[\u4e00-\u9fff]{2,}", normalized)
    return [part for part in parts if part not in _STOP_WORDS]
