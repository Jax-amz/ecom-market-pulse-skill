"""子 agent 分析结果的本地合同。"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from .models import ContractModel, Evidence, ImpactDimension, PrimaryCategory


class AgentArticleAnalysis(ContractModel):
    relevant: bool
    exclusion_reason: str | None = Field(..., alias="exclusionReason")
    primary_category: PrimaryCategory | None = Field(..., alias="primaryCategory")
    impact_dimensions: list[ImpactDimension] = Field(..., alias="impactDimensions", max_length=3)
    title: str | None = Field(..., min_length=1)
    summary: str | None = Field(..., min_length=1)
    affected_marketplaces: list[str] = Field(..., alias="affectedMarketplaces")
    affected_seller_types: list[str] = Field(..., alias="affectedSellerTypes")
    what_happened: str | None = Field(..., alias="whatHappened", min_length=1)
    why_important: str | None = Field(..., alias="whyImportant", min_length=1)
    effective_at: datetime | None = Field(..., alias="effectiveAt")
    deadline_at: datetime | None = Field(..., alias="deadlineAt")
    suggestions: list[str] = Field(..., max_length=3)
    evidence: list[Evidence] = Field(...)

    @field_validator("suggestions")
    @classmethod
    def validate_suggestions(cls, suggestions: list[str]) -> list[str]:
        if any(not 15 <= len(item) <= 60 for item in suggestions):
            raise ValueError("每条 suggestions 必须为 15 至 60 个字符")
        return suggestions

    @model_validator(mode="after")
    def validate_relevant_fields(self) -> "AgentArticleAnalysis":
        if not self.relevant:
            if not self.exclusion_reason or self.primary_category is not None or self.impact_dimensions:
                raise ValueError("无关文章必须仅填写 exclusionReason")
            return self
        if self.exclusion_reason is not None or self.primary_category is None or not 1 <= len(self.impact_dimensions) <= 3:
            raise ValueError("相关文章必须有一个主分类和一至三个影响维度")
        if not all((self.title, self.summary, self.what_happened, self.why_important, self.evidence)):
            raise ValueError("相关文章必须填写标题、摘要、事实、影响和证据")
        return self
