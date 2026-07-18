"""从已通过验证的报告 JSON 渲染可读 Markdown。"""

from __future__ import annotations

from typing import Any, Mapping


def render_markdown(report: Mapping[str, Any]) -> str:
    """按报告固定栏目生成 Markdown；不生成新的业务结论。"""

    lead = report.get("lead") or {}
    lines = [f"# {lead.get('title') or '跨境电商情报报告'} - {report.get('date', '')}", ""]
    if lead.get("summary"):
        lines.extend([str(lead["summary"]), ""])
    lines.extend(["## 统计", ""])
    stats = report.get("stats") or {}
    lines.append(" | ".join(f"{key}: {value}" for key, value in stats.items()))
    lines.append("")
    for section in report.get("sections") or []:
        lines.extend([f"## {section.get('label')}", ""])
        items = section.get("items") or []
        if not items:
            lines.extend(["暂无入选资讯。", ""])
            continue
        for item in items:
            lines.extend(_render_item(item))
    key_dates = report.get("keyDates") or []
    if key_dates:
        lines.extend(["## 关键日期", ""])
        for key_date in key_dates:
            lines.append(f"- {key_date.get('date')}（{key_date.get('dateType')}）：{key_date.get('event')}")
        lines.append("")
    gate = report.get("gate") or {}
    lines.extend(["## 最终关门验证", "", f"状态：{gate.get('status', 'pending')}"])
    for issue in gate.get("issues") or []:
        lines.append(f"- {issue}")
    lines.append("")
    return "\n".join(lines)


def _render_item(item: Mapping[str, Any]) -> list[str]:
    lines = [f"### {item.get('title') or '未命名资讯'}", ""]
    source = item.get("source") or {}
    details = []
    if source.get("name"):
        details.append(f"来源：{source['name']}（{source.get('sourceClass', 'unknown')}）")
    if item.get("publishedAt"):
        details.append(f"发布时间：{item['publishedAt']}")
    if item.get("sourceUrl"):
        details.append(f"原文：{item['sourceUrl']}")
    if details:
        lines.extend(["  ".join(details), ""])
    for label, key in (("摘要", "summary"), ("发生了什么", "whatHappened"), ("为什么重要", "whyImportant")):
        if item.get(key):
            lines.append(f"- {label}：{item[key]}")
    if item.get("impactDimensions"):
        lines.append(f"- 影响维度：{'、'.join(item['impactDimensions'])}")
    dates = []
    if item.get("effectiveAt"):
        dates.append(f"生效：{item['effectiveAt']}")
    if item.get("deadlineAt"):
        dates.append(f"截止：{item['deadlineAt']}")
    if dates:
        lines.append(f"- 关键日期：{'；'.join(dates)}")
    for suggestion in item.get("suggestions") or []:
        lines.append(f"- 建议关注：{suggestion}")
    lines.append("")
    return lines
