# 跨境电商 AI 情报雷达 Skill 技术设计

> 文档状态：可进入开发  
> 版本：v1.8  
> 日期：2026-07-18  
> Skill 名称：`ecom-market-pulse`  
> 架构结论：完全自研轻量实现，不依赖第三方资讯框架

## 1. 文档目标

本项目要交付一个可被 Codex/Agent 调用、也可由定时任务独立执行的 Skill。它从少量高价值信源采集跨境电商新闻，将发现、原始响应、正文、分析和报告完整写入 DuckDB，再完成去重、可信度标注、多子 Agent 分析、业务分类和日报/周报/月报 JSON 导出。

第一版重点不是建设资讯网站，而是建立稳定、可追溯、可扩展的“情报生产流水线”。任何最终发布的结论都必须能回溯到原文 URL、原始采集记录、子 Agent 任务版本和主 Agent 校验记录。

## 2. 唯一需求基线

本文件是项目唯一的产品与技术基线，完整定义产品范围、分类维度、资讯解读、数据合同、库表、处理流程和验收标准。开发和验收均以本文明确写出的规则为准。

### 2.1 产品定位

产品定位为“跨境电商卖家决策情报 Skill”，面向 Amazon 及其他跨境平台的运营、广告、供应链、合规、财务和管理人员。系统不是新闻搬运工具，而是把公开变化转成可追溯、可分类、可执行的卖家情报。

每条入选情报必须回答：

1. **发生了什么**：只陈述原文支持的事实。
2. **影响谁**：明确平台、站点、卖家类型和业务环节。
3. **为什么重要**：说明对钱、货、号、流量、效率或竞争的影响。
4. **何时生效**：区分发布日期、生效日期和操作截止日期。
5. **建议关注什么**：给出具体、有限的关注事项，不生成任务管理信息。
6. **是否可信**：保留来源类型、证据和冲突信息。

### 2.2 六个卖家决策维度

| 决策维度 | 业务含义 | 典型问题 |
| --- | --- | --- |
| 钱 | 费用、利润、税务、关税、汇率、现金流 | 是否需要重新核算利润或调整定价 |
| 货 | 库存、FBA、仓储、运输、清关、退货 | 是否需要改变补货、入仓或履约计划 |
| 号 | 账号健康、产品合规、知识产权、类目准入 | 是否存在下架、限制销售或封号风险 |
| 流量 | 广告、搜索、Listing、评论、VOC | 是否影响曝光、点击、转化和广告效率 |
| 效率 | API、AI、ERP、BI、客服与运营自动化 | 是否能降低人工成本或提升决策速度 |
| 竞争 | Walmart、Shopify、TikTok Shop、Temu、eBay 等平台变化 | 是否出现新市场、新渠道或竞争风险 |

### 2.3 固定交付物

MVP 固定交付以下数据：

- 完整入库的采集事实、原始响应、正文版本和来源关系。
- 每篇文章的结构化分析 JSON。
- 按业务日期生成的日报、周报和月报 JSON。
- 可选 Markdown 导出。
- 分类栏目、关键日期、卖家影响解读、建议关注事项，以及报告级 Agent 关门验证结果。
- 运行、子 Agent 任务、taxonomy、Schema、主 Agent 校验和导出的必要追溯信息。

## 3. 产品边界

### 3.1 MVP 必须完成

1. 从 4～8 个配置化信源发现新闻。
2. 支持 RSS/Atom、普通网页列表、Sitemap 三类采集入口。
3. 提取正文、发布时间、作者、原始标题和 canonical URL。
4. 完成 URL 去重、内容去重和同事件聚类。
5. 由主 Agent 按文章并行分派子 Agent，完成分类、摘要、影响维度判断和建议关注事项。
6. 生成统一文章 JSON，以及日报、周报、月报 JSON。
7. 记录每次运行、采集失败、子 Agent 原始输出和主 Agent 校验结果，支持断点续跑。

### 3.2 MVP 不做

- 不建设 Web 管理后台。
- 不建设用户、权限、收藏和订阅系统。
- 不接入需要登录、验证码或绕过反爬的页面。
- 不使用向量数据库；MVP 使用可解释的 URL、文本指纹和标题相似度去重。
- 未通过最终 Agent 关门验证的报告不导出、不发布。
- 不引入第三方资讯框架、工作流引擎或内容管理系统。

### 3.3 自研轻量方案确认

本项目完全自研，不 fork、包装或依赖现有资讯系统。核心运行时只包含五部分：

1. 可插拔信源采集器。
2. 统一正文与去重处理。
3. 主 Agent 分派与子 Agent 文章分析器。
4. 稳定的 JSON/Markdown 报告生成器。
5. 报告导出前的 Agent 关门验证器。

采集、去重、落库和导出在同一个 Python 进程内完成；文章分析由当前主 Agent 有界并行分派子 Agent，不引入消息队列、外部模型网关、独立服务或复杂编排。未来扩展通过新增 source adapter、子 Agent 任务模板或 exporter 完成，不修改主流程。

## 4. 核心设计原则

1. **原文优先**：行业媒体转述平台政策时，优先寻找并关联官方原文。
2. **采集与分类解耦**：信源标签只是线索，最终分类由文章内容决定。
3. **事实与建议分离**：`whatHappened` 只描述事实；`whyImportant` 和 `suggestions` 才表达影响和建议。
4. **单一主类、少量维度**：每篇文章只有一个 `primaryCategory`，再选择 1～3 个 `impactDimensions`。
5. **主 Agent 关门校验**：主 Agent 校验子 Agent 输出和最终报告及其引用证据；通过后才允许导出。
6. **结构化输出优先**：子 Agent 必须返回受 JSON Schema 约束的对象，不以自然语言作为程序间合同。
7. **幂等和可重跑**：同一文章版本和任务版本不重复分析；变更任务模板时可显式重算。
8. **不绕过站点保护**：尊重 robots、服务条款、速率限制、登录和验证码边界。

## 5. 总体架构

```text
信源配置
   │
   ▼
发现器 RSS / HTML List / Sitemap
   │
   ▼
正文抓取与规范化 ──► 原始快照
   │
   ▼
确定性过滤与去重 ──► 事件聚类
   │
   ▼
主 Agent 并行分派子 Agent 单篇结构化分析
   │
   ▼
日报 / 周报 / 月报聚合
   │
   ▼
主 Agent 最终关门校验
   │
   ▼
   ├──► JSON
   └──► Markdown（可选）
```

### 5.1 模块职责

| 模块 | 职责 | 禁止承担的职责 |
| --- | --- | --- |
| Discovery | 发现候选 URL 和基础元数据 | 不做业务分类 |
| Fetcher | 下载正文、缓存响应、限流和重试 | 不绕过登录/验证码 |
| Extractor | 提取正文、标题、日期、canonical | 不生成业务结论 |
| Normalizer | 统一时间、语言、URL 和文本 | 不修改原始快照 |
| Deduplicator | URL/内容去重和事件聚类 | 不丢弃佐证来源 |
| AgentOrchestrator | 按文章有界并行分派子 Agent，收集输出并交给主 Agent 校验 | 不直接写库、不直接发布 |
| SubAgentAnalyzer | 单篇完成相关性、分类、摘要、影响解读和建议关注事项 | 不直接写库、不直接发布 |
| Aggregator | 根据文章分析生成日报/周报/月报草稿 | 不重新抓取文章 |
| MainAgentValidator | 校验单篇输出、完整报告草稿及其引用证据 | 不修改已通过的文章分析；不通过的报告不得导出 |
| Exporter | 写 JSON、Markdown 或外部适配 | 不改变分析结果 |

## 6. Skill 与仓库结构

开发仓库保留唯一技术文档；真正可安装的 Skill 放在名称严格匹配的目录中。

```text
ecom-market-pulse-skill/
├── .gitignore
├── LICENSE
├── docs/
│   └── technical-design.md
├── skills/
│   └── ecom-market-pulse/
│       ├── SKILL.md
│       ├── scripts/
│       │   ├── pulse.py
│       │   └── ecom_market_pulse/
│       │       ├── agent_orchestrator.py
│       │       ├── analysis_contract.py
│       │       ├── cli.py / config.py / models.py / database.py
│       │       ├── schema.sql
│       │       ├── collectors/
│       │       ├── reports/
│       │       └── exporters/
│       ├── references/
│       │   ├── taxonomy.md
│       │   ├── source-policy.md
│       │   └── output-contract.md
│       └── assets/
│           ├── config.example.yaml
│           └── schemas/
└── pyproject.toml
```

