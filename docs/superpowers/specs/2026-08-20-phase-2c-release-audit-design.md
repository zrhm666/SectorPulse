# Phase 2C：发布前核准、导出与审计设计

## 目标

在 Phase 2B 的编辑与治理基础上，提供“核准并复制”的人工发布前流程：只有通过治理检查的草稿版本才能被人工核准；核准动作、复制导出和撤销都留下可重放审计记录。系统仍只生成草稿、复制和导出内容，不接入任何平台账号或自动发布。

## 核心流程

```text
草稿版本 -> 治理复检 -> READY_FOR_HUMAN_REVIEW -> 人工核准 -> APPROVED_FOR_COPY -> 复制/导出
                                      \-> 驳回/撤销 -> 返回审核
```

- 核准绑定 `draft_id + version + governance_check_hash`，旧版本不可被“就地核准”。
- 治理不通过时，核准接口返回 409/422，并且不改变草稿状态。
- 导出只读取已核准版本；Markdown、纯文本和结构化 JSON 共用同一个版本快照。
- 每次核准、撤销、导出、复制记录 actor、时间、版本、内容 hash 和结果，不记录 API Key 或完整 Prompt。

## 持久化

新增 migration 010：`draft_approvals`、`draft_exports`、`audit_events`。审计事件追加写入、禁止更新和删除；审批唯一约束为 `draft_id + version`，撤销通过新事件表达。

## API

```text
POST /api/runs/{run_id}/drafts/{draft_id}/approve
POST /api/runs/{run_id}/drafts/{draft_id}/revoke
GET  /api/runs/{run_id}/drafts/{draft_id}/approval
GET  /api/runs/{run_id}/drafts/{draft_id}/audit
GET  /api/runs/{run_id}/drafts/{draft_id}/export.json
```

## 验收边界

- 治理未通过不能核准。
- 核准只作用于指定版本，后续 Patch 自动使其回到审核态。
- 回滚、撤销和导出不删除历史。
- 前端显示当前版本、核准状态、审计时间线和导出按钮。
- 全量后端、前端测试与构建通过；不调用真实 LLM。
