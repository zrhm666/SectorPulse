# SectorPulse Reference UI Phase 3: Data Run Workbench Implementation Plan

> **Execution mode:** 当前会话按任务顺序连续执行；每项遵循测试驱动、独立提交和证据验收。除非遇到必须由用户提供的新权限或外部条件，不在任务间等待确认。

**Goal:** 将现有数据运行详情升级为可恢复、可审计的真实工作台，完成候选板块确认版本、草稿生成门禁、2 秒可靠轮询、服务端数据视图和新闻详情抽屉，同时保持现有真实采集、证据和写作链路兼容。

**Architecture:** 在现有 `real_data_runs`、候选、行情、新闻、证据和内容运行之上新增独立的候选选择版本边界。后端负责校验候选集合、持久化确认版本并让 Web 生成入口只读取已确认版本；工作台查询继续只读现有持久化记录，不触发 Provider。前端拆分页面状态、轮询、候选选择、页签资源和详情抽屉，所有未知字段与历史血缘缺失均显示真实原因。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLite、PostgreSQL、SQLAlchemy 2、pytest、React 18、TypeScript 5.6、Vitest、Testing Library、Playwright、语义 CSS。

**Approved references:**

- `docs/superpowers/specs/2026-08-27-sectorpulse-reference-ui-refactor-design.md`
- `docs/design/sectorpulse-reference-ui-system.md`
- `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md`
- Phase 2 acceptance: `docs/superpowers/acceptance/2026-08-27-sectorpulse-reference-ui-phase2.md`

## Existing Capability Audit

Already reliable and retained:

- `/api/data-runs/{id}` and five persisted run statuses/stages;
- acquisition summary and Provider status;
- market and news server-side offset/limit pagination;
- evidence and quality read models;
- content run lookup, retry and generate routes;
- content/data detail routes and existing two-second interval behavior;
- news domain intentionally stores metadata and a maximum 500-character summary, not full article text.

Gaps this phase closes:

- candidate choices currently exist only in React state and reset to all-selected after reload;
- generate currently accepts transient `sector_ids` instead of reading a confirmed version;
- candidate selection lacks search, sorting, explicit confirmation, data version and edit count;
- current interval polling can overlap and does not pause when hidden or retain stale state explicitly;
- candidate list is not a server-side page and lacks market/news facts required by the design;
- news cards do not expose a stable detail model or explicitly distinguish summary, flash and link-only records;
- long page composition lacks a consistent workbench hierarchy and right-side details drawer.

## Global Constraints

- Do not write fixture or acceptance rows into the user's configured database.
- Do not claim PostgreSQL acceptance while the configured service returns `WinError 1225`.
- Do not persist API keys, cookies, prompts, raw provider payloads, model reasoning or complete news article bodies.
- A news record may be labeled `FULL_TEXT` only when persisted text truly exists; current records normally resolve to `SUMMARY`, `FLASH` or `LINK_ONLY`.
- Only `http` and `https` citation URLs may become clickable external links.
- Candidate confirmation must contain 3–12 unique candidates belonging to the same data run.
- Draft generation from the Web API must use the latest confirmed selection version. Unconfirmed local edits cannot reach the writing pipeline.
- Scheduled generation remains compatible by creating or resolving a system-default confirmed selection before writing.
- Existing data-run, market, evidence, quality and content routes remain valid; new fields and routes are additive unless a test proves an unsafe legacy behavior.
- Poll every 2 seconds only while a run or linked content run is non-terminal; pause while hidden; never overlap requests; use bounded exponential retry after consecutive failures.
- Large lists use server-side pagination. Search and sort parameters are validated and use a deterministic tie-breaker.
- Page actions, links and values must correspond to implemented behavior and persisted data.

## Target Data Contracts

### Candidate selection

```text
DataRunCandidateSelection
  run_id: UUID
  version: int >= 1
  selected_sector_ids: tuple[str, 3..12]
  method: DEFAULT | MANUAL
  confirmed_at: UTC datetime
  data_version: sha256 of ordered available candidates
  edit_count: int >= 0
```