说明：

- `SKILL.md` 只保留触发条件、执行顺序、必要输入和失败处理；运行时 `references/` 和 JSON Schema 必须从本文的分类与数据合同实现，不得另行改变业务语义。
- `scripts/pulse.py` 是稳定入口，避免 Agent 临时拼装采集脚本。
- `assets/schemas/` 保存程序运行时使用的 JSON Schema。
- 运行数据不写入 Skill 安装目录，而写入 `--workspace` 指定的工作区。

## 7. DuckDB 数据层与库表设计

### 7.1 存储原则

DuckDB 是项目唯一事实源。MVP 只建 6 张表，按照实际业务过程保存数据，不把一次抓取、一次分析或一份报告拆成多张关系表。

必须落库的数据包括：

- 信源配置和增量采集断点。
- 每次运行的配置快照、状态、统计和错误。
- 每次抓取的请求信息、响应状态和完整原始响应体。
- 提取后的正文及正文版本。
- 子 Agent 任务、原始 JSON 输出、主 Agent 校验结果和结构化解读结果。
- 日报、周报和月报的完整 JSON；Markdown 只在用户明确需要时作为可选阅读副本。

JSON、可选 Markdown 和 Parquet 文件只是导出物，可以从 DuckDB 重新生成。

### 7.2 运行工作区

```text
<workspace>/
├── config.yaml
├── data/
│   └── ecom_market_pulse.duckdb
├── exports/
│   ├── daily/
│   ├── weekly/
│   └── monthly/
└── backups/
```

同一时刻只允许一个写进程。采集可以在同一进程内并发，但数据库写入由单个连接完成。

### 7.3 六张核心表

| 表 | 用途 |
| --- | --- |
| `sources` | 信源配置、启停状态和采集断点 |
| `runs` | 每次采集、分析或报告运行的状态与日志 |
| `fetches` | 每次抓取及完整原始响应 |
| `articles` | 提取后的文章正文、内容版本和事件去重键 |
| `analyses` | 子 Agent 任务与输出、主 Agent 校验后的分类和影响维度 |
| `reports` | 日报、周报、月报草稿、最终关门验证结果及导出内容 |

合并规则：

- 发现、请求、响应和错误统一保存在 `fetches`。
- 同一 URL 正文发生变化时，在 `articles` 新增一行，不覆盖旧正文。
- 同事件文章通过 `event_key` 归组，不建立独立聚类表。
- 子 Agent 任务模板、taxonomy、原始输出和主 Agent 校验结果统一保存在 `analyses`。
- 报告栏目关系、文章 ID、最终关门验证结果和导出文本统一保存在 `reports`。

### 7.4 完整建表 SQL

以下 SQL 是设计稿，不在文档编写阶段执行。

```sql
CREATE TABLE IF NOT EXISTS sources (
    source_id        VARCHAR PRIMARY KEY,
    name             VARCHAR NOT NULL,
    source_class     VARCHAR NOT NULL CHECK (source_class IN ('official', 'professional-media', 'community', 'aggregator')),
    adapter_type     VARCHAR NOT NULL CHECK (adapter_type IN ('rss', 'html', 'sitemap', 'amz123-zb', 'amazon-global-selling-cn', 'amazon-ads-whats-new')),
    base_url         VARCHAR NOT NULL,
    config_json      JSON NOT NULL,
    checkpoint_json  JSON,
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    last_success_at  TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runs (
    run_id            VARCHAR PRIMARY KEY,
    run_type          VARCHAR NOT NULL CHECK (run_type IN ('collect', 'analyze', 'daily', 'weekly', 'monthly', 'full')),
    window_start      TIMESTAMPTZ,
    window_end        TIMESTAMPTZ,
    status            VARCHAR NOT NULL,
    config_json       JSON NOT NULL,
    stats_json        JSON,
    events_json       JSON,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS fetches (
    fetch_id              VARCHAR PRIMARY KEY,
    run_id                VARCHAR NOT NULL REFERENCES runs(run_id),
    source_id             VARCHAR NOT NULL REFERENCES sources(source_id),
    discovered_url        VARCHAR NOT NULL,
    canonical_url_hint    VARCHAR,
    title_hint            VARCHAR,
    published_at_hint     TIMESTAMPTZ,
    discovered_at         TIMESTAMPTZ NOT NULL,
    request_url           VARCHAR NOT NULL,
    final_url             VARCHAR,
    request_headers_json  JSON,
    response_headers_json JSON,
    http_status           INTEGER,
    content_type          VARCHAR,
    charset               VARCHAR,
    raw_body              BLOB,
    raw_sha256            VARCHAR,
    duration_ms           BIGINT,
    status                VARCHAR NOT NULL,
    error_message         VARCHAR,
    fetched_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS articles (
    article_id        VARCHAR PRIMARY KEY,
    fetch_id          VARCHAR NOT NULL REFERENCES fetches(fetch_id),
    canonical_url     VARCHAR NOT NULL,
    title             VARCHAR NOT NULL,
    original_title    VARCHAR,
    author            VARCHAR,
    published_at      TIMESTAMPTZ,
    language          VARCHAR,
    extracted_text    VARCHAR NOT NULL,
    extracted_html    VARCHAR,
    extractor_version VARCHAR NOT NULL,
    content_sha256    VARCHAR NOT NULL,
    event_key         VARCHAR,
    is_representative BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (canonical_url, content_sha256)
);

CREATE TABLE IF NOT EXISTS analyses (
    analysis_id           VARCHAR PRIMARY KEY,
    run_id                VARCHAR NOT NULL REFERENCES runs(run_id),
    article_id            VARCHAR NOT NULL REFERENCES articles(article_id),
    relevant              BOOLEAN NOT NULL,
    exclusion_reason      VARCHAR,
    primary_category      VARCHAR,
    impact_dimensions     VARCHAR[],
    title_zh              VARCHAR,
    summary               VARCHAR,
    affected_marketplaces VARCHAR[],
    affected_seller_types VARCHAR[],
    what_happened         VARCHAR,
    why_important         VARCHAR,
    effective_at          TIMESTAMPTZ,
    deadline_at           TIMESTAMPTZ,
    suggestions_json      JSON,
    evidence_json         JSON,
    taxonomy_version      VARCHAR NOT NULL,
    taxonomy_json         JSON NOT NULL,
    prompt_version        VARCHAR NOT NULL,
    prompt_text           VARCHAR NOT NULL,
    output_schema_version VARCHAR NOT NULL,
    model                 VARCHAR NOT NULL,
    request_json          JSON NOT NULL,
    response_json         JSON,
    analysis_json         JSON,
    input_tokens          BIGINT,
    output_tokens         BIGINT,
    duration_ms           BIGINT,
    status                VARCHAR NOT NULL,
    error_message         VARCHAR,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (article_id, prompt_version, model)
);

CREATE TABLE IF NOT EXISTS reports (
    report_id       VARCHAR PRIMARY KEY,
    run_id          VARCHAR NOT NULL REFERENCES runs(run_id),
    report_type     VARCHAR NOT NULL CHECK (report_type IN ('daily', 'weekly', 'monthly')),
    business_date   DATE NOT NULL,
    period_start    TIMESTAMPTZ NOT NULL,
    period_end      TIMESTAMPTZ NOT NULL,
    revision        INTEGER NOT NULL DEFAULT 1,
    status          VARCHAR NOT NULL,
    title           VARCHAR,
    summary         VARCHAR,
    article_ids     VARCHAR[],
    report_json     JSON NOT NULL,
    markdown_text   VARCHAR,
    gate_status     VARCHAR NOT NULL DEFAULT 'pending' CHECK (gate_status IN ('pending', 'passed', 'rejected')),
    gate_json       JSON,
    content_sha256  VARCHAR NOT NULL,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (report_type, business_date, revision)
);
```

### 7.5 表和字段注释

DuckDB 使用 `COMMENT ON TABLE` 和 `COMMENT ON COLUMN`。所有表和字段都必须有中文注释。

