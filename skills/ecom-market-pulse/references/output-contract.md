# 输出合同与版本

`assets/schemas/article.schema.json` 和 `assets/schemas/report.schema.json` 由 `ecom_market_pulse.models` 生成，是程序校验和对外交付的唯一 JSON Schema 来源。当前版本：

- 文章 `schemaVersion`: `1.0.0`
- 报告 `schemaVersion`: `1.2.0`
- `taxonomyVersion`: `1.0.0`

`1.2.0` 是业务截止合同的当前写入版本。读取端继续兼容既有 `1.1.0` 日报和周报：旧周报沿用周六零点结束，新生成的 `1.2.0` 周报和月报统一使用 16:00 业务截止；月报本身必须使用 `1.2.0`。

文章对象保存来源、规范 URL、采集与发布时间、一个主分类、一至三个影响维度、事实/影响/建议、关键日期、证据、佐证、冲突，以及子 Agent 任务追溯信息。

日报、周报和月报都必须有十个固定分类区块（空分类保留空数组）、关键日期、关门验证和 build 追溯信息。日报统计发现、抓取、独立事件、分析和纳入数量；周报额外保存周期、主题、重复信号、重要变更与下周观察；月报额外保存平台矩阵、成本风险、流量转化、机会、趋势证据和下月日历。

周报周期是固定的五个工作日合同：

- `date` 与 `period.startDate` 必须是同一个周一。
- `period.endDate` 必须是该周周五。
- `windowStart` 必须是周一 `00:00:00+08:00`。
- `windowEnd` 必须是周五 `16:00:00+08:00`。
- `period.isoWeek` 必须由周一计算，且只用于 `weekly/YYYY-Www.json` 文件名。
- 通过关门验证的周报必须满足 `stats.dailyReports = 5`。
- `build.dataCutoffAt` 必须等于 `windowEnd`，且 `generatedAt`、`gate.validatedAt` 都不得早于截止点。

周报还必须区分候选事件集与重点展示集。五份日报 articleId 回查事实层并完成跨日
`same-event` 归并后得到候选事件集，`stats.uniqueEvents` 记录其数量；`sections`
只保存重点展示集。候选不超过 20 个时全部展示，超过 20 个时展示 12～20 个且
不得超过 20。每个候选非空分类至少保留一个代表事件，所有周报扩展字段只能引用
最终 `sections` 中的 articleId。详细判定见
[weekly-editorial-policy.md](weekly-editorial-policy.md)。

公开归档中的“第X周”不是 ISO 周号，也不额外写入报告 JSON。它按周一 `period.startDate` 在所属月份的位置计算：`X = ((day - 1) // 7) + 1`。因此 `2026-07-20` 是“第3周”，`2026-06-29` 是“第5周”。正文日期范围直接由 `period.startDate ～ period.endDate` 渲染。每次周报交付必须明确报告这两个用户可见结果。

月报按自然月归档，并使用月末业务截止合同：

- `date` 与 `period.startDate` 必须是同一个自然月第一天。
- `period.endDate` 必须是同月最后一天，`period.month` 必须为对应的 `YYYY-MM`。
- `windowStart` 必须是月初 `00:00:00+08:00`。
- `windowEnd` 必须是自然月最后一天 `16:00:00+08:00`。
- `stats.dailyReports` 统计目标月周一至周五且已通过关门的日报；第一版不处理法定节假日和调休。
- 通过关门验证的月报必须拥有全部预期工作日日报，完成月末截止增量采集，且 `generatedAt`、`gate.validatedAt` 均不得早于 `windowEnd`。
- `platformMatrix`、`costAndRisk`、`trafficAndConversion`、`opportunities`、`trendEvidence` 和 `nextMonthCalendar` 的文章引用必须存在于本月 `sections`。
- `trendEvidence.eventCount` 必须等于对应 `articleIds` 去重后的数量；`nextMonthCalendar.date` 必须位于紧随报告期之后的自然月。
- 稳定文件名只取 `period.month`，输出为 `monthly/YYYY-MM.json`。

周报在周五 16:00、月报在月末 16:00 都必须先执行截止增量采集。周报需要据此刷新周五日报；月末是周末时不虚构日报，新增文章直接进入月报候选事实层。截止点之后首次发现的资讯顺延到下一业务周期，保证不丢失也不回写已发布报告。

月报不得只基于周报再次提炼。截止点前可以生成 `pending` 草稿用于预检，但到达 16:00 后必须基于截止补采结果重新生成，才能批准 `passed` 和导出。

日报 `lead.title` 还必须通过 [editorial-title-policy.md](editorial-title-policy.md)：使用一至两个可回溯到入选文章的具体事件，长度 18～24 个字符，并与最近七期归档标题保持足够差异。占位报告名、分类堆砌和公文式风险提示不得通过关门或导出。

每份报告还必须提供 `sourceDirectory`。它仅来自运行配置中所有 `enabled: true` 的信源，按配置顺序输出 `id`、`name`、`sourceClass`、`homepageUrl` 与 `articleCount`。`articleCount` 统计最终进入 `sections[].items[]` 的代表文章，因此 `0` 表示本期没有被纳入报告，不表示该信源失效或没有抓到内容。报告构建时，任何入选文章若没有对应的已启用信源配置，必须失败，不能用不完整目录继续导出。

只有 `gate.status = "passed"` 的报告可以导出 JSON；Markdown 仅按需从同一份已通过 JSON 渲染。`rejected` 报告保留草稿和问题，但不得发布。
