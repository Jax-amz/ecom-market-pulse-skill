from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ecom_market_pulse import cli, extraction, pipeline
from ecom_market_pulse.analysis_preparation import prepare_analysis_tasks
from ecom_market_pulse.collectors.base import DiscoveredItem, RawArticle
from ecom_market_pulse.config import PulseConfig
from ecom_market_pulse.database import Database
from ecom_market_pulse.normalization import content_sha256, normalize_article_main_text, normalize_text


NOW = datetime.fromisoformat("2026-10-14T10:00:00+08:00")
URL = "https://www.amz123.com/kx/example"
MARKER = "AMZ123跨境卖家导航旗下公众号"
MAIN_TEXT = "平台发布新的入仓安排，卖家可以在后台核对自己的货件。"


def _version(text: str, *, article_id: str = "old", created_at: datetime = NOW - timedelta(days=1)) -> dict:
    return {
        "article_id": article_id, "canonical_url": URL, "extracted_text": text,
        "content_sha256": content_sha256(text), "created_at": created_at,
    }


def _lookup(versions: list[dict]) -> Database:
    # 只模拟 SELECT 的返回值，不建立数据库或执行建表/写入 SQL。
    database = object.__new__(Database)
    database.get_article_version = lambda url, sha: next(  # type: ignore[method-assign]
        (v for v in versions if v["canonical_url"] == url and v["content_sha256"] == sha), None,
    )

    def select(sql: str, params: list) -> list[dict]:
        assert sql.lstrip().startswith("SELECT")
        return [v for v in versions if v["canonical_url"] == params[0] and (len(params) == 1 or v["created_at"] < params[1])]

    database._fetchall = select  # type: ignore[method-assign]
    return database


def test_sidebar_changes_match_legacy_full_text_hash() -> None:
    old = _version(MAIN_TEXT + MARKER + "旧推荐资料")
    database = _lookup([old])

    assert database.get_article_version_by_main_text(URL, MAIN_TEXT + MARKER + "新推荐资料") == old


def test_changed_main_text_is_not_discarded() -> None:
    database = _lookup([_version(MAIN_TEXT + MARKER + "推荐资料")])

    assert database.get_article_version_by_main_text(URL, "平台公布了不同的入仓日期。" + MARKER + "推荐资料") is None


def test_history_lookup_does_not_match_the_current_version_itself() -> None:
    current = _version(MAIN_TEXT, article_id="current", created_at=NOW)
    database = _lookup([current])

    assert database.get_article_version_by_main_text(URL, MAIN_TEXT, before=NOW) is None


@pytest.mark.parametrize("url", ["https://example.com/article", "https://www.amz123.com.example.com/article"])
def test_other_sites_keep_text_containing_the_marker(url: str) -> None:
    text = MAIN_TEXT + MARKER + "这仍是正文的一部分"

    assert normalize_article_main_text(text, url) == normalize_text(text)


