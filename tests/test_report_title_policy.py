from __future__ import annotations

import json

import pytest

from ecom_market_pulse.exporters.report_exporter import export_passed_report
from ecom_market_pulse.reports.builder import apply_gate_result
from ecom_market_pulse.reports.title_policy import (
    report_editorial_title_issues,
    validate_report_editorial_title,
)


VALID_TITLE = "AI素材与锂电合规升温，东南亚平台费用生变"


def _daily_report(title: str, *, source_class: str = "professional-media") -> dict[str, object]:
    return {
        "reportId": "daily-2026-07-24",
        "reportType": "daily",
        "date": "2026-07-24",
        "lead": {"title": title, "summary": "摘要"},
        "sections": [
            {
                "items": [
                    {
                        "title": "AMZ123报道亚马逊调整AI人像素材标记要求",
                        "source": {"sourceClass": source_class},
                    },
                    {
                        "title": "AMZ123报道亚马逊北美锂电池小家电合规要求收紧",
                        "source": {"sourceClass": source_class},
                    },
                    {
                        "title": "AMZ123报道TikTok Shop东南亚调整平台费用规则",
                        "source": {"sourceClass": source_class},
                    },
                ]
            }
        ],
        "gate": {"status": "pending"},
        "build": {"gatePromptVersion": "report-gate-v1"},
    }


def test_accepts_grounded_editorial_title() -> None:
    validate_report_editorial_title(_daily_report(VALID_TITLE))


@pytest.mark.parametrize(
    "title",
    [
        "跨境电商资讯日报",
        "物流履约、平台竞争与合规风险需优先复核",
        "平台政策、物流与合规变化的经营影响汇总",
    ],
)
def test_rejects_placeholder_and_officialese_titles(title: str) -> None:
    assert report_editorial_title_issues(_daily_report(title))


def test_rejects_title_unrelated_to_selected_articles() -> None:
    issues = report_editorial_title_issues(_daily_report("欧洲仓储火灾扩大，拉美家电旺季提前启动"))
    assert any("回溯" in issue for issue in issues)


def test_rejects_strong_claim_without_official_source() -> None:
    issues = report_editorial_title_issues(_daily_report("亚马逊正式宣布AI素材新规全面生效"))
    assert any("非官方信源" in issue for issue in issues)


def test_rejects_recently_repeated_title() -> None:
    issues = report_editorial_title_issues(
        _daily_report(VALID_TITLE),
        recent_titles=["AI素材与锂电合规升温，东南亚平台费用再变"],
    )
    assert any("近期归档" in issue for issue in issues)


def test_passed_gate_cannot_bypass_title_policy() -> None:
    with pytest.raises(ValueError, match="日报标题未通过编辑规范"):
        apply_gate_result(
            _daily_report("跨境电商资讯日报"),
            {"reportId": "daily-2026-07-24", "status": "passed", "issues": []},
        )


def test_export_rechecks_recent_manifest_titles(tmp_path) -> None:
    manifest_path = tmp_path / "exports" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "reports": {
                    "daily": [
                        {
                            "date": "2026-07-23",
                            "title": "AI素材与锂电合规升温，东南亚平台费用再变",
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = _daily_report(VALID_TITLE)
    report["gate"] = {"status": "passed"}
    with pytest.raises(ValueError, match="近期归档"):
        export_passed_report(report, tmp_path)