```sql
COMMENT ON TABLE sources IS '新闻信源配置和采集断点';
COMMENT ON COLUMN sources.source_id IS '稳定的信源标识';
COMMENT ON COLUMN sources.name IS '信源显示名称';
COMMENT ON COLUMN sources.source_class IS '信源类型：官方、专业媒体、社区或聚合转载';
COMMENT ON COLUMN sources.adapter_type IS '采集适配器类型';
COMMENT ON COLUMN sources.base_url IS '信源站点根地址';
COMMENT ON COLUMN sources.config_json IS '脱敏后的信源采集配置';
COMMENT ON COLUMN sources.checkpoint_json IS '增量采集游标、ETag 和更新时间等断点信息';
COMMENT ON COLUMN sources.enabled IS '信源是否启用';
COMMENT ON COLUMN sources.last_success_at IS '最近采集成功时间';
COMMENT ON COLUMN sources.created_at IS '信源创建时间';
COMMENT ON COLUMN sources.updated_at IS '信源最后更新时间';

COMMENT ON TABLE runs IS '采集、分析和报告任务运行记录';
COMMENT ON COLUMN runs.run_id IS '运行标识';
COMMENT ON COLUMN runs.run_type IS '运行类型';
COMMENT ON COLUMN runs.window_start IS '数据窗口开始时间';
COMMENT ON COLUMN runs.window_end IS '数据窗口结束时间';
COMMENT ON COLUMN runs.status IS '运行状态';
COMMENT ON COLUMN runs.config_json IS '本次运行使用的脱敏配置快照';
COMMENT ON COLUMN runs.stats_json IS '各阶段数量统计';
COMMENT ON COLUMN runs.events_json IS '结构化日志和错误列表';
COMMENT ON COLUMN runs.started_at IS '运行开始时间';
COMMENT ON COLUMN runs.finished_at IS '运行结束时间';

COMMENT ON TABLE fetches IS '每次新闻抓取及完整原始响应';
COMMENT ON COLUMN fetches.fetch_id IS '抓取记录标识';
COMMENT ON COLUMN fetches.run_id IS '关联运行标识';
COMMENT ON COLUMN fetches.source_id IS '关联信源标识';
COMMENT ON COLUMN fetches.discovered_url IS '发现阶段取得的原始地址';
COMMENT ON COLUMN fetches.canonical_url_hint IS '发现阶段取得的 canonical 地址线索';
COMMENT ON COLUMN fetches.title_hint IS '发现阶段取得的标题线索';
COMMENT ON COLUMN fetches.published_at_hint IS '发现阶段取得的发布时间线索';
COMMENT ON COLUMN fetches.discovered_at IS '内容发现时间';
COMMENT ON COLUMN fetches.request_url IS '实际请求地址';
COMMENT ON COLUMN fetches.final_url IS '重定向后的最终地址';
COMMENT ON COLUMN fetches.request_headers_json IS '脱敏后的请求头';
COMMENT ON COLUMN fetches.response_headers_json IS '脱敏后的响应头';
COMMENT ON COLUMN fetches.http_status IS 'HTTP 响应状态码';
COMMENT ON COLUMN fetches.content_type IS '响应内容类型';
COMMENT ON COLUMN fetches.charset IS '响应字符集';
COMMENT ON COLUMN fetches.raw_body IS '完整原始响应体';
COMMENT ON COLUMN fetches.raw_sha256 IS '原始响应体内容哈希';
COMMENT ON COLUMN fetches.duration_ms IS '抓取耗时，单位毫秒';
COMMENT ON COLUMN fetches.status IS '抓取状态';
COMMENT ON COLUMN fetches.error_message IS '抓取错误信息';
COMMENT ON COLUMN fetches.fetched_at IS '抓取完成时间';

COMMENT ON TABLE articles IS '提取后的文章正文和内容版本';
COMMENT ON COLUMN articles.article_id IS '文章版本标识';
COMMENT ON COLUMN articles.fetch_id IS '关联抓取记录标识';
COMMENT ON COLUMN articles.canonical_url IS '规范化后的文章地址';
COMMENT ON COLUMN articles.title IS '清洗后的文章标题';
COMMENT ON COLUMN articles.original_title IS '信源中的原始标题';
COMMENT ON COLUMN articles.author IS '文章作者';
COMMENT ON COLUMN articles.published_at IS '原文发布时间';
COMMENT ON COLUMN articles.language IS '正文语言代码';
COMMENT ON COLUMN articles.extracted_text IS '提取并清洗后的正文文本';
COMMENT ON COLUMN articles.extracted_html IS '提取后的正文 HTML';
COMMENT ON COLUMN articles.extractor_version IS '正文提取器版本';
COMMENT ON COLUMN articles.content_sha256 IS '清洗正文内容哈希';
COMMENT ON COLUMN articles.event_key IS '同一新闻事件的归组键';
COMMENT ON COLUMN articles.is_representative IS '是否为该事件的代表文章';
COMMENT ON COLUMN articles.created_at IS '文章版本创建时间';

COMMENT ON TABLE analyses IS '子 Agent 输出经主 Agent 校验后的结构化资讯解读';
COMMENT ON COLUMN analyses.analysis_id IS '文章分析标识';
COMMENT ON COLUMN analyses.run_id IS '关联运行标识';
COMMENT ON COLUMN analyses.article_id IS '关联文章版本标识';
COMMENT ON COLUMN analyses.relevant IS '是否与跨境电商卖家经营相关';
COMMENT ON COLUMN analyses.exclusion_reason IS '无关内容的排除原因';
COMMENT ON COLUMN analyses.primary_category IS '十个一级分类中的主分类';
COMMENT ON COLUMN analyses.impact_dimensions IS '钱、货、号、流量、效率、竞争影响维度';
COMMENT ON COLUMN analyses.title_zh IS '生成的中文标题';
COMMENT ON COLUMN analyses.summary IS '文章事实摘要';
COMMENT ON COLUMN analyses.affected_marketplaces IS '受影响平台或站点';
COMMENT ON COLUMN analyses.affected_seller_types IS '受影响卖家类型';
COMMENT ON COLUMN analyses.what_happened IS '原文支持的事件事实';
COMMENT ON COLUMN analyses.why_important IS '对卖家的影响解读';
COMMENT ON COLUMN analyses.effective_at IS '规则、费用或功能生效时间';
COMMENT ON COLUMN analyses.deadline_at IS '卖家操作截止时间';
COMMENT ON COLUMN analyses.suggestions_json IS '建议关注事项';
COMMENT ON COLUMN analyses.evidence_json IS '支撑分类、日期和影响解读的证据';
COMMENT ON COLUMN analyses.taxonomy_version IS '分类体系版本';
COMMENT ON COLUMN analyses.taxonomy_json IS '本次分析使用的完整分类体系';
COMMENT ON COLUMN analyses.prompt_version IS '子 Agent 任务模板版本，保留原字段名以兼容表结构';
COMMENT ON COLUMN analyses.prompt_text IS '本次分派给子 Agent 的完整任务说明，保留原字段名以兼容表结构';
COMMENT ON COLUMN analyses.output_schema_version IS '输出 JSON Schema 版本';
COMMENT ON COLUMN analyses.model IS '子 Agent 执行器标识，保留原字段名以兼容表结构';
COMMENT ON COLUMN analyses.request_json IS '主 Agent 分派的完整任务包，保留原字段名以兼容表结构';
COMMENT ON COLUMN analyses.response_json IS '子 Agent 原始 JSON 输出，保留原字段名以兼容表结构';
COMMENT ON COLUMN analyses.analysis_json IS '符合文章 JSON 合同的完整解读结果';
COMMENT ON COLUMN analyses.input_tokens IS '兼容保留字段；子 Agent 不提供时为空';
COMMENT ON COLUMN analyses.output_tokens IS '兼容保留字段；子 Agent 不提供时为空';
COMMENT ON COLUMN analyses.duration_ms IS '子 Agent 分析与主 Agent 校验耗时，单位毫秒';
COMMENT ON COLUMN analyses.status IS '分析状态';
COMMENT ON COLUMN analyses.error_message IS '分析错误信息';
COMMENT ON COLUMN analyses.created_at IS '分析创建时间';

COMMENT ON TABLE reports IS '日报、周报和月报';
COMMENT ON COLUMN reports.report_id IS '报告标识';
COMMENT ON COLUMN reports.run_id IS '关联运行标识';
COMMENT ON COLUMN reports.report_type IS '报告类型';
COMMENT ON COLUMN reports.business_date IS '报告业务日期';
COMMENT ON COLUMN reports.period_start IS '统计窗口开始时间';
COMMENT ON COLUMN reports.period_end IS '统计窗口结束时间';
COMMENT ON COLUMN reports.revision IS '同一周期报告修订号';
COMMENT ON COLUMN reports.status IS '报告生成状态';
COMMENT ON COLUMN reports.title IS '报告标题';
COMMENT ON COLUMN reports.summary IS '报告概览';
COMMENT ON COLUMN reports.article_ids IS '报告包含的文章标识列表';
COMMENT ON COLUMN reports.report_json IS '完整报告 JSON';
COMMENT ON COLUMN reports.markdown_text IS '通过关门验证后生成的完整 Markdown 报告';
COMMENT ON COLUMN reports.gate_status IS '最终主 Agent 关门校验状态';
COMMENT ON COLUMN reports.gate_json IS '最终主 Agent 校验版本、输入摘要、问题列表和校验时间';
COMMENT ON COLUMN reports.content_sha256 IS '报告内容哈希';
COMMENT ON COLUMN reports.generated_at IS '报告生成时间';
```

