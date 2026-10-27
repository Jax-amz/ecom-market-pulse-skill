"""在派发模型任务前，只读排除已完成分析和主文未变的版本。"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from .agent_orchestrator import build_agent_task
from .database import Database
from .normalization import normalize_url


def _confirmed_old_media_publication(database: Database, article: dict[str, Any], window_start: datetime) -> bool:
    """只信当前文章有时区的原发元数据；本期更新、聚合提示或不明日期继续送审。"""
    fetch_id = article.get("fetch_id")
    if not fetch_id:
        return False
    fetch = database.get_fetch(fetch_id)
    if not fetch or not fetch.get("raw_body"):
        return False
    from bs4 import BeautifulSoup

    html = bytes(fetch["raw_body"]).decode(fetch.get("charset") or "utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            document = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        nodes = document if isinstance(document, list) else document.get("@graph", [document]) if isinstance(document, dict) else []
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kinds = node.get("@type", [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if not isinstance(kinds, list) or not any(k in {"Article", "NewsArticle", "BlogPosting"} for k in kinds if isinstance(k, str)):
                continue
            url = node.get("url") or node.get("@id")
            if not isinstance(url, str) or normalize_url(url, article["canonical_url"]) != normalize_url(article["canonical_url"]):
                continue
            try:
                published = datetime.fromisoformat(node["datePublished"].replace("Z", "+00:00"))
                modified_raw = node.get("dateModified")
                modified = datetime.fromisoformat(modified_raw.replace("Z", "+00:00")) if modified_raw is not None else published
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if published.tzinfo is None or modified.tzinfo is None:
                continue
            if published == article["published_at"] and published < window_start and modified < window_start:
                return True
    return False


def prepare_analysis_tasks(database: Database, run_id: str) -> dict[str, Any]:
    """只消费已结束的采集批次；保留新主文，不猜测聚合文章的原发时间。"""
    run = database.get_run(run_id)
    if run is None or run["run_type"] != "collect":
        raise ValueError("找不到指定采集批次")
    if run["status"] not in {"completed", "succeeded_with_warnings"}:
        raise ValueError("采集批次尚未结束，不能派发文章分析")
    articles = database._fetchall(
        """SELECT a.*, f.source_id, s.source_class
           FROM articles a JOIN fetches f ON f.fetch_id = a.fetch_id
           JOIN sources s ON s.source_id = f.source_id
           WHERE f.run_id = ? ORDER BY a.created_at, a.article_id""",
        [run_id],
    )
    completed = {
        row["article_id"]
        for row in database._fetchall(
            """SELECT DISTINCT n.article_id FROM analyses n
               JOIN articles a ON a.article_id = n.article_id
               JOIN fetches f ON f.fetch_id = a.fetch_id
               WHERE f.run_id = ? AND n.status = 'completed'""",
            [run_id],
        )
    }
    tasks: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for article in articles:
        prior = database.get_article_version_by_main_text(
            article["canonical_url"], article["extracted_text"], before=article["created_at"],
        )
        reason_code = reason = None
        if prior is not None:
            reason_code = "unchanged-main-text"
            reason = "该网址已有相同主文，推荐尾栏变化不构成新增资讯"
        elif article["article_id"] in completed:
            reason_code = "already-analyzed"
            reason = "该正文版本已完成分析，直接复用结果，不再调用模型"
        elif (
            article["published_at"] is not None
            and run["window_start"] is not None
            and article["published_at"] < run["window_start"]
            and (
                article["source_class"] == "official"
                or _confirmed_old_media_publication(database, article, run["window_start"])
            )
        ):
            reason_code = "before-discovery-window"
            reason = "已确认文章原发早于本次采集窗口"
        if reason is not None:
            excluded.append({
                "articleId": article["article_id"],
                "sourceUrl": article["canonical_url"],
                "reasonCode": reason_code,
                "reason": reason,
            })
        else:
            task = build_agent_task(article)
            task["sourceId"] = article["source_id"]
            task["sourceClass"] = article["source_class"]
            tasks.append(task)
    return {
        "runId": run_id,
        "stats": {"candidates": len(articles), "toAnalyze": len(tasks), "prefiltered": len(excluded)},
        "tasks": tasks,
        "excluded": excluded,
    }
