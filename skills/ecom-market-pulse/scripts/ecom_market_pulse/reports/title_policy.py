"""日报编辑标题的生成边界与确定性校验。"""

from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any, Iterable, Mapping


DAILY_TITLE_MIN_LENGTH = 18
DAILY_TITLE_MAX_LENGTH = 24
DAILY_TITLE_MAX_SEPARATORS = 1
DAILY_TITLE_RECENT_SIMILARITY = 0.72

BANNED_DAILY_TITLE_FRAGMENTS = (
    "跨境电商资讯日报",
    "跨境电商日报",
    "需优先复核",
    "需优先核验",
    "经营影响汇总",
    "经营信号",
    "出现新变化",
    "成为今日焦点",
)
STRONG_ASSERTION_FRAGMENTS = (
    "正式宣布",
    "正式发布",
    "正式实施",
    "确认实施",
    "全面生效",
)
GENERIC_TITLE_UNITS = frozenset(
    {
        "平台",
        "电商",
        "跨境",
        "市场",
        "卖家",
        "政策",
        "规则",
        "费用",
        "物流",
        "履约",
        "合规",
        "风险",
        "变化",
        "变动",
        "调整",
        "服务",
        "经营",
        "影响",
        "资讯",
        "日报",
        "今日",
    }
)
TITLE_SEPARATORS = "，,:：;；"
TITLE_END_PUNCTUATION = "。！？!?；;，,"


def validate_report_editorial_title(
    report: Mapping[str, Any], *, recent_titles: Iterable[str] = ()
) -> None:
    """拒绝无法作为归档标题的日报；周报和月报暂不应用此规则。"""

    issues = report_editorial_title_issues(report, recent_titles=recent_titles)
    if issues:
        raise ValueError(f"日报标题未通过编辑规范：{'；'.join(issues)}")


def report_editorial_title_issues(
    report: Mapping[str, Any], *, recent_titles: Iterable[str] = ()
) -> list[str]:
    """返回日报标题问题列表，供关门 Agent 和导出器复用。"""

    if str(report.get("reportType") or "") != "daily":
        return []
    lead = report.get("lead")
    title = str(lead.get("title") or "").strip() if isinstance(lead, Mapping) else ""
    issues: list[str] = []
    if not title:
        return ["标题不能为空"]
    if not DAILY_TITLE_MIN_LENGTH <= len(title) <= DAILY_TITLE_MAX_LENGTH:
        issues.append(f"标题长度必须为 {DAILY_TITLE_MIN_LENGTH} 至 {DAILY_TITLE_MAX_LENGTH} 个字符（含标点）")
    if sum(title.count(separator) for separator in TITLE_SEPARATORS) > DAILY_TITLE_MAX_SEPARATORS:
        issues.append("标题最多使用一个分隔符，只表达一个主事件和一个次事件")
    if title.endswith(tuple(TITLE_END_PUNCTUATION)):
        issues.append("标题末尾不得使用标点")
    banned = next((fragment for fragment in BANNED_DAILY_TITLE_FRAGMENTS if fragment in title), None)
    if banned:
        issues.append(f"标题不得使用占位式或公文式表达：{banned}")

    items = _report_items(report)
    if not items:
        issues.append("日报没有纳入事件，无法生成编辑标题")
    elif not _is_grounded_in_items(title, items):
        issues.append("标题必须包含至少一个可回溯到入选事件的具体对象或变化")
    if items and not _has_official_source(items) and any(fragment in title for fragment in STRONG_ASSERTION_FRAGMENTS):
        issues.append("仅有非官方信源时不得在标题中使用确定性官方措辞")

    normalized = _normalize_title(title)
    for recent_title in recent_titles:
        recent_normalized = _normalize_title(recent_title)
        if not recent_normalized:
            continue
        if SequenceMatcher(None, normalized, recent_normalized).ratio() >= DAILY_TITLE_RECENT_SIMILARITY:
            issues.append("标题与近期归档标题过于相似，必须更换事件切入点或句式")
            break
    return issues


def _report_items(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sections = report.get("sections")
    if not isinstance(sections, Iterable) or isinstance(sections, (str, bytes, Mapping)):
        return []
    items: list[Mapping[str, Any]] = []
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        section_items = section.get("items")
        if not isinstance(section_items, Iterable) or isinstance(section_items, (str, bytes, Mapping)):
            continue
        items.extend(item for item in section_items if isinstance(item, Mapping))
    return items


def _is_grounded_in_items(title: str, items: Iterable[Mapping[str, Any]]) -> bool:
    title_units = _title_units(title)
    item_units: set[str] = set()
    for item in items:
        item_units.update(_title_units(str(item.get("title") or "")))
    overlap = title_units & item_units
    meaningful_overlap = overlap - GENERIC_TITLE_UNITS
    return len(overlap) >= 2 and bool(meaningful_overlap)


def _title_units(value: str) -> set[str]:
    units = {token.lower() for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]{1,}", value)}
    for sequence in re.findall(r"[\u4e00-\u9fff]+", value):
        for width in (2, 3, 4):
            units.update(sequence[index : index + width] for index in range(len(sequence) - width + 1))
    return units


def _has_official_source(items: Iterable[Mapping[str, Any]]) -> bool:
    for item in items:
        source = item.get("source")
        if isinstance(source, Mapping) and source.get("sourceClass") == "official":
            return True
    return False


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())