`GET /api/data-runs/{run_id}/selection` returns the latest confirmed selection or an explicit unconfirmed default preview. `PUT /api/data-runs/{run_id}/selection` accepts `sector_ids` and `expected_version`; it validates membership and writes a new immutable version. A stale expected version returns 409.

### Candidate page

`GET /api/data-runs/{run_id}/candidates` gains validated `query`, `sort`, `direction`, `offset` and `limit`. It returns:

```text
items, total, offset, limit, query, sort, direction, data_version
```

Each item retains rank/score/reasons/name and adds available market facts plus `news_count`. Missing Provider fields remain `null` with field availability, never zero-filled.

### News detail

The paged news list and detail model expose:

```text
content_kind: FULL_TEXT | SUMMARY | FLASH | LINK_ONLY
content: string | null
content_available: bool
citation_url: safe http(s) URL | null
```

For the current metadata-only domain, `content` is the persisted short summary when present. `FLASH` is used only for a source/query classified as a flash feed; `LINK_ONLY` means no persisted text. The drawer explains that full text is not stored when `FULL_TEXT` is unavailable.

---

## Task 1: Persist Versioned Candidate Selections

**Files:**

- Create: `backend/src/sector_pulse/domain/candidate_selection.py`
- Create: `backend/src/sector_pulse/storage/migrations/015_data_run_candidate_selection.sql`
- Create: `backend/src/sector_pulse/storage/candidate_selection_repository.py`
- Create: `backend/src/sector_pulse/storage/postgres_candidate_selection_repository.py`
- Modify: `backend/src/sector_pulse/storage/runtime_bundle.py`
- Create: `backend/tests/unit/domain/test_candidate_selection.py`
- Create: `backend/tests/integration/test_candidate_selection_repository.py`
- Create: `backend/tests/integration/test_postgres_candidate_selection_repository.py`

- [x] Write domain tests for uniqueness, 3–12 bounds, UTC confirmation time, immutable versions and deterministic candidate data hashes.
- [x] Run focused tests and verify RED because the domain model does not exist.
- [x] Implement the frozen selection model and hash helper.
- [x] Write repository tests for no selection, append-only versions, latest lookup, optimistic version conflicts and run deletion cascade.
- [x] Add migration 015 with `(run_id, version)` primary key, JSON candidate IDs, method, confirmed time, data version and edit count.
- [x] Implement SQLite and PostgreSQL repositories with the same contract and register them in `RuntimeStorageBundle`.
- [x] Run domain/storage tests, Ruff and mypy for changed backend files.
- [x] Commit: `feat: persist candidate selection versions`.

## Task 2: Enforce Confirmation In The Generation Boundary

**Files:**

- Create: `backend/src/sector_pulse/application/candidate_selection_service.py`
- Modify: `backend/src/sector_pulse/application/real_data_writing_bridge.py`
- Modify: `backend/src/sector_pulse/application/scheduled_data_bridge.py`
- Modify: `backend/src/sector_pulse/web/data_run_schemas.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `backend/src/sector_pulse/web/data_run_writing_service.py`
- Create: `backend/tests/unit/application/test_candidate_selection_service.py`
- Modify: `backend/tests/unit/application/test_real_data_writing_bridge.py`
- Modify: `backend/tests/integration/test_real_data_workbench_api.py`

- [ ] Write failing service tests for default preview, manual confirmation, invalid membership, duplicate IDs, stale version and latest confirmed lookup.
- [ ] Implement confirmation against the run's persisted candidate set and deterministic data version.
- [ ] Add GET/PUT selection endpoints with typed schemas and 404/409/422 semantics.
- [ ] Write a failing API test proving `/generate` rejects an unconfirmed run even when transient `sector_ids` are supplied.
- [ ] Change the Web generation route to resolve the latest confirmed selection and pass only that immutable set to writing.
- [ ] Preserve scheduled generation by explicitly confirming the system default candidate set before its call to writing.
- [ ] Verify refresh returns the latest confirmed version and old versions remain queryable through repository tests.
- [ ] Run focused application/API tests, Ruff and mypy.
- [ ] Commit: `feat: require confirmed candidate selection`.

## Task 3: Extend Truthful Workbench Read Models

**Files:**

- Modify: `backend/src/sector_pulse/application/data_run_workbench_queries.py`
- Modify: `backend/src/sector_pulse/web/data_run_schemas.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Create: `backend/tests/unit/application/test_data_run_workbench_queries.py`
- Modify: `backend/tests/integration/test_real_data_workbench_api.py`

