-- 跨境电商情报脉冲 DuckDB 唯一事实源。
-- 本文件只定义六张业务表；可安全重复执行。

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

COMMENT ON TABLE analyses IS '子 Agent 对文章的结构化资讯解读';
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
COMMENT ON COLUMN analyses.prompt_version IS '子 Agent 任务模板版本（兼容历史字段名）';
COMMENT ON COLUMN analyses.prompt_text IS '本次分派给子 Agent 的完整任务说明（兼容历史字段名）';
COMMENT ON COLUMN analyses.output_schema_version IS '输出 JSON Schema 版本';
COMMENT ON COLUMN analyses.model IS '执行器标识（兼容历史字段名）';
COMMENT ON COLUMN analyses.request_json IS '脱敏后的完整子 Agent 任务包';
COMMENT ON COLUMN analyses.response_json IS '子 Agent 原始输出';
COMMENT ON COLUMN analyses.analysis_json IS '符合文章 JSON 合同的完整解读结果';
COMMENT ON COLUMN analyses.input_tokens IS '输入 token 数';
COMMENT ON COLUMN analyses.output_tokens IS '输出 token 数';
COMMENT ON COLUMN analyses.duration_ms IS '子 Agent 分析耗时，单位毫秒';
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
COMMENT ON COLUMN reports.gate_status IS '最终 Agent 关门验证状态';
COMMENT ON COLUMN reports.gate_json IS '最终关门验证的执行器、任务模板、任务结果、问题列表和验证时间';
COMMENT ON COLUMN reports.content_sha256 IS '报告内容哈希';
COMMENT ON COLUMN reports.generated_at IS '报告生成时间';