字段注释 SQL 必须在创建表后立即执行。下面的只读验收 SQL 必须返回 0 行：

```sql
SELECT table_name, column_name
FROM duckdb_columns()
WHERE internal = FALSE
  AND schema_name = 'main'
  AND comment IS NULL;
```

### 7.6 写入和恢复

处理流程按四个短事务提交：

1. 采集完成后写入 `fetches`，成功和失败都保留。
2. 正文提取成功后写入 `articles`。
3. 子 Agent 输出经主 Agent 校验后写入 `analyses`，包括失败输出和校验错误。
4. 报告草稿和最终关门验证结果写入 `reports`；只有验证通过后才写导出内容。

进程重启时根据各表 `status` 查找未完成记录继续处理。每日完成报告后复制 DuckDB 文件到 `backups/`；需要跨版本导入时再导出 Parquet，不在 MVP 中增加额外备份表。
## 8. 信源设计

### 8.1 信源类型

信源只做事实类型标记，不打分、不换算权重。类型用于决定能否直接发布以及是否需要回溯原文。

| `sourceClass` | 定义 | 使用规则 |
| --- | --- | --- |
| `official` | 平台、政府、物流商、API 官方来源 | 可作为政策、金额和日期的主来源 |
| `professional-media` | 有编辑责任的行业媒体和专业机构 | 可报道行业事件；涉及平台政策、金额和日期时应回溯官方原文 |
| `community` | 卖家社区、论坛和社媒 | 只作为异常信号；未经独立证据确认不得正式发布 |
| `aggregator` | 聚合转载、营销软文或来源不明内容 | 只用于发现线索，不进入正式日报 |

### 8.2 MVP 信源建议

第一批固定覆盖以下高价值来源，不在第一版贪多。

| sourceId | 信源 | `sourceClass` | 采集方式 | 主要用途 |
| --- | --- | --- | --- | --- |
| `amazon-global-selling-cn` | `gs.amazon.cn` | `official` | 官网专用列表适配器 | 招商、政策、活动、运营公告 |
| `about-amazon` | `aboutamazon.com` | `official` | RSS/HTML | Amazon 公司与平台官方动态 |
| `amazon-science` | `amazon.science` | `official` | RSS/HTML | 搜索、推荐、AI 与技术趋势 |
| `amz123` | AMZ123 | `professional-media` | HTML | 中文跨境线索发现；转载内容需回溯原始来源 |
| `amazon-ads-whats-new` | Amazon Ads What's New | `official` | 公开 JSON 索引 | 广告产品、站点和 API 变化 |

后续再加入 Shopify Changelog、Walmart Marketplace Release Notes、TikTok Shop 官方公告、eBay Seller Announcements，以及海关/税务/物流官方来源。

### 8.3 信源配置模型

```yaml
sources:
  - id: amazon-ads-whats-new
    name: Amazon Ads What's New
    enabled: true
    source_class: official
    homepage_url: "https://advertising.amazon.com/zh-cn/resources/whats-new"
    discovery:
      type: html
      url: "${AMAZON_ADS_WHATS_NEW_URL}"
    category_hints:
      - ads-traffic
    fetch:
      interval_minutes: 120
      requests_per_minute: 10
      timeout_seconds: 20
      max_retries: 2
    content:
      language: en
      timezone: UTC
```

`homepage_url` 是信源面向读者的主页，不得用 RSS 或 Sitemap 地址代替；日报、周报和月报的 `sourceDirectory` 直接使用它渲染信源名称链接。

每个 HTML 信源上线前必须完成一次“适配器验收”：入口可公开访问、robots/条款允许、发布时间可提取、正文可提取、canonical 可识别、连续抓取不会触发登录或验证码。

### 8.4 信源扩展接口

主流程只依赖统一接口，不写任何站点判断。内置 `rss`、`html`、`sitemap` 三个 adapter；新增信源优先通过 YAML 复用现有 adapter，只有页面结构特殊时才新增实现。

```python
class SourceAdapter(Protocol):
    def discover(
        self,
        source: SourceConfig,
        since: datetime,
    ) -> list[DiscoveredItem]: ...

    def fetch(
        self,
        source: SourceConfig,
        item: DiscoveredItem,
    ) -> RawArticle: ...
```

扩展约束：

- `SourceAdapter` 只返回统一 `RawArticle`，不包含业务分类逻辑。
- adapter 通过 `discovery.type` 注册到简单字典工厂，不使用插件框架或依赖注入容器。
- 站点特有 CSS selector、分页和时区放在 YAML 配置中，代码只保留无法配置化的解析差异。

## 9. 分类体系

### 9.1 分类总规则

分类依据是文章要求卖家作出的**主要经营决策**，不是信源名称、文章栏目或标题关键词。系统必须遵守以下规则：

1. 每篇相关文章必须且只能有一个 `primaryCategory`。
2. 先判断账号与合规风险，再判断费用影响、履约动作、流量动作、工具效率和竞争机会。
3. 能进入更具体分类时，不使用宽泛的 `amazon-policy`。
4. 同时涉及物流和成本时：主要要求调整运输、补货或清关方案，归 `crossborder-logistics`；主要要求重算利润、税费或定价，归 `fee-margin-tax`。
5. 社区传言获得官方确认后，主分类改为对应业务分类，社区来源只保留为佐证来源。
6. 无法在 10 个分类中找到明确业务归属，或仅为企业公关、泛科技新闻、无可验证营销软文时，标记 `relevant = false`，不得硬塞分类。

### 9.2 十个一级分类的完整定义

日报不按分类配额筛选，经过去重、确认且与卖家经营相关的资讯全部进入对应栏目，栏目内按发布时间倒序排列。

