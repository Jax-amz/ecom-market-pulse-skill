"""为 Codex 多子 agent 分析提供本地任务与合同校验。"""

from __future__ import annotations

from typing import Any, Mapping

from .analysis_contract import AgentArticleAnalysis


ARTICLE_ANALYSIS_INSTRUCTION = """仅依据文章正文输出一个 JSON 对象。不得编造事实。
字段必须符合 AgentArticleAnalysis：相关内容须有一个主分类、一至三个影响维度、
摘要、影响、建议和原文证据；无关内容仅填写 exclusionReason。"""


def build_agent_task(article: Mapping[str, Any]) -> dict[str, Any]:
    """输出可直接发给一个子 agent 的最小任务，不包含数据库或运行时配置。"""

    return {
        "articleId": article["article_id"],
        "instruction": ARTICLE_ANALYSIS_INSTRUCTION,
        "article": {
            "title": article["title"],
            "sourceUrl": article["canonical_url"],
            "publishedAt": article.get("published_at"),
            "language": article.get("language"),
            "text": article["extracted_text"],
        },
    }


def validate_agent_output(payload: Mapping[str, Any]) -> dict[str, Any]:
    """主 agent 在写库前执行的唯一合同校验。"""

    return AgentArticleAnalysis.model_validate(payload).model_dump(mode="json", by_alias=True)
