# Data Run Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the real-data run detail page into a persistent workbench that truthfully shows collection progress, market sectors, candidates, linked news evidence and quality, while retaining a clear next action after draft generation.

**Architecture:** Persist the selected data provider on each `real_data_runs` row so terminal runs can be retried after restart. Keep orchestration writes in the existing repositories and add a read-only workbench query service that joins the already-persisted market/news/content records without calling providers. Expose small REST endpoints for each independently loaded panel. The React page derives stage state from persisted run status, keeps actions on the data-run route, and links to the Phase 1B run only when the user chooses to leave the page.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLite, PostgreSQL/asyncpg, pytest, React 18, TypeScript, Vitest, Testing Library, CSS.

## Global Constraints

- Preserve the existing uncommitted `backend/src/sector_pulse/web/server.py`; do not edit, stage, or commit it.
- Do not call a real provider or LLM in unit/integration tests.
- Do not expose raw news bodies, secrets, provider stack traces, or news unrelated to the selected run.
- Draft generation remains explicit; this work must not auto-trigger an LLM or publishing.
- Existing `run_id` identity between `real_data_runs` and `phase1b_runs` remains the only content-run association; do not add a mapping table.
- Each UI panel loads and fails independently so one broken endpoint does not hide data from the other panels.
- Stage and empty-state labels must distinguish `尚未产生`, `等待中`, `进行中`, `已完成`, `失败`, `已中断`, `已取消`, and `未执行`.
- Stage only exact files listed by each task; never use broad `git add backend` or `git add .` while `server.py` is dirty.

---

### Task 1: Persist the selected provider for restart-safe retry

**Files:**
- Create: `backend/src/sector_pulse/storage/migrations/013_data_run_workbench.sql`
- Modify: `backend/src/sector_pulse/domain/real_data_run.py`
- Modify: `backend/src/sector_pulse/storage/real_data_run_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_real_data_run_repository.py`
- Modify: `backend/src/sector_pulse/application/real_data_orchestrator.py`
- Modify: `backend/src/sector_pulse/web/data_run_service.py`
- Test: `backend/tests/unit/storage/test_real_data_run_repository.py`
- Test: `backend/tests/integration/test_postgres_real_data_run_repository.py`
- Test: `backend/tests/integration/test_real_data_orchestrator.py`

**Interfaces:**
- Adds `RealDataRun.provider: Literal["fixture", "live"] = "live"`.
- Adds `provider TEXT NOT NULL DEFAULT 'live'` to `real_data_runs` in both database engines.
- Adds optional `provider: Literal["fixture", "live"] = "live"` to `run_real_data_workflow(...)` and persists it on insert.

- [ ] **Step 1: Write failing repository round-trip tests**

Insert one `RealDataRun(provider="fixture", ...)` into SQLite and PostgreSQL and assert `get_run(...).provider == "fixture"`. Extend the orchestrator test to assert that the provider passed into the workflow reaches the persisted run.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_real_data_run_repository.py backend/tests/integration/test_real_data_orchestrator.py -q -p no:cacheprovider
```

Expected: construction, persistence, or retrieval fails because `provider` is not part of the current model/schema.

- [ ] **Step 3: Add migration and domain field**

Create migration 013 with the equivalent of:

```sql
ALTER TABLE real_data_runs
ADD COLUMN provider TEXT NOT NULL DEFAULT 'live';
```

Add the typed default to `RealDataRun`. Keep the default so historical rows and direct test construction remain compatible.

- [ ] **Step 4: Update both repositories and orchestration**

Write and read `provider` in the SQLite and PostgreSQL repositories. Pass the provider from `DataRunService.create()` into `run_real_data_workflow()`, and construct the initial `RealDataRun` with that value. Do not infer provider from process environment during reads.

- [ ] **Step 5: Run SQLite and PostgreSQL persistence tests**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_real_data_run_repository.py backend/tests/integration/test_real_data_orchestrator.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_postgres_real_data_run_repository.py -q -p no:cacheprovider
```

Expected: focused SQLite tests pass; PostgreSQL tests pass when the configured local PostgreSQL is reachable, otherwise report the environment skip/failure separately.

- [ ] **Step 6: Commit provider persistence**