| 枚举与中文名称 | 纳入范围 | 排除边界与归类优先级 | 典型判定信号 |
| --- | --- | --- | --- |
| `amazon-policy` Amazon 官方政策与卖家公告 | Amazon 面向多个业务环节的卖家协议、经营规则、站点开放/关闭、注册与招商政策、官方全局公告 | 费用归 `fee-margin-tax`；FBA 操作归 `amazon-fba-fulfillment`；广告归 `ads-traffic`；账号处罚和产品合规归 `account-compliance-ip`。只有无法落到更具体业务类时才使用本类 | 强制执行、适用站点或卖家范围变化、明确生效日/截止日、卖家协议更新 |
| `amazon-fba-fulfillment` FBA、仓储、配送与退货 | 入仓、分仓、仓储容量、库存绩效、低库存运营要求、AWD、MCF、配送时效、退货和弃置流程 | 只谈收费金额归 `fee-margin-tax`；跨境干线、清关、外部海外仓归 `crossborder-logistics`；账号限制归 `account-compliance-ip` | 补货或入仓流程变化、容量限制、配送承诺变化、库存积压/断货风险、退货责任变化 |
| `fee-margin-tax` 平台费用、利润、税务与关税 | 佣金、FBA 费用、仓储费、低库存费、广告计费口径、VAT/GST、关税、汇率、结算周期、成本和利润模型 | 只改变操作流程且没有实质金额影响的 FBA/物流新闻，分别归履约或物流；账号合规义务优先归 `account-compliance-ip` | 费率或税率变化、计费公式变化、现金流变化、利润率受损、需要重新定价或重算 SKU 利润 |
| `ads-traffic` 广告与流量 | Sponsored Ads、DSP、AMC、广告归因、广告 API、预算/竞价、流量入口、站内外投放和促销流量 | 自然搜索、Listing 内容和评论转化归 `listing-seo-voc`；纯 API 运维能力且不改变广告经营决策时可归 `ai-ops-tools` | 新广告产品或站点、归因口径变化、流量入口变化、投放资格变化、预算和竞价动作 |
| `listing-seo-voc` Listing、SEO、评论与 VOC | 标题、五点、图片、视频、A+、变体、自然搜索排序、评论、买家反馈、退货原因和 VOC | 评论操纵处罚、侵权和类目审核归 `account-compliance-ip`；付费广告归 `ads-traffic` | 内容规范变化、搜索权重变化、评论机制变化、转化率或退货率信号、集中客户投诉 |
| `account-compliance-ip` 账号健康、合规与知识产权 | 账号健康、KYC、产品安全、受限商品、危险品、EPR、认证、类目准入、知识产权、下架、冻结和封号 | 单纯费用核算归 `fee-margin-tax`；不涉及销售资格的 Listing 优化归 `listing-seo-voc` | 法律或平台义务、材料提交截止日、停售/下架/封号风险、召回、侵权投诉、认证要求 |
| `crossborder-logistics` 跨境物流、供应链与海关 | 海运/空运/铁路、港口、承运商、清关、海外仓、尾程、供应中断、运输时效和运价 | Amazon 仓内与 FBA 操作归 `amazon-fba-fulfillment`；关税税率和利润核算归 `fee-margin-tax` | 航线或港口中断、清关规则变化、运价显著波动、时效变化、需要调整备货或承运商 |
| `competitor-marketplaces` 竞品平台动态 | Walmart、Shopify、TikTok Shop、Temu、eBay 等非 Amazon 平台的政策、费用、广告、履约、站点扩张和卖家机会 | Amazon 新闻必须归前述 Amazon 业务类；泛公司财报且不能转成卖家决策时排除 | 新市场/站点开放、招商补贴、费率和规则改变、流量红利、渠道进入或退出信号 |
| `ai-ops-tools` AI 工具与运营自动化 | AI Agent、ERP、BI、客服、选品、广告自动化、SP-API/Ads API、数据接口和可量化的效率工具 | 泛 AI 新闻、没有卖家场景的技术发布、无法验证的工具营销稿排除；广告经营规则变化归 `ads-traffic` | API 破坏性变更、新增自动化能力、明显节省人工、提高决策速度、必须升级集成 |
| `seller-community-signal` 卖家社区与异常信号 | Reddit、论坛、社群、社媒中多个独立卖家集中报告的异常、故障、审核波动或未确认规则变化 | 单一匿名帖子、情绪表达、无证据抱怨排除；找到官方确认后改归对应业务类 | 同一时间多卖家复现、多个独立来源、截图/工单等证据、可能影响账号或收入；未经确认的信息由关门验证决定是否拒绝发布 |

### 9.3 边界冲突的固定决策顺序

当一篇文章符合多个分类时，按以下顺序只确定一个主分类：

1. 存在停售、下架、封号、法律义务、认证或侵权风险：`account-compliance-ip`。
2. 主要变化可直接换算为费用、税负、利润或现金流：`fee-margin-tax`。
3. 主要动作发生在 Amazon 入仓、仓储、配送、退货：`amazon-fba-fulfillment`。
4. 主要动作发生在跨境运输、清关、海外仓或承运商：`crossborder-logistics`。
5. 主要动作是调整付费投放、归因或广告流量：`ads-traffic`。
6. 主要动作是优化自然搜索、商品内容、评论或 VOC：`listing-seo-voc`。
7. 主要动作是接入 API、AI 或运营工具：`ai-ops-tools`。
8. 主体是非 Amazon 平台：`competitor-marketplaces`。
9. 只有社区证据且尚未确认：`seller-community-signal`。
10. Amazon 全局公告无法归入以上具体业务类：`amazon-policy`。

### 9.4 卖家影响维度

一级分类回答“这是什么资讯”，影响维度回答“它影响卖家的哪一块经营”。每篇文章可选择 1～3 个维度：

| 枚举 | 中文 | 判断标准 |
| --- | --- | --- |
| `money` | 钱 | 影响费用、利润、税务、关税、汇率、结算或现金流 |
| `goods` | 货 | 影响库存、补货、仓储、运输、清关、配送或退货 |
| `account` | 号 | 影响账号健康、销售资格、产品合规、认证或知识产权 |
| `traffic` | 流量 | 影响广告、搜索、Listing、评论、曝光、点击或转化 |
| `efficiency` | 效率 | 影响 API、AI、ERP、BI、客服或运营自动化效率 |
| `competition` | 竞争 | 影响其他平台布局、新渠道机会或竞争态势 |

不再额外维护展示标签、影响分数、风险分数或优先级，避免相同含义被重复建模。

## 10. 多子 Agent 资讯解读

### 10.1 主 Agent 分派与单篇分析流程

每篇去重后的文章由当前主 Agent 分派一个子 Agent 进行结构化解读。子 Agent 之间按文章有界并行，主 Agent 负责汇总、校验和落库；项目代码不调用外部模型网关或模型接口。

分派前先由程序完成低成本确定性处理：

- URL 和内容重复直接跳过。
- 正文过短、发布时间超窗、明显空页或错误页直接跳过。
- `aggregator` 来源且找不到原始链接的转载只保留为线索，不进入正式分析和日报。

每个子 Agent 只接收一篇文章的标题、来源、发布时间、清洗正文、信源类型、分类定义和固定任务说明，只返回一个 `AgentArticleAnalysis` JSON 对象。输出内容包括：

- 是否与跨境电商相关及排除理由。
- 一个主分类和 1～3 个卖家影响维度。
- 中文标题、事实摘要和卖家影响。
- 影响站点、卖家类型和关键日期。
- 建议关注事项和证据定位。

主 Agent 依次校验 JSON Schema、文章 ID、分类枚举、影响维度、证据 URL、日期格式及“事实不得超出原文”规则。无关文章保留最小分析记录，不进入报告；校验通过的相关文章作为报告草稿候选内容；子 Agent 超时、输出非法或校验失败时写入失败记录，绝不以猜测结果补齐。

```json
{
  "articleId": "art_01J...",
  "taskVersion": "article-analysis-v1",
  "instruction": "仅返回 AgentArticleAnalysis JSON；结论只能由原文支持。",
  "article": {
    "title": "...",
    "sourceUrl": "https://example.com/original",
    "publishedAt": "2026-07-17T01:00:00Z",
    "language": "en",
    "text": "..."
  }
}
```

日报先按分类和发布时间生成草稿。周报和月报的主线、主题综述由主 Agent 基于已校验文章和统计结果归纳；文章列表、数量、日期和引用始终由程序确定。草稿完整生成后统一进入主 Agent 关门校验，通过后才导出 JSON/Markdown。

### 10.2 单篇文章输出维度

系统不计算任何文章分数或优先级。每篇相关文章只输出以下必要字段：

| 字段 | 规则 |
| --- | --- |
| `relevant` | 是否与跨境电商卖家经营相关 |
| `exclusionReason` | `relevant = false` 时说明排除原因 |
| `primaryCategory` | 第 9.2 节十个一级分类之一 |
| `impactDimensions` | 第 9.4 节六个卖家影响维度中的 1～3 个 |
| `title`、`summary` | 中文标题和事实摘要，不扩写原文没有的信息 |
| `whatHappened` | 只说明发生了什么 |
| `whyImportant` | 只说明对卖家的影响，围绕已选影响维度解释 |
| `affectedMarketplaces` | 受影响平台或站点；无法确认时为空数组 |
| `affectedSellerTypes` | 受影响卖家类型；无法确认时为空数组 |
| `effectiveAt`、`deadlineAt` | 原文明确出现时填写，否则为 `null` |
| `suggestions` | 0～3 条建议关注事项；没有明确建议时为空数组 |
| `evidence` | 支撑分类、日期和影响解读的原文证据 |

没有原文依据时，日期、金额、适用站点和影响范围不得由子 Agent 猜测。

### 10.3 主 Agent 关门校验

