"""仅负责公开文章采集的本地流水线。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .collectors import create_adapter
from .config import PulseConfig, redacted_snapshot
from .database import Database
from .deduplication import build_event_key
from .extraction import extract_article
from .normalization import content_sha256, raw_sha256


@dataclass
class RunSummary:
    run_id: str
    run_type: str
    stats: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    exported_files: dict[str, str] = field(default_factory=dict)
    gate_status: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"runId": self.run_id, "runType": self.run_type, "stats": self.stats, "warnings": self.warnings, "exportedFiles": self.exported_files, "gateStatus": self.gate_status}


def collect(*, workspace: Path, config: PulseConfig, since: datetime) -> RunSummary:
    """发现、抓取、正文提取和精确去重；不调用任何模型 API。"""

    with Database(workspace.expanduser().resolve()) as database:
        run_id = database.create_run("collect", redacted_snapshot(config), window_start=since, window_end=datetime.now(ZoneInfo("UTC")))
        summary = RunSummary(run_id, "collect", {"discovered": 0, "fetched": 0, "fetchFailed": 0, "extracted": 0, "duplicates": 0, "extractFailed": 0})
        try:
            for source in config.sources:
                if not source.enabled:
                    continue
                database.upsert_source({"source_id": source.id, "name": source.name, "source_class": source.source_class.value, "adapter_type": source.discovery.type.value, "base_url": source.discovery.url, "config_json": redacted_snapshot(source), "enabled": source.enabled})
                try:
                    items = create_adapter(source.discovery.type.value).discover(source, since)
                except Exception as error:
                    summary.warnings.append(f"{source.id}: 发现失败：{_safe_message(error)}")
                    continue
                summary.stats["discovered"] += len(items)
                adapter = create_adapter(source.discovery.type.value)
                for item in items:
                    raw = adapter.fetch(source, item)
                    fetch_id = database.record_fetch(_fetch_record(run_id, raw))
                    if not raw.succeeded:
                        summary.stats["fetchFailed"] += 1
                        continue
                    summary.stats["fetched"] += 1
                    extracted = extract_article(raw, source)
                    if not extracted.succeeded or not extracted.canonical_url or not extracted.title:
                        summary.stats["extractFailed"] += 1
                        continue
                    text_hash = content_sha256(extracted.extracted_text)
                    if database.get_article_version(extracted.canonical_url, text_hash):
                        summary.stats["duplicates"] += 1
                        continue
                    database.record_article({"fetch_id": fetch_id, "canonical_url": extracted.canonical_url, "title": extracted.title, "original_title": extracted.original_title, "author": extracted.author, "published_at": extracted.published_at, "language": extracted.language, "extracted_text": extracted.extracted_text, "extracted_html": extracted.extracted_html, "extractor_version": extracted.extractor_version, "content_sha256": text_hash, "event_key": build_event_key(extracted.title, extracted.published_at), "is_representative": True})
                    summary.stats["extracted"] += 1
                database.update_source_checkpoint(source.id, {"lastCollectedAt": datetime.now(ZoneInfo("UTC")).isoformat(), "since": since.isoformat()})
            database.finish_run(run_id, "succeeded_with_warnings" if summary.warnings else "completed", stats=summary.stats)
        except BaseException:
            database.finish_run(run_id, "failed", stats=summary.stats)
            raise
    return summary


def _fetch_record(run_id: str, raw: Any) -> dict[str, Any]:
    return {"run_id": run_id, "source_id": raw.source_id, "discovered_url": raw.item.url, "canonical_url_hint": raw.item.canonical_url_hint, "title_hint": raw.item.title_hint, "published_at_hint": raw.item.published_at_hint, "discovered_at": raw.item.discovered_at, "request_url": raw.request_url, "final_url": raw.final_url, "request_headers_json": {}, "response_headers_json": dict(raw.headers), "http_status": raw.status_code, "content_type": raw.content_type, "charset": raw.charset, "raw_body": raw.body, "raw_sha256": raw_sha256(raw.body), "duration_ms": raw.duration_ms, "status": "fetched" if raw.succeeded else raw.error_code or "fetch_failed", "error_message": raw.error_message, "fetched_at": raw.fetched_at}


def _safe_message(error: BaseException) -> str:
    return (str(error).replace("\n", " ") or error.__class__.__name__)[:500]