```powershell
git add backend/src/sector_pulse/storage/migrations/013_data_run_workbench.sql backend/src/sector_pulse/domain/real_data_run.py backend/src/sector_pulse/storage/real_data_run_repository.py backend/src/sector_pulse/storage/postgres_real_data_run_repository.py backend/src/sector_pulse/application/real_data_orchestrator.py backend/src/sector_pulse/web/data_run_service.py backend/tests/unit/storage/test_real_data_run_repository.py backend/tests/integration/test_postgres_real_data_run_repository.py backend/tests/integration/test_real_data_orchestrator.py
git commit -m "feat: persist real data run provider"
```

---

### Task 2: Add the read-only workbench query layer

**Files:**
- Create: `backend/src/sector_pulse/application/data_run_workbench_queries.py`
- Modify: `backend/src/sector_pulse/application/real_data_queries.py`
- Test: `backend/tests/unit/application/test_data_run_workbench_queries.py`
- Test: `backend/tests/unit/application/test_real_data_queries.py`

**Interfaces:**
- Produces `market(run_id, kind, offset, limit)` with snapshot summaries, paged rows, and `total`.
- Produces `evidence(run_id)` containing only events linked to the run through `sector_event_links`, plus document metadata and related sector IDs.
- Produces `quality(run_id)` with complete quality counters and error code.
- Produces `content_run(run_id)` returning `None` or the same-ID Phase 1B summary.
- Enriches candidate responses with the sector name found in the persisted matching snapshot.

- [ ] **Step 1: Write failing query tests with persisted fixtures**

Use a temporary SQLite runtime bundle to seed:

- industry and concept snapshots with more rows than one page;
- candidates whose IDs resolve to snapshot names;
- two news events, but link only one to the selected run;
- document metadata for the linked event;
- quality counters and downgrade reasons;
- a same-ID `phase1b_runs` record.

Assert pagination boundaries, name enrichment, linked-only evidence, no article body field, full quality output, and `None`/present content-run behavior.

- [ ] **Step 2: Run query tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_data_run_workbench_queries.py backend/tests/unit/application/test_real_data_queries.py -q -p no:cacheprovider
```

Expected: imports or assertions fail because the workbench service and enriched payloads do not exist.

- [ ] **Step 3: Implement storage-only joins**

Build `DataRunWorkbenchQueries` around `RuntimeStorageBundle`. Query repositories only; never instantiate `RealDataProviderFactory`. Deduplicate event/document IDs before batch reads, preserve stable rank/event ordering, and serialize dates/enums with Pydantic JSON mode.

Market result shape:

```python
{
    "snapshots": [{"kind": "INDUSTRY", "provider_id": "...", "sector_count": 90, ...}],
    "kind": "INDUSTRY",
    "items": [{"sector_id": "...", "name": "...", ...}],
    "total": 90,
    "offset": 0,
    "limit": 20,
}
```

Content-run result must include at least `run_id`, `status`, `draft_id`, and `can_view_draft`.

- [ ] **Step 4: Extend the existing run/candidate serializer**

Return `provider`, `cutoff_at`, request fields, and the full quality summary from run details. Add resolved candidate `name` without removing existing fields used by the frontend.

- [ ] **Step 5: Run query tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_data_run_workbench_queries.py backend/tests/unit/application/test_real_data_queries.py -q -p no:cacheprovider
```

- [ ] **Step 6: Commit query layer**

```powershell
git add backend/src/sector_pulse/application/data_run_workbench_queries.py backend/src/sector_pulse/application/real_data_queries.py backend/tests/unit/application/test_data_run_workbench_queries.py backend/tests/unit/application/test_real_data_queries.py
git commit -m "feat: query persisted data run evidence"
```

---

### Task 3: Expose workbench endpoints and original-parameter retry

**Files:**
- Modify: `backend/src/sector_pulse/web/data_run_service.py`
- Modify: `backend/src/sector_pulse/web/data_run_schemas.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Test: `backend/tests/unit/web/test_app.py`
- Create: `backend/tests/unit/web/test_data_run_service.py`

**Interfaces:**
- `GET /api/data-runs/{run_id}/market?kind=INDUSTRY&offset=0&limit=20`
- `GET /api/data-runs/{run_id}/evidence`
- `GET /api/data-runs/{run_id}/quality`
- `GET /api/data-runs/{run_id}/content-run`
- `POST /api/data-runs/{run_id}/retry`

- [ ] **Step 1: Write failing service and API tests**

Cover:

- retry creates a different ID with the original request/provider;
- retry accepts `DEGRADED`, `BLOCKED`, `FAILED`, `CANCELLED`, and `INTERRUPTED`;
- retry rejects active and `READY_FOR_ATTRIBUTION` runs with HTTP 409;
- missing run returns 404;
- invalid market kind/offset/limit returns 422;
- each successful endpoint returns the query payload without provider calls;
- content-run returns JSON `null` when absent.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/web/test_data_run_service.py backend/tests/unit/web/test_app.py -q -p no:cacheprovider
```

