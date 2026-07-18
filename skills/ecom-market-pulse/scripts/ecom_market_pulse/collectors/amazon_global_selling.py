"""亚马逊全球开店中国站的资讯发现器。"""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .base import DiscoveredItem, PublicHttpFetcher, RawArticle, source_id, source_value


_ARTICLE_PATH = re.compile(r"/news/news-(?:notices|brand|product)-(?P<date>\d{6})$")


class AmazonGlobalSellingNewsAdapter:
    """从官网文章 URL 中提取发布日期，避免导航链接和无日期卡片混入。"""

    def __init__(self, fetcher: PublicHttpFetcher | None = None) -> None:
        self._fetcher = fetcher or PublicHttpFetcher()

    def discover(self, source: Any, since: datetime) -> list[DiscoveredItem]:
        listing_url = str(source_value(source, "discovery.url", ""))
        if not listing_url:
            raise ValueError("Amazon 全球开店中国信源缺少 discovery.url。")
        listing = DiscoveredItem(source_id(source), listing_url, datetime.now(UTC))
        raw = self._fetcher.get(source, listing)
        if not raw.succeeded:
            return []
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover - packaging boundary
            raise RuntimeError("缺少 beautifulsoup4 依赖，无法解析 Amazon 全球开店资讯列表。") from exc

        boundary = since.astimezone(UTC) if since.tzinfo else since.replace(tzinfo=UTC)
        items: list[DiscoveredItem] = []
        for link in BeautifulSoup(raw.text(), "html.parser").select('a[href*="/news/news-"]'):
            href = link.get("href")
            if not isinstance(href, str):
                continue
            url = _canonical_url(href)
            published_at = _published_at(url)
            if published_at is None or published_at < boundary:
                continue
            items.append(
                DiscoveredItem(
                    source_id=source_id(source),
                    url=url,
                    discovered_at=datetime.now(UTC),
                    title_hint=link.get_text(" ", strip=True) or None,
                    published_at_hint=published_at,
                )
            )
        return _limit(
            sorted(_unique(items), key=lambda item: item.published_at_hint or datetime.min.replace(tzinfo=UTC), reverse=True),
            source_value(source, "discovery.max_items", None),
        )

    def fetch(self, source: Any, item: DiscoveredItem) -> RawArticle:
        return self._fetcher.get(source, item)


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _published_at(url: str) -> datetime | None:
    match = _ARTICLE_PATH.search(urlsplit(url).path)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group("date"), "%y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _unique(items: list[DiscoveredItem]) -> list[DiscoveredItem]:
    seen: set[str] = set()
    return [item for item in items if not (item.url in seen or seen.add(item.url))]


def _limit(items: list[DiscoveredItem], max_items: Any) -> list[DiscoveredItem]:
    return items[: max(1, int(max_items))] if max_items is not None else items
