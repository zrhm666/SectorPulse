# SectorPulse Reference UI Phase 3 Acceptance

**Date:** 2026-08-28  
**Branch:** `refactoring`  
**Scope:** 数据运行工作台、候选确认版本、生成门禁、可靠轮询、服务端分页、行情与新闻详情抽屉

## Acceptance Result

Phase 3 的代码、SQLite 路径、确定性浏览器夹具和隔离浏览器运行验收通过。候选板块选择现在以不可变版本持久化，Web 生成入口只读取最新已确认版本；运行刷新不会覆盖页签、筛选、分页或本地未确认选择。新闻界面只展示实际保存的摘要、快讯或链接状态，并在没有正文时明确显示 `系统未保存新闻全文`。

PostgreSQL 环境验收未通过：使用 `.env` 中现有 `SECTOR_PULSE_DATABASE_URL` 初始化候选选择仓储时，服务返回 `ConnectionRefusedError: [WinError 1225]`。该结果仅记录为本机 PostgreSQL 服务不可达，不计为 PostgreSQL 流程通过，也不阻塞已通过的非 live、SQLite 与前端阶段验收。

## Delivered Contract

- 新增不可变候选选择版本、3–12 个候选边界、候选集合哈希、乐观版本冲突和 SQLite/PostgreSQL 同构仓储。
- `GET/PUT /api/data-runs/{run_id}/selection` 提供默认预览、手工确认和版本冲突语义。
- Web `/generate` 拒绝未确认选择，不再信任请求体临时板块 ID；定时任务显式确认系统默认版本。
- 候选查询支持服务端搜索、排序、稳定分页、行情事实、新闻覆盖数和 `data_version`。
- 新闻详情提供 `FULL_TEXT | SUMMARY | FLASH | LINK_ONLY`、安全 HTTP(S) 链接和持久化内容可用性。
- 工作台使用无重叠递归定时器每 2 秒刷新；隐藏时暂停，连续失败指数退避，终态停止并保留最近成功数据。
- 页面重组为摘要、五阶段进度、真实采集、生成门禁和五个稳定页签；行情与新闻详情使用可键盘关闭的响应式抽屉。

## Verification Evidence

### Frontend

```powershell
Set-Location web
npm.cmd test
npm.cmd run build
node node_modules/@playwright/test/cli.js test shell.spec.ts data-workbench.spec.ts
```

Result:

- Vitest: 39 files, 134 tests passed.
- TypeScript and Vite production build: passed; 103 modules transformed.
- Playwright shell + data workbench: 14 tests passed.
- Data workbench suite alone: 10 tests passed in 7.8 seconds.
- Responsive assertions covered 1536×1024, 1440×900, 1024×768, 768×1024 and 390×844.
- Ready、active、degraded、empty、stale、failed 六种确定性状态均通过；夹具不写用户数据库。
- 每项浏览器测试收集 `pageerror` 和 console error；最终均为空。

### Backend, non-live and non-PostgreSQL

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not live and not live_llm" `
  --import-mode=importlib `
  --ignore-glob='backend/tests/integration/test_postgres*'
.\.venv\Scripts\python.exe -m ruff check backend
```

Result:

- Pytest: 266 passed, 7 live tests deselected, 1 existing Starlette deprecation warning.
- Ruff: all backend checks passed.
- `--import-mode=importlib` is required because two existing test directories contain the same module basename.

### Type checking

Strict mypy passed for the six Phase 3 core modules: candidate selection domain/service, workbench query, SQLite/PostgreSQL selection repositories and Web schemas.

The repository-wide strict mypy command still reports 198 pre-existing errors across 30 legacy files. This baseline is recorded, not presented as a Phase 3 success; the newly introduced core boundary is clean.

### PostgreSQL reachability

The configured URL was loaded into the test process without printing it:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  backend/tests/integration/test_postgres_candidate_selection_repository.py `
  --import-mode=importlib -q
```

Result: connection initialization failed with `ConnectionRefusedError: [WinError 1225]`; no repository contract assertion ran.

### Frontend skill checks

- Impeccable detector returned `[]` for the changed data workbench TSX/CSS set.
- The single flagged side-accent notice was replaced with a restrained full border before final verification.

## Browser Inspection

The production build was opened in the in-app browser against a temporary SQLite database. A fixture-provider data run was created only in that isolated database and removed after inspection.

- The run persisted 90 industry rows and 375 concept rows before terminating with an integrity error; the page truthfully showed failure, the exact error category and the retry action.
- Acquisition cards distinguished partial market fields from missing fields and displayed Provider, versions, timestamps and raw-response hashes.
- The first market detail drawer showed the actual sector values and complete collection lineage.
- Root and body widths stayed within the viewport; no warning or error console entries were captured.
- The temporary backend process and SQLite database were stopped and deleted after inspection.

## Non-blocking Notes

- Vite reports existing React plugin deprecation notices for `esbuild` options.
- npm reports a newer major version; no dependency upgrade was performed.
- PostgreSQL must be started and reachable before the selection contract and complete “采集→确认→生成” path can be rerun there.
- The isolated fixture run exposed an existing `INTEGRITYERROR` after market acquisition. Phase 3 failure-state UX handled it correctly; diagnosing that provider workflow is separate from this frontend acceptance.

## Exit Decision

Phase 3 is accepted on `refactoring` for its implemented code and non-live paths, with PostgreSQL reachability and the isolated fixture workflow integrity error explicitly retained as environment/workflow follow-ups. Phase 4 may proceed without manufacturing PostgreSQL success.
