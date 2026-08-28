# SectorPulse Reference UI Phase 5: Remaining Pages Implementation Plan

> **Execution mode:** 当前会话连续执行；测试先行、按任务独立提交。除非需要新的外部权限或用户提供必要条件，不在任务间等待确认。

**Goal:** 将分析运行、新建分析、内容运行、调度任务、系统状态和影子验收迁移到统一参考 UI 体系，清除假操作和整页堆叠，同时保持现有 API、路由和真实业务能力不变。

**Architecture:** 继续使用 Phase 1 的统一 Shell、令牌和基础组件，为普通管理页新增一层 `operations-pages.css` 页面模式。页面状态读取留在现有 API 模块，先补请求取消、显式错误与可恢复状态，再重组信息层级。不存在后端合同的编辑、删除、重试或恢复动作不在前端制造；只有现有 `create/trigger/retry` API 对应真实按钮。

**Tech Stack:** React 18、TypeScript 5.6、Vitest、Testing Library、Playwright、现有 FastAPI API、SectorPulse 设计令牌、Impeccable Operate 模式。

**References:**

- `docs/superpowers/specs/2026-08-27-sectorpulse-reference-ui-refactor-design.md` §12
- `docs/design/sectorpulse-reference-ui-system.md`
- `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md`
- Phase 4 acceptance: `docs/superpowers/acceptance/2026-08-28-sectorpulse-reference-ui-phase4.md`

## Reality Audit

Retain:

- combined content/data run list, status/provider filtering and detail links;
- fixture and live analysis creation, prerequisite checks and real navigation;
- content run snapshot, SSE progress, retry endpoint and six existing detail views;
- schedule list, create and manual trigger APIs;
- task stage/event data, operations readiness response and read-only shadow acceptance history.

Do not invent:

- schedule edit/delete until backend endpoints exist;
- task retry/recover buttons because no task-run action API exists;
- unknown next-run times, check durations, versions or shadow pass rates;
- user/account/notification functions from the reference images.

## Task 1: Upgrade The Run Registry

**Files:** `RunListPage.tsx`, tests, `styles/pages/operations-pages.css`, `styles/index.css`

- [x] Write tests for status, scene, provider, time-range filters and failure detail disclosure.
- [x] Add compact registry toolbar, truthful result count and reset action.
- [x] Keep data/content run identity and detail routes distinct.
- [x] Show stored safe failure summary and retryability only when returned by the API.
- [x] Preserve loading, request failure, empty and no-match states.
- [x] Verify responsive table behavior, build and detector.
- [x] Commit `refactor: upgrade analysis run registry`.

Verification evidence (2026-08-28): focused Vitest passed 2 tests; production build transformed 106 modules; Impeccable detector returned `[]`; `git diff --check` reported no whitespace errors.

## Task 2: Build The Four-Step Analysis Launcher

**Files:** `NewAnalysisPage.tsx`, tests, `styles/pages/operations-pages.css`

- [x] Expand flow to 场景 → 执行方式 → 参数确认 → 启动.
- [x] Keep preflight loading/error and explicit Live blockers; Fixture never claims real data or LLM usage.
- [x] Present only parameters actually submitted by current APIs.
- [x] Prevent duplicate submission and retain user choices when moving backward.
- [x] Add compact sticky summary on desktop and a single-column order on mobile.
- [x] Run focused tests, build and detector.
- [x] Commit `refactor: build guided analysis launcher`.

Verification evidence (2026-08-28): focused Vitest passed 3 tests; production build transformed 106 modules; Impeccable detector returned `[]`; the submit ref lock prevents same-render duplicate requests and backward navigation retains both selected values.

## Task 3: Clarify The Content Run Workspace

**Files:** `RunDetailPage.tsx`, related tabs/tests, `styles/pages/operations-pages.css`

- [x] Add a truthful stage rail derived from status/SSE events without fabricating completed stages.
- [x] Keep snapshot-first loading, SSE refresh, terminal handling and stored draft access after failure.
- [x] Group overview, attribution, evidence, draft, review and governance into a stable responsive view switcher.
- [x] Expose retry only from `retryable`; preserve safe failure message and input-snapshot wording.
- [x] Add direct review-workspace link when a draft is reviewable.
- [x] Run focused/full tests, build and detector.
- [x] Commit `refactor: clarify content run workspace`.

Verification evidence (2026-08-28): focused suites passed 10 tests; full frontend passed 44 files / 157 tests after one isolated autosave timing rerun confirmed the first full-run failure was transient; production build transformed 107 modules; Impeccable detector returned `[]`.

## Task 4: Finish Management Pages Without Fake Actions

**Files:** SchedulePage, TaskRunPage, SystemStatusPage, ShadowAcceptancePage, tests, `components/ui/ManagementDrawer.tsx`, CSS

- [x] Move schedule creation into an accessible side drawer; retain create and trigger only.
- [x] Do not expose schedule edit/delete until corresponding backend contracts exist.
- [x] Remove fake task retry/recover buttons; add load failure/retry and render persisted task events.
- [x] Present readiness, consent, safe configuration labels and generated check time without secrets.
- [x] Keep shadow acceptance paused/read-only with explicit true empty, partial and history states.
- [x] Verify drawer focus return, Escape, responsive layout, loading/error/empty states and no console logging of request errors.
- [x] Run focused/full tests, build and detector.
- [x] Commit `refactor: finish management page system`.

Verification evidence (2026-08-28): focused management suites passed 15 tests; full frontend passed 45 files / 160 tests; production build transformed 108 modules; Impeccable detector returned `[]`; the generic drawer test verifies initial focus, Escape close and focus return.

## Task 5: Browser Acceptance And Phase Closure

**Files:** `web/e2e/remaining-pages.spec.ts`, acceptance report, master plan, this plan

- [x] Add isolated fixtures for all remaining pages without writing the user database.
- [x] Cover 1536×1024, 1440×900, 1280×800, 1024×768, 768×1024 and 390×844.
- [x] Verify run filtering/detail, four-step launcher, content run tabs/retry, schedule drawer/trigger, task history, system safety and shadow empty/history.
- [x] Assert keyboard access, focus return, no root overflow, no page errors and no unexpected console errors.
- [x] Run full Vitest/build, relevant Playwright, backend non-live tests, Ruff and changed-source mypy.
- [x] Inspect isolated production pages in the in-app browser.
- [x] Write exact acceptance evidence and commit `docs: record reference ui phase 5 acceptance`.

Acceptance evidence: `docs/superpowers/acceptance/2026-08-28-sectorpulse-reference-ui-phase5.md`.

## Exit Criteria

- All remaining primary pages use the same hierarchy, spacing, status and responsive contracts as Phases 1–4.
- Every visible action maps to an implemented API; unsupported edit/delete/retry/recover controls are absent.
- Existing creation, trigger, retry, navigation, read-only history and safety behavior remains intact.
- Loading, empty, partial, failed, blocked and success states are distinguishable without fake data.
- Phase 5 automated and browser acceptance passes before Phase 6 begins.
