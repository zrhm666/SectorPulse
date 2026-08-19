# Phase 2C 验收记录

## 已验证

- 审批绑定 `draft_id + version`，治理不通过返回 422，不能核准。
- 撤销核准追加审计事件，不删除历史版本。
- 未核准版本导出返回 409；核准后 JSON 导出记录内容 hash 和导出事件。
- 前端在治理 PASS 时启用“核准并允许复制”，支持撤销和 JSON 导出。

## 验证结果

- 后端：168 passed（unit、integration、e2e）。
- Ruff：All checks passed。
- 前端：13 passed。
- 前端生产构建成功。
- 未调用真实 LLM，未发生外部发布。

## 产品边界

Phase 2C 仍是草稿、复制、导出和人工发布流程，不接入账号、平台发布 API 或自动发布。
