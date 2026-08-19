# Phase 2D：审核指标与审计报表设计

## 目标

在 Phase 2C 的核准、导出和审计事件基础上，提供单机可用的审核运营视图：按运行、草稿版本和时间范围统计审核耗时、修订次数、治理阻断、核准率、导出次数与失败原因，帮助用户定位数据或写作流程瓶颈。

## 边界

- 只读指标与报表，不改变事实、证据和治理规则。
- 不引入账号体系、远程埋点、自动发布或第三方分析服务。
- 所有指标由 SQLite 审计事件、Patch、治理检查和运行记录确定性计算。

## 指标

- `review_duration_seconds`：首次进入审核到核准/撤销的时长。
- `patch_count` / `revision_rounds`：版本和 Patch 数量。
- `governance_failures`：治理失败次数及规则代码。
- `approval_rate`：进入审核的版本中最终核准比例。
- `export_count`：按格式统计导出次数。
- `llm_cost_cny`：沿用 agent invocation 已记录成本，不重新估算。

## API 与报表

```text
GET /api/analytics/summary?from=...&to=...
GET /api/analytics/runs/{run_id}
GET /api/analytics/runs/{run_id}/report.json
```

响应只包含聚合值、状态和审计事件引用，不返回 API Key、Prompt 或模型原始响应。空范围返回零值报告。

## 验收

- 从真实持久化 Patch、审批、导出和治理记录计算稳定指标。
- 时间边界使用 UTC 且包含起始、不包含结束。
- 前端显示审核摘要、最近运行和失败原因。
- 后端全量测试、Ruff、前端测试和构建通过。
