# 输出合同与版本

`assets/schemas/article.schema.json` 和 `assets/schemas/report.schema.json` 由 `ecom_market_pulse.models` 生成，是程序校验和对外交付的唯一 JSON Schema 来源。当前版本：

- 文章 `schemaVersion`: `1.0.0`
- 报告 `schemaVersion`: `1.1.0`
- `taxonomyVersion`: `1.0.0`

文章对象保存来源、规范 URL、采集与发布时间、一个主分类、一至三个影响维度、事实/影响/建议、关键日期、证据、佐证、冲突，以及子 Agent 任务追溯信息。

日报、周报和月报都必须有十个固定分类区块（空分类保留空数组）、关键日期、关门验证和 build 追溯信息。日报统计发现、抓取、独立事件、分析和纳入数量；周报额外保存周期、主题、重复信号、重要变更与下周观察；月报额外保存平台矩阵、成本风险、流量转化、机会、趋势证据和下月日历。

日报 `lead.title` 还必须通过 [editorial-title-policy.md](editorial-title-policy.md)：使用一至两个可回溯到入选文章的具体事件，长度 18～24 个字符，并与最近七期归档标题保持足够差异。占位报告名、分类堆砌和公文式风险提示不得通过关门或导出。

每份报告还必须提供 `sourceDirectory`。它仅来自运行配置中所有 `enabled: true` 的信源，按配置顺序输出 `id`、`name`、`sourceClass`、`homepageUrl` 与 `articleCount`。`articleCount` 统计最终进入 `sections[].items[]` 的代表文章，因此 `0` 表示本期没有被纳入报告，不表示该信源失效或没有抓到内容。报告构建时，任何入选文章若没有对应的已启用信源配置，必须失败，不能用不完整目录继续导出。

只有 `gate.status = "passed"` 的报告可以导出 JSON；Markdown 仅按需从同一份已通过 JSON 渲染。`rejected` 报告保留草稿和问题，但不得发布。
