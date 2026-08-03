---
name: ecom-market-pulse
description: 采集指定公开信源文章；由 Codex 主 agent 调度结构化解读、校验后写入 DuckDB，并生成带来源证据的跨境电商日报、周五 16:00 业务截止周报和月末 16:00 业务截止月报。用于执行或补跑日报、生成本周或历史周报、生成本月或历史月报、执行截止补采、关门校验、导出公开 JSON 和准备严格发布清单。
---

# 跨境电商情报雷达

适用于：采集公开跨境电商资讯、分析已有文章的卖家影响，或生成工作区内的日报、周报、月报。它只把有原文依据的事实转为“钱、货、号、流量、效率、竞争”决策情报。

## 执行前检查

1. 明确 `--workspace`，运行数据只能写入该工作区。
2. 检查 `<workspace>/config.yaml` 存在并通过 `validate-config`。
3. 用户只要求解读已有文章时，不启动网络采集。
4. 分析由当前 Codex 主 agent 并行派发子 agent；每篇只接受符合 `analysis_contract.py` 的 JSON，再由主 agent 校验并落库。

## 日报标题与关门

1. 选出代表文章后，读取 [editorial-title-policy.md](references/editorial-title-policy.md)。
2. 从卖家影响最大的事件中选择一个主事件，可再选择一个不同维度的次事件；生成具体对象加方向动词的新闻编辑式标题，并写入 `narrative.lead.title`。
3. 从现有 `exports/manifest.json` 读取最近七个日报标题，避免重复事件切入点和句式。
4. 在批准 `gate.status = passed` 前调用 `validate_report_editorial_title`；把返回的任何问题视为关门失败，重新拟题后再验证。不得用默认报告名、分类堆砌或公文式风险提示绕过校验。

## 周报固定合同

1. 读取 [output-contract.md](references/output-contract.md) 和 [weekly-editorial-policy.md](references/weekly-editorial-policy.md)；定时任务在周五 16:00 生成本周周报。手动运行选择最近一个已经到达周五 16:00 截止点的工作周，或用户明确指定的历史工作周。
2. 周报汇总周一至周五 5 份日报。每份日报都必须日期匹配、`gate.status = passed`、`gate.issues = []`；缺失时补跑该日期，不能用 `latest.json`、周末或其他日期替代。
3. 周五 16:00 先执行截止增量采集，覆盖周五上午日报生成后至 16:00 的新增资讯；发现新文章时必须重新分析并重建周五日报，不能因为上午版本已经 `passed` 就跳过。
4. 固定输出 `date = period.startDate = 周一`、`period.endDate = 周五`、`windowStart = 周一 00:00:00+08:00`、`windowEnd = 周五 16:00:00+08:00`。`period.isoWeek` 只用于文件名 `weekly/YYYY-Www.json`。
5. 归档名称不展示 ISO 周。以周一 `period.startDate` 在所属月份的位置计算：`第X周`，其中 `X = ((day - 1) // 7) + 1`；例如 `2026-07-20` 必须显示“第3周”。报告正文日期范围直接显示 `period.startDate ～ period.endDate`。
6. 最终关门必须确认 `stats.dailyReports = 5`、`generatedAt >= windowEnd`、`gate.validatedAt >= windowEnd`、日期合同一致且所有主题都有入选文章依据。导出器会再次执行同一合同校验。
7. 周五 16:00 之后及周末首次发现的资讯归入下一业务周的首个合格日报，不能丢弃或回写到已发布周报。
8. 完成交付时必须明确输出：`归档：第X周`、`日期范围：YYYY-MM-DD ～ YYYY-MM-DD`、`数据截止：周五 16:00`，并附本地 JSON 路径和 gate 状态。
9. 五份日报只组成候选集；周报必须先执行不依赖发布日期的跨日 `same-event` 归并，再生成重点展示集。`stats.uniqueEvents` 记录去重后的候选事件数，`sections` 只放重点展示事件。
10. 候选事件不超过 20 个时全部展示；超过 20 个时展示 12～20 个，默认上限 20。每个候选非空分类至少保留一个代表事件；同一主题族不得继续无上限铺陈。
11. 主 Agent 如提交 `narrative.selectedArticleIds`，只能引用候选集 articleId，并必须通过数量、重复 ID、分类覆盖和全部周报扩展字段引用校验；自动推荐结果也执行同一约束。