- [ ] Write failing tests for candidate search, sort, pagination, stable tie-breaking, market facts, news coverage count and candidate `data_version`.
- [ ] Implement candidate paging without invoking market/news providers.
- [ ] Add explicit workflow-stage and run-summary fields only where they are derived from persisted status/timestamps.
- [ ] Write failing tests for news `content_kind`, `content_available`, safe citation URL and detail lookup by document ID.
- [ ] Implement additive news list fields and `GET /api/data-runs/{run_id}/news-records/{document_id}`.
- [ ] Reject unsafe citation schemes by returning `citation_url=null`; do not rewrite or follow the URL.
- [ ] Keep evidence/quality routes compatible and record why they remain non-paged when their bounded cardinality is below the large-list threshold.
- [ ] Run focused query/API tests for SQLite; run PostgreSQL tests only if the configured service is reachable.
- [ ] Commit: `feat: extend data workbench read models`.

## Task 4: Add Typed Frontend State And Reliable Polling

**Files:**

- Modify: `web/src/dataRunsApi.ts`
- Modify: `web/src/dataRunsApi.test.ts`
- Create: `web/src/hooks/useDataRunWorkbench.ts`
- Create: `web/src/hooks/useDataRunWorkbench.test.tsx`

- [ ] Define typed selection, candidate page, workflow summary and news detail contracts.
- [ ] Add API methods for selection GET/PUT, candidate query params and news detail.
- [ ] Preserve safe server error messages and AbortSignal support on every request used by the workbench.
- [ ] Write hook tests for initial load, active two-second polling, terminal stop, hidden pause, no overlap, stale retention, exponential retry and manual refresh.
- [ ] Implement recursive timeout polling rather than `setInterval`.
- [ ] Poll the linked content run while it remains non-terminal, then stop when both workflows settle.
- [ ] Keep per-tab resources lazy and cancellable; a stale tab response must not replace a newer filter request.
- [ ] Run focused API/hook tests and TypeScript build.
- [ ] Commit: `feat: add reliable data workbench state`.

## Task 5: Build The Candidate Selection Workspace

**Frontend skill direction:** use Impeccable Operate mode and the approved SectorPulse design tokens. The selection table is the primary task surface, not a decorative card gallery.

**Files:**

- Modify: `web/src/pages/data-run/CandidatesPanel.tsx`
- Create: `web/src/pages/data-run/CandidatesPanel.test.tsx`
- Create: `web/src/pages/data-run/CandidateSelectionBar.tsx`
- Create: `web/src/pages/data-run/CandidateSelectionBar.test.tsx`
- Modify: `web/src/pages/data-run/DataRunActionPanel.tsx`
- Create: `web/src/styles/pages/data-run.css`
- Modify: `web/src/styles/index.css`

- [ ] Write failing UI tests for search, score/rank/change/news sorting, page selection, select-all-current-page, clear, dirty state and confirmed version.
- [ ] Replace the unbounded checkbox list with a compact accessible table showing only available market/news fields.
- [ ] Add sticky selection summary with selected count, dirty/confirmed state, version, confirm button and cancel-local-edits action.
- [ ] Disable confirmation outside `READY_FOR_ATTRIBUTION`, while loading, below 3, above 12 or during save.
- [ ] After a version conflict, preserve local choices and offer reload/reapply instead of silently discarding them.
- [ ] Make `DataRunActionPanel` require a confirmed non-dirty selection and explain the exact blocking reason.
- [ ] Add responsive behavior: table viewport scroll only within panel; mobile uses a list-like row treatment without hiding selection state.
- [ ] Run focused component tests and Impeccable detector after UI files are complete.
- [ ] Commit: `refactor: build candidate selection workspace`.

