# 运行对比验收记录

日期：2026-09-07  
分支：`codex/run-comparison`  
范围：运行对比只读后端、对照工作台、双数据库回归与浏览器验收。

## 结果

本轮功能在隔离分支完成本地验收。SQLite 与原生 PostgreSQL 均覆盖运行历史、候选板块、新闻成员、板块证据和只读 HTTP 查询；前端覆盖选择、交换、URL 恢复、分页、错误与响应式布局。

## 验证证据

| 检查 | 结果 |
| --- | --- |
| 后端普通回归 | 400 passed, 14 skipped, 21 deselected, 1 warning |
| PostgreSQL 专项 | 6 passed, 1 warning |
| Ruff | passed |
| Mypy | 167 source files, no issues |
| 前端单元/集成 | 58 files, 209 tests passed |
| 前端工具链 | 4 passed |
| 生产构建 | Vite build passed |
| 生产浏览器验收 | 40 passed |
| 开发浏览器验收 | 42 passed |
| 只读约束 | comparison 页面仅使用 GET；未触发采集、LLM、重试或写入接口 |

PostgreSQL 使用本轮专用临时实例：PostgreSQL 18.6、`127.0.0.1:55447`、数据库 `sector_pulse_run_comparison_test`。测试开始前校验 `current_database()`，没有读取业务 `.env`，没有写入本机业务库。

## UI 验收

已检查 1440×900、1024×768、390×844：共享侧栏保持固定，主内容独立滚动，无页面级横向溢出，窄屏表格在局部区域滚动，选择器支持关闭和焦点回归。参考截图见 [运行对比页面](../../screenshots/sectorpulse-run-comparison.png)。

## 已知边界

- 不包含 Live 行情、新闻、LLM 或影子测试；本功能只比较已经持久化的运行结果。
- 新闻正文依赖历史记录中实际保存的字段；缺失正文会明确显示，不伪造内容。
- 既有 `real_data_candidates` 主键未迁移，仍是 `(run_id, sector_id)`；同一运行同一板块同时存在 industry/concept 时属于既有数据模型限制。
- 新闻及链接的历史级联删除能力未在本轮改造；缺失成员不被解释为零。
- 本轮未合入 `main`、未推送远端。

## 提交

- `55f55c4` 定义可信比较规则
- `5da1e7f` 完成 SQLite/PostgreSQL 历史查询
- `0c806fd` 暴露只读比较查询
- `6d31004` 完成运行选择与恢复
- `583b942` 完成板块、新闻、证据对照面板
- `b4957b1` 完成本地验证、README 与浏览器验收资产