## 月报固定合同

1. 读取 [output-contract.md](references/output-contract.md)；月报按自然月归档，定时任务在每月最后一个自然日执行，业务数据截止点固定为当天 16:00。
2. 月报只汇总目标月内周一至周五的全部日报。每份日报都必须日期匹配、`gate.status = passed`、`gate.issues = []`；周六、周日不要求日报，缺失的工作日日报必须先补跑。
3. 月末 16:00 必须执行截止增量采集。若月末是工作日，发现新文章时重建当天日报；若月末是周末，截止采集新增的合格文章直接进入月报候选事实层，但不虚构周末日报。
4. 候选集来自目标月全部合格日报与月末截止增量事实，不从周报二次提炼。回到 DuckDB 的文章事实层按事件聚类去重，再形成平台矩阵、成本风险、流量转化、机会与趋势证据。
5. 固定输出 `date = period.startDate = 月初`、`period.endDate = 月末`、`windowStart = 月初 00:00:00+08:00`、`windowEnd = 月末当天 16:00:00+08:00`，并使用 `period.month = YYYY-MM` 生成 `monthly/YYYY-MM.json`。
6. `stats.dailyReports` 必须等于该自然月的周一至周五数量；第一版不计算法定节假日或调休。例如 2026 年 7 月必须是 23 份。
7. 最终关门必须确认 `generatedAt >= windowEnd`、`gate.validatedAt >= windowEnd`、全部工作日日报齐全、扩展字段只引用入选文章、`trendEvidence.eventCount` 与去重后的引用数一致，且 `nextMonthCalendar` 只包含下一个自然月日期。
8. 月末 16:00 之后首次发现的资讯归入下一个业务月，不能丢弃或回写到已发布月报。
9. 完成交付时必须明确输出：`归档：YYYY年M月`、`日期范围：YYYY-MM-DD ～ YYYY-MM-DD`、`数据截止：月末 16:00`、`工作日日报：N/N`，并附本地 JSON 路径和 gate 状态。

## 命令

```bash
python skills/ecom-market-pulse/scripts/pulse.py validate-config --workspace ./runtime
python skills/ecom-market-pulse/scripts/pulse.py collect --workspace ./runtime --since 24h
```

辅助命令：`schema-check`。

## 失败处理与交付说明

- 401、403、验证码或登录页不绕过；记录失败并停止该信源本次采集。
- 抓取和正文提取失败保留审计记录；子 agent 输出不符合合同则不落库。
- 主 agent 核对文章证据与日报引用后才批准导出。
- 日报标题未通过编辑规范时必须拒绝关门；导出器会再次校验标题及最近七期相似度。
- 构建日报、周报或月报时，必须从当前配置中全部 `enabled: true` 的信源生成 `sourceDirectory`；按最终纳入 `sections` 的代表文章计数，`0` 篇仅表示本期未纳入，且信源名称链接必须使用配置的 `homepage_url`。
- 周报交付必须同时报告“第X周”和周一至周五的日期范围；若任一日期字段或 5 份日报覆盖不满足固定合同，必须拒绝导出。
- 周报/月报都必须先做 16:00 截止增量采集；截止点尚未到达、日报缺失或引用不合法时必须拒绝导出。
- 月报交付必须报告自然月日期范围、月末 16:00 截止点和工作日日报覆盖数。
- 完成后报告时间窗口、实际信源、发现/去重/分析/草稿/关门结果和绝对导出路径。
