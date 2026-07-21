"""跨境电商情报 Skill 的稳定业务合同。

Pydantic 模型是文章与报告 JSON Schema 的唯一事实来源。数据库记录、子 Agent
输出和导出器都应通过本模块校验，避免在各层重复维护枚举或字段定义。
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, Literal, Mapping, TypeAlias
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


ARTICLE_SCHEMA_VERSION = "1.0.0"
REPORT_SCHEMA_VERSION = "1.1.0"
# 保留既有文章合同调用方对 SCHEMA_VERSION 的兼容；报告合同单独按版本演进。
SCHEMA_VERSION = ARTICLE_SCHEMA_VERSION
TAXONOMY_VERSION = "1.0.0"


class PrimaryCategory(StrEnum):
    """卖家需要作出的主要经营决策分类，枚举值不得随意扩展。"""

    AMAZON_POLICY = "amazon-policy"
    AMAZON_FBA_FULFILLMENT = "amazon-fba-fulfillment"
    FEE_MARGIN_TAX = "fee-margin-tax"
    ADS_TRAFFIC = "ads-traffic"
    LISTING_SEO_VOC = "listing-seo-voc"
    ACCOUNT_COMPLIANCE_IP = "account-compliance-ip"
    CROSSBORDER_LOGISTICS = "crossborder-logistics"
    COMPETITOR_MARKETPLACES = "competitor-marketplaces"
    AI_OPS_TOOLS = "ai-ops-tools"
    SELLER_COMMUNITY_SIGNAL = "seller-community-signal"


class ImpactDimension(StrEnum):
    """资讯对卖家经营的影响面，相关文章必须选择一至三个。"""

    MONEY = "money"
    GOODS = "goods"
    ACCOUNT = "account"
    TRAFFIC = "traffic"
    EFFICIENCY = "efficiency"
    COMPETITION = "competition"


PRIMARY_CATEGORY_ORDER: tuple[PrimaryCategory, ...] = (
    PrimaryCategory.AMAZON_POLICY,
    PrimaryCategory.AMAZON_FBA_FULFILLMENT,
    PrimaryCategory.FEE_MARGIN_TAX,
    PrimaryCategory.ADS_TRAFFIC,
    PrimaryCategory.LISTING_SEO_VOC,
    PrimaryCategory.ACCOUNT_COMPLIANCE_IP,
    PrimaryCategory.CROSSBORDER_LOGISTICS,
    PrimaryCategory.COMPETITOR_MARKETPLACES,
    PrimaryCategory.AI_OPS_TOOLS,
    PrimaryCategory.SELLER_COMMUNITY_SIGNAL,
)

IMPACT_DIMENSION_ORDER: tuple[ImpactDimension, ...] = (
    ImpactDimension.MONEY,
    ImpactDimension.GOODS,
    ImpactDimension.ACCOUNT,
    ImpactDimension.TRAFFIC,
    ImpactDimension.EFFICIENCY,
    ImpactDimension.COMPETITION,
)

CATEGORY_LABELS: Mapping[PrimaryCategory, str] = MappingProxyType(
    {
        PrimaryCategory.AMAZON_POLICY: "Amazon 官方政策与卖家公告",
        PrimaryCategory.AMAZON_FBA_FULFILLMENT: "FBA、仓储、配送与退货",
        PrimaryCategory.FEE_MARGIN_TAX: "平台费用、利润、税务与关税",
        PrimaryCategory.ADS_TRAFFIC: "广告与流量",
        PrimaryCategory.LISTING_SEO_VOC: "Listing、SEO、评论与 VOC",
        PrimaryCategory.ACCOUNT_COMPLIANCE_IP: "账号健康、合规与知识产权",
        PrimaryCategory.CROSSBORDER_LOGISTICS: "跨境物流、供应链与海关",
        PrimaryCategory.COMPETITOR_MARKETPLACES: "竞品平台动态",
        PrimaryCategory.AI_OPS_TOOLS: "AI 工具与运营自动化",
        PrimaryCategory.SELLER_COMMUNITY_SIGNAL: "卖家社区与异常信号",
    }
)

IMPACT_DIMENSION_LABELS: Mapping[ImpactDimension, str] = MappingProxyType(
    {
        ImpactDimension.MONEY: "钱",
        ImpactDimension.GOODS: "货",
        ImpactDimension.ACCOUNT: "号",
        ImpactDimension.TRAFFIC: "流量",
        ImpactDimension.EFFICIENCY: "效率",
        ImpactDimension.COMPETITION: "竞争",
    }
)


class SourceClass(StrEnum):
    OFFICIAL = "official"
    PROFESSIONAL_MEDIA = "professional-media"
    COMMUNITY = "community"
    AGGREGATOR = "aggregator"


class SourceType(StrEnum):
    RSS = "rss"
    HTML = "html"
    SITEMAP = "sitemap"
    AMZ123_ZB = "amz123-zb"
    AMAZON_GLOBAL_SELLING_CN = "amazon-global-selling-cn"
    AMAZON_ADS_WHATS_NEW = "amazon-ads-whats-new"


class ReportType(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class GateStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    REJECTED = "rejected"


class KeyDateType(StrEnum):
    EFFECTIVE = "effective"
    DEADLINE = "deadline"


class ContractModel(BaseModel):
    """所有对外 JSON 合同共享的严格序列化规则。"""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class SourceReference(ContractModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    source_class: SourceClass = Field(..., alias="sourceClass")
    source_type: SourceType = Field(..., alias="sourceType")


class CorroboratingSource(ContractModel):
    source: SourceReference
    source_url: str = Field(..., alias="sourceUrl", min_length=1)


class Evidence(ContractModel):
    fact: str = Field(..., min_length=1)
    source_url: str = Field(..., alias="sourceUrl", min_length=1)
    location: str = Field(..., min_length=1)


class Conflict(ContractModel):
    """同事件不同来源的冲突，不把未经解决的冲突伪装成事实。"""

    description: str = Field(..., min_length=1)
    source_urls: list[str] = Field(..., alias="sourceUrls", min_length=2)


class ArticleAnalysis(ContractModel):
    what_happened: str = Field(..., alias="whatHappened", min_length=1)
    why_important: str = Field(..., alias="whyImportant", min_length=1)
    suggestions: list[str] = Field(..., min_length=0, max_length=3)
    effective_at: datetime | None = Field(..., alias="effectiveAt")
    deadline_at: datetime | None = Field(..., alias="deadlineAt")

    @field_validator("suggestions")
    @classmethod
    def validate_suggestion_length(cls, suggestions: list[str]) -> list[str]:
        return _validate_suggestion_length(suggestions)


class AgentProvenance(ContractModel):
    executor: str = Field(..., min_length=1)
    task_version: str = Field(..., alias="taskVersion", min_length=1)
    analyzed_at: datetime = Field(..., alias="analyzedAt")


class Article(ContractModel):
    """单篇文章的权威业务 JSON 合同。"""

    schema_version: Literal[ARTICLE_SCHEMA_VERSION] = Field(..., alias="schemaVersion")
    id: str = Field(..., min_length=1)
    cluster_id: str = Field(..., alias="clusterId", min_length=1)
    title: str = Field(..., min_length=1)
    original_title: str | None = Field(..., alias="originalTitle")
    summary: str = Field(..., min_length=1)
    source_url: str = Field(..., alias="sourceUrl", min_length=1)
    canonical_url: str = Field(..., alias="canonicalUrl", min_length=1)
    permalink: str | None = Field(...)
    source: SourceReference
    published_at: datetime | None = Field(..., alias="publishedAt")
    collected_at: datetime = Field(..., alias="collectedAt")
    language: str = Field(..., min_length=2, max_length=35)
    relevant: bool
    exclusion_reason: str | None = Field(..., alias="exclusionReason")
    primary_category: PrimaryCategory | None = Field(..., alias="primaryCategory")
    impact_dimensions: list[ImpactDimension] = Field(..., alias="impactDimensions", max_length=3)
    affected_marketplaces: list[str] = Field(..., alias="affectedMarketplaces")
    affected_seller_types: list[str] = Field(..., alias="affectedSellerTypes")
    analysis: ArticleAnalysis
    evidence: list[Evidence] = Field(...)
    corroborating_sources: list[CorroboratingSource] = Field(..., alias="corroboratingSources")
    conflicts: list[Conflict] = Field(...)
    agent: AgentProvenance
    content_hash: str = Field(
        ...,
        alias="contentHash",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_relevance_contract(self) -> Article:
        if self.relevant:
            if self.exclusion_reason is not None:
                raise ValueError("相关文章不得填写 exclusionReason")
            if self.primary_category is None:
                raise ValueError("相关文章必须填写 primaryCategory")
            if not 1 <= len(self.impact_dimensions) <= 3:
                raise ValueError("相关文章必须有一至三个 impactDimensions")
            if len(self.impact_dimensions) != len(set(self.impact_dimensions)):
                raise ValueError("impactDimensions 不能重复")
            if not self.evidence:
                raise ValueError("相关文章至少需要一条 evidence")
            if (self.analysis.effective_at or self.analysis.deadline_at) and not self.evidence:
                raise ValueError("关键日期必须有 evidence 支撑")
            return self

        if not self.exclusion_reason:
            raise ValueError("无关文章必须填写 exclusionReason")
        if self.primary_category is not None:
            raise ValueError("无关文章不得填写 primaryCategory")
        if self.impact_dimensions:
            raise ValueError("无关文章不得填写 impactDimensions")
        return self


class ReportSource(ContractModel):
    name: str = Field(..., min_length=1)
    source_class: SourceClass = Field(..., alias="sourceClass")


class SourceDirectoryEntry(ContractModel):
    """报告期内所有已启用信源的可展示目录项。"""

    id: str = Field(..., min_length=1, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(..., min_length=1)
    source_class: SourceClass = Field(..., alias="sourceClass")
    homepage_url: str = Field(..., alias="homepageUrl", min_length=1)
    article_count: int = Field(..., alias="articleCount", ge=0)

    @field_validator("homepage_url")
    @classmethod
    def validate_homepage_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("homepageUrl 必须是完整的 http 或 https URL")
        return value


class ReportItem(ContractModel):
    article_id: str = Field(..., alias="articleId", min_length=1)
    cluster_id: str = Field(..., alias="clusterId", min_length=1)
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    source: ReportSource
    source_url: str = Field(..., alias="sourceUrl", min_length=1)
    published_at: datetime | None = Field(..., alias="publishedAt")
    primary_category: PrimaryCategory = Field(..., alias="primaryCategory")
    impact_dimensions: list[ImpactDimension] = Field(..., alias="impactDimensions", min_length=1, max_length=3)
    what_happened: str = Field(..., alias="whatHappened", min_length=1)
    why_important: str = Field(..., alias="whyImportant", min_length=1)
    affected_marketplaces: list[str] = Field(..., alias="affectedMarketplaces")
    affected_seller_types: list[str] = Field(..., alias="affectedSellerTypes")
    effective_at: datetime | None = Field(..., alias="effectiveAt")
    deadline_at: datetime | None = Field(..., alias="deadlineAt")
    suggestions: list[str] = Field(..., min_length=0, max_length=3)

    @field_validator("suggestions")
    @classmethod
    def validate_suggestion_length(cls, suggestions: list[str]) -> list[str]:
        return _validate_suggestion_length(suggestions)

    @field_validator("impact_dimensions")
    @classmethod
    def validate_unique_impact_dimensions(cls, values: list[ImpactDimension]) -> list[ImpactDimension]:
        if len(values) != len(set(values)):
            raise ValueError("impactDimensions 不能重复")
        return values


def _validate_suggestion_length(suggestions: list[str]) -> list[str]:
    for suggestion in suggestions:
        if not 15 <= len(suggestion) <= 60:
            raise ValueError("每条 suggestions 必须为 15 至 60 个字符")
    return suggestions


class ReportSection(ContractModel):
    category: PrimaryCategory
    label: str = Field(..., min_length=1)
    items: list[ReportItem] = Field(...)

    @model_validator(mode="after")
    def validate_section(self) -> ReportSection:
        if self.label != CATEGORY_LABELS[self.category]:
            raise ValueError("section.label 必须使用固定分类中文名称")
        if any(item.primary_category != self.category for item in self.items):
            raise ValueError("section 内每个 item 的 primaryCategory 必须与 section.category 一致")
        return self


class Lead(ContractModel):
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1, max_length=200)


class DailyStats(ContractModel):
    discovered: int = Field(..., ge=0)
    fetched: int = Field(..., ge=0)
    unique_events: int = Field(..., alias="uniqueEvents", ge=0)
    analyzed: int = Field(..., ge=0)
    included: int = Field(..., ge=0)


class WeeklyStats(ContractModel):
    unique_events: int = Field(..., alias="uniqueEvents", ge=0)
    sources: int = Field(..., ge=0)
    official_sources: int = Field(..., alias="officialSources", ge=0)
    daily_reports: int = Field(..., alias="dailyReports", ge=0)


class MonthlyStats(ContractModel):
    unique_events: int = Field(..., alias="uniqueEvents", ge=0)
    sources: int = Field(..., ge=0)
    official_sources: int = Field(..., alias="officialSources", ge=0)
    published_reports: int = Field(..., alias="publishedReports", ge=0)


class KeyDate(ContractModel):
    date: date
    date_type: KeyDateType = Field(..., alias="dateType")
    article_id: str = Field(..., alias="articleId", min_length=1)
    event: str = Field(..., min_length=1)


class GateResult(ContractModel):
    """Agent 对完整报告草稿做出的最终关门验证结果。"""

    report_id: str = Field(..., alias="reportId", min_length=1)
    status: Literal[GateStatus.PASSED, GateStatus.REJECTED]
    issues: list[str] = Field(...)


class ReportGate(ContractModel):
    """嵌入报告 JSON 的关门状态；草稿允许 pending，导出前必须为 passed。"""

    status: GateStatus
    issues: list[str] = Field(...)
    validated_at: datetime | None = Field(..., alias="validatedAt")
    prompt_version: str | None = Field(..., alias="promptVersion")

    @model_validator(mode="after")
    def validate_gate_metadata(self) -> ReportGate:
        if self.status is GateStatus.PENDING:
            if self.validated_at is not None or self.prompt_version is not None:
                raise ValueError("pending gate 不得填写验证时间或 Prompt 版本")
            return self
        if self.validated_at is None or not self.prompt_version:
            raise ValueError("已完成的 gate 必须填写 validatedAt 和 promptVersion")
        return self


class BuildMetadata(ContractModel):
    run_id: str = Field(..., alias="runId", min_length=1)
    prompt_version: str = Field(..., alias="promptVersion", min_length=1)
    gate_prompt_version: str = Field(..., alias="gatePromptVersion", min_length=1)
    report_prompt_version: str | None = Field(..., alias="reportPromptVersion")
    taxonomy_version: Literal[TAXONOMY_VERSION] = Field(..., alias="taxonomyVersion")
    schema_version: Literal[REPORT_SCHEMA_VERSION] = Field(..., alias="schemaVersion")
    data_cutoff_at: datetime = Field(..., alias="dataCutoffAt")


class ReportBase(ContractModel):
    schema_version: Literal[REPORT_SCHEMA_VERSION] = Field(..., alias="schemaVersion")
    report_id: str = Field(..., alias="reportId", min_length=1)
    date: date
    timezone: Literal["Asia/Shanghai"]
    generated_at: datetime = Field(..., alias="generatedAt")
    window_start: datetime = Field(..., alias="windowStart")
    window_end: datetime = Field(..., alias="windowEnd")
    lead: Lead
    source_directory: list[SourceDirectoryEntry] = Field(..., alias="sourceDirectory")
    sections: list[ReportSection] = Field(..., min_length=10, max_length=10)
    key_dates: list[KeyDate] = Field(..., alias="keyDates")
    gate: ReportGate
    build: BuildMetadata

    @model_validator(mode="after")
    def validate_report_shape(self) -> ReportBase:
        if self.window_start >= self.window_end:
            raise ValueError("windowStart 必须早于 windowEnd")
        categories = [section.category for section in self.sections]
        if tuple(categories) != PRIMARY_CATEGORY_ORDER:
            raise ValueError("sections 必须按固定顺序完整输出十个一级分类")
        if any(key_date.article_id not in self.article_ids for key_date in self.key_dates):
            raise ValueError("keyDates 中的 articleId 必须存在于 reports.sections")
        if self.key_dates != sorted(self.key_dates, key=lambda item: item.date):
            raise ValueError("keyDates 必须按日期升序排列")
        source_ids = [source.id for source in self.source_directory]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("sourceDirectory.id 必须唯一")
        return self

    @property
    def article_ids(self) -> set[str]:
        return {item.article_id for section in self.sections for item in section.items}


class DailyReport(ReportBase):
    report_type: Literal[ReportType.DAILY] = Field(..., alias="reportType")
    stats: DailyStats


class ReportPeriod(ContractModel):
    iso_week: str = Field(..., alias="isoWeek", min_length=1)
    start_date: date = Field(..., alias="startDate")
    end_date: date = Field(..., alias="endDate")

    @model_validator(mode="after")
    def validate_period(self) -> ReportPeriod:
        if self.start_date > self.end_date:
            raise ValueError("period.startDate 不得晚于 period.endDate")
        return self


class ReportTheme(ContractModel):
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    article_ids: list[str] = Field(..., alias="articleIds", min_length=1)


class RecurringSignal(ContractModel):
    summary: str = Field(..., min_length=1)
    article_ids: list[str] = Field(..., alias="articleIds", min_length=1)


class ImportantChange(ContractModel):
    summary: str = Field(..., min_length=1)
    article_ids: list[str] = Field(..., alias="articleIds", min_length=1)


class WatchlistItem(ContractModel):
    item: str = Field(..., min_length=1)
    watch_date: date | None = Field(None, alias="date")
    article_ids: list[str] = Field(..., alias="articleIds")


class WeeklyReport(ReportBase):
    report_type: Literal[ReportType.WEEKLY] = Field(..., alias="reportType")
    stats: WeeklyStats
    period: ReportPeriod
    themes: list[ReportTheme] = Field(..., min_length=3, max_length=8)
    recurring_signals: list[RecurringSignal] = Field(..., alias="recurringSignals")
    important_changes: list[ImportantChange] = Field(..., alias="importantChanges")
    next_week_watchlist: list[WatchlistItem] = Field(..., alias="nextWeekWatchlist")


class NarrativeSection(ContractModel):
    summary: str = Field(..., min_length=1)
    article_ids: list[str] = Field(..., alias="articleIds")


class PlatformMatrixEntry(ContractModel):
    platform: Literal["Amazon", "Walmart", "Shopify", "TikTok Shop", "Temu", "eBay"]
    summary: str = Field(..., min_length=1)
    article_ids: list[str] = Field(..., alias="articleIds")


class TrendEvidence(ContractModel):
    trend: str = Field(..., min_length=1)
    article_ids: list[str] = Field(..., alias="articleIds", min_length=1)
    event_count: int = Field(..., alias="eventCount", ge=1)


PLATFORM_MATRIX_ORDER: tuple[str, ...] = (
    "Amazon",
    "Walmart",
    "Shopify",
    "TikTok Shop",
    "Temu",
    "eBay",
)


class MonthlyReport(ReportBase):
    report_type: Literal[ReportType.MONTHLY] = Field(..., alias="reportType")
    stats: MonthlyStats
    month_lead: Lead = Field(..., alias="monthLead")
    platform_matrix: list[PlatformMatrixEntry] = Field(..., alias="platformMatrix")
    cost_and_risk: NarrativeSection = Field(..., alias="costAndRisk")
    traffic_and_conversion: NarrativeSection = Field(..., alias="trafficAndConversion")
    opportunities: NarrativeSection
    trend_evidence: list[TrendEvidence] = Field(..., alias="trendEvidence")
    next_month_calendar: list[KeyDate] = Field(..., alias="nextMonthCalendar")

    @model_validator(mode="after")
    def validate_platform_matrix(self) -> MonthlyReport:
        platforms = tuple(entry.platform for entry in self.platform_matrix)
        if platforms != PLATFORM_MATRIX_ORDER:
            raise ValueError("platformMatrix 必须按固定顺序覆盖六个竞品平台")
        return self


Report: TypeAlias = Annotated[
    DailyReport | WeeklyReport | MonthlyReport,
    Field(discriminator="report_type"),
]

REPORT_ADAPTER = TypeAdapter(Report)


def article_json_schema() -> dict[str, Any]:
    """生成严格使用 camelCase 字段的文章 JSON Schema。"""

    return Article.model_json_schema(by_alias=True)


def report_json_schema() -> dict[str, Any]:
    """生成日报、周报和月报联合 JSON Schema。"""

    return REPORT_ADAPTER.json_schema(by_alias=True)


def validate_report(payload: Any) -> DailyReport | WeeklyReport | MonthlyReport:
    """按 reportType 分派并校验报告 JSON。"""

    return REPORT_ADAPTER.validate_python(payload)


__all__ = [
    "Article",
    "ArticleAnalysis",
    "ARTICLE_SCHEMA_VERSION",
    "BuildMetadata",
    "CATEGORY_LABELS",
    "Conflict",
    "ContractModel",
    "CorroboratingSource",
    "DailyReport",
    "DailyStats",
    "Evidence",
    "GateResult",
    "GateStatus",
    "IMPACT_DIMENSION_LABELS",
    "IMPACT_DIMENSION_ORDER",
    "ImpactDimension",
    "KeyDate",
    "KeyDateType",
    "AgentProvenance",
    "MonthlyReport",
    "PLATFORM_MATRIX_ORDER",
    "PRIMARY_CATEGORY_ORDER",
    "PrimaryCategory",
    "Report",
    "ReportGate",
    "ReportItem",
    "ReportSection",
    "REPORT_SCHEMA_VERSION",
    "ReportType",
    "SCHEMA_VERSION",
    "SourceClass",
    "SourceDirectoryEntry",
    "SourceReference",
    "SourceType",
    "TAXONOMY_VERSION",
    "WeeklyReport",
    "article_json_schema",
    "report_json_schema",
    "validate_report",
]
