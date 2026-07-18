# 输出合同与版本

`assets/schemas/article.schema.json` 和 `assets/schemas/report.schema.json` 由 `ecom_market_pulse.models` 生成，是程序校验和对外交付的唯一 JSON Schema 来源。当前版本：

- `schemaVersion`: `1.0.0`
- `taxonomyVersion`: `1.0.0`

文章对象保存来源、规范 URL、采集与发布时间、一个主分类、一至三个影响维度、事实/影响/建议、关键日期、证据、佐证、冲突，以及子 Agent 任务追溯信息。

日报、周报和月报都必须有十个固定分类区块（空分类保留空数组）、关键日期、关门验证和 build 追溯信息。日报统计发现、抓取、独立事件、分析和纳入数量；周报额外保存周期、主题、重复信号、重要变更与下周观察；月报额外保存平台矩阵、成本风险、流量转化、机会、趋势证据和下月日历。

只有 `gate.status = "passed"` 的报告可以导出 JSON；Markdown 仅按需从同一份已通过 JSON 渲染。`rejected` 报告保留草稿和问题，但不得发布。
