# SectorPulse Reference UI Phase 4 Acceptance

**Date:** 2026-08-28
**Branch:** `refactoring`
**Scope:** 三栏审核工作台、连续结构化编辑、自动保存、上下文证据、治理与审批门禁

## Acceptance Result

Phase 4 已通过代码、确定性浏览器夹具和隔离 SQLite 实页验收。审核页现在在桌面使用 `22% / 53% / 25%` 三栏工作区，队列、草稿和证据各自滚动；1024px 及以下使用队列/草稿/证据页签。草稿仍按结构化字段和追加版本保存，不引入富文本覆盖写入。

自动保存会在停止输入 800ms 后执行，失焦立即提交；全草稿保存请求串行化，后续输入保留在队列中。网络失败和 409 版本冲突都保留本地文本并提供重试。历史版本只读，未保存、保存中、失败、冲突、历史版本或治理失败均会阻止批准并显示具体原因。

## Delivered Contract

- 审核 API 读取支持 AbortSignal、可分类安全错误和旧响应抑制。
- 审核状态边界统一管理队列、选中运行、版本、治理、批准和证据决定，并在刷新失败时保留最近成功数据。
- 队列支持待审核、已批准和全部筛选；筛选不改变当前运行选择。
- 桌面三栏与移动单栏页签共享同一套组件状态，不制造不同导航或假功能。
- 标题、导语、各板块段落、结论和风险提示组成连续文档表面，但保存路径、字段哈希和追加版本合同保持不变。
- 同一时刻全草稿只发出一个保存请求；较新的字段文本排队并基于服务端返回的新版本继续保存。
- 当前字段携带持久化 `source_ids` 时，右栏只展示相关来源；没有映射时明确标注为全部来源回退。
- 来源、治理、审计三个子视图共享常驻审核操作区；证据理由和退回理由互不复用。
- 批准、撤销、退回和证据决定只刷新受影响状态，保留队列、编辑位置和活动字段。

## Verification Evidence

### Frontend

```powershell
Set-Location web
npm.cmd test -- --run
npm.cmd run build
npx.cmd playwright test e2e/shell.spec.ts e2e/review-workspace.spec.ts --reporter=line
```

Result:

- Vitest: 44 files, 154 tests passed.
- TypeScript and Vite production build: passed; 106 modules transformed.
- Playwright shell + review workspace: 14 tests passed.
- Review workspace suite: 10 tests passed.
- Responsive assertions covered 1536×1024, 1440×900, 1024×768, 768×1024 and 390×844.
- Loading、empty、pending、approved、governance-blocked、save-failed 和 conflict 状态均使用请求拦截夹具完成，不写用户数据库。
- Impeccable detector returned `[]` for the changed review TSX/CSS set.

### Backend

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests `
  --import-mode=importlib `
  --ignore-glob='backend/tests/integration/test_postgres*' `
  -m 'not live' -q
.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests
```

Result:

- Pytest: 266 passed, 1 live test skipped, 6 tests deselected.
- Ruff: all checks passed.
- One existing Starlette/httpx deprecation warning remains.
- Phase 4 changed no Python source files, so changed-source mypy has an empty target set. The repository-wide strict mypy baseline from Phase 3 remains 198 pre-existing errors across 30 legacy files and is not represented as passing.

## Browser Inspection

The production build was opened in the in-app browser against a temporary SQLite database. One fixture-provider run was created only in that isolated database and reached `READY_FOR_HUMAN_REVIEW` with eight sectors. No editing, approval or evidence action was submitted during visual inspection.

Desktop at 1536×1024:

- measured pane widths were 260 / 626 / 296 px, matching the 22 / 53 / 25 proportion after gaps;
- root horizontal overflow was false and body overflow remained hidden;
- editor and evidence panes exceeded their client height and scrolled independently;
- responsive pane tabs were hidden;
- queue metadata and status remained readable after the final vertical card adjustment.

Mobile at 390×844:

- root horizontal overflow was false;
- pane tabs rendered as a three-option grid;
- only the selected pane was visible;
- switching from 草稿 to 证据 retained the workspace and displayed the full evidence form without compressed columns.

Desktop and mobile browser console inspection returned no warning or error entries. The temporary browser tab, backend service and SQLite database were closed and removed after inspection.

## Non-blocking Notes

- Vite continues to report the existing React plugin deprecation notice for `esbuild` options.
- npm reports a newer major version; dependency upgrades were intentionally left outside this refactor.
- PostgreSQL was not required for this frontend-only phase. The Phase 3 PostgreSQL reachability follow-up remains recorded separately.

## Exit Decision

Phase 4 is accepted on `refactoring`. The review workspace meets its desktop, responsive, autosave, version safety, contextual evidence and governance criteria. Phase 5 may proceed without additional user confirmation.
