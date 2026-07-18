"""AMZ123 跨境早报的公开 JSON 接口适配器。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from .base import DiscoveredItem, PublicHttpFetcher, RawArticle, source_id, source_value


LIST_ENDPOINT = "https://api.amz123.com/ugc/v1/morning_news/list"
DETAIL_ENDPOINT = "https://api.amz123.com/ugc/v1/morning_news/detail"


class Amz123MorningNewsAdapter:
    """以早报聚合接口发现文章，再仅抓取详情中列出的公开网页。"""

    def __init__(
        self,
        fetcher: PublicHttpFetcher | None = None,
        post_json: Callable[[str, Mapping[str, Any], float], Mapping[str, Any]] | None = None,
    ) -> None:
        self._fetcher = fetcher or PublicHttpFetcher()
        self._post_json = post_json or _post_public_json

    def discover(self, source: Any, since: datetime) -> list[DiscoveredItem]:
        max_items = int(source_value(source, "discovery.max_items", 20) or 20)
        timeout_seconds = float(source_value(source, "fetch.timeout_seconds", 20))
        payload = self._post_json(LIST_ENDPOINT, {"page": 1, "page_size": min(max_items, 100)}, timeout_seconds)
        rows = _rows(payload)
        boundary = since.astimezone(UTC) if since.tzinfo else since.replace(tzinfo=UTC)
        items: list[DiscoveredItem] = []
        for row in rows:
            published_at = _timestamp(row.get("published_at"))
            if published_at and published_at < boundary:
                continue
            cid = row.get("cid")
            if not isinstance(cid, int):
                continue
            detail = self._post_json(DETAIL_ENDPOINT, {"cid": cid, "client_type": 0}, timeout_seconds)
            for article in _content(detail):
                url = article.get("url")
                title = article.get("title")
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    continue
                items.append(
                    DiscoveredItem(
                        source_id=source_id(source),
                        url=url,
                        discovered_at=datetime.now(UTC),
                        title_hint=title if isinstance(title, str) else None,
                        published_at_hint=published_at,
                        metadata={"amz123_cid": str(cid)},
                    )
                )
                if len(items) >= max_items:
                    return _unique(items)
        return _unique(items)

    def fetch(self, source: Any, item: DiscoveredItem) -> RawArticle:
        return self._fetcher.get(source, item)


def _post_public_json(url: str, payload: Mapping[str, Any], timeout_seconds: float) -> Mapping[str, Any]:
    response = httpx.post(
        url,
        json=dict(payload),
        headers={"Accept": "application/json", "User-Agent": "ecom-market-pulse/1.0 (+public-content-collector)"},
        timeout=timeout_seconds,
        follow_redirects=False,
    )
    response.raise_for_status()
    decoded = response.json()
    if not isinstance(decoded, dict):
        raise ValueError("AMZ123 公开接口返回格式不合法")
    return decoded


def _rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = payload.get("data")
    rows = data.get("rows") if isinstance(data, Mapping) else None
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _content(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = payload.get("data")
    content = data.get("content") if isinstance(data, Mapping) else None
    return [item for item in content if isinstance(item, Mapping)] if isinstance(content, list) else []


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _unique(items: list[DiscoveredItem]) -> list[DiscoveredItem]:
    seen: set[str] = set()
    return [item for item in items if not (item.url in seen or seen.add(item.url))]