日报、周报或月报草稿完整生成后，主 Agent 对最终 `report_json` 草稿及其中每个文章引用对应的来源 URL、原文证据和结构化分析执行关门校验。校验只返回报告级 `passed` 或 `rejected`，不修改文章分析，也不直接改写报告。

关门验证检查六件事：

1. 报告中的每个事件、结论和关键日期是否都能追溯到有效文章及 evidence。
2. 标题、摘要、金额、站点、生效日和截止日是否与引用证据一致。
3. 主分类和影响维度是否使用本文规定的枚举且含义匹配。
4. `whyImportant`、周期综述和 `suggestions` 是否出现证据无法支持的推断。
5. 社区消息、转载内容和来源冲突是否被误写成已经确认的事实。
6. 报告 JSON 合同、文章引用、数量统计和报告时间窗口是否完整一致。

每份报告固定输出：

```json
{
  "reportId": "daily-2026-07-17",
  "status": "passed",
  "issues": []
}
```

- `passed`：写入 `reports.gate_status = 'passed'`，将报告状态更新为 `completed`，随后才允许导出 JSON/Markdown。
- `rejected`：写入 `reports.gate_status = 'rejected'`，将报告状态更新为 `rejected`，保留草稿但不导出、不发布。
- 主 Agent 无法完成校验或无法判断时按 `rejected` 处理；下次运行重新生成报告草稿后再校验。
- `reports.gate_json` 保存校验版本、输入摘要、问题列表和校验时间。
- 一次校验只对应一份完整报告，不按文章拆批，避免失去报告上下文。

### 10.4 建议关注事项

`suggestions` 是简短的资讯解读补充，不是任务系统。每篇文章最多生成 3 条字符串建议；没有可信建议时返回空数组。

生成要求：

- 每条建议 15～60 个汉字，尽量明确站点、账号、ASIN/SKU、库存、广告活动、接口或证照等对象。
- 不得重复新闻摘要，不得写“持续关注”“及时调整”等空话。
- 不输出负责人、任务状态、完成条件或人为优先级。
- 涉及费用、税务、合规和法律义务的建议必须提示回到官方原文确认。

### 10.5 三类日期的固定语义

| 字段 | 定义 | 缺失处理 |
| --- | --- | --- |
| `publishedAt` | 原文首次公开发布时间 | 无法确认时为 `null`，不得使用采集时间冒充 |
| `effectiveAt` | 政策、费率、功能或规则开始生效的时间 | 原文未说明时为 `null` |
| `deadlineAt` | 卖家必须提交、修改、迁移或完成动作的最后时间 | 原文未说明时为 `null` |

日期必须关联 `evidence`。只出现“即将”“近期”“未来几周”等相对表述时，保留原文表述到事实摘要，但结构化日期字段为 `null`。

## 11. 多子 Agent 分派与落库

### 11.1 并行边界

主 Agent 先完成采集、正文提取、确定性去重和事件聚类；只有通过这些步骤的代表文章才进入子 Agent 队列。并发度由主 Agent 根据当前可用槽位控制，每个子 Agent 只分析一篇文章，互不共享可写状态。

子 Agent 不得访问 DuckDB、不生成报告、不修改信源配置，也不得把未验证结论写入文件。它的唯一职责是基于输入文章返回第 10.2 节合同对应的 JSON。

### 11.2 主 Agent 校验与落库

主 Agent 收到每个输出后，必须在同一轮中完成以下处理：

1. 去除代码围栏并解析 JSON。
2. 以 Pydantic 与 `article.schema.json` 校验字段、枚举和必填项。
3. 校验 `articleId`、`sourceUrl`、证据 URL 和日期均与输入文章及其可追溯来源一致。
4. 校验事实、金额、站点和建议没有超出原文证据。
5. 仅将通过校验的结果写入 `analyses`；原始任务包、原始输出、任务版本、耗时、失败原因和校验结果一并保存。

`analyses` 现有字段不变：`prompt_*` 保存任务模板，`model` 保存执行器标识，`request_json`/`response_json` 保存任务包和子 Agent 原始输出，`input_tokens`/`output_tokens` 在不可获得时为 `NULL`。不配置、不读取也不调用项目内的外部模型接口。

### 11.3 失败与重跑

- 子 Agent 未返回合法 JSON、字段校验失败或证据不一致：记录 `analysis_failed`，该文章不进入报告。
- 单个子 Agent 失败不影响其他文章；主 Agent 收齐所有结果后再生成报告草稿。
- 同一 `article_id + task_version + content_sha256` 已有通过校验的结果时直接复用；只有文章正文或任务模板变化才重新分派。
- 主 Agent 不能确认事实时宁可拒绝落库，不使用修复型 API 重试或人工补造结构化字段。

## 12. 去重与事件聚类

按以下顺序执行：

1. URL 规范化：移除跟踪参数、统一尾斜杠、读取 canonical。
2. 精确 URL 去重：`canonicalUrl` 唯一。
3. 内容去重：正文标准化后计算 SHA-256。
4. 近似去重：标题分词后计算 SimHash；阈值只生成候选，不直接删除。
5. 事件聚类：标题、实体、日期和主题综合判断是否为同一事件。

同一事件有多个来源时：

- `official` 来源优先作为 `primarySource`。
- `professional-media` 和 `community` 来源保存到 `corroboratingSources`。
- 不重复进入日报配额。
- 若不同来源信息冲突，写入 `conflicts`；最终报告必须明确保留冲突，关门验证据此判断整份报告能否发布。

## 13. 统一文章 JSON 合同

下面是面向业务的权威核心对象定义。实现阶段生成的 `article.schema.json` 必须逐字段落实本节合同，不得增删必填语义或改变枚举含义。

```json
{
  "schemaVersion": "1.0.0",
  "id": "art_01J...",
  "clusterId": "evt_01J...",
  "title": "Amazon 更新美国站 FBA 费用",
  "originalTitle": "...",
  "summary": "Amazon 调整部分 FBA 费用，卖家需重新核算相关 SKU 成本。",
  "sourceUrl": "https://example.com/original",
  "canonicalUrl": "https://example.com/original",
  "permalink": null,
  "source": {
    "id": "amazon-official",
    "name": "Amazon Official",
    "sourceClass": "official",
    "sourceType": "html"
  },
  "publishedAt": "2026-07-17T01:00:00Z",
  "collectedAt": "2026-07-17T02:00:00Z",
  "language": "en",
  "relevant": true,
  "primaryCategory": "fee-margin-tax",
  "impactDimensions": ["money", "goods"],
  "affectedMarketplaces": ["US"],
  "affectedSellerTypes": ["FBA", "brand-seller"],
  "analysis": {
    "whatHappened": "Amazon 公布了美国站部分 FBA 费用调整。",
    "whyImportant": "单位履约成本变化会影响相关 SKU 的利润核算和补货判断。",
    "suggestions": [
      "核对美国站受影响 SKU，并按新费率重新测算单位利润。"
    ],
    "effectiveAt": "2026-10-15T00:00:00Z",
    "deadlineAt": null
  },
  "evidence": [
    {
      "fact": "新费用于 2026-10-15 生效",
      "sourceUrl": "https://example.com/original",
      "location": "正文费用说明段"
    }
  ],
  "corroboratingSources": [],
  "conflicts": [],
  "agent": {
    "executor": "codex-subagent",
    "taskVersion": "article-analysis-v1",
    "validatedAt": "2026-07-17T02:10:00Z"
  },
  "contentHash": "sha256:..."
}
```

关键约束：

- `summary` 不写未经原文支持的新事实。
- `effectiveAt` 和 `deadlineAt` 必须可在 evidence 中找到对应依据。
- `permalink` 预留给未来博客页面；MVP 可为 `null`。
- 单篇文章对象不保存关门状态；关门验证只属于最终报告。

## 14. 报告 JSON 合同

### 14.1 分类式日报

日报以北京时间业务日期生成，默认统计前一自然日内首次发现或正文发生有效变化的独立事件。日报不打分、不设优先级、不做分类配额，固定输出以下内容：

