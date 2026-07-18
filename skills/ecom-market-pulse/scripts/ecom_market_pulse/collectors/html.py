"""配置驱动的公开 HTML 列表发现器。"""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any
from urllib.parse import urljoin

from .base import DiscoveredItem, PublicHttpFetcher, RawArticle, parse_datetime, source_id, source_value


class HtmlSourceAdapter:
    """从文章列表页提取链接、标题和可选发布时间。

    CSS selector 全部来自 ``source.discovery``，从而避免在代码内写站点特例。
    """

    def __init__(self, fetcher: PublicHttpFetcher | None = None) -> None:
        self._fetcher = fetcher or PublicHttpFetcher()

    def discover(self, source: Any, since: datetime) -> list[DiscoveredItem]:
        listing_url = str(source_value(source, "discovery.url", ""))
        if not listing_url:
            raise ValueError("HTML 信源配置缺少 discovery.url。")
        page = DiscoveredItem(source_id(source), listing_url, datetime.now(UTC))
        raw = self._fetcher.get(source, page)
        if not raw.succeeded:
            return []
        items = _parse_listing(
            raw.text(),
            source_id(source),
            raw.final_url or listing_url,
            source_value(source, "discovery", {}),
            str(source_value(source, "content.timezone", "UTC")),
        )
        boundary = since.astimezone(UTC) if since.tzinfo else since.replace(tzinfo=UTC)
        filtered = [item for item in items if item.published_at_hint is None or item.published_at_hint >= boundary]
        return _limit_items(filtered, source_value(source, "discovery.max_items", None))

    def fetch(self, source: Any, item: DiscoveredItem) -> RawArticle:
        return self._fetcher.get(source, item)


def _parse_listing(html: str, source_identifier: str, base_url: str, discovery: Any, timezone: str) -> list[DiscoveredItem]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - checked in packaging / runtime tests
        raise RuntimeError("缺少 beautifulsoup4 依赖，无法解析 HTML 列表页。") from exc

    soup = BeautifulSoup(html, "html.parser")
    item_selector = _value(discovery, "item_selector", "article, li")
    link_selector = _value(discovery, "link_selector", "a[href]")
    title_selector = _value(discovery, "title_selector", None)
    date_selector = _value(discovery, "date_selector", "time")
    include_pattern = _value(discovery, "include_regex", _value(discovery, "url_pattern", None))
    exclude_pattern = _value(discovery, "exclude_regex", None)

    candidates = soup.select(item_selector)
    if not candidates:
        candidates = soup.select("a[href]")
    results: list[DiscoveredItem] = []
    for candidate in candidates:
        link_node = candidate if getattr(candidate, "name", None) == "a" and candidate.get("href") else candidate.select_one(link_selector)
        if link_node is None or not link_node.get("href"):
            continue
        url = urljoin(base_url, link_node["href"])
        if include_pattern and not re.search(str(include_pattern), url):
            continue
        if exclude_pattern and re.search(str(exclude_pattern), url):
            continue
        title_node = candidate.select_one(title_selector) if title_selector else link_node
        title = title_node.get_text(" ", strip=True) if title_node else None
        date_node = candidate.select_one(date_selector) if date_selector else None
        date_value = None
        if date_node is not None:
            date_value = date_node.get("datetime") or date_node.get("content") or date_node.get_text(" ", strip=True)
        results.append(
            DiscoveredItem(
                source_id=source_identifier,
                url=url,
                discovered_at=datetime.now(UTC),
                title_hint=title or None,
                published_at_hint=parse_datetime(date_value, timezone),
            )
        )
    return _unique_items(results)


def _value(config: Any, key: str, default: Any) -> Any:
    if isinstance(config, dict):
        value = config.get(key, config.get(_camel(key), default))
    else:
        value = getattr(config, key, getattr(config, _camel(key), default))
    return default if value is None else value


def _camel(snake: str) -> str:
    first, *rest = snake.split("_")
    return first + "".join(part.title() for part in rest)


def _unique_items(items: list[DiscoveredItem]) -> list[DiscoveredItem]:
    seen: set[str] = set()
    return [item for item in items if not (item.url in seen or seen.add(item.url))]


def _limit_items(items: list[DiscoveredItem], max_items: Any) -> list[DiscoveredItem]:
    return items[: max(1, int(max_items))] if max_items is not None else items
