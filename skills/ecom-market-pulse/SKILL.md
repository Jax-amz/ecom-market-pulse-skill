---
name: ecom-market-pulse
description: 采集指定公开信源文章；由 Codex 主 agent 调度结构化解读、校验后写入 DuckDB，并生成带来源证据的跨境电商日报、五个工作日周报和月报。用于执行或补跑日报、汇总周一至周五周报、生成月报、关门校验、导出公开 JSON 和准备严格发布清单。
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

1. 读取 [output-contract.md](references/output-contract.md)；目标周期只能是上一完整工作周或用户明确指定的历史工作周。
2. 周报只汇总周一至周五 5 份日报。每份日报都必须日期匹配、`gate.status = passed`、`gate.issues = []`；缺失时补跑该日期，不能用 `latest.json`、周末或其他日期替代。
3. 固定输出 `date = period.startDate = 周一`、`period.endDate = 周五`、`windowStart = 周一 00:00:00+08:00`、`windowEnd = 周六 00:00:00+08:00`。`period.isoWeek` 只用于文件名 `weekly/YYYY-Www.json`。
4. 归档名称不展示 ISO 周。以周一 `period.startDate` 在所属月份的位置计算：`第X周`，其中 `X = ((day - 1) // 7) + 1`；例如 `2026-07-20` 必须显示“第3周”。报告正文日期范围直接显示 `period.startDate ～ period.endDate`。
5. 最终关门必须确认 `stats.dailyReports = 5`、日期合同一致且所有主题都有入选文章依据。导出器会再次执行同一合同校验。
6. 完成交付时必须明确输出两行简洁结果：`归档：第X周`、`日期范围：YYYY-MM-DD ～ YYYY-MM-DD`，并附本地 JSON 路径和 gate 状态；不要用 `period.isoWeek` 代替用户可见周序。

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
- 完成后报告时间窗口、实际信源、发现/去重/分析/草稿/关门结果和绝对导出路径。
