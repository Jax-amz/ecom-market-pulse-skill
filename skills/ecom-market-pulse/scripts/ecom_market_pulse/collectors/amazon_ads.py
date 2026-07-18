"""Amazon Ads What's New 的公开索引适配器。"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, Mapping
from urllib.parse import urljoin

from .base import DiscoveredItem, PublicHttpFetcher, RawArticle, source_id, source_value


INDEX_ENDPOINT = "https://advertising.amazon.com/a20m-api/v1/pages?subpageType=Whats%20new&locale=zh-cn"


class AmazonAdsWhatsNewAdapter:
    """消费 Amazon Ads 页面自身使用的公开 JSON 索引，并保留原文页抓取。"""

    def __init__(self, fetcher: PublicHttpFetcher | None = None) -> None:
        self._fetcher = fetcher or PublicHttpFetcher()

    def discover(self, source: Any, since: datetime) -> list[DiscoveredItem]:
        index_item = DiscoveredItem(source_id(source), INDEX_ENDPOINT, datetime.now(UTC))
        raw = self._fetcher.get(source, index_item)
        if not raw.succeeded:
            return []
        try:
            rows = json.loads(raw.text())
        except json.JSONDecodeError:
            return []
        if not isinstance(rows, list):
            return []

        boundary = since.astimezone(UTC) if since.tzinfo else since.replace(tzinfo=UTC)
        items: list[DiscoveredItem] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            published_at = _published_at(row.get("publishDateTimestamp"))
            if published_at is None or published_at < boundary:
                continue
            url = _article_url(row.get("url"))
            title = row.get("title")
            if url is None or not isinstance(title, str) or not title.strip():
                continue
            items.append(
                DiscoveredItem(
                    source_id=source_id(source),
                    url=url,
                    discovered_at=datetime.now(UTC),
                    title_hint=title.strip(),
                    published_at_hint=published_at,
                )
            )
        return _limit(_unique(items), source_value(source, "discovery.max_items", None))

    def fetch(self, source: Any, item: DiscoveredItem) -> RawArticle:
        return self._fetcher.get(source, item)


def _published_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


def _article_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("/"):
        return None
    path = value.removeprefix("/advertising.amazon.com")
    if not path.startswith("/zh-cn/"):
        path = f"/zh-cn{path}"
    return urljoin("https://advertising.amazon.com", path)


def _unique(items: list[DiscoveredItem]) -> list[DiscoveredItem]:
    seen: set[str] = set()
    return [item for item in items if not (item.url in seen or seen.add(item.url))]


def _limit(items: list[DiscoveredItem], max_items: Any) -> list[DiscoveredItem]:
    return items[: max(1, int(max_items))] if max_items is not None else items
