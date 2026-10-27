from __future__ import annotations

from datetime import datetime, timedelta
from contextlib import nullcontext
import json
from unittest.mock import Mock

import httpx
import pytest

from ecom_market_pulse.collectors import create_adapter
from ecom_market_pulse.collectors.amz123_flash import FLASH_LIST_ENDPOINT, Amz123FlashNewsAdapter
from ecom_market_pulse.config import PulseConfig
from ecom_market_pulse.database import Database


NOW = datetime.fromisoformat("2026-10-15T10:00:00+08:00")
SINCE = NOW - timedelta(hours=24)
SOURCE = {
    "id": "amz123-kx", "name": "AMZ123 跨境快讯", "enabled": True,
    "source_class": "professional-media", "homepage_url": "https://www.amz123.com/kx",
    "discovery": {"type": "amz123-kx", "url": "https://www.amz123.com/kx", "max_items": 500},
    "category_hints": ["amazon-policy", "competitor-marketplaces"],
    "fetch": {"interval_minutes": 240, "requests_per_minute": 4, "timeout_seconds": 20, "max_retries": 2},
    "content": {"language": "zh", "timezone": "Asia/Shanghai"},
}


def news(identifier: str, published: datetime = NOW) -> dict:
    return {"id": identifier, "title": "平台新增操作入口", "url": "", "published_at": published.timestamp(), "is_morning_news": 0}


def payload(*groups: list[dict], count: int | None = None) -> dict:
    return {"status": 0, "data": {
        "row_map": {str(index): {"kx_content": rows, "zb_content": {"title": "不应当作文章"}} for index, rows in enumerate(groups)},
        "query_total_count": sum(map(len, groups)) if count is None else count,
        "next_data": 1,
    }}


def adapter(result: dict) -> tuple[Amz123FlashNewsAdapter, Mock]:
    post = Mock(return_value=result)
    return Amz123FlashNewsAdapter(post_json=post, wall_clock=lambda: NOW), post


def test_window_uses_article_epoch_across_groups_and_ignores_early_and_future_rows() -> None:
    source, post = adapter(payload(
        [news("old", SINCE - timedelta(seconds=1)), news("inside", SINCE + timedelta(hours=1))],
        [news("future", NOW + timedelta(seconds=1)), news("boundary", SINCE), news("latest", NOW)],
    ))
    items = source.discover(SOURCE, SINCE)
    assert [item.url.rsplit("/", 1)[-1] for item in items] == ["latest", "inside", "boundary"]
    assert [item.published_at_hint.isoformat() for item in items] == [
        "2026-10-15T02:00:00+00:00", "2026-10-14T03:00:00+00:00", "2026-10-14T02:00:00+00:00",
    ]
    endpoint, request, timeout = post.call_args.args
    assert endpoint == FLASH_LIST_ENDPOINT and timeout == 20
    assert request["start_time"] == int(SINCE.timestamp())
    assert request["end_time"] == int(NOW.timestamp())
    assert request["is_query_zb"] == 0 and request["is_query_total_count"] == 1


def test_duplicate_urls_are_shared_with_morning_news_without_batch_date_or_sidebar_links() -> None:
    row = news("E8CtNFsh", NOW - timedelta(hours=1))
    source, _ = adapter(payload([row], [row]))
    items = source.discover(SOURCE, SINCE)
    assert len(items) == 1
    assert items[0].url == items[0].canonical_url_hint == "https://www.amz123.com/kx/E8CtNFsh"
    assert items[0].source_id == "amz123-kx"
    assert items[0].published_at_hint == NOW - timedelta(hours=1)


def test_incomplete_response_cannot_be_reported_as_successful_coverage() -> None:
    source, _ = adapter(payload([news("one")], count=2))
    with pytest.raises(ValueError, match="完整覆盖"):
        source.discover(SOURCE, SINCE)


def test_max_items_cannot_silently_truncate_the_discovery_window() -> None:
    source, _ = adapter(payload([news("one"), news("two")]))
    settings = {**SOURCE, "discovery": {**SOURCE["discovery"], "max_items": 1}}
    with pytest.raises(ValueError, match="禁止静默截断"):
        source.discover(settings, SINCE)


@pytest.mark.parametrize("change", [{"published_at": None}, {"published_at": True}, {"id": "../external"}, {"title": " "}])
def test_invalid_in_window_metadata_fails_instead_of_inventing_dates_or_urls(change: dict) -> None:
    source, _ = adapter(payload([{**news("one"), **change}]))
    with pytest.raises(ValueError):
        source.discover(SOURCE, SINCE)


@pytest.mark.parametrize("result", [{"status": 401, "data": {}}, {"status": 0, "data": {}}, {"status": 0, "data": {"row_map": {}, "query_total_count": 3}}])
def test_api_errors_and_shape_changes_do_not_become_empty_success(result: dict) -> None:
    source, _ = adapter(result)
    with pytest.raises(ValueError):
        source.discover(SOURCE, SINCE)


def test_legitimate_empty_window_and_morning_batch_entries() -> None:
    source, _ = adapter(payload([]))
    assert source.discover(SOURCE, SINCE) == []
    source, _ = adapter(payload([{**news("morning"), "is_morning_news": 1}]))
    assert source.discover(SOURCE, SINCE) == []


def test_access_protection_stops_without_retries() -> None:
    post = Mock(side_effect=httpx.HTTPStatusError("Forbidden", request=httpx.Request("POST", FLASH_LIST_ENDPOINT), response=httpx.Response(403)))
    source = Amz123FlashNewsAdapter(post_json=post, wall_clock=lambda: NOW)
    with pytest.raises(httpx.HTTPStatusError):
        source.discover(SOURCE, SINCE)
    assert post.call_count == 1


def test_adapter_registration_and_config_contract() -> None:
    config = PulseConfig.model_validate({"timezone": "Asia/Shanghai", "sources": [SOURCE]})
    assert config.sources[0].discovery.type.value == "amz123-kx"
    assert isinstance(create_adapter("amz123-kx"), Amz123FlashNewsAdapter)


def test_details_use_existing_protected_public_fetcher() -> None:
    fetcher = Mock()
    source, _ = adapter(payload([news("one")]))
    item = source.discover(SOURCE, SINCE)[0]
    source = Amz123FlashNewsAdapter(fetcher=fetcher)
    assert source.fetch(SOURCE, item) is fetcher.get.return_value
    fetcher.get.assert_called_once_with(SOURCE, item)


def test_new_web_adapter_satisfies_legacy_storage_constraint_and_keeps_exact_config() -> None:
    # 模拟实际旧库的 CHECK；不建立数据库，不执行建表或写 SQL。
    database = object.__new__(Database)
    database.transaction = lambda: nullcontext()
    legacy_types = {"rss", "html", "sitemap", "amz123-zb", "amazon-global-selling-cn", "amazon-ads-whats-new"}

    def constrained_execute(sql: str, values: list) -> None:
        assert values[3] in legacy_types
        assert json.loads(values[5])["discovery"]["type"] == "amz123-kx"

    database._connection = Mock()
    database._connection.execute.side_effect = constrained_execute
    assert database.upsert_source({
        "source_id": SOURCE["id"], "name": SOURCE["name"], "source_class": SOURCE["source_class"],
        "adapter_type": "amz123-kx", "base_url": SOURCE["discovery"]["url"], "config_json": SOURCE,
    }) == "amz123-kx"
    assert database._connection.execute.call_count == 1