| 顺序 | 区块 | 内容 |
| ---: | --- | --- |
| 1 | `lead` | 当日资讯概览，不超过 200 个汉字 |
| 2 | `stats` | 发现、抓取、去重后事件、分析和纳入草稿的数量 |
| 3 | `sourceDirectory` | 所有已启用信源的 ID、名称、类型、主页和本期纳入篇数；0 篇不代表失效或未抓到内容 |
| 4 | `sections` | 固定输出 10 个一级分类；空分类保留空数组；分类内按发布时间倒序 |
| 5 | `keyDates` | 原文明确给出的生效日和截止日，按日期升序 |
| 6 | `gate` | 最终主 Agent 关门校验状态、问题和校验时间 |
| 7 | `build` | run、taxonomy、子 Agent 任务、关门校验、Schema 和数据截止时间版本 |

选稿规则只有四条：

1. 读取报告窗口内 `relevant = true` 的最新文章分析。
2. 同一事件只使用代表文章，其他来源保留为佐证。
3. 候选内容全部进入对应主分类，不再按分数、优先级或配额筛选。
4. 完整报告草稿生成后统一执行最终关门验证；未通过时整份报告不导出。

`sections[].items[]` 固定包含文章标识、标题、摘要、来源、原文链接、发布时间、主分类、影响维度、卖家影响、影响范围、关键日期和建议关注事项。

```json
{
  "schemaVersion": "1.2.0",
  "reportId": "daily-2026-07-17",
  "reportType": "daily",
  "date": "2026-07-17",
  "timezone": "Asia/Shanghai",
  "generatedAt": "2026-07-17T08:00:00+08:00",
  "windowStart": "2026-07-16T00:00:00+08:00",
  "windowEnd": "2026-07-17T00:00:00+08:00",
  "lead": {
    "title": "跨境电商资讯日报",
    "summary": "今日主要更新集中在平台费用、FBA 履约和广告流量。"
  },
  "stats": {
    "discovered": 120,
    "fetched": 96,
    "uniqueEvents": 42,
    "analyzed": 38,
    "included": 34
  },
  "sourceDirectory": [
    {
      "id": "amazon-global-selling-cn",
      "name": "Amazon 全球开店中国",
      "sourceClass": "official",
      "homepageUrl": "https://gs.amazon.cn/news",
      "articleCount": 0
    },
    {
      "id": "amz123-zb",
      "name": "AMZ123 跨境早报",
      "sourceClass": "professional-media",
      "homepageUrl": "https://www.amz123.com/zb",
      "articleCount": 15
    }
  ],
  "sections": [
    {
      "category": "fee-margin-tax",
      "label": "平台费用、利润、税务与关税",
      "items": [
        {
          "articleId": "art_01J...",
          "clusterId": "evt_01J...",
          "title": "Amazon 更新美国站 FBA 费用",
          "summary": "部分 FBA 费用将在指定日期调整。",
          "source": {"name": "Amazon Official", "sourceClass": "official"},
          "sourceUrl": "https://example.com/original",
          "publishedAt": "2026-07-16T09:00:00Z",
          "impactDimensions": ["money", "goods"],
          "whatHappened": "Amazon 公布了美国站部分 FBA 费用调整。",
          "whyImportant": "单位履约成本变化会影响相关 SKU 的利润核算和补货判断。",
          "affectedMarketplaces": ["US"],
          "affectedSellerTypes": ["FBA"],
          "effectiveAt": "2026-10-15T00:00:00Z",
          "deadlineAt": null,
          "suggestions": ["核对美国站受影响 SKU，并按新费率重新测算单位利润。"]
        }
      ]
    }
  ],
  "keyDates": [
    {
      "date": "2026-10-15",
      "dateType": "effective",
      "articleId": "art_01J...",
      "event": "新 FBA 费用生效"
    }
  ],
  "gate": {
    "status": "passed",
    "issues": [],
    "validatedAt": "2026-07-17T08:01:00+08:00",
    "validationVersion": "report-gate-v1"
  },
  "build": {
    "runId": "run_01J...",
    "analysisTaskVersion": "article-analysis-v1",
    "gateValidationVersion": "report-gate-v1",
    "taxonomyVersion": "1.0.0",
    "schemaVersion": "1.2.0",
    "dataCutoffAt": "2026-07-17T00:00:00+08:00"
  }
}
```

### 14.2 周报

周报不只是七份日报拼接，需要增加：

- `period`: ISO week、开始和结束日期。
- `lead`: 本周主线标题和综述。
- `stats`: 独立事件、来源数、官方源数量、日报数量。
- `themes`: 3～8 个主题，每个主题包含综述和关联文章。
- `recurringSignals`: 多日重复出现的社区或平台异常。
- `importantChanges`: 本周确认的政策、费用和规则变化。
- `nextWeekWatchlist`: 下周关键日期和待观察事项。

### 14.3 月报

月报面向经营复盘，需要增加：

- `period`: `YYYY-MM`、自然月开始和结束日期。
- `monthLead`: 本月核心判断。
- `stats`: 独立事件、来源数、官方源数量、合格工作日日报数量。
- `platformMatrix`: Amazon、Walmart、Shopify、TikTok Shop、Temu、eBay 的变化矩阵。
- `costAndRisk`: 费用、物流、关税、税务和合规风险。
- `trafficAndConversion`: 广告、搜索、Listing、评论和 VOC 趋势。
- `opportunities`: 平台开放、站点扩张、工具与自动化机会。
- `trendEvidence`: 支撑趋势的文章 ID 和事件数量。
- `nextMonthCalendar`: 下一月生效日和截止日。

周报/月报的趋势必须由已发布事件数量和来源证据支撑，禁止由子 Agent 脱离证据制造趋势。

周报和月报采用业务截止口径：周报 `windowEnd` 为周五 16:00，月报 `windowEnd` 为自然月最后一天 16:00。截止任务必须先补采上午日报之后的新资讯，再重新构建汇总报告；`generatedAt`、`gate.validatedAt` 均不得早于 `windowEnd`。

月报顶层 `date` 等于月初，候选集直接来自目标月全部周一至周五的合格日报与月末截止增量事实并回到文章事实层聚类，不能只基于周报再次提炼。通过关门时 `stats.dailyReports` 必须等于目标月的全部工作日数量。截止点之后首次发现的资讯顺延到下一业务周期。

## 15. 采集与调度

### 15.1 CLI

```bash
python skills/ecom-market-pulse/scripts/pulse.py validate-config --workspace ./runtime
python skills/ecom-market-pulse/scripts/pulse.py collect --workspace ./runtime --since 24h
python skills/ecom-market-pulse/scripts/pulse.py build --workspace ./runtime --period daily
```

辅助命令：

```bash
python skills/ecom-market-pulse/scripts/pulse.py retry --workspace ./runtime --run-id <run-id>
python skills/ecom-market-pulse/scripts/pulse.py schema-check --workspace ./runtime
```

文章分析由当前主 Agent 在采集完成后按第 10、11 节执行，不提供会绕过主 Agent 校验的独立文章分析或一键全流程 CLI。

### 15.2 定时策略

Skill 本身不是调度器。开发环境可由 Agent 手动调用；生产环境使用 cron、launchd、GitHub Actions 或现有任务平台调度。

建议：

- 官方 RSS：每 2 小时。
- 普通网页：每 4 小时，单域名限速。
- 日报：北京时间工作日 10:00，生成当天资讯快照。
- 周报：每周五 16:00，先做截止增量采集，再聚合本周周一至周五。
- 月报：每月最后一个自然日 20:00，使用当日 16:00 截止数据聚合本月；不能写死为 31 日。

月末恰逢周五时，周报先执行，月报后执行。月报更新 manifest 前必须重新读取最新远端版本，避免覆盖当天刚发布的周报条目。

同一周期按以下顺序执行：

1. 将完整报告草稿和文章 ID 写入 `reports`，此时 `status = 'draft'`、`gate_status = 'pending'`，`markdown_text` 为空。
2. 主 Agent 对完整草稿和引用证据执行最终关门校验。
3. 验证通过后，将 `gate` 结果合入最终 `report_json`，更新内容哈希和 `status = 'completed'`，再生成并导出 JSON/Markdown。
4. 验证拒绝或异常时，更新 `status = 'rejected'` 和 `gate_json`，不生成磁盘导出。

磁盘导出采用临时文件加原子替换；即使导出失败，数据库中已通过验证的报告仍可重新导出，失败信息写入对应 `runs.events_json`。

## 16. 错误处理与幂等

