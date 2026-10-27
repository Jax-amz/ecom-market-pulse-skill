"""AMZ123 跨境快讯：按逐篇发布时间查询公开列表，核对窗口覆盖。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import re
from typing import Any

from .amz123 import _post_public_json
from .base import DiscoveredItem, PublicHttpFetcher, RawArticle, source_id, source_value


FLASH_LIST_ENDPOINT = "https://api.amz123.com/ugc_new/v1/user_content/kx_list"


class Amz123FlashNewsAdapter:
    """复用网页公开的时间范围查询；不依赖早报选编或相对时间标签。"""

    def __init__(
        self,
        fetcher: PublicHttpFetcher | None = None,
        post_json: Callable[[str, Mapping[str, Any], float], Mapping[str, Any]] | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._fetcher = fetcher or PublicHttpFetcher()
        self._post_json = post_json or _post_public_json
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))

    def discover(self, source: Any, since: datetime) -> list[DiscoveredItem]:
        if since.tzinfo is None:
            raise ValueError("跨境快讯发现窗口必须包含时区")
        boundary = since.astimezone(UTC)
        cutoff = self._wall_clock().astimezone(UTC)
        if boundary > cutoff:
            raise ValueError("跨境快讯发现起点不能晚于当前时间")
        maximum = int(source_value(source, "discovery.max_items", 500) or 500)
        timeout = float(source_value(source, "fetch.timeout_seconds", 20))
        payload = self._post_json(
            FLASH_LIST_ENDPOINT,
            {
                "is_important": -1,
                "category_id": 0,
                "start_time": int(boundary.timestamp()),
                "end_time": int(cutoff.timestamp()),
                "keyword": "",
                "is_query_zb": 0,
                "is_query_total_count": 1,
            },
            timeout,
        )
        rows = _complete_rows(payload)
        items: dict[str, DiscoveredItem] = {}
        for row in rows:
            if row.get("is_morning_news") == 1:
                continue
            published = _published_time(row.get("published_at"))
            if not boundary <= published <= cutoff:
                continue
            identifier = row.get("id")
            if not isinstance(identifier, str) or re.fullmatch(r"[A-Za-z0-9_-]+", identifier) is None:
                raise ValueError("跨境快讯返回无效文章标识，不能确认完整覆盖")
            title = row.get("title")
            if not isinstance(title, str) or not title.strip():
                raise ValueError("跨境快讯返回空标题，不能确认完整覆盖")
            # 列表中的 url 实测为空；网页同样用该 id 构造 /kx/ 详情链接。
            url = f"https://www.amz123.com/kx/{identifier}"
            items.setdefault(url, DiscoveredItem(
                source_id=source_id(source),
                url=url,
                canonical_url_hint=url,
                discovered_at=cutoff,
                title_hint=title.strip(),
                published_at_hint=published,
                metadata={"amz123_kx_id": identifier},
            ))
        if len(items) > maximum:
            raise ValueError(f"跨境快讯窗口内有 {len(items)} 篇，超过 max_items={maximum}；禁止静默截断")
        return sorted(items.values(), key=lambda item: item.published_at_hint, reverse=True)

    def fetch(self, source: Any, item: DiscoveredItem) -> RawArticle:
        return self._fetcher.get(source, item)


def _complete_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if payload.get("status") != 0:
        raise ValueError("跨境快讯公开接口未返回成功状态")
    data = payload.get("data")
    if not isinstance(data, Mapping) or not isinstance(data.get("row_map"), Mapping):
        raise ValueError("跨境快讯公开列表结构不合法")
    rows: list[Mapping[str, Any]] = []
    for group in data["row_map"].values():
        if not isinstance(group, Mapping) or not isinstance(group.get("kx_content"), list):
            raise ValueError("跨境快讯日期分组缺少文章列表")
        for row in group["kx_content"]:
            if not isinstance(row, Mapping):
                raise ValueError("跨境快讯文章格式不合法")
            rows.append(row)
    expected = data.get("query_total_count")
    if type(expected) is not int or expected < 0 or expected != len(rows):
        # 公开接口实测按显式起止时间返回该范围的全量文章。若日后出现分页
        # 或响应缺失，拒绝把不完整列表当成成功，不猜测新的分页协议。
        raise ValueError("跨境快讯返回条数与窗口总数不一致，不能确认完整覆盖")
    return rows


def _published_time(value: Any) -> datetime:
    if type(value) not in (int, float):
        raise ValueError("跨境快讯缺少逐篇原始发布时间")
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError("跨境快讯逐篇发布时间不合法") from error
