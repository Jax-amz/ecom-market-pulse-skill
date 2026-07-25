"""报告 JSON 和 Markdown 的受控导出。"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

from ..models import validate_report
from ..reports.title_policy import validate_report_editorial_title
from .json_exporter import _atomic_write, export_report_json
from .markdown import render_markdown


def export_passed_report(report: Mapping[str, Any], workspace: Path, *, include_markdown: bool = False) -> dict[str, Path]:
    """仅在 gate=passed 时导出 JSON 主交付物，Markdown 仅按需生成。"""

    if (report.get("gate") or {}).get("status") != "passed":
        raise ValueError("未通过最终关门验证的报告不得导出")
    report_type = str(report.get("reportType") or "")
    business_date = str(report.get("date") or "")
    if report_type not in {"daily", "weekly", "monthly"} or not business_date:
        raise ValueError("报告缺少合法 reportType 或 date")
    if report_type == "weekly":
        # 导出是最后一道确定性边界；即使报告不是由内置 builder 生成，也不能绕过工作周合同。
        validate_report(report)
    workspace = workspace.expanduser().resolve()
    validate_report_editorial_title(
        report,
        recent_titles=_recent_daily_titles(workspace, business_date) if report_type == "daily" else (),
    )
    output_dir = workspace / "exports" / report_type
    artifact_name = _artifact_name(report_type, business_date, report)
    report_json = export_report_json(report, output_dir / f"{artifact_name}.json")
    latest_json = export_report_json(report, output_dir / "latest.json")
    exported = {"json": report_json, "latest_json": latest_json}
    if include_markdown:
        markdown_path = output_dir / f"{artifact_name}.md"
        _atomic_write(markdown_path, render_markdown(report))
        exported["markdown"] = markdown_path.resolve()
    return exported


def _recent_daily_titles(workspace: Path, business_date: str) -> list[str]:
    manifest_path = workspace / "exports" / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest["reports"]["daily"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("现有 manifest 无法读取，禁止绕过近期标题查重") from error
    if not isinstance(entries, list):
        raise ValueError("现有 manifest.reports.daily 必须为数组")
    return [
        str(entry["title"])
        for entry in entries
        if isinstance(entry, Mapping)
        and entry.get("date") != business_date
        and isinstance(entry.get("title"), str)
    ][:7]


def _artifact_name(report_type: str, business_date: str, report: Mapping[str, Any]) -> str:
    """按交付周期输出稳定文件名，而不是依赖任意报告生成日。"""

    if report_type == "daily":
        _require_match(business_date, r"\d{4}-\d{2}-\d{2}", "日报 date")
        return business_date
    if report_type == "weekly":
        period = report.get("period")
        iso_week = period.get("isoWeek") if isinstance(period, Mapping) else None
        if not isinstance(iso_week, str):
            raise ValueError("周报缺少 period.isoWeek")
        _require_match(iso_week, r"\d{4}-W\d{2}", "周报 period.isoWeek")
        return iso_week
    _require_match(business_date, r"\d{4}-\d{2}-\d{2}", "月报 date")
    return business_date[:7]


def _require_match(value: str, pattern: str, field: str) -> None:
    if re.fullmatch(pattern, value) is None:
        raise ValueError(f"{field} 格式不合法：{value}")
