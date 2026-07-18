---
name: ecom-market-pulse
description: 采集指定公开信源文章；由 Codex 主 agent 并行调度子 agent 做结构化解读、校验后写入 DuckDB，并生成带来源证据的跨境电商日报。
---

# 跨境电商情报雷达

适用于：采集公开跨境电商资讯、分析已有文章的卖家影响，或生成工作区内的日报、周报、月报。它只把有原文依据的事实转为“钱、货、号、流量、效率、竞争”决策情报。

## 执行前检查

1. 明确 `--workspace`，运行数据只能写入该工作区。
2. 检查 `<workspace>/config.yaml` 存在并通过 `validate-config`。
3. 用户只要求解读已有文章时，不启动网络采集。
4. 分析由当前 Codex 主 agent 并行派发子 agent；每篇只接受符合 `analysis_contract.py` 的 JSON，再由主 agent 校验并落库。

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
- 完成后报告时间窗口、实际信源、发现/去重/分析/草稿/关门结果和绝对导出路径。
