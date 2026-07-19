# 跨境电商情报雷达（ecom-market-pulse）

一个面向跨境电商卖家的、可追溯的公开资讯采集与决策情报 Skill。

它不做新闻搬运站，也不试图用一段没有来源的 AI 总结替代判断：系统把公开信源中的文章采集到本地 DuckDB，保留原始抓取记录、正文版本和来源 URL；后续由 Codex 主 Agent 调度子 Agent 做结构化解读，并在报告导出前执行最终关门校验。每条进入报告的结论都应能回溯到具体原文和处理记录。

> 当前版本：`0.1.0`。这是一个 **Codex Skill**，推荐部署到 Codex 并通过 Codex 的主 Agent 执行；Python 脚本是 Skill 的运行实现，不是面向业务用户的首选操作入口。稳定 CLI 已支持配置校验、公开资讯采集与数据库结构校验；文章 AI 解读、日报/周报/月报草稿、关门验证和受控导出已提供为 Python 模块。部署前请先阅读下方的[当前能力边界](#当前能力边界)。

## 目录

- [项目背景](#项目背景)
- [核心能力](#核心能力)
- [当前能力边界](#当前能力边界)
- [整体流程](#整体流程)
- [在 Codex 中部署与首次启用](#在-codex-中部署与首次启用)
- [配置说明](#配置说明)
- [在 Codex 中使用](#在-codex-中使用)
- [AI 分析与报告接入](#ai-分析与报告接入)
- [Codex 定时任务与手动备用](#codex-定时任务与手动备用)
- [数据、审计与安全](#数据审计与安全)
- [常见问题](#常见问题)
- [项目结构](#项目结构)
- [参考资料与许可证](#参考资料与许可证)

## 项目背景

跨境卖家真正需要的不是更多资讯，而是能影响经营决策的、可验证的变化。例如 Amazon 政策何时生效、FBA 费用是否变化、广告能力是否更新、是否存在合规风险、物流或竞争平台是否出现新的机会。

这类信息经常分散在官方公告、平台 RSS、行业媒体和社区讨论中，人工浏览存在三个问题：

1. **时效与覆盖难兼顾**：高价值信息散落在多个站点，固定人工巡检容易遗漏。
2. **结论难以复核**：二次转述常丢失原文、发布日期和适用范围，导致错误判断费用、政策或截止日期。
3. **资讯与动作脱节**：标题和摘要无法直接回答“影响谁、影响什么、需要关注什么”。

本项目将公开资讯转化为围绕六个卖家决策维度的情报：**钱、货、号、流量、效率、竞争**。它采用轻量本地架构：Python 负责采集、正文提取、规范化、去重和存储；DuckDB 负责单文件审计数据；Codex 主 Agent 与子 Agent 负责受约束的业务解读和报告关门验证。

## 核心能力

### Codex 可直接调用的基础能力

| 能力 | 说明 |
| --- | --- |
| 配置校验 | 在采集前校验 YAML、时区、信源 ID、公开 URL、采集参数和分类提示。 |
| 公开信源采集 | 内置 RSS/Atom、普通 HTML 列表、Sitemap，以及 Amazon 全球开店中国站、Amazon Ads What's New、AMZ123 跨境早报适配器。 |
| 合规抓取 | 按单域名限速、超时和有限重试；遇到 401、403、登录页或验证码不绕过、不重试规避。 |
| 正文提取与规范化 | 提取标题、作者、发布时间、canonical URL、正文和 HTML，保留原始响应审计记录。 |
| 幂等去重 | 以 `canonical URL + 正文哈希` 去重，并生成事件键，重复运行不会重复写入相同文章版本。 |
| 本地审计库 | 运行、信源、抓取、文章、分析和报告统一保存在工作区内的 DuckDB 单文件中。 |
| 结构化运行结果 | 底层执行会输出机器可读 JSON，包含运行 ID、阶段计数、警告与导出信息，供 Codex 汇总为交付说明。 |

### 已提供的后续能力模块

| 能力 | 约束与用途 |
| --- | --- |
| 子 Agent 任务合同 | 为每篇文章生成最小化任务载荷；只接受符合 Pydantic 合同的 JSON，防止把自然语言直接当作系统输入。 |
| 十类业务分类 | 覆盖 Amazon 政策、FBA、费用税务、广告流量、Listing/VOC、合规/IP、物流、竞品平台、AI 工具、社区信号。 |
| 卖家影响分析 | 相关文章必须选择 1 个主分类和 1～3 个影响维度，并给出事实、影响、建议关注事项和原文证据。 |
| 报告构建 | 可构建日报、周报和月报草稿，固定保留十个分类区块、关键日期、统计和构建追溯信息。 |
| 关门验证与导出 | 只有 `gate.status = "passed"` 的报告允许导出 JSON；Markdown 只从同一份已通过的 JSON 生成。 |

## 当前能力边界

这一节非常重要：仓库内的技术设计描述了完整目标，但实际部署必须以当前代码入口为准。

| 项目 | 当前状态 |
| --- | --- |
| `validate-config` | 由 Codex 在执行前调用的底层校验命令；也可在开发排障时手动运行。 |
| `collect` | 由 Codex Skill 调用的底层采集命令，执行发现、抓取、提取、去重和落库，不调用任何模型 API。 |
| `schema-check` | 由 Codex 调用的底层数据库结构校验命令；也可用于开发排障。 |
| 子 Agent 调用 | 由 Codex 主 Agent 调度；提供任务构建、返回值校验和数据库接口，子 Agent 不直接写库或发布。 |
| 日报/周报/月报 | 提供构建、关门结果合并、受控导出模块；目前没有 `build`、`retry` 或“一键全流程” CLI。 |
| Web 管理后台、用户权限、订阅推送 | 本期不提供。 |
| 登录站点、付费墙、验证码或反爬绕过 | 明确不支持，也不应扩展为绕过。 |

因此，业务使用时应在 Codex 中显式调用本 Skill，而不是把 `pulse.py` 当成独立应用入口。若要自动产生正式日报/周报/月报，仍需在现有模块之上补齐 Agent 编排与报告命令；请不要在任何自动化中假定 `pulse.py build` 已可用。

## 整体流程

```text
工作区 config.yaml
        │
        ▼
信源发现（RSS / HTML / Sitemap / 专用适配器）
        │
        ▼
公开 HTTP 抓取（限速、超时、有限重试）
        │
        ▼
正文提取与规范化（标题、日期、canonical URL、正文）
        │
        ▼
URL / 正文哈希去重、事件键生成
        │
        ▼
DuckDB：runs / sources / fetches / articles
        │
        ├──► Codex 主 Agent → 子 Agent 结构化分析 → analyses
        │                                         │
        └─────────────────────────────────────────┘
                                                  ▼
                               日报/周报/月报草稿 → 关门校验
                                                  │
                                                  ├──► 通过：JSON / Markdown
                                                  └──► 拒绝：只保留审计记录，不导出
```

## 在 Codex 中部署与首次启用

### 推荐方式：作为仓库级 Codex Skill 使用

本仓库的 Skill 源码位于 `skills/ecom-market-pulse/`。Codex 推荐从仓库的 `.agents/skills/` 发现团队 Skill，因此首次接入时，在仓库根目录建立一个指向源码的链接：

```bash
mkdir -p .agents/skills
ln -s ../../skills/ecom-market-pulse .agents/skills/ecom-market-pulse
```

这样做不会复制出第二份 Skill；后续修改 `skills/ecom-market-pulse/` 后，当前项目中的 Codex 会读取同一份内容。关闭并重新打开 Codex 项目（或新建会话）后，在 Skills 面板或 `/skills` 中确认已出现 `ecom-market-pulse`。

如果你希望在多个仓库中使用，可将同一目录链接到个人 Skill 目录：`~/.agents/skills/ecom-market-pulse`。本机已有其他 Codex Skill 部署目录时，沿用已有的用户级目录即可；关键是 Skill 文件夹内必须直接包含 `SKILL.md`。

> 不建议把 `skills/ecom-market-pulse/` 单独复制到一个脱离本仓库的目录后就直接运行。它依赖同仓库的 `pyproject.toml`、脚本和资源；开发期使用符号链接能避免 Skill、Python 代码和配置样例版本漂移。

### 由 Codex 完成首次初始化

在 Codex 中打开本仓库后，直接发送下面的提示词。它会让 Codex 安装运行依赖、建立工作区、复制示例配置并进行校验；用户无需手工敲 Python 采集命令。

```text
请使用 $ecom-market-pulse Skill 为当前项目完成首次初始化：
1. 按 pyproject.toml 准备 Python 3.11+ 的项目运行环境；
2. 创建 ./runtime，并从 assets/config.example.yaml 生成 ./runtime/config.yaml；
3. 仅执行配置校验和数据库结构校验，不要启动网络采集；
4. 报告已启用信源、工作区绝对路径和发现的配置问题。
```

运行数据始终放在 `--workspace` 对应目录，而不是 Skill 安装目录：

```text
runtime/
├── config.yaml                       # 你维护的信源配置
└── data/
    └── ecom_market_pulse.duckdb      # 首次校验或采集后自动创建
```

首次初始化的前置条件仅有：Python `3.11+`、可访问已配置的公开信源，以及足够的本地磁盘空间。项目无需部署 Web 服务、Docker 容器或常驻后端。

## 配置说明

### `config.yaml` 的最小结构

请以 [config.example.yaml](skills/ecom-market-pulse/assets/config.example.yaml) 为起点。每个信源都必须有唯一的 `id`、来源级别、发现方式、采集策略和内容时区。

```yaml
timezone: Asia/Shanghai

sources:
  - id: about-amazon
    name: About Amazon
    enabled: true
    source_class: official
    discovery:
      type: rss
      url: https://www.aboutamazon.com/rss/feed.rss
      max_items: 20
    category_hints: [amazon-policy]
    fetch:
      interval_minutes: 120
      requests_per_minute: 10
      timeout_seconds: 20
      max_retries: 2
    content:
      language: en
      timezone: UTC
```

### 字段说明

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `timezone` | 否 | 工作区业务时区，默认 `Asia/Shanghai`。 |
| `sources[].id` | 是 | 小写字母、数字和连字符组成的唯一稳定 ID，例如 `amazon-ads-whats-new`。 |
| `name` | 是 | 报告与审计中展示的来源名称。 |
| `enabled` | 是 | 是否参与本次采集。遇到问题可先改为 `false`，无需删除配置。 |
| `source_class` | 是 | `official`、`professional-media`、`community`、`aggregator` 四选一。 |
| `discovery.type` | 是 | `rss`、`html`、`sitemap`，或项目内置的专用适配器类型。 |
| `discovery.url` | 是 | 可公开访问的完整 `http`/`https` 地址。 |
| `discovery.max_items` | 否 | 单次最多发现的候选条数。 |
| `category_hints` | 是 | 1～3 个分类提示，只用于采集线索，不替代后续文章分析分类。 |
| `fetch` | 是 | 单信源抓取间隔建议、每分钟请求数、超时和最大重试次数。 |
| `content` | 是 | 来源内容的语言和原站时区，用于解析发布时间。 |

### 支持的信源类型

| `discovery.type` | 用途 | 额外配置 |
| --- | --- | --- |
| `rss` | RSS 或 Atom 订阅源 | 一般只需 `url` 与可选 `max_items`。 |
| `html` | 普通资讯列表页 | 需要提供列表、链接、标题、日期等 CSS 选择器。 |
| `sitemap` | 网站 Sitemap | 可设置 `url_pattern`、`include_regex`、`exclude_regex`、`max_sitemaps`。 |
| `amazon-global-selling-cn` | Amazon 全球开店中国站新闻 | 使用示例配置中的公开入口。 |
| `amazon-ads-whats-new` | Amazon Ads What's New | 使用示例配置中的公开入口。 |
| `amz123-zb` | AMZ123 跨境早报 | 使用示例配置中的公开入口。 |

新增 HTML 信源的示例：

```yaml
- id: example-industry-news
  name: 示例行业媒体
  enabled: false
  source_class: professional-media
  discovery:
    type: html
    url: https://example.com/news
    max_items: 20
    selectors:
      item: ".news-list article"
      link: "a"
      title: "h2"
      date: "time"
  category_hints: [competitor-marketplaces]
  fetch:
    interval_minutes: 240
    requests_per_minute: 4
    timeout_seconds: 20
    max_retries: 2
  content:
    language: zh
    timezone: Asia/Shanghai
```

配置校验会拒绝未知字段、非法时区、重复 ID、非公开 URL、空选择器和非法正则。YAML 字符串中可以使用 `${VARIABLE_NAME}` 插入环境变量；未设置或为空会在校验阶段失败。基础公开采集不需要 API Key、Cookie 或登录凭据。

### 分类与信源规则

文章分析的十个一级分类、冲突优先级和六个影响维度见 [taxonomy.md](skills/ecom-market-pulse/references/taxonomy.md)。信源可信度规则见 [source-policy.md](skills/ecom-market-pulse/references/source-policy.md)：

- `official` 可作为政策、金额和日期的主来源；
- `professional-media` 可报道事件，但政策、金额和日期应尽量回溯官方原文；
- `community` 仅作为异常信号，未经独立证实不能写成已确认事实；
- `aggregator` 仅作发现线索，不应进入正式日报。

## 在 Codex 中使用

### 显式调用 Skill

业务操作通过 Codex 对话发起。将 `$ecom-market-pulse` 写入提示词可避免依赖自动匹配；Codex 会读取 `SKILL.md`、使用其中的脚本和引用资料，并在当前项目内执行必要的命令。

**常规增量采集：**

```text
请使用 $ecom-market-pulse Skill 采集 ./runtime 中最近 24 小时的公开跨境电商资讯。
先校验 config.yaml；只使用其中启用的公开信源；不要绕过登录、验证码或反爬。
完成后告诉我：实际时间窗口、使用和失败的信源、发现/抓取/提取/去重数量、runId，以及工作区绝对路径。
```

**新增信源或修改配置后的验证：**

```text
请使用 $ecom-market-pulse Skill 检查 ./runtime/config.yaml。
只做配置校验和数据库结构校验，不进行网络采集；如果配置有问题，请指出具体字段和修复建议。
```

**只解读已有数据、不启动网络采集：**

```text
请使用 $ecom-market-pulse Skill 只读取 ./runtime 里已经采集的文章，
按卖家经营影响做结构化解读。不要启动新的网络采集；所有事实必须保留 sourceUrl 证据。
```

同一工作区可被 Codex 反复使用。相同 `canonical URL + content SHA-256` 的文章会被视为重复；网页正文改变时，系统会保存为新的文章版本，便于追溯内容修订。

### 让 Codex 查看审计数据

不要直接打开或传播 DuckDB 文件。需要查看运行情况时，向 Codex 发起只读请求即可：

```text
请只读检查 ./runtime/data/ecom_market_pulse.duckdb：
列出最近 10 次运行的 runId、状态、时间窗口和统计；再列出最近 20 篇文章的标题、发布时间和 sourceUrl。
不要修改数据库，也不要展示原始正文或响应体。
```

原始抓取响应可能包含受网站版权保护的内容；对外沟通应使用带来源 URL 的摘要与已验证结论，不应直接导出大段原文。

## AI 分析与报告接入

当前仓库的设计刻意将“确定性采集”与“Agent 判断”分开：底层 `collect` 不调用模型，因此不会在定时抓取时意外产生模型费用或未审计的结论。**推荐由 Codex 主 Agent 承担后续编排**，而不是把这一部分拆给 cron 或独立脚本。

Codex 主 Agent 的完整处理顺序如下：

1. 从 `Database.list_articles_for_analysis()` 读取待分析文章。
2. 使用 `agent_orchestrator.build_agent_task(article)` 生成只包含文章必要字段的子 Agent 任务。
3. 子 Agent 必须只依据正文返回 JSON；主 Agent 使用 `validate_agent_output(payload)` 校验合同后，才调用 `Database.upsert_analysis(...)` 记录结果。
4. 从已完成、相关文章分析中按统计周期读取数据，调用 `reports.builder.build_report_draft(...)` 构建草稿。
5. 主 Agent 结合 `reports.builder.collect_evidence(...)` 对完整草稿和证据做最终关门校验，并通过 `apply_gate_result(...)` 写入 `passed` 或 `rejected` 结果。
6. 仅当状态为 `passed`，才调用 `exporters.report_exporter.export_passed_report(...)` 写出 JSON；若需要人读版，再同时生成 Markdown。

这条链路的关键约束：

- 子 Agent 不直接写数据库、不直接发布报告；
- 事实、影响判断和建议关注事项必须分离；
- 无关文章只返回排除原因，不能伪造分类；
- 未通过关门验证的报告只能留在审计库中，不能导出或发布；
- 具体 JSON 字段以 [output-contract.md](skills/ecom-market-pulse/references/output-contract.md) 和 `assets/schemas/` 为准。

## Codex 定时任务与手动备用

### 推荐：在 Codex 中创建定时任务

对于“每两小时采集”“每天生成简报”这类持续工作，优先使用 ChatGPT 桌面端或 Web 的 **Scheduled** 创建任务，并在任务提示词中显式指定 `$ecom-market-pulse`。本项目依赖本地工作区和 DuckDB，因此优先选择能在本地项目目录运行的桌面端定时任务；运行本地项目时，需要保持电脑与桌面应用可用。

先在普通 Codex 对话中完整测试一次，再创建定时任务。推荐的采集任务提示词如下：

```text
在本地项目 ecom-market-pulse-skill 中执行 $ecom-market-pulse Skill：
使用 ./runtime 作为唯一工作区，先校验配置，再采集过去 3 小时的公开资讯。
不得绕过登录、验证码、付费墙或反爬；仅使用已启用信源。
完成后给出运行统计、失败信源、runId 和工作区绝对路径。
如果配置校验失败，停止采集并报告字段级原因。
```

建议频率：官方 RSS/公告每 2 小时一次，普通 HTML 列表每 4 小时一次。当前底层采集器不会自动依据 `fetch.interval_minutes` 跳过某个信源，因此应在 Codex 定时任务层控制频率，并避免同一工作区的任务并发执行。

> 不推荐用 cron 或 systemd 作为正式业务主路径：它们只能启动底层 Python 采集，无法天然保留 Codex 的上下文、子 Agent 编排、报告关门验证和交互式异常处理。只有在 CI、无 Codex 环境或底层采集调试时才考虑手动命令。

### 手动 Python：仅开发、CI 与故障排查备用

当 Codex 不可用、需要调试采集器，或在 CI 中验证基础采集时，可以直接运行底层命令。它只覆盖确定性配置校验、采集和结构校验，不替代 Codex 的 Agent 分析流程：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .

mkdir -p runtime
cp skills/ecom-market-pulse/assets/config.example.yaml runtime/config.yaml
python skills/ecom-market-pulse/scripts/pulse.py validate-config --workspace ./runtime
python skills/ecom-market-pulse/scripts/pulse.py collect --workspace ./runtime --since 24h
```

底层命令的退出码：`0` 为成功，`2` 为配置/运行错误，`3` 表示报告关门校验被拒绝（当前采集命令不会产生该状态）。如需只读排障，可让 Codex 查询 DuckDB；不要在业务操作中直接修改数据库。

### 更新、回滚与备份

更新 Skill 后应重新打开 Codex 项目或新建会话，让 Codex 重新加载 `SKILL.md`。在变更配置、升级代码或恢复历史版本前，先让 Codex 备份 `runtime/config.yaml` 和 `runtime/data/ecom_market_pulse.duckdb`；运行数据位于独立工作区，不会随着代码检出而删除。恢复数据库前应暂停同一工作区的定时任务，避免读写竞争。

## 数据、审计与安全

### DuckDB 六张核心表

| 表 | 保存内容 |
| --- | --- |
| `sources` | 信源配置快照、启用状态和采集断点。 |
| `runs` | 每次采集、分析、报告运行的时间窗口、状态、统计和结构化事件。 |
| `fetches` | 每次候选文章抓取的 URL、响应状态、响应头、原始响应、哈希、耗时和错误。 |
| `articles` | 提取后的 canonical URL、标题、正文、发布时间、正文哈希和事件键。 |
| `analyses` | 子 Agent 的结构化分析、输入/输出审计、模型、版本、证据和状态。 |
| `reports` | 报告草稿、版本、引用文章、关门结果、最终 JSON 和 Markdown。 |

### 安全与合规原则

- 仅采集公开可访问内容，遵守网站服务条款、robots 与速率限制。
- 不传入登录凭据，不绕过 401、403、验证码、付费墙或反爬挑战。
- 审计数据会对 API Key、Authorization、Cookie、Token、密码等敏感字段做脱敏；仍不应将数据库文件公开上传。
- 政策、费用、税务、法律等结论必须保留官方原文链接，最终解释以官方文件为准。
- 根目录 `.gitignore` 已忽略运行目录、数据库、备份、导出物、临时文件、`.env` 和虚拟环境；不要强行将这些文件提交到 Git。

## 常见问题

### `ModuleNotFoundError: No module named 'yaml'`

这是项目 Python 运行环境尚未准备好的提示。不要直接在终端反复尝试采集；在 Codex 中发送“请使用 `$ecom-market-pulse` 为当前项目按 `pyproject.toml` 安装运行依赖，然后仅做配置校验”，让 Codex 完成环境修复和验证。只有在开发/CI 备用模式下，才按上文的手动 Python 步骤处理。

### 某信源返回 401、403、登录页或验证码

这是预期的合规终止行为。采集器不会尝试伪造 Cookie、登录、代理或绕过验证；请禁用该信源、寻找公开 RSS/官方公告入口，或确认站点授权方式后再设计合法集成。

### 采集结果为 0 条

依次检查：

1. `validate-config` 是否成功，且信源为 `enabled: true`；
2. Codex 提示词中的采集时间窗口是否过窄；
3. 目标 RSS/列表页是否近期没有内容或发布时间无法解析；
4. Codex 返回的运行结果中，`warnings` 是否显示发现失败；
5. 页面是否已改版，导致 HTML 选择器或专用适配器失效。

### `duplicates` 很多，是不是数据丢了？

不是。系统以 canonical URL 和正文哈希进行幂等去重。定时采集时反复发现同一篇文章是正常的；统计为重复意味着已保留的文章版本被安全复用。

### 为什么 `pulse.py build` 或 `retry` 不可用？

它们出现在完整技术设计的规划中，但当前 CLI 尚未实现。当前可用命令只有 `validate-config`、`collect` 与 `schema-check`。正式报告应通过上文的 Agent 编排与报告模块接入，或先完成对应 CLI 的实现。

### 我可以直接把原文导出为日报吗？

不建议。系统的目标是生成带引用的结构化情报，而不是再发布原文。对外输出应保留 `sourceUrl`、来源名、摘要和经过验证的结论，避免大段复制受版权保护的文章内容。

## 项目结构

```text
ecom-market-pulse-skill/
├── README.md
├── pyproject.toml                         # Python 包与依赖定义
├── docs/
│   └── technical-design.md                # 完整产品与技术设计基线
└── skills/
    └── ecom-market-pulse/
        ├── SKILL.md                       # Codex Skill 触发与执行约定
        ├── assets/
        │   ├── config.example.yaml        # 可直接复制的配置示例
        │   └── schemas/                    # 对外文章/报告 JSON Schema
        ├── references/
        │   ├── taxonomy.md                 # 十类业务分类和影响维度
        │   ├── source-policy.md            # 信源准入与合规边界
        │   └── output-contract.md          # 输出合同与版本规则
        └── scripts/
            ├── pulse.py                   # 稳定 CLI 入口
            └── ecom_market_pulse/
                ├── collectors/            # RSS、HTML、Sitemap 与专用适配器
                ├── reports/               # 报告草稿构建
                ├── exporters/             # JSON / Markdown 受控导出
                ├── config.py              # YAML 校验与环境变量插值
                ├── database.py            # DuckDB 数据访问与审计
                ├── pipeline.py            # 确定性采集流程
                ├── agent_orchestrator.py  # 子 Agent 任务与合同校验
                └── schema.sql             # 六张核心业务表
```

## 参考资料与许可证

- [完整技术设计](docs/technical-design.md)：产品边界、数据模型、报告合同、验收标准与演进计划。
- [Skill 使用约定](skills/ecom-market-pulse/SKILL.md)：Codex 触发条件、执行前检查与交付要求。
- [Codex Skills 官方说明](https://learn.chatgpt.com/docs/build-skills.md)：Skill 的发现范围、显式调用与本地开发约定。
- [Codex Scheduled 官方说明](https://learn.chatgpt.com/docs/automations.md)：在 Codex 中创建和管理定时任务。
- [信源与采集边界](skills/ecom-market-pulse/references/source-policy.md)：公开采集与合规规则。
- [输出合同](skills/ecom-market-pulse/references/output-contract.md)：文章与报告的 Schema 版本和导出规则。
- [GPL-3.0 许可证](LICENSE)：本项目以 GNU General Public License v3.0 发布。
