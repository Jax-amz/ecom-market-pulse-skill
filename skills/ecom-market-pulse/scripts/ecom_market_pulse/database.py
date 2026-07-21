"""DuckDB 持久化层。

数据库是本 Skill 的唯一事实源。此模块只接收基础 ``Mapping`` 和 JSON
兼容值，避免采集、子 Agent 分析和报告模块互相耦合。
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import duckdb


JsonValue = Any
Record = dict[str, Any]

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_JSON_COLUMNS = {
    "config_json",
    "checkpoint_json",
    "stats_json",
    "events_json",
    "request_headers_json",
    "response_headers_json",
    "suggestions_json",
    "evidence_json",
    "taxonomy_json",
    "request_json",
    "response_json",
    "analysis_json",
    "report_json",
    "gate_json",
}
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "id_token",
    "password",
    "secret",
    "cookie",
)
_ENVIRONMENT_KEYS = {"env", "environ", "environment", "environment_variables", "env_variables"}
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_SECRET_TOKEN_PATTERN = re.compile(r"\bsk-[a-zA-Z0-9_-]{8,}\b")


class DatabaseError(RuntimeError):
    """数据库记录不符合流水线约束时抛出。"""


class Database:
    """单进程 DuckDB 连接及六张业务表的读写接口。

    参数可以是工作区目录，也可以是以 ``.duckdb`` 结尾的数据库文件。工作区
    目录会固定使用 ``data/ecom_market_pulse.duckdb``，与技术设计的运行目录一致。
    调用方应为一个运行进程复用一个实例；每个写操作自行开启并提交短事务。
    """

    def __init__(self, workspace_or_database: str | Path, *, initialize: bool = True) -> None:
        self.database_path = self._resolve_database_path(workspace_or_database)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = duckdb.connect(str(self.database_path))
        self._transaction_active = False
        if initialize:
            self.initialize()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    @staticmethod
    def _resolve_database_path(workspace_or_database: str | Path) -> Path:
        candidate = Path(workspace_or_database).expanduser()
        if candidate.suffix == ".duckdb":
            return candidate
        return candidate / "data" / "ecom_market_pulse.duckdb"

    def close(self) -> None:
        """关闭连接；重复调用安全。"""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def initialize(self) -> None:
        """初始化或校验六张表，建表和注释 SQL 可重复执行。"""
        self._require_connection()
        if self._has_legacy_source_adapter_constraint():
            self._migrate_legacy_source_adapter_constraint()
        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        self._connection.execute(schema_sql)

    def _has_legacy_source_adapter_constraint(self) -> bool:
        """识别不支持 Amazon 专用采集适配器的历史 ``sources`` 表。"""
        tables = self._fetchall(
            "SELECT table_name FROM duckdb_tables() WHERE internal = FALSE AND schema_name = 'main'"
        )
        if "sources" not in {row["table_name"] for row in tables}:
            return False
        rows = self._fetchall(
            """
            SELECT constraint_text
            FROM duckdb_constraints()
            WHERE schema_name = 'main'
              AND table_name = 'sources'
              AND constraint_type = 'CHECK'
            """
        )
        return any(
            "adapter_type" in str(row["constraint_text"])
            and "amazon-global-selling-cn" not in str(row["constraint_text"])
            for row in rows
        )

    def _migrate_legacy_source_adapter_constraint(self) -> None:
        """无损重建包含旧 ``sources`` 约束的 DuckDB 文件。

        DuckDB 目前不支持删除 CHECK 约束。历史运行库会因此无法写入
        ``amazon-global-selling-cn`` 与 ``amazon-ads-whats-new``，所以在原文件
        所在目录新建符合当前 schema 的数据库，按外键依赖顺序复制六张表，
        校验行数后原子替换；替换前的库保留为同目录备份，便于人工回退。
        """
        self._require_connection()
        original_path = self.database_path
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        temporary_path = original_path.with_name(f"{original_path.stem}.migration-{uuid4().hex}.duckdb")
        backup_path = original_path.with_name(f"{original_path.stem}.pre-migration-{stamp}.duckdb")
        original_literal = str(original_path).replace("'", "''")
        table_names = ("sources", "runs", "fetches", "articles", "analyses", "reports")

        self._connection.close()
        self._connection = None
        try:
            migrated = duckdb.connect(str(temporary_path))
            try:
                migrated.execute(_SCHEMA_PATH.read_text(encoding="utf-8"))
                migrated.execute(f"ATTACH '{original_literal}' AS legacy (READ_ONLY)")
                for table_name in table_names:
                    migrated.execute(f"INSERT INTO {table_name} SELECT * FROM legacy.{table_name}")
                    expected_count = migrated.execute(f"SELECT count(*) FROM legacy.{table_name}").fetchone()[0]
                    actual_count = migrated.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]
                    if actual_count != expected_count:
                        raise DatabaseError(
                            f"历史数据库迁移校验失败：{table_name} 预期 {expected_count} 行，实际 {actual_count} 行"
                        )
                migrated.execute("DETACH legacy")
            finally:
                migrated.close()

            os.replace(original_path, backup_path)
            try:
                os.replace(temporary_path, original_path)
            except BaseException:
                os.replace(backup_path, original_path)
                raise
            self._connection = duckdb.connect(str(original_path))
        except BaseException:
            if temporary_path.exists():
                temporary_path.unlink()
            if self._connection is None and original_path.exists():
                self._connection = duckdb.connect(str(original_path))
            raise

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """显式短事务，异常时完整回滚，禁止嵌套事务。"""
        self._require_connection()
        if self._transaction_active:
            raise DatabaseError("不支持嵌套事务；请让一次持久化操作自行提交")

        self._transaction_active = True
        self._connection.execute("BEGIN TRANSACTION")
        try:
            yield
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")
        finally:
            self._transaction_active = False

    # ------------------------------------------------------------------
    # Schema 与运行记录
    # ------------------------------------------------------------------

    def missing_schema_comments(self) -> list[Record]:
        """返回缺失中文表/列注释的记录；正常初始化后应为空。"""
        self._require_connection()
        rows: list[Record] = []
        table_rows = self._fetchall(
            """
            SELECT table_name
            FROM duckdb_tables()
            WHERE internal = FALSE
              AND schema_name = 'main'
              AND table_name IN ('sources', 'runs', 'fetches', 'articles', 'analyses', 'reports')
              AND comment IS NULL
            ORDER BY table_name
            """
        )
        rows.extend({"object_type": "table", "table_name": row["table_name"], "column_name": None} for row in table_rows)
        column_rows = self._fetchall(
            """
            SELECT table_name, column_name
            FROM duckdb_columns()
            WHERE internal = FALSE
              AND schema_name = 'main'
              AND table_name IN ('sources', 'runs', 'fetches', 'articles', 'analyses', 'reports')
              AND comment IS NULL
            ORDER BY table_name, column_index
            """
        )
        rows.extend(
            {"object_type": "column", "table_name": row["table_name"], "column_name": row["column_name"]}
            for row in column_rows
        )
        return rows

    def schema_check(self) -> None:
        """在表缺失或任一业务表、字段没有注释时抛出异常。"""
        self._require_connection()
        existing = {
            row["table_name"]
            for row in self._fetchall(
                "SELECT table_name FROM duckdb_tables() WHERE internal = FALSE AND schema_name = 'main'"
            )
        }
        expected = {"sources", "runs", "fetches", "articles", "analyses", "reports"}
        missing_tables = sorted(expected - existing)
        comment_gaps = self.missing_schema_comments()
        if missing_tables or comment_gaps:
            raise DatabaseError(
                f"数据库结构校验失败：缺失表={missing_tables!r}，缺失注释={comment_gaps!r}"
            )

    def create_run(
        self,
        run_type: str,
        config: Mapping[str, JsonValue],
        *,
        run_id: str | None = None,
        window_start: datetime | str | None = None,
        window_end: datetime | str | None = None,
        status: str = "running",
        started_at: datetime | str | None = None,
    ) -> str:
        """创建运行清单并立即提交，返回运行标识。"""
        run_id = run_id or self._new_id("run")
        started_at = started_at or _utc_now()
        with self.transaction():
            existing = self._fetchone("SELECT run_id FROM runs WHERE run_id = ?", [run_id])
            if existing is not None:
                return str(existing["run_id"])
            self._connection.execute(
                """
                INSERT INTO runs (
                    run_id, run_type, window_start, window_end, status, config_json,
                    stats_json, events_json, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, CAST(? AS JSON), NULL, CAST(? AS JSON), ?, NULL)
                """,
                [
                    run_id,
                    run_type,
                    window_start,
                    window_end,
                    status,
                    _json_dumps(_redact(config)),
                    _json_dumps([]),
                    started_at,
                ],
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        stats: Mapping[str, JsonValue] | None = None,
        finished_at: datetime | str | None = None,
    ) -> None:
        """结束一次运行，保留之前已经记录的统计和事件。"""
        finished_at = finished_at or _utc_now()
        with self.transaction():
            self._assert_exists("runs", "run_id", run_id)
            if stats is None:
                self._connection.execute(
                    "UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ?",
                    [status, finished_at, run_id],
                )
            else:
                self._connection.execute(
                    "UPDATE runs SET status = ?, stats_json = CAST(? AS JSON), finished_at = ? WHERE run_id = ?",
                    [status, _json_dumps(_redact(stats)), finished_at, run_id],
                )

    def record_run_event(self, run_id: str, event: Mapping[str, JsonValue]) -> None:
        """安全追加一个结构化运行事件。

        事件统一补齐设计稿规定的最小字段，并在入库前剔除 API Key、
        Authorization、Cookie 以及完整环境变量，避免审计日志反向泄密。
        """
        normalized = {
            "stage": None,
            "source_id": None,
            "article_id": None,
            "level": "info",
            "event_type": "event",
            "duration_ms": None,
        }
        normalized.update(_redact(dict(event)))
        with self.transaction():
            row = self._fetchone("SELECT events_json FROM runs WHERE run_id = ?", [run_id])
            if row is None:
                raise DatabaseError(f"运行记录不存在：{run_id}")
            events = _json_loads(row["events_json"], default=[])
            if not isinstance(events, list):
                events = [events]
            events.append(normalized)
            self._connection.execute(
                "UPDATE runs SET events_json = CAST(? AS JSON) WHERE run_id = ?",
                [_json_dumps(events), run_id],
            )

    def get_run(self, run_id: str) -> Record | None:
        return self._fetchone("SELECT * FROM runs WHERE run_id = ?", [run_id])

    def list_resumable_runs(self) -> list[Record]:
        """查询尚未结束的运行，供进程重启后的断点恢复使用。"""
        return self._fetchall(
            "SELECT * FROM runs WHERE finished_at IS NULL AND status NOT IN ('completed', 'rejected') ORDER BY started_at"
        )

    # ------------------------------------------------------------------
    # 信源与采集
    # ------------------------------------------------------------------

    def upsert_source(self, source: Mapping[str, JsonValue]) -> str:
        """新增或更新信源配置，不覆盖未显式提交的采集断点。"""
        source_id = _required(source, "source_id")
        checkpoint_supplied = "checkpoint_json" in source
        with self.transaction():
            self._connection.execute(
                """
                INSERT INTO sources (
                    source_id, name, source_class, adapter_type, base_url, config_json,
                    checkpoint_json, enabled, last_success_at
                ) VALUES (?, ?, ?, ?, ?, CAST(? AS JSON), CAST(? AS JSON), ?, ?)
                ON CONFLICT (source_id) DO UPDATE SET
                    name = excluded.name,
                    source_class = excluded.source_class,
                    adapter_type = excluded.adapter_type,
                    base_url = excluded.base_url,
                    config_json = excluded.config_json,
                    checkpoint_json = CASE WHEN ? THEN excluded.checkpoint_json ELSE sources.checkpoint_json END,
                    enabled = excluded.enabled,
                    last_success_at = CASE
                        WHEN excluded.last_success_at IS NULL THEN sources.last_success_at
                        ELSE excluded.last_success_at
                    END,
                    updated_at = now()
                """,
                [
                    source_id,
                    _required(source, "name"),
                    _required(source, "source_class"),
                    _required(source, "adapter_type"),
                    _required(source, "base_url"),
                    _json_dumps(_redact(_required(source, "config_json"))),
                    _json_dumps(_redact(source.get("checkpoint_json"))) if checkpoint_supplied else None,
                    bool(source.get("enabled", True)),
                    source.get("last_success_at"),
                    checkpoint_supplied,
                ],
            )
        return str(source_id)

    def update_source_checkpoint(
        self,
        source_id: str,
        checkpoint: Mapping[str, JsonValue] | None,
        *,
        last_success_at: datetime | str | None = None,
    ) -> None:
        """原子写入增量断点；成功时间默认使用当前 UTC 时间。"""
        with self.transaction():
            self._assert_exists("sources", "source_id", source_id)
            self._connection.execute(
                """
                UPDATE sources
                SET checkpoint_json = CAST(? AS JSON), last_success_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE source_id = ?
                """,
                [
                    _json_dumps(_redact(checkpoint)) if checkpoint is not None else None,
                    last_success_at or _utc_now(),
                    source_id,
                ],
            )

    def get_source(self, source_id: str) -> Record | None:
        return self._fetchone("SELECT * FROM sources WHERE source_id = ?", [source_id])

    def list_enabled_sources(self) -> list[Record]:
        return self._fetchall("SELECT * FROM sources WHERE enabled = TRUE ORDER BY source_id")

    def record_fetch(self, fetch: Mapping[str, JsonValue]) -> str:
        """保存一次抓取；成功和失败都写入完整的抓取审计记录。"""
        fetch_id = str(fetch.get("fetch_id") or self._new_id("fetch"))
        with self.transaction():
            existing = self._fetchone("SELECT fetch_id FROM fetches WHERE fetch_id = ?", [fetch_id])
            if existing is not None:
                return str(existing["fetch_id"])
            self._connection.execute(
                """
                INSERT INTO fetches (
                    fetch_id, run_id, source_id, discovered_url, canonical_url_hint, title_hint,
                    published_at_hint, discovered_at, request_url, final_url, request_headers_json,
                    response_headers_json, http_status, content_type, charset, raw_body, raw_sha256,
                    duration_ms, status, error_message, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSON), CAST(? AS JSON), ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    fetch_id,
                    _required(fetch, "run_id"),
                    _required(fetch, "source_id"),
                    _required(fetch, "discovered_url"),
                    fetch.get("canonical_url_hint"),
                    fetch.get("title_hint"),
                    fetch.get("published_at_hint"),
                    _required(fetch, "discovered_at"),
                    _required(fetch, "request_url"),
                    fetch.get("final_url"),
                    _json_dumps(_redact(fetch.get("request_headers_json")))
                    if fetch.get("request_headers_json") is not None
                    else None,
                    _json_dumps(_redact(fetch.get("response_headers_json")))
                    if fetch.get("response_headers_json") is not None
                    else None,
                    fetch.get("http_status"),
                    fetch.get("content_type"),
                    fetch.get("charset"),
                    _as_bytes(fetch.get("raw_body")),
                    fetch.get("raw_sha256"),
                    fetch.get("duration_ms"),
                    _required(fetch, "status"),
                    fetch.get("error_message"),
                    fetch.get("fetched_at") or _utc_now(),
                ],
            )
        return fetch_id

    def get_fetch(self, fetch_id: str) -> Record | None:
        return self._fetchone("SELECT * FROM fetches WHERE fetch_id = ?", [fetch_id])

    def list_resumable_fetches(self) -> list[Record]:
        return self._fetchall(
            "SELECT * FROM fetches WHERE status IN ('pending', 'fetching', 'extracting') ORDER BY discovered_at"
        )

    # ------------------------------------------------------------------
    # 正文与分析
    # ------------------------------------------------------------------

    def record_article(self, article: Mapping[str, JsonValue]) -> str:
        """保存正文版本；相同 canonical URL 与正文哈希只保留一条记录。"""
        article_id = str(article.get("article_id") or self._new_id("article"))
        canonical_url = _required(article, "canonical_url")
        content_sha256 = _required(article, "content_sha256")
        with self.transaction():
            existing = self._fetchone(
                "SELECT article_id FROM articles WHERE canonical_url = ? AND content_sha256 = ?",
                [canonical_url, content_sha256],
            )
            if existing is not None:
                return str(existing["article_id"])
            self._connection.execute(
                """
                INSERT INTO articles (
                    article_id, fetch_id, canonical_url, title, original_title, author, published_at,
                    language, extracted_text, extracted_html, extractor_version, content_sha256,
                    event_key, is_representative
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    article_id,
                    _required(article, "fetch_id"),
                    canonical_url,
                    _required(article, "title"),
                    article.get("original_title"),
                    article.get("author"),
                    article.get("published_at"),
                    article.get("language"),
                    _required(article, "extracted_text"),
                    article.get("extracted_html"),
                    _required(article, "extractor_version"),
                    content_sha256,
                    article.get("event_key"),
                    bool(article.get("is_representative", True)),
                ],
            )
        return article_id

    def get_article(self, article_id: str) -> Record | None:
        return self._fetchone("SELECT * FROM articles WHERE article_id = ?", [article_id])

    def get_article_version(self, canonical_url: str, content_sha256: str) -> Record | None:
        return self._fetchone(
            "SELECT * FROM articles WHERE canonical_url = ? AND content_sha256 = ?",
            [canonical_url, content_sha256],
        )

    def list_articles_for_analysis(self, *, include_non_representative: bool = False) -> list[Record]:
        sql = "SELECT * FROM articles"
        if not include_non_representative:
            sql += " WHERE is_representative = TRUE"
        sql += " ORDER BY created_at"
        return self._fetchall(sql)

    def upsert_analysis(self, analysis: Mapping[str, JsonValue]) -> str:
        """写入一次子 Agent 解读；同文章、任务模板、执行器的重试覆盖同一分析记录。"""
        analysis_id = str(analysis.get("analysis_id") or self._new_id("analysis"))
        columns = (
            "analysis_id", "run_id", "article_id", "relevant", "exclusion_reason", "primary_category",
            "impact_dimensions", "title_zh", "summary", "affected_marketplaces", "affected_seller_types",
            "what_happened", "why_important", "effective_at", "deadline_at", "suggestions_json",
            "evidence_json", "taxonomy_version", "taxonomy_json", "prompt_version", "prompt_text",
            "output_schema_version", "model", "request_json", "response_json", "analysis_json",
            "input_tokens", "output_tokens", "duration_ms", "status", "error_message",
        )
        values = [
            analysis_id,
            _required(analysis, "run_id"),
            _required(analysis, "article_id"),
            _required(analysis, "relevant"),
            analysis.get("exclusion_reason"),
            analysis.get("primary_category"),
            _as_list(analysis.get("impact_dimensions")),
            analysis.get("title_zh"),
            analysis.get("summary"),
            _as_list(analysis.get("affected_marketplaces")),
            _as_list(analysis.get("affected_seller_types")),
            analysis.get("what_happened"),
            analysis.get("why_important"),
            analysis.get("effective_at"),
            analysis.get("deadline_at"),
            _json_dumps(analysis.get("suggestions_json")) if analysis.get("suggestions_json") is not None else None,
            _json_dumps(analysis.get("evidence_json")) if analysis.get("evidence_json") is not None else None,
            _required(analysis, "taxonomy_version"),
            _json_dumps(_required(analysis, "taxonomy_json")),
            _required(analysis, "prompt_version"),
            _required(analysis, "prompt_text"),
            _required(analysis, "output_schema_version"),
            _required(analysis, "model"),
            _json_dumps(_redact(_required(analysis, "request_json"))),
            _json_dumps(analysis.get("response_json")) if analysis.get("response_json") is not None else None,
            _json_dumps(analysis.get("analysis_json")) if analysis.get("analysis_json") is not None else None,
            analysis.get("input_tokens"),
            analysis.get("output_tokens"),
            analysis.get("duration_ms"),
            _required(analysis, "status"),
            analysis.get("error_message"),
        ]
        placeholders = ", ".join("CAST(? AS JSON)" if column in _JSON_COLUMNS else "?" for column in columns)
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns if column != "analysis_id")
        with self.transaction():
            existing = self.get_analysis(
                str(_required(analysis, "article_id")),
                str(_required(analysis, "prompt_version")),
                str(_required(analysis, "model")),
            )
            if existing is not None:
                analysis_id = str(existing["analysis_id"])
                values[0] = analysis_id
            self._connection.execute(
                f"""
                INSERT INTO analyses ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT (article_id, prompt_version, model) DO UPDATE SET {updates}
                """,
                values,
            )
        return analysis_id

    def get_analysis(self, article_id: str, prompt_version: str, model: str) -> Record | None:
        return self._fetchone(
            "SELECT * FROM analyses WHERE article_id = ? AND prompt_version = ? AND model = ?",
            [article_id, prompt_version, model],
        )

    def get_analysis_by_id(self, analysis_id: str) -> Record | None:
        return self._fetchone("SELECT * FROM analyses WHERE analysis_id = ?", [analysis_id])

    def list_resumable_analyses(self) -> list[Record]:
        return self._fetchall(
            """
            SELECT * FROM analyses
            WHERE status IN ('pending', 'analyzing', 'analysis_failed', 'analysis_refused')
            ORDER BY created_at
            """
        )

    def list_latest_relevant_analyses(
        self,
        period_start: datetime | str,
        period_end: datetime | str,
        *,
        prompt_version: str | None = None,
        model: str | None = None,
    ) -> list[Record]:
        """返回窗口内可生成报告的最新成功分析及其文章和信源。

        报告一次只消费同一文章分析 Prompt/模型组合，避免 ``reanalyze`` 后旧
        Prompt 与新 Prompt 同时进入报告而造成重复 articleId 或版本漂移。
        """
        filters = [
            "analyses.relevant = TRUE",
            "analyses.status = 'completed'",
            "articles.is_representative = TRUE",
            "articles.created_at >= ?",
            "articles.created_at < ?",
        ]
        parameters: list[Any] = [period_start, period_end]
        if prompt_version is not None:
            filters.append("analyses.prompt_version = ?")
            parameters.append(prompt_version)
        if model is not None:
            filters.append("analyses.model = ?")
            parameters.append(model)
        return self._fetchall(
            f"""
            SELECT * EXCLUDE (analysis_rank)
            FROM (
                SELECT analyses.*, articles.canonical_url, articles.published_at, articles.event_key,
                       articles.is_representative, fetches.source_id AS source_id,
                       sources.name AS source_name, sources.source_class,
                       ROW_NUMBER() OVER (
                           PARTITION BY analyses.article_id
                           ORDER BY analyses.created_at DESC, analyses.analysis_id DESC
                       ) AS analysis_rank
                FROM analyses
                JOIN articles ON articles.article_id = analyses.article_id
                JOIN fetches ON fetches.fetch_id = articles.fetch_id
                JOIN sources ON sources.source_id = fetches.source_id
                WHERE {' AND '.join(filters)}
            )
            WHERE analysis_rank = 1
            ORDER BY published_at DESC NULLS LAST, created_at DESC
            """,
            parameters,
        )

    def report_stage_counts(self, period_start: datetime | str, period_end: datetime | str) -> Record:
        """返回报告窗口内各确定性阶段的真实计数。

        日报统计不从子 Agent 输出或导出结果反推：发现、抓取、独立事件和分析数量全部
        从 DuckDB 的事实记录聚合得出，调用方仅补充最终纳入报告的数量。
        """
        row = self._fetchone(
            """
            SELECT
                (SELECT COUNT(*) FROM fetches WHERE discovered_at >= ? AND discovered_at < ?) AS discovered,
                (SELECT COUNT(*) FROM fetches WHERE fetched_at >= ? AND fetched_at < ? AND status = 'fetched') AS fetched,
                (
                    SELECT COUNT(DISTINCT COALESCE(event_key, article_id))
                    FROM articles
                    WHERE created_at >= ? AND created_at < ?
                ) AS unique_events,
                (
                    SELECT COUNT(DISTINCT analyses.article_id)
                    FROM analyses
                    JOIN articles ON articles.article_id = analyses.article_id
                    WHERE analyses.status = 'completed'
                      AND articles.created_at >= ? AND articles.created_at < ?
                ) AS analyzed
            """,
            [
                period_start,
                period_end,
                period_start,
                period_end,
                period_start,
                period_end,
                period_start,
                period_end,
            ],
        )
        return row or {"discovered": 0, "fetched": 0, "unique_events": 0, "analyzed": 0}

    # ------------------------------------------------------------------
    # 报告与关门验证
    # ------------------------------------------------------------------

    def create_report_draft(
        self,
        report: Mapping[str, JsonValue],
        *,
        replace_existing_draft: bool = False,
    ) -> str:
        """保存完整报告草稿，草稿阶段不允许保存 Markdown 导出文本。

        同周期、同修订号的记录默认直接复用；仅当它仍是草稿且调用方显式
        ``replace_existing_draft`` 时更新草稿。已完成或被拒绝的修订不可被覆盖。
        """
        report_id = str(report.get("report_id") or self._new_id("report"))
        report_type = str(_required(report, "report_type"))
        business_date = _required(report, "business_date")
        revision = int(report.get("revision", 1))
        with self.transaction():
            existing = self._fetchone(
                "SELECT * FROM reports WHERE report_type = ? AND business_date = ? AND revision = ?",
                [report_type, business_date, revision],
            )
            if existing is not None:
                if not replace_existing_draft:
                    return str(existing["report_id"])
                if existing["status"] != "draft" or existing["gate_status"] != "pending":
                    raise DatabaseError("只能覆盖尚未关门验证的报告草稿")
                report_id = str(existing["report_id"])
                self._connection.execute(
                    """
                    UPDATE reports
                    SET run_id = ?, period_start = ?, period_end = ?, title = ?, summary = ?, article_ids = ?,
                        report_json = CAST(? AS JSON), markdown_text = NULL, gate_status = 'pending',
                        gate_json = NULL, content_sha256 = ?, generated_at = CURRENT_TIMESTAMP, status = 'draft'
                    WHERE report_id = ?
                    """,
                    self._report_draft_values(report) + [report_id],
                )
                return report_id

            self._connection.execute(
                """
                INSERT INTO reports (
                    report_id, run_id, report_type, business_date, period_start, period_end, revision,
                    status, title, summary, article_ids, report_json, markdown_text, gate_status,
                    gate_json, content_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, CAST(? AS JSON), NULL, 'pending', NULL, ?)
                """,
                [report_id, _required(report, "run_id"), report_type, business_date, _required(report, "period_start"),
                 _required(report, "period_end"), revision] + self._report_draft_values(report, include_run=False),
            )
        return report_id

    def _report_draft_values(self, report: Mapping[str, JsonValue], *, include_run: bool = True) -> list[Any]:
        values: list[Any] = []
        if include_run:
            values.extend(
                [
                    _required(report, "run_id"),
                    _required(report, "period_start"),
                    _required(report, "period_end"),
                ]
            )
        values.extend(
            [
                report.get("title"),
                report.get("summary"),
                _as_list(report.get("article_ids")),
                _json_dumps(_required(report, "report_json")),
                _required(report, "content_sha256"),
            ]
        )
        return values

    def finalize_report(
        self,
        report_id: str,
        *,
        gate_status: str,
        gate_json: Mapping[str, JsonValue] | JsonValue,
        report_json: Mapping[str, JsonValue] | JsonValue,
        content_sha256: str,
        markdown_text: str | None = None,
    ) -> None:
        """记录关门验证结果；只有 ``passed`` 才能保存 Markdown 导出文本。

        超时、拒绝和非法响应等所有非通过状态都归一为 ``rejected``。该分支强制
        清空 ``markdown_text``，从持久层保证拒绝报告绝不保存导出内容。
        """
        accepted = gate_status == "passed"
        if accepted and markdown_text is None:
            raise DatabaseError("关门验证通过后必须同时写入完整 Markdown 报告")
        normalized_gate_status = "passed" if accepted else "rejected"
        report_status = "completed" if accepted else "rejected"
        with self.transaction():
            current = self._fetchone("SELECT * FROM reports WHERE report_id = ?", [report_id])
            if current is None:
                raise DatabaseError(f"报告不存在：{report_id}")
            if current["status"] != "draft" or current["gate_status"] != "pending":
                raise DatabaseError(f"报告已关门验证，必须重建新草稿后再验证：{report_id}")
            self._connection.execute(
                """
                UPDATE reports
                SET status = ?, gate_status = ?, gate_json = CAST(? AS JSON), report_json = CAST(? AS JSON),
                    content_sha256 = ?, markdown_text = ?
                WHERE report_id = ?
                """,
                [
                    report_status,
                    normalized_gate_status,
                    _json_dumps(_redact(gate_json)),
                    _json_dumps(report_json),
                    content_sha256,
                    markdown_text if accepted else None,
                    report_id,
                ],
            )

    def get_report(self, report_id: str) -> Record | None:
        return self._fetchone("SELECT * FROM reports WHERE report_id = ?", [report_id])

    def get_report_revision(self, report_type: str, business_date: date | str, revision: int = 1) -> Record | None:
        return self._fetchone(
            "SELECT * FROM reports WHERE report_type = ? AND business_date = ? AND revision = ?",
            [report_type, business_date, revision],
        )

    def find_reusable_report(
        self,
        report_type: str,
        business_date: date | str,
        *,
        build_versions: Mapping[str, JsonValue] | None = None,
    ) -> Record | None:
        """查询可复用的同周期草稿或已完成报告。

        ``build_versions`` 可传入 ``promptVersion``、``gatePromptVersion`` 和
        ``reportPromptVersion``；只要已存报告 JSON 中的 ``build`` 不匹配，就不会
        被复用。被拒绝报告按设计必须重建，因此不返回。
        """
        candidates = self._fetchall(
            """
            SELECT * FROM reports
            WHERE report_type = ? AND business_date = ? AND status IN ('draft', 'completed')
            ORDER BY revision DESC
            """,
            [report_type, business_date],
        )
        for candidate in candidates:
            if _build_versions_match(candidate.get("report_json"), build_versions):
                return candidate
        return None

    def next_report_revision(self, report_type: str, business_date: date | str) -> int:
        row = self._fetchone(
            "SELECT COALESCE(MAX(revision), 0) AS max_revision FROM reports WHERE report_type = ? AND business_date = ?",
            [report_type, business_date],
        )
        return int(row["max_revision"]) + 1 if row is not None else 1

    def list_resumable_reports(self) -> list[Record]:
        return self._fetchall(
            "SELECT * FROM reports WHERE status = 'draft' AND gate_status = 'pending' ORDER BY generated_at"
        )

    # ------------------------------------------------------------------
    # 内部 SQL 与转换
    # ------------------------------------------------------------------

    def _assert_exists(self, table_name: str, key_name: str, key_value: str) -> None:
        row = self._fetchone(f"SELECT 1 AS exists_flag FROM {table_name} WHERE {key_name} = ?", [key_value])
        if row is None:
            raise DatabaseError(f"{table_name} 中不存在 {key_name}={key_value!r}")

    def _fetchone(self, sql: str, parameters: Sequence[Any] | None = None) -> Record | None:
        cursor, timezone_columns = self._execute_query(sql, parameters)
        row = cursor.fetchone()
        return _row_to_record(cursor, row, timezone_columns) if row is not None else None

    def _fetchall(self, sql: str, parameters: Sequence[Any] | None = None) -> list[Record]:
        cursor, timezone_columns = self._execute_query(sql, parameters)
        return [_row_to_record(cursor, row, timezone_columns) for row in cursor.fetchall()]

    def _execute_query(
        self,
        sql: str,
        parameters: Sequence[Any] | None,
    ) -> tuple[duckdb.DuckDBPyConnection, set[str]]:
        """执行查询，并兼容最小化 Python 环境中缺少 pytz 的 DuckDB。"""
        query_parameters = parameters or []
        cursor = self._connection.execute(sql, query_parameters)
        timezone_columns = {
            column[0]
            for column in cursor.description
            if str(column[1]).upper() == "TIMESTAMP WITH TIME ZONE"
        }
        if not timezone_columns:
            return cursor, timezone_columns

        projections = []
        for name, column_type, *_ in cursor.description:
            quoted_name = _quote_identifier(name)
            if name in timezone_columns:
                projections.append(f"CAST(result.{quoted_name} AS VARCHAR) AS {quoted_name}")
            else:
                projections.append(f"result.{quoted_name}")
        rewritten_sql = f"SELECT {', '.join(projections)} FROM ({sql}) AS result"
        cursor = self._connection.execute(rewritten_sql, query_parameters)
        return cursor, timezone_columns

    def _require_connection(self) -> None:
        if self._connection is None:
            raise DatabaseError("数据库连接已关闭")

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"


def _required(record: Mapping[str, JsonValue], field: str) -> JsonValue:
    value = record.get(field)
    if value is None:
        raise DatabaseError(f"缺少必填字段：{field}")
    return value


def _as_list(value: JsonValue) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise DatabaseError("数组字段必须是字符串序列")
    return [str(item) for item in value]


def _as_bytes(value: JsonValue) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    raise DatabaseError("raw_body 必须为 bytes、bytearray 或 memoryview")


def _json_dumps(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default, separators=(",", ":"))


def _json_default(value: JsonValue) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _json_loads(value: JsonValue, *, default: JsonValue) -> JsonValue:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def _row_to_record(
    cursor: duckdb.DuckDBPyConnection,
    row: Sequence[Any],
    timezone_columns: set[str] | None = None,
) -> Record:
    record = dict(zip((column[0] for column in cursor.description), row, strict=True))
    for column in timezone_columns or set():
        value = record.get(column)
        if isinstance(value, str):
            try:
                record[column] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
    for column in _JSON_COLUMNS:
        if column in record:
            record[column] = _json_loads(record[column], default=None)
    raw_body = record.get("raw_body")
    if isinstance(raw_body, memoryview):
        record["raw_body"] = raw_body.tobytes()
    return record


def _redact(value: JsonValue) -> JsonValue:
    """递归脱敏可持久化配置、请求头和运行事件。"""
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.lower().replace("-", "_").replace(" ", "_")
            if normalized in _ENVIRONMENT_KEYS or any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                result[key] = "[REDACTED]"
            else:
                result[key] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
        return _SECRET_TOKEN_PATTERN.sub("[REDACTED]", redacted)
    return value


def _build_versions_match(report_json: JsonValue, expected: Mapping[str, JsonValue] | None) -> bool:
    if not expected:
        return True
    if not isinstance(report_json, Mapping):
        return False
    build = report_json.get("build")
    if not isinstance(build, Mapping):
        return False
    return all(build.get(key) == value for key, value in expected.items())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
