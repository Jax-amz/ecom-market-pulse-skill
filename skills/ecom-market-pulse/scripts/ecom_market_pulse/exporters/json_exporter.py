"""报告 JSON 的原子导出。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


def export_report_json(report: Mapping[str, Any], target: Path) -> Path:
    """使用临时文件和原子替换写出 UTF-8 JSON，返回绝对路径。"""

    target = target.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    _atomic_write(target, serialized)
    return target


def _atomic_write(target: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
