"""稳定 CLI 的参数解析与流水线调度。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from .config import ConfigurationError, load_config
from .database import Database
from .pipeline import collect


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pulse.py", description="跨境电商 AI 情报雷达")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate-config", "collect", "schema-check"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--workspace", required=True, type=Path, help="运行工作区；配置固定为其中的 config.yaml")
    subparsers.choices["collect"].add_argument("--since", default="24h", help="采集窗口，如 24h、7d 或 ISO 时间")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        result = _dispatch(args)
    except (ConfigurationError, ValueError, RuntimeError) as error:
        _print({"status": "failed", "error": _safe_message(error)})
        return 2
    _print(result)
    if isinstance(result, dict) and result.get("gateStatus") == "rejected":
        return 3
    return 0


def _dispatch(args: argparse.Namespace) -> dict[str, object]:
    workspace = args.workspace.expanduser().resolve()
    if args.command == "schema-check":
        with Database(workspace) as database:
            database.schema_check()
        return {"status": "ok", "workspace": str(workspace), "schema": "valid"}

    config = load_config(workspace / "config.yaml")
    if args.command == "validate-config":
        with Database(workspace) as database:
            database.schema_check()
        return {
            "status": "ok",
            "workspace": str(workspace),
            "timezone": config.timezone,
            "enabledSources": [source.id for source in config.sources if source.enabled],
        }
    if args.command == "collect":
        return collect(workspace=workspace, config=config, since=_parse_since(args.since, config.timezone)).as_dict()
    raise ValueError(f"不支持的命令：{args.command}")


def _parse_since(value: str, timezone: str) -> datetime:
    try:
        if value.endswith("h") and value[:-1].isdigit():
            return datetime.now(ZoneInfo(timezone)) - timedelta(hours=int(value[:-1]))
        if value.endswith("d") and value[:-1].isdigit():
            return datetime.now(ZoneInfo(timezone)) - timedelta(days=int(value[:-1]))
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo(timezone))
    except ValueError as error:
        raise ValueError("--since 必须是如 24h、7d 或 ISO 8601 时间") from error


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, default=str))


def _safe_message(error: BaseException) -> str:
    return (str(error).replace("\n", " ") or error.__class__.__name__)[:500]


__all__ = ["create_parser", "main"]
