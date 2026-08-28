# SectorPulse Reference UI Phase 5 Acceptance

**Date:** 2026-08-28
**Branch:** `refactoring`
**Scope:** 分析运行注册表、四步启动器、内容运行工作区、调度任务、系统状态、影子验收

## Acceptance Result

Phase 5 已通过组件测试、隔离浏览器夹具、非 Live 后端回归和真实生产构建浏览器检查。剩余主页面现在使用统一 Shell、设计令牌、页面密度和响应式合同；所有可见操作均映射到现有 API，不存在无合同的调度编辑/删除或任务重试/恢复按钮。

## Delivered Contract

- 分析运行注册表统一展示内容运行和数据运行，支持状态、场景、Provider、时间范围筛选、真实结果数与重置；失败详情只显示后端存储的安全消息与 `retryable` 能力。
- 新建分析使用“场景 → 执行方式 → 参数确认 → 启动”四步流程；Live 条件不足时明确阻止推进，Fixture 不声称使用实时数据或真实 LLM，提交锁防止重复请求。
- 内容运行阶段轨道始终可见，并从持久化状态和 SSE 事件推导；普通失败不伪造已完成阶段，失败后仍可访问已存草稿，待审核草稿可直达对应审核队列项。
- 调度创建移入具备初始焦点、焦点约束、Escape 关闭、焦点归还和背景滚动锁定的通用侧抽屉；调度页仅保留真实的创建和立即触发操作。
- 任务运行页移除无后端 API 的“重试/恢复”，提供显式加载失败重试，并展示持久化阶段和事件历史。
- 系统状态展示数据库、LLM、实时数据授权、调度器与后端生成的检查时间，不展示 API Key、密码或连接串。
- 影子验收保持暂停和只读，区分真正未开始、仅有汇总的部分状态和完整历史记录。

## Verification Evidence

### Frontend

```powershell
Set-Location web
npm.cmd test -- --run
npm.cmd run build
npx.cmd playwright test e2e/shell.spec.ts e2e/remaining-pages.spec.ts --reporter=line
node C:\Users\18067\.codex\skills\impeccable\scripts\detect.mjs --json <changed-ui-files>
```

Results:

- Vitest: 45 files, 160 tests passed.
- TypeScript and Vite production build: passed; 108 modules transformed.
- Playwright Shell + remaining pages: 14 tests passed; remaining-pages suite alone: 10 tests passed.
- Responsive coverage: 1536×1024, 1440×900, 1280×800, 1024×768, 768×1024 and 390×844.
- Browser fixtures covered filtering/error disclosure, four-step creation, content tabs/retry, direct review link, schedule drawer/create/trigger, task history, safe system status and shadow history.
- Every fixture test asserted no unexpected page errors or console errors and no root horizontal overflow.
- Impeccable detector returned `[]` for each changed Phase 5 UI set.

### Backend

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests `
  --import-mode=importlib `
  --ignore-glob='backend/tests/integration/test_postgres*' `
  -m 'not live' -q
.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests
```

Results:

- Pytest: 266 passed, 1 live test skipped, 6 tests deselected.
- Ruff: all checks passed.
- One existing Starlette/httpx deprecation warning remains.
- Phase 5 changed no Python source, so changed-source mypy had an empty target set; the repository-wide strict mypy legacy baseline remains outside this frontend phase.

## Production Browser Inspection

The production build was served by the real FastAPI application against `D:\work\SectorPulse\.tmp-test\phase5-browser.db`. The existing `.env` PostgreSQL URL and Live LLM path were overridden for this isolated inspection; no user database, API quota or external provider was used.

Desktop at 1536×1024:

- four launcher steps aligned as one rail with the primary configuration panel and sticky truthful summary in a balanced two-column composition;
- the scene cards, primary action and summary remained visually distinct without nested-card overload;
- schedule creation opened as a 480px side drawer, left the underlying page legible, and focused the plan-name field.

Mobile at 390×844:

- root horizontal overflow was false and measured main width equaled the 390px viewport;
- the launcher used a compact numeric step rail, stacked scene choices and placed the summary after the primary panel;
- the schedule drawer occupied the full 390px width, kept actions reachable and set body overflow to `hidden` while open.

Browser warning/error logs were empty. The browser tab and viewport override were closed/reset, both temporary services were stopped, and the isolated SQLite file was removed after inspection.

## Non-blocking Notes

- Vite continues to report the existing React plugin deprecation warning for `esbuild` options.
- npm reports a newer major version; dependency upgrades remain outside this refactor.
- Repository-wide `legacy` CSS removal is intentionally deferred until Phase 6 can inventory all remaining compatibility consumers.

## Exit Decision

Phase 5 is accepted on `refactoring`. All primary product pages now follow the same visual and interaction system while preserving truthful backend capabilities. Phase 6 full-project review, documentation screenshots and final merge decision may proceed without additional confirmation.
