"""RSS 与 Atom 发现器。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping
from urllib.parse import urljoin
from xml.etree import ElementTree

from .base import DiscoveredItem, PublicHttpFetcher, RawArticle, json_metadata, parse_datetime, source_id, source_value


class RssSourceAdapter:
    """通过标准 RSS/Atom 文档发现候选文章。"""

    def __init__(self, fetcher: PublicHttpFetcher | None = None) -> None:
        self._fetcher = fetcher or PublicHttpFetcher()

    def discover(self, source: Any, since: datetime) -> list[DiscoveredItem]:
        discovery_url = str(source_value(source, "discovery.url", ""))
        if not discovery_url:
            raise ValueError("RSS 信源配置缺少 discovery.url。")
        feed_item = DiscoveredItem(source_id(source), discovery_url, datetime.now(UTC))
        raw = self._fetcher.get(source, feed_item)
        if not raw.succeeded:
            return []
        timezone = str(source_value(source, "content.timezone", "UTC"))
        items = _parse_feed(raw.text(), source_id(source), raw.final_url or discovery_url, timezone)
        return _limit_items(_within_since(items, since), source_value(source, "discovery.max_items", None))

    def fetch(self, source: Any, item: DiscoveredItem) -> RawArticle:
        return self._fetcher.get(source, item)


def _parse_feed(xml_text: str, source_identifier: str, base_url: str, timezone: str) -> list[DiscoveredItem]:
    """用标准库解析 RSS/Atom，避免发现阶段依赖 feedparser 的隐式行为。"""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    results: list[DiscoveredItem] = []
    for node in root.iter():
        if _local_name(node.tag) not in {"item", "entry"}:
            continue
        link = _entry_link(node)
        if not link:
            continue
        title = _child_text(node, "title")
        published = _child_text(node, "published") or _child_text(node, "pubDate") or _child_text(node, "updated")
        guid = _child_text(node, "guid") or _child_text(node, "id")
        results.append(
            DiscoveredItem(
                source_id=source_identifier,
                url=urljoin(base_url, link),
                discovered_at=datetime.now(UTC),
                title_hint=title,
                published_at_hint=parse_datetime(published, timezone),
                metadata=json_metadata(feed_id=guid),
            )
        )
    return _unique_items(results)


def _entry_link(node: ElementTree.Element) -> str | None:
    for child in node:
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        relation = child.attrib.get("rel", "alternate")
        if href and relation in {"alternate", ""}:
            return href.strip()
        if child.text and child.text.strip():
            return child.text.strip()
    return None


def _child_text(node: ElementTree.Element, name: str) -> str | None:
    for child in node:
        if _local_name(child.tag) == name and child.text and child.text.strip():
            return child.text.strip()
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _within_since(items: list[DiscoveredItem], since: datetime) -> list[DiscoveredItem]:
    boundary = since.astimezone(UTC) if since.tzinfo else since.replace(tzinfo=UTC)
    return [item for item in items if item.published_at_hint is None or item.published_at_hint >= boundary]


def _unique_items(items: list[DiscoveredItem]) -> list[DiscoveredItem]:
    seen: set[str] = set()
    unique: list[DiscoveredItem] = []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            unique.append(item)
    return unique


def _limit_items(items: list[DiscoveredItem], max_items: Any) -> list[DiscoveredItem]:
    return items[: max(1, int(max_items))] if max_items is not None else items