## Task 6: Recompose Data Tabs And Detail Drawers

**Files:**

- Modify: `web/src/pages/DataRunPage.tsx`
- Modify: `web/src/pages/DataRunPage.test.tsx`
- Modify: `web/src/pages/data-run/MarketPanel.tsx`
- Modify: `web/src/pages/data-run/NewsRecordsPanel.tsx`
- Modify: `web/src/pages/data-run/EvidencePanel.tsx`
- Modify: `web/src/pages/data-run/QualityPanel.tsx`
- Create: `web/src/pages/data-run/WorkbenchDrawer.tsx`
- Create: `web/src/pages/data-run/NewsDetailDrawer.tsx`
- Create: `web/src/pages/data-run/MarketDetailDrawer.tsx`
- Create: `web/src/pages/data-run/WorkbenchDrawers.test.tsx`
- Modify: `web/src/styles/pages/data-run.css`

- [ ] Write page-state tests for loading, empty, partial acquisition, active refresh, stale data, hard failure, confirmed selection and linked content run.
- [ ] Recompose page as header, compact summary, five-stage progress, acquisition strip, selection workspace, action bar and stable detail tabs.
- [ ] Keep one main vertical scroll region; completed stages remain compact and the current stage receives emphasis without animation.
- [ ] Add market row drawer with field availability and collection provenance.
- [ ] Add news drawer with title, source, times, content-kind badge, available summary/flash text, lineage and optional safe original link.
- [ ] Explicitly state `系统未保存新闻全文` when full text is unavailable; never label the summary as article body.
- [ ] Preserve active tab, filters, pagination and confirmed selection after run polling updates.
- [ ] Add focus return, Escape close, labelled dialog semantics and mobile full-width drawer behavior.
- [ ] Run component/page tests, full frontend tests, build and detector.
- [ ] Commit: `refactor: compose data run workbench`.

## Task 7: Browser Acceptance And Phase Closure

**Files:**

- Create: `web/e2e/data-workbench.spec.ts`
- Create: `docs/superpowers/acceptance/2026-08-27-sectorpulse-reference-ui-phase3.md`
- Modify: `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md`
- Modify: this plan

- [ ] Add deterministic E2E fixtures for active, ready, degraded, empty, stale and failed runs without writing the user's database.
- [ ] Verify 1536×1024 and 1440×900 hierarchy, 1024×768 stacking, 768×1024 drawer behavior and 390×844 reachability/no root overflow.
- [ ] Verify candidate search/sort/select/confirm/reload, then prove generate remains disabled for dirty or unconfirmed state.
- [ ] Verify market/news pagination and both drawers, including summary/flash/link-only labels and safe-link rules.
- [ ] Run complete frontend Vitest, build and shell/data-workbench Playwright suites.
- [ ] Run complete non-live backend unit/integration tests, Ruff and mypy for changed source.
- [ ] Attempt PostgreSQL selection flow only when reachable; otherwise record the exact connection exception without claiming success.
- [ ] Inspect the built page in the in-app browser with no console errors, clipped actions, fake values or full-text mislabeling.
- [ ] Run `git diff --check` and confirm only Phase 3 closure files remain.
- [ ] Write exact acceptance evidence, mark Phase 3 complete in the master plan and commit `docs: record reference ui phase 3 acceptance`.

## Phase Exit Criteria

- A user can reload after confirming candidates and see the same immutable selection version.
- A dirty local selection cannot start draft generation.
- The generated draft request uses the latest confirmed version, not arbitrary request-body IDs.
- Candidate, market and news large lists paginate on the server with stable ordering.
- News UI truthfully distinguishes stored summary, flash and link-only records; full body is never invented.
- Active workflows poll every 2 seconds without overlap and stop at terminal states.
- Empty, partial, stale, failed and historical-coverage states remain distinguishable.
- Desktop/tablet/mobile tests show no page-level horizontal overflow.
- SQLite/non-live verification passes; PostgreSQL outcome is either passed with evidence or recorded as an environment exception.