@pytest.mark.parametrize("changed", [False, True])
def test_collection_keeps_fetch_audit_and_only_stores_changed_main_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changed: bool) -> None:
    current_main = "平台公布了不同的入仓日期。" if changed else MAIN_TEXT
    raw = RawArticle(
        source_id="amz123-zb",
        item=DiscoveredItem("amz123-zb", URL, NOW, title_hint="入仓安排", published_at_hint=NOW),
        request_url=URL, final_url=URL, status_code=200, headers={},
        body=b"<html><head><title>article</title></head><body>article</body></html>",
        fetched_at=NOW, duration_ms=1,
    )
    adapter = MagicMock()
    adapter.discover.return_value = [raw.item]
    adapter.fetch.return_value = raw
    monkeypatch.setattr(pipeline, "create_adapter", lambda _: adapter)
    monkeypatch.setattr(extraction, "_extract_with_trafilatura", lambda _: (None, current_main + MARKER + "变化的推荐", "test-extractor"))
    lookup = _lookup([_version(MAIN_TEXT + MARKER + "历史推荐")])
    database = MagicMock(spec=Database)
    database.__enter__.return_value = database
    database.create_run.return_value = "run-test"
    database.record_fetch.return_value = "fetch-test"
    database.get_article_version_by_main_text.side_effect = lookup.get_article_version_by_main_text
    factory = MagicMock(return_value=database)
    monkeypatch.setattr(pipeline, "Database", factory)
    config = PulseConfig.model_validate({
        "timezone": "Asia/Shanghai",
        "sources": [{
            "id": "amz123-zb", "name": "AMZ123", "enabled": True,
            "source_class": "professional-media", "homepage_url": "https://www.amz123.com/zb",
            "discovery": {"type": "amz123-zb", "url": "https://www.amz123.com/zb", "max_items": 100},
            "category_hints": ["amazon-fba-fulfillment"],
            "fetch": {"interval_minutes": 60, "requests_per_minute": 10, "timeout_seconds": 20, "max_retries": 1},
            "content": {"language": "zh", "timezone": "Asia/Shanghai"},
        }],
    })

    summary = pipeline.collect(workspace=tmp_path, config=config, since=NOW - timedelta(hours=24), initialize_database=False)

    factory.assert_called_once_with(tmp_path.resolve(), initialize=False)
    database.record_fetch.assert_called_once()
    assert summary.stats["discovered"] == summary.stats["fetched"] == 1
    assert summary.stats["duplicates"] == int(not changed)
    assert summary.stats["extracted"] == int(changed)
    if changed:
        saved = database.record_article.call_args.args[0]
        assert saved["extracted_text"] == current_main
        assert saved["content_sha256"] == content_sha256(current_main)
    else:
        database.record_article.assert_not_called()


def _candidate(article_id: str, *, source_class: str = "professional-media", published_at: datetime = NOW) -> dict:
    return {
        "article_id": article_id, "canonical_url": URL, "title": "入仓安排",
        "extracted_text": MAIN_TEXT + MARKER + "推荐资料", "created_at": NOW,
        "source_id": "amz123-zb", "source_class": source_class,
        "published_at": published_at, "language": "zh",
    }


def test_prefilter_skips_known_duplicates_and_completed_results_but_keeps_new_content() -> None:
    database = MagicMock(spec=Database)
    database.get_run.return_value = {"run_type": "collect", "status": "completed", "window_start": NOW - timedelta(hours=24)}
    database._fetchall.side_effect = [
        [_candidate("duplicate"), _candidate("completed"), _candidate("new"), _candidate("old-official", source_class="official", published_at=NOW - timedelta(days=3))],
        [{"article_id": "completed"}],
    ]
    database.get_article_version_by_main_text.side_effect = [_version(MAIN_TEXT), None, None, None]

    bundle = prepare_analysis_tasks(database, "run-test")

    assert bundle["stats"] == {"candidates": 4, "toAnalyze": 1, "prefiltered": 3}
    assert [task["articleId"] for task in bundle["tasks"]] == ["new"]
    assert bundle["tasks"][0]["article"]["text"] == normalize_text(MAIN_TEXT)
    assert {item["reasonCode"] for item in bundle["excluded"]} == {"unchanged-main-text", "already-analyzed", "before-discovery-window"}


def test_running_collection_is_not_prepared_for_analysis() -> None:
    database = MagicMock(spec=Database)
    database.get_run.return_value = {"run_type": "collect", "status": "running"}

    with pytest.raises(ValueError, match="尚未结束"):
        prepare_analysis_tasks(database, "run-test")
    database._fetchall.assert_not_called()