- [ ] **Step 3: Implement retry in `DataRunService`**

Read the persisted source run, validate the allowed terminal states, then call the existing `create(source.request, source.provider)`. This deliberately re-runs live-data consent preflight. Return the new ID and do not mutate the source row.

- [ ] **Step 4: Wire the workbench query service into `create_app`**

Construct `DataRunWorkbenchQueries` from the existing runtime storage bundle. Use FastAPI `Query` constraints for `offset >= 0` and `1 <= limit <= 100`, and map not-found/state conflicts to 404/409 without returning internal exception text.

- [ ] **Step 5: Run API tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/web/test_data_run_service.py backend/tests/unit/web/test_app.py -q -p no:cacheprovider
```

- [ ] **Step 6: Commit the API contract**

```powershell
git add backend/src/sector_pulse/web/data_run_service.py backend/src/sector_pulse/web/data_run_schemas.py backend/src/sector_pulse/web/app.py backend/tests/unit/web/test_app.py backend/tests/unit/web/test_data_run_service.py
git commit -m "feat: expose data run workbench api"
```

---

### Task 4: Add typed frontend API clients

**Files:**
- Modify: `web/src/dataRunsApi.ts`
- Create: `web/src/dataRunsApi.test.ts`

**Interfaces:**
- Adds typed clients for market, evidence, quality, content-run, and retry endpoints.
- Expands `DataRunView` with provider, cutoff, request parameters, finished time, and full quality fields.

- [ ] **Step 1: Write failing client tests**

Mock `fetch` and assert URL encoding for market kind/pagination, JSON parsing of nullable content-run, and `POST` semantics for retry. Assert a non-2xx response rejects with the API detail message.

- [ ] **Step 2: Run the API client test and verify RED**

```powershell
npm.cmd --prefix web test -- dataRunsApi.test.ts
```

- [ ] **Step 3: Implement types and client functions**

Add explicit response interfaces; avoid `any`. Reuse the module's existing HTTP error helper. Export:

```typescript
fetchDataRunMarket(runId, kind, offset, limit)
fetchDataRunEvidence(runId)
fetchDataRunQuality(runId)
fetchDataRunContentRun(runId)
retryDataRun(runId)
```

- [ ] **Step 4: Run the client test and type-check**

```powershell
npm.cmd --prefix web test -- dataRunsApi.test.ts
npm.cmd --prefix web run build
```

- [ ] **Step 5: Commit frontend client contract**

```powershell
git add web/src/dataRunsApi.ts web/src/dataRunsApi.test.ts
git commit -m "feat: add data run workbench client"
```

---

### Task 5: Rebuild the data-run page as a persistent workbench

**Files:**
- Modify: `web/src/pages/DataRunPage.tsx`
- Modify: `web/src/pages/DataRunPage.test.tsx`
- Create: `web/src/pages/data-run/DataRunTimeline.tsx`
- Create: `web/src/pages/data-run/DataRunActionPanel.tsx`
- Create: `web/src/pages/data-run/MarketPanel.tsx`
- Create: `web/src/pages/data-run/CandidatesPanel.tsx`
- Create: `web/src/pages/data-run/EvidencePanel.tsx`
- Create: `web/src/pages/data-run/QualityPanel.tsx`
- Modify: `web/src/styles.css`

**Behavior:**
- The page retains the header and summary, adds a truthful five-stage timeline, a fixed next-action panel, and four data tabs.
- Generating a draft stays on `/data-runs/{run_id}` and replaces the action with a content-progress/detail link.
- Retry navigates only to the newly created data run.
- Market defaults to industry, 20 rows per page; industry/concept switches reset the offset.

- [ ] **Step 1: Write failing workbench component tests**

Add tests for:

- `FETCHING_MARKET`: only market collection is `进行中`; later stages are `等待中`; action is disabled;
- `READY_FOR_ATTRIBUTION`: all five stages are complete and `生成分析稿` is visible;
- generate success: route does not change and `查看生成进度` becomes visible;
- existing terminal content run: `查看分析稿` or `查看生成进度` survives refresh;
- failed/interrupted data run: exact failure node plus `按原参数重新采集`;
- retry response: navigate to `/data-runs/{new_id}`;
- market rows, enriched candidates, linked news/document metadata, and quality counters render in their tabs;
- one panel request failure leaves other loaded panels visible;
- missing partial data says `尚未产生` or identifies the pending stage rather than displaying a misleading zero-success state.

- [ ] **Step 2: Run the page tests and verify RED**

```powershell
npm.cmd --prefix web test -- DataRunPage.test.tsx
```

- [ ] **Step 3: Implement deterministic timeline state**

Map persisted statuses to ordered stages:

```typescript
const stages = [
  'FETCHING_MARKET',
  'RANKING_PRE_CANDIDATES',
  'FETCHING_NEWS',
  'BUILDING_EVIDENCE',
  'READY_FOR_ATTRIBUTION',
]
```

Earlier stages are complete, the matching active stage is running, and later stages wait. Terminal failure/cancel/interruption labels only the last known active stage with its outcome; `READY_FOR_ATTRIBUTION` completes all stages.

- [ ] **Step 4: Implement persistent action and independent panels**

Load the run summary first. Load candidates, content association, and the active tab separately with local loading/error/empty states. Do not use a single `Promise.all` that can blank the whole screen. Keep generation/retry errors inside the action panel.

- [ ] **Step 5: Implement accessible tabs, tables, and pagination**

Use buttons with `role="tab"`/`aria-selected`, semantic tables, disabled pagination boundaries, safe external links using `target="_blank" rel="noreferrer"`, and concise mobile stacking in the existing stylesheet.

- [ ] **Step 6: Run focused frontend tests and build**

```powershell
npm.cmd --prefix web test -- DataRunPage.test.tsx dataRunsApi.test.ts RunListPage.test.tsx
npm.cmd --prefix web run build
```

- [ ] **Step 7: Commit the workbench UI**

```powershell
git add web/src/pages/DataRunPage.tsx web/src/pages/DataRunPage.test.tsx web/src/pages/data-run/DataRunTimeline.tsx web/src/pages/data-run/DataRunActionPanel.tsx web/src/pages/data-run/MarketPanel.tsx web/src/pages/data-run/CandidatesPanel.tsx web/src/pages/data-run/EvidencePanel.tsx web/src/pages/data-run/QualityPanel.tsx web/src/styles.css
git commit -m "feat: turn data run detail into workbench"
```

---

### Task 6: Run migrations and complete end-to-end regression

**Files:**
- Modify only if a verified defect is found in files already listed above.

- [ ] **Step 1: Apply and inspect migrations on temporary SQLite**

Run the repository's normal migration command against a fresh temporary SQLite database, then inspect `real_data_runs` to confirm the provider column and schema version 013.

- [ ] **Step 2: Apply migration to configured local PostgreSQL**

Use the existing `.env` database URL and repository migration command. Query the migration/version table and `information_schema.columns` to confirm migration 013 and `real_data_runs.provider` without printing the password.

- [ ] **Step 3: Run complete non-live backend regression**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider -m "not live"
```

