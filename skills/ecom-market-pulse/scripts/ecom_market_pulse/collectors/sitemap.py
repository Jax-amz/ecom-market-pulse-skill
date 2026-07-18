"""公开 Sitemap 发现器，支持 sitemap index。"""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

from .base import DiscoveredItem, PublicHttpFetcher, RawArticle, parse_datetime, source_id, source_value


class SitemapSourceAdapter:
    """解析 ``urlset`` 和 ``sitemapindex``，不尝试访问受保护页面。"""

    def __init__(self, fetcher: PublicHttpFetcher | None = None) -> None:
        self._fetcher = fetcher or PublicHttpFetcher()

    def discover(self, source: Any, since: datetime) -> list[DiscoveredItem]:
        sitemap_url = str(source_value(source, "discovery.url", ""))
        if not sitemap_url:
            raise ValueError("Sitemap 信源配置缺少 discovery.url。")
        max_sitemaps = max(1, int(source_value(source, "discovery.max_sitemaps", 10)))
        timezone = str(source_value(source, "content.timezone", "UTC"))
        include_pattern = source_value(source, "discovery.include_regex", source_value(source, "discovery.url_pattern", None))
        exclude_pattern = source_value(source, "discovery.exclude_regex", None)
        queue = [sitemap_url]
        visited: set[str] = set()
        items: list[DiscoveredItem] = []
        while queue and len(visited) < max_sitemaps:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            request_item = DiscoveredItem(source_id(source), current, datetime.now(UTC))
            raw = self._fetcher.get(source, request_item)
            if not raw.succeeded:
                continue
            child_sitemaps, discovered = _parse_sitemap(raw.text(), source_id(source), raw.final_url or current, timezone)
            queue.extend(url for url in child_sitemaps if url not in visited)
            items.extend(
                item for item in discovered
                if _matches(item.url, include_pattern, exclude_pattern)
                and (item.published_at_hint is None or item.published_at_hint >= _as_utc(since))
            )
        return _unique_items(items)

    def fetch(self, source: Any, item: DiscoveredItem) -> RawArticle:
        return self._fetcher.get(source, item)


def _parse_sitemap(xml_text: str, source_identifier: str, base_url: str, timezone: str) -> tuple[list[str], list[DiscoveredItem]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return [], []
    root_name = _local_name(root.tag)
    if root_name == "sitemapindex":
        nested = []
        for node in root:
            if _local_name(node.tag) == "sitemap":
                loc = _child_text(node, "loc")
                if loc:
                    nested.append(urljoin(base_url, loc))
        return nested, []
    if root_name != "urlset":
        return [], []
    articles: list[DiscoveredItem] = []
    for node in root:
        if _local_name(node.tag) != "url":
            continue
        loc = _child_text(node, "loc")
        if loc:
            articles.append(
                DiscoveredItem(
                    source_id=source_identifier,
                    url=urljoin(base_url, loc),
                    discovered_at=datetime.now(UTC),
                    published_at_hint=parse_datetime(_child_text(node, "lastmod"), timezone),
                )
            )
    return [], articles


def _matches(url: str, include: Any, exclude: Any) -> bool:
    return (not include or re.search(str(include), url) is not None) and (not exclude or re.search(str(exclude), url) is None)


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(node: ElementTree.Element, name: str) -> str | None:
    for child in node:
        if _local_name(child.tag) == name and child.text and child.text.strip():
            return child.text.strip()
    return None


def _unique_items(items: list[DiscoveredItem]) -> list[DiscoveredItem]:
    seen: set[str] = set()
    return [item for item in items if not (item.url in seen or seen.add(item.url))]