@pytest.mark.parametrize("variant,excluded", [
    ("confirmed-original", True),
    ("discovery-hint-only", False),
    ("different-article", False),
    ("timezone-unknown", False),
    ("updated-in-window", False),
])
def test_media_old_news_requires_current_original_metadata_and_keeps_new_updates(variant: str, excluded: bool) -> None:
    old = NOW - timedelta(days=3)
    article = {**_candidate("media-old", published_at=old), "fetch_id": "fetch-old"}
    node = {"@type": "NewsArticle", "url": URL, "datePublished": old.isoformat()}
    if variant == "discovery-hint-only":
        del node["datePublished"]
    elif variant == "different-article":
        node["url"] = "https://www.amz123.com/kx/another"
    elif variant == "timezone-unknown":
        node["datePublished"] = old.replace(tzinfo=None).isoformat()
    elif variant == "updated-in-window":
        node["dateModified"] = NOW.isoformat()
    html = '<script type="application/ld+json">' + json.dumps(node) + '</script>'
    database = MagicMock(spec=Database)
    database.get_run.return_value = {"run_type": "collect", "status": "completed", "window_start": NOW - timedelta(hours=24)}
    database._fetchall.side_effect = [[article], []]
    database.get_article_version_by_main_text.return_value = None
    database.get_fetch.return_value = {"raw_body": html.encode(), "charset": "utf-8"}

    bundle = prepare_analysis_tasks(database, "run-test")

    assert bundle["stats"] == {"candidates": 1, "toAnalyze": int(not excluded), "prefiltered": int(excluded)}
    if excluded:
        assert bundle["excluded"][0]["reasonCode"] == "before-discovery-window"


def test_default_daily_collection_uses_24_hours_even_on_monday(monkeypatch: pytest.MonkeyPatch) -> None:
    monday = datetime.fromisoformat("2026-10-19T10:00:00+08:00")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return monday.astimezone(tz)

    monkeypatch.setattr(cli, "datetime", Clock)
    args = cli.create_parser().parse_args(["collect", "--workspace", "runtime", "--no-initialize"])

    assert args.since == "24h"
    assert cli._parse_since(args.since, "Asia/Shanghai") == monday - timedelta(hours=24)


def test_cli_collection_can_reuse_schema_without_initialization(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = MagicMock(timezone="Asia/Shanghai")
    monkeypatch.setattr(cli, "load_config", lambda _: config)
    collect = MagicMock()
    collect.return_value.as_dict.return_value = {"runId": "run-test"}
    monkeypatch.setattr(cli, "collect", collect)
    args = cli.create_parser().parse_args(["collect", "--workspace", str(tmp_path), "--since", "24h", "--no-initialize"])

    assert cli._dispatch(args) == {"runId": "run-test"}
    assert collect.call_args.kwargs["initialize_database"] is False


def test_jsonld_original_publication_keeps_explicit_utc_offset() -> None:
    html = '''<script type="application/ld+json">{
        "@type":"NewsArticle", "url":"https://www.amz123.com/kx/example",
        "datePublished":"2026-10-13T07:02:14+00:00",
        "dateModified":"2026-10-14T00:18:17+00:00"
    }</script><time>2026-10-13 07:02</time>'''

    metadata = extraction._extract_metadata(html, URL, "Asia/Shanghai")

    assert metadata.published_at == datetime.fromisoformat("2026-10-13T15:02:14+08:00")


def test_jsonld_date_for_another_article_is_ignored() -> None:
    html = '''<script type="application/ld+json">{
        "@type":"NewsArticle", "url":"https://www.amz123.com/kx/other",
        "datePublished":"2026-10-14T07:02:14+00:00"
    }</script>'''

    assert extraction._extract_metadata(html, URL, "Asia/Shanghai").published_at is None


def test_jsonld_modified_date_does_not_become_original_publication() -> None:
    html = '''<script type="application/ld+json">{"@type":"NewsArticle",
        "url":"https://www.amz123.com/kx/example",
        "dateModified":"2026-10-14T00:18:17+00:00"
    }</script>'''

    assert extraction._extract_metadata(html, URL, "Asia/Shanghai").published_at is None


def test_about_amazon_relative_time_label_does_not_create_new_main_text() -> None:
    url = "https://www.aboutamazon.com/news/community/example"

    assert normalize_article_main_text("6 hours ago " + MAIN_TEXT, url) == normalize_article_main_text("9 hours ago " + MAIN_TEXT, url)


def test_relative_time_in_other_sites_or_article_body_is_preserved() -> None:
    text = "9 hours ago " + MAIN_TEXT

    assert normalize_article_main_text(text, "https://example.com/news") == normalize_text(text)
    assert normalize_article_main_text("Amazon responded 9 hours ago.", "https://www.aboutamazon.com/news") == "Amazon responded 9 hours ago."