| 场景 | 处理 |
| --- | --- |
| 429 | 读取 `Retry-After`；指数退避；不并发重试 |
| 5xx/网络超时 | 最多重试 2 次，记录失败原因 |
| 401/403/验证码 | 不重试绕过，禁用本次采集并记录配置错误 |
| 正文为空 | 保留元数据，进入 `extract_failed` |
| 日期不明 | 使用 `publishedAt = null`，不得用采集时间冒充发布时间 |
| 子 Agent 未完成或超时 | 记录 `analysis_failed`；不重复采集，其他文章继续分析 |
| 子 Agent JSON 非法或证据不一致 | 主 Agent 拒绝落库，不调用外部修复接口 |
| Schema 不通过 | 阻止构建该报告 |
| 最终关门校验拒绝、无法完成或结果非法 | 报告状态记为 `rejected`，完整记录 `gate_json`，不导出；下次运行重建后再校验 |
| 同周期重复执行 | 复用已有结果，除非指定 `--force` 或子 Agent 任务版本变化 |

## 17. 可观测性与审计

每次运行在 `runs` 中生成一条运行清单，统计和错误摘要分别写入 JSON 字段：

```json
{
  "runId": "run_01J...",
  "startedAt": "...",
  "finishedAt": "...",
  "status": "succeeded_with_warnings",
  "configHash": "sha256:...",
  "sourceCounts": {},
  "stageCounts": {},
  "errors": [],
  "outputs": []
}
```

本次运行的结构化日志和错误数组写入 `runs.events_json`，事件至少包含 `stage`、`source_id`、`article_id`、`level`、`event_type` 和 `duration_ms`。控制台日志只是展示，不作为持久化记录；不得记录与任务无关的敏感上下文。

建议指标：

- 各信源发现数、抓取成功率、正文提取成功率。
- 去重率、事件聚类数量。
- 子 Agent 分析成功率、无关内容占比、主 Agent Schema 拒绝率。
- 各分类数量、官方来源占比、最终关门校验通过和拒绝数量。
- 单篇子 Agent 耗时和主 Agent 校验耗时。

## 18. 安全与合规

1. 只抓取公开可访问内容，不绕过身份验证、付费墙、验证码或反爬挑战。
2. 默认保存结构化事实和摘要，不对外再发布大段原文。
3. 对外输出保留 `sourceUrl`、来源名称和 canonical。
4. 对政策、费用和法律义务的摘要必须保留官方原文链接，并提示读者以官方原文为准。
5. `.env`、DuckDB 数据库、备份、临时目录和导出文件必须加入 `.gitignore`。
6. Webhook、博客或外部存储属于新增的数据传输边界，启用前单独配置和评审。

## 19. Skill 触发与交互约定

`SKILL.md` 的 description 应覆盖以下触发场景：

- 采集跨境电商、Amazon、FBA、广告、合规、物流或竞品平台新闻。
- 生成跨境电商日报、周报或月报。
- 对现有文章执行卖家影响解读、分类或建议关注事项提取。
- 查询现有运行工作区中的历史情报。

Skill 执行前检查：

1. 工作区路径是否明确。
2. 配置文件是否存在并通过校验。
3. 当前主 Agent 是否可并行分派足够的子 Agent。
4. 若用户只要求分析已有文章，不启动网络采集。

Skill 完成后必须报告：

- 使用的时间窗口和信源。
- 发现、去重、分析、纳入草稿、关门通过/拒绝和发布数量。
- 生成文件的绝对路径。
- 失败信源和降级情况。
- 最终关门校验状态和拒绝原因；拒绝的报告明确标记为未导出。

## 20. 技术选型

| 领域 | 建议 | 理由 |
| --- | --- | --- |
| 语言 | Python 3.11+ | 采集、文本处理和结构化数据生态成熟 |
| HTTP | `httpx` | 超时、连接池、同步/异步统一 |
| RSS | `feedparser` | 成熟稳定 |
| 正文提取 | `trafilatura`，BeautifulSoup 兜底 | 对新闻正文和元数据提取友好 |
| 模型 | `pydantic` v2 | 配置和结构化数据校验 |
| 配置 | YAML + 环境变量插值 | 便于维护多信源 |
| 存储 | DuckDB 单文件数据库 | 原始数据完整落库，适合本地分析、JSON、聚合和 Parquet 导出 |
| 数据库驱动 | `duckdb` Python 包 | 同进程读写、事务和批量插入 |
| Agent 协作 | Codex 主 Agent + 子 Agent | 子 Agent 分析，主 Agent 校验与落库，不经项目内 API |
| 重试 | 程序级采集重试 | 明确 HTTP 退避策略；子 Agent 失败由主 Agent 记录 |

不建议第一版引入 Celery、Kafka、PostgreSQL、向量数据库或微服务拆分。

## 21. 验收标准

| 指标 | MVP 目标 |
| --- | ---: |
| RSS 抓取成功率 | ≥ 95% |
| 已验收 HTML 信源正文提取成功率 | ≥ 90% |
| JSON Schema 通过率 | 100% |
| 固定样本主分类准确率 | ≥ 85% |
| 明确日期提取准确率 | ≥ 95% |
| 发布内容原文 URL 完整率 | 100% |
| 官方/社区属性标记完整率 | 100% |
| 有响应体抓取记录的原始响应入库率 | 100% |
| 分析到正文、子 Agent 任务、主 Agent 校验、taxonomy 的可追溯率 | 100% |
| 报告到文章分析的可追溯率 | 100% |
| 未通过最终关门校验的报告导出数 | 0 |
| 子 Agent 原始输出未经主 Agent 校验即入库 | 0 次 |
| 同输入幂等重跑重复分派已通过文章 | 0 次 |

分类准确率不达标时，优先调整 taxonomy、子 Agent 任务说明和示例，不通过扩大结论范围解决。

## 22. 实施里程碑

### M0：合同冻结与信源验收

- 冻结分类枚举、影响维度和文章/报告 Schema。
- 验收首批 4～6 个信源。

### M1：Skill 骨架与确定性流水线

- 初始化 `ecom-market-pulse` Skill。
- 完成配置、CLI、DuckDB `schema.sql`、工作区和运行清单。
- 完成 RSS、HTML、Sitemap 发现器与正文提取。
- 完成 URL/内容去重。

### M2：多子 Agent 分析

- 完成主 Agent 并行分派、单篇结构化输出和 JSON Schema 校验。
- 完成主 Agent 校验后的分析缓存。
- 用固定带预期结果的样本迭代子 Agent 任务说明。

### M3：报告聚合

- 完成日报、周报和月报草稿聚合。
- 完成报告级主 Agent 最终关门校验。
- 完成通过验证后的 JSON 和 Markdown 导出。
- JSON 是默认主交付物，固定命名为 `daily/YYYY-MM-DD.json`、`weekly/YYYY-Www.json`、`monthly/YYYY-MM.json`；`latest.json` 始终指向各周期最新通过版本。
- 完成周报/月报趋势聚合。
- 完成关键日期日历和 `latest.json`。

### M4：稳定性与交付

- 线上小规模验收和幂等重跑。
- 完成日志、错误恢复和 Skill 校验。
- 产出可安装 Skill 目录及示例工作区配置。

## 23. 开发前必须确认的一个外部条件

该条件不影响本文档定稿，但会阻塞真实联网验收：

1. 首批信源中 AMZ123 和各 HTML 页面是否允许自动化抓取，以及最终采用的具体栏目 URL。

## 24. 最终结论

本项目应定位为“跨境电商卖家决策情报 Skill”，不是普通新闻爬虫，也不是单纯日报渲染器。

技术上采用一个完全自研、自包含、可审计的轻量 Python Skill，不依赖第三方资讯框架或项目内外部模型接口。DuckDB 是唯一事实源，保存从信源发现、原始响应、正文版本、子 Agent 任务与输出、主 Agent 校验、报告草稿、最终关门校验到报告导出的完整链路；确定性程序负责采集、规范化、去重和合同校验；子 Agent 按文章完成相关性、分类、影响、日期和建议解读；主 Agent 校验后落库并生成日报、周报和月报草稿，再核对整份报告及其引用证据，通过后才允许导出。

第一版以少量高质量官方源为主、中文行业源为线索，先把“原文可追溯、分类准确、最终报告验证、JSON 稳定”四件事做牢，再扩展更多平台、社区、Webhook 和博客展示。