Expected: all non-live tests pass. If an environment-only test is skipped, record the exact skip separately.

- [ ] **Step 4: Run complete frontend regression and production build**

```powershell
npm.cmd --prefix web test
npm.cmd --prefix web run build
```

- [ ] **Step 5: Perform local HTTP smoke acceptance without real LLM use**

Start the web service against the migrated local database, choose an existing persisted data run, and verify:

```powershell
Invoke-RestMethod "http://127.0.0.1:8010/api/data-runs/$id"
Invoke-RestMethod "http://127.0.0.1:8010/api/data-runs/$id/market?kind=INDUSTRY&offset=0&limit=20"
Invoke-RestMethod "http://127.0.0.1:8010/api/data-runs/$id/evidence"
Invoke-RestMethod "http://127.0.0.1:8010/api/data-runs/$id/quality"
Invoke-RestMethod "http://127.0.0.1:8010/api/data-runs/$id/content-run"
```

Open `/data-runs/{id}` and verify the timeline, action panel, four data tabs, pagination, and refresh persistence. Do not click draft generation unless the user separately authorizes another real LLM request.

- [ ] **Step 6: Review dirty-worktree boundaries**

```powershell
git status --short
git diff --check
git diff -- backend/src/sector_pulse/web/server.py
```

Expected: no whitespace errors; `server.py` remains exactly the pre-existing user change and is absent from every implementation commit.

- [ ] **Step 7: Commit only verified final corrections, if any**

Stage exact corrected files only. If no corrections were needed, create no empty commit.
