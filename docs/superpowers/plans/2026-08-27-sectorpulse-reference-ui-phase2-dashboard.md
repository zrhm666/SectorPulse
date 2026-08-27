# SectorPulse Reference UI Phase 2 Operations Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将运营总览迁移为只展示真实运行、真实趋势和真实就绪状态的高保真 Dashboard，并在运行活跃时可靠刷新。

**Architecture:** 后端新增独立的运营聚合查询边界，将内容运行和数据运行规范化为同一只读视图，再由 FastAPI 在保留旧字段的同时增量返回 `summary`、`trend`、`readiness`、`recent_runs` 和 `generated_at`。前端通过类型化 API、无重叠轮询 Hook 和小型 Dashboard 组件消费该契约；趋势只由持久化运行时间聚合产生，数据不足时显示原因而不生成示意曲线。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLite、PostgreSQL、SQLAlchemy 2、pytest、React 18、TypeScript 5.6、Vitest、Testing Library、Playwright、语义 CSS

**Spec:** `docs/superpowers/specs/2026-08-27-sectorpulse-reference-ui-refactor-design.md`

## Global Constraints

- 三张参考图是高保真视觉和布局目标，不是需要逐项复制的功能清单。
- 正式页面禁止静态示意指标、假按钮、假通知、假用户资料和不可追溯趋势。
- 现有 `/api/operations/summary` 的 `database`、`llm`、`consent`、`providers` 和 `runs` 字段继续有效。
- 聚合同时覆盖 `phase1b_runs` 内容运行和 `real_data_runs` 数据运行；同一运行不得重复计数。
- 运行状态映射集中在后端，前端不得自行猜测成功、活跃或待处理状态。
- 趋势默认返回最近 30 个自然日；7 天视图从同一真实序列截取，不额外制造数值。
- 无可用历史时 `trend.available=false`、`trend.reason` 为可读原因，`points=[]`。
- 运行中每 5 秒刷新；页面隐藏时暂停；前一次请求结束前不发起下一次请求；刷新失败保留最近成功数据。
- API Key、数据库密码、连接串、原始提示词和未脱敏模型响应不得进入响应、日志、截图或验收报告。
- 不新增数据库表或破坏性迁移；本阶段只读取现有运行表和候选表。
- 桌面验收尺寸为 1536×1024 和 1440×900；响应式检查覆盖 1024×768、768×1024 和 390×844。

---

## File Map

- Create `backend/src/sector_pulse/application/operations_summary.py`: 统一状态语义、聚合 DTO 和查询服务。
- Create `backend/src/sector_pulse/storage/operations_query.py`: SQLite 精确计数、30 日趋势和统一近期运行查询。
- Create `backend/src/sector_pulse/storage/postgres_operations_query.py`: 与 SQLite 返回同一契约的 PostgreSQL 查询。
- Modify `backend/src/sector_pulse/storage/runtime_bundle.py`: 为两种存储运行时注册 `operations` 查询端口。
- Modify `backend/src/sector_pulse/web/operations_schemas.py`: 增量定义新版响应字段。
- Modify `backend/src/sector_pulse/web/app.py`: 组合聚合结果与数据库、Provider、LLM、授权和调度器就绪状态。
- Create `backend/tests/unit/application/test_operations_summary.py`: 验证状态映射和趋势空态。
- Modify `backend/tests/integration/test_operations_summary_api.py`: 验证 SQLite 空库、真实记录和兼容字段。
- Create `backend/tests/integration/test_postgres_operations_query.py`: 在已配置 PostgreSQL 时验证查询契约。
- Modify `web/src/operationsApi.ts`: 定义完整响应类型和请求错误。
- Modify `web/src/operationsApi.test.ts`: 锁定增量响应和错误行为。
- Create `web/src/hooks/useOperationsSummary.ts`: 可见性与活跃状态驱动的无重叠轮询。
- Create `web/src/hooks/useOperationsSummary.test.tsx`: 验证首次加载、5 秒轮询、隐藏暂停、保留旧数据和手动恢复。
- Create `web/src/components/dashboard/OperationsMetricGrid.tsx`: 四项真实核心指标。
- Create `web/src/components/dashboard/OperationsTrendPanel.tsx`: 7/30 天真实 SVG 趋势和无数据原因。
- Create `web/src/components/dashboard/OperationsReadinessPanel.tsx`: 数据库、Provider、LLM、调度器就绪状态。
- Create `web/src/components/dashboard/RecentRunsTable.tsx`: 内容/数据运行统一近期表格和真实详情链接。
- Create `web/src/components/dashboard/DashboardComponents.test.tsx`: 组件语义、空态和路由测试。
- Modify `web/src/pages/OperationsDashboardPage.tsx`: 只负责页面编排和动作。
- Modify `web/src/pages/OperationsDashboardPage.test.tsx`: 覆盖加载、空、部分降级、失败、陈旧数据和运行中状态。
- Create `web/src/styles/pages/dashboard.css`: Dashboard 专属布局与响应式样式。
- Modify `web/src/styles/index.css`: 将页面样式加入 `components` 层。
- Create `web/e2e/dashboard.spec.ts`: 桌面、平板、移动端布局和真实状态检查。
- Create `docs/superpowers/acceptance/2026-08-27-sectorpulse-reference-ui-phase2.md`: 阶段验收证据。
- Modify `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md`: 标记 Phase 2 完成并链接验收报告。

---

### Task 1: Define The Canonical Operations Model

**Files:**
- Create: `backend/src/sector_pulse/application/operations_summary.py`
- Create: `backend/tests/unit/application/test_operations_summary.py`

**Interfaces:**
- Produces: `OperationalRun`, `OperationsSnapshot`, `OperationsSummaryQueryPort`, `classify_status(status, kind)`, `build_operations_snapshot(records, now, days=30, recent_limit=10)`。
- Consumes: 已持久化的运行 ID、类型、模式、状态、Provider、时间、成本和候选数；不访问网络。

- [ ] **Step 1: Write failing classification and aggregation tests**

```python
def test_build_snapshot_unifies_content_and_data_runs() -> None:
    now = datetime(2026, 8, 27, 12, tzinfo=UTC)
    records = [
        OperationalRun("content-1", "content", "内容生成", "READY_FOR_HUMAN_REVIEW", "live", now, now, 1200, Decimal("0.4"), 3),
        OperationalRun("data-1", "data", "盘后复盘", "FETCHING_NEWS", "live", now, None, None, None, 12),
        OperationalRun("data-2", "data", "盘中分析", "FAILED", "live", now, now, 900, None, 0),
    ]

    snapshot = build_operations_snapshot(records, now=now)

    assert snapshot.summary.total == 3
    assert snapshot.summary.completed_today == 1
    assert snapshot.summary.active == 1
    assert snapshot.summary.attention == 2
    assert [item.run_id for item in snapshot.recent_runs] == ["content-1", "data-1", "data-2"]


def test_empty_snapshot_explains_absent_trend() -> None:
    snapshot = build_operations_snapshot([], now=datetime(2026, 8, 27, tzinfo=UTC))
    assert snapshot.trend.available is False
    assert snapshot.trend.reason == "当前还没有可用于趋势统计的运行记录"
    assert snapshot.trend.points == ()
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_operations_summary.py -q -p no:cacheprovider`

Expected: FAIL because `sector_pulse.application.operations_summary` does not exist.

- [ ] **Step 3: Implement canonical status sets and immutable models**

```python
CONTENT_ACTIVE = {"RUNNING"}
CONTENT_SUCCESS = {"READY_FOR_HUMAN_REVIEW"}
CONTENT_ATTENTION = {"READY_FOR_HUMAN_REVIEW", "REVISE_REQUIRED", "UNREVIEWED", "BUDGET_EXCEEDED", "ATTRIBUTION_BLOCKED", "DRAFT_GENERATION_FAILED", "FAILED"}
DATA_ACTIVE = {"PREFLIGHT", "FETCHING_MARKET", "RANKING_PRE_CANDIDATES", "FETCHING_NEWS", "BUILDING_EVIDENCE"}
DATA_SUCCESS = {"READY_FOR_ATTRIBUTION", "DEGRADED"}
DATA_ATTENTION = {"DEGRADED", "BLOCKED", "FAILED", "INTERRUPTED"}
```

`build_operations_snapshot` must sort by `requested_at` descending, calculate exact summary values, create one point for each UTC calendar day containing records, and return no points plus the exact reason above when no records exist.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `\.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_operations_summary.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit the canonical model**

```powershell
git add backend/src/sector_pulse/application/operations_summary.py backend/tests/unit/application/test_operations_summary.py
git commit -m "feat: define operations summary model"
```

### Task 2: Add Exact SQLite And PostgreSQL Operations Queries

**Files:**
- Create: `backend/src/sector_pulse/storage/operations_query.py`
- Create: `backend/src/sector_pulse/storage/postgres_operations_query.py`
- Modify: `backend/src/sector_pulse/storage/runtime_bundle.py`
- Create: `backend/tests/integration/test_postgres_operations_query.py`
- Modify: `backend/tests/integration/test_operations_summary_api.py`

**Interfaces:**
- Consumes: `phase1b_runs`, `sector_analysis_cards`, `real_data_runs`, `real_data_candidates`。
- Produces: `SQLiteOperationsQuery.list_records(since, limit=None)` and `PostgresOperationsQuery.list_records(since, limit=None) -> list[OperationalRun]` with identical semantics.

- [ ] **Step 1: Add a failing SQLite integration scenario with both run kinds**

Insert one `phase1b_runs` row and one `real_data_runs` row into the temporary SQLite database, call `/api/operations/summary`, and assert:

```python
assert payload["summary"] == {
    "total": 2,
    "completed_today": 1,
    "active": 1,
    "attention": 1,
}
assert [item["kind"] for item in payload["recent_runs"]] == ["data", "content"]
assert payload["recent_runs"][0]["detail_path"].startswith("/data-runs/")
assert payload["trend"]["available"] is True
```

- [ ] **Step 2: Run the SQLite integration test and verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_operations_summary_api.py -q -p no:cacheprovider`

Expected: FAIL because the additive fields are absent.

- [ ] **Step 3: Implement the SQLite query**

Use one `UNION ALL` query that normalizes both tables into:

```text
run_id, kind, mode, status, provider, requested_at, finished_at,
elapsed_ms, total_cost_cny, candidate_count
```

Content candidate count comes from `sector_analysis_cards`; data candidate count comes from `real_data_candidates`. A missing count is `0`, while unavailable elapsed time and cost stay `NULL`.

- [ ] **Step 4: Implement PostgreSQL parity and runtime registration**

Use SQLAlchemy `text()` with named parameters and `result.mappings()`. Register `operations` in `RuntimeStorageBundle`; wrap PostgreSQL with the existing `BlockingAsyncRepository` bridge. Do not add a migration.

- [ ] **Step 5: Add the PostgreSQL contract test**

The test uses the repository’s existing PostgreSQL fixture/skip convention, inserts one row of each kind, and asserts the normalized fields match the SQLite test. It must skip cleanly when PostgreSQL is unavailable rather than replacing it with a mock database.

- [ ] **Step 6: Run storage and integration tests**

Run: `\.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_operations_summary_api.py backend/tests/integration/test_postgres_operations_query.py -q -p no:cacheprovider`

Expected: SQLite PASS; PostgreSQL PASS when configured or SKIP with the repository suite’s standard reason.

- [ ] **Step 7: Commit the storage queries**

```powershell
git add backend/src/sector_pulse/storage/operations_query.py backend/src/sector_pulse/storage/postgres_operations_query.py backend/src/sector_pulse/storage/runtime_bundle.py backend/tests/integration/test_operations_summary_api.py backend/tests/integration/test_postgres_operations_query.py
git commit -m "feat: query real operations history"
```

### Task 3: Extend The Operations API Compatibly

**Files:**
- Modify: `backend/src/sector_pulse/web/operations_schemas.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `backend/tests/integration/test_operations_summary_api.py`

**Interfaces:**
- Consumes: `storage.operations.list_records(...)`, settings, consent files, Provider preflight and scheduler state.
- Produces: additive fields `summary`, `trend`, `readiness`, `recent_runs`, `generated_at` while preserving all legacy fields.

- [ ] **Step 1: Add failing response-contract assertions**

```python
assert payload["generated_at"].endswith("Z") or "+" in payload["generated_at"]
assert set(payload["readiness"]) == {"database", "live_data", "llm", "scheduler"}
assert payload["readiness"]["database"]["status"] == "ready"
assert "must-never-appear" not in response.text
assert payload["runs"]["total"] == payload["summary"]["total"]
```

- [ ] **Step 2: Run the API test and verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_operations_summary_api.py -q -p no:cacheprovider`

Expected: FAIL on missing `generated_at` and `readiness`.

- [ ] **Step 3: Add immutable Pydantic response models**

Define `OperationsCoreSummary`, `OperationsTrendPoint`, `OperationsTrend`, `OperationsReadinessItem`, and `OperationsRecentRun`. `detail_path` must be generated only as `/runs/{id}` or `/data-runs/{id}` from the trusted `kind` value.

- [ ] **Step 4: Compose the endpoint response**

Use one captured `now = datetime.now(UTC)` for all calculations and `generated_at`. Map readiness status to `ready | warning | unavailable | disabled`; reasons must mention missing consent/configuration names without exposing values. Keep the legacy `runs.recent` content-only shape for existing consumers.

- [ ] **Step 5: Run backend regression**

Run: `\.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_operations_summary.py backend/tests/unit/web backend/tests/integration/test_operations_summary_api.py -q -p no:cacheprovider -m "not live"`

Expected: PASS, with only documented environment-dependent skips.

- [ ] **Step 6: Commit the API contract**

```powershell
git add backend/src/sector_pulse/web/operations_schemas.py backend/src/sector_pulse/web/app.py backend/tests/integration/test_operations_summary_api.py
git commit -m "feat: extend operations dashboard api"
```

### Task 4: Type The Frontend Contract And Build Reliable Polling

**Files:**
- Modify: `web/src/operationsApi.ts`
- Modify: `web/src/operationsApi.test.ts`
- Create: `web/src/hooks/useOperationsSummary.ts`
- Create: `web/src/hooks/useOperationsSummary.test.tsx`

**Interfaces:**
- Produces: `OperationsSummary`, `OperationsTrendPoint`, `OperationsRecentRun`, `fetchOperationsSummary(signal?)`, `useOperationsSummary()`.
- Hook returns: `{ data, initialLoading, refreshing, stale, error, lastSuccessfulAt, refresh }`.

- [ ] **Step 1: Write failing API and hook tests**

Tests must assert:

```typescript
expect(fetch).toHaveBeenCalledWith('/api/operations/summary', { signal: undefined })
expect(result.current.initialLoading).toBe(false)
expect(result.current.data?.summary.active).toBe(1)
```

With fake timers, advance 5 seconds and expect a second request only when `summary.active > 0`. Set `document.visibilityState` to `hidden`, dispatch `visibilitychange`, advance 10 seconds, and expect no request. Reject a refresh after one successful response and assert `data` is preserved while `stale=true`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `Set-Location web; npm.cmd test -- src/operationsApi.test.ts src/hooks/useOperationsSummary.test.tsx`

Expected: FAIL because the hook and additive types do not exist.

- [ ] **Step 3: Implement typed API and request cancellation**

`fetchOperationsSummary(signal?: AbortSignal)` passes the signal to `fetch`, throws `OperationsApiError` containing only HTTP status and a safe message, and validates no secrets client-side.

- [ ] **Step 4: Implement recursive timeout polling**

Use `setTimeout` after each completed request rather than `setInterval`, so requests cannot overlap. Schedule 5 seconds only if `data.summary.active > 0` and the document is visible. Abort in-flight requests on unmount. Manual `refresh` works in stale state and does not clear the retained data.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `Set-Location web; npm.cmd test -- src/operationsApi.test.ts src/hooks/useOperationsSummary.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit the frontend data layer**

```powershell
git add web/src/operationsApi.ts web/src/operationsApi.test.ts web/src/hooks/useOperationsSummary.ts web/src/hooks/useOperationsSummary.test.tsx
git commit -m "feat: add reliable operations polling"
```

### Task 5: Build The Real Operations Dashboard

**Files:**
- Create: `web/src/components/dashboard/OperationsMetricGrid.tsx`
- Create: `web/src/components/dashboard/OperationsTrendPanel.tsx`
- Create: `web/src/components/dashboard/OperationsReadinessPanel.tsx`
- Create: `web/src/components/dashboard/RecentRunsTable.tsx`
- Create: `web/src/components/dashboard/DashboardComponents.test.tsx`
- Modify: `web/src/pages/OperationsDashboardPage.tsx`
- Modify: `web/src/pages/OperationsDashboardPage.test.tsx`
- Create: `web/src/styles/pages/dashboard.css`
- Modify: `web/src/styles/index.css`

**Interfaces:**
- Consumes: Phase 2 `OperationsSummary` and `useOperationsSummary`.
- Produces: a truthful `DashboardLayout` with metric cards, real trend, readiness list, recent runs, loading/error/empty/stale states and actual routes.

- [ ] **Step 1: Write failing component tests**

Tests assert that:

- metric cards render `运行总数`, `今日已完成`, `运行中`, `异常与待处理` from props;
- the 7/30 day segmented control has correct `aria-pressed` states;
- unavailable trend shows the backend reason and no SVG polyline;
- readiness displays all four real items and links only to `/system`;
- recent data runs link to `/data-runs/{id}` and content runs to `/runs/{id}`;
- `candidate_count=null` renders `暂无` rather than `0`;
- table empty state does not include invented records.

- [ ] **Step 2: Run component tests and verify RED**

Run: `Set-Location web; npm.cmd test -- src/components/dashboard/DashboardComponents.test.tsx`

Expected: FAIL because the components do not exist.

- [ ] **Step 3: Implement semantic dashboard components**

Use existing `MetricCard`, `Panel`, `StatusBadge`, `Button`, and `AppIcon`. Draw the trend with one accessible SVG per selected range and include a visually available summary such as `最近 7 天共 12 次运行` outside the graphic. Do not add a chart dependency, tooltip-only facts, gradients, fake percentages or animation.

- [ ] **Step 4: Write failing page-state tests**

Mock `useOperationsSummary` rather than timers. Cover initial loading, empty success, full success, partial readiness warning, initial hard failure, retained stale data, refreshing label and active-run polling copy.

- [ ] **Step 5: Recompose `OperationsDashboardPage`**

The page contains:

```text
PageHeader + last successful time + refresh + new analysis
4 metric cards
trend panel (2/3) + readiness panel (1/3)
recent runs table
```

Initial failure uses a full recovery alert. Refresh failure with retained data uses a compact warning banner and keeps all last successful cards visible. The refresh button exposes a loading label without changing width.

- [ ] **Step 6: Add page-scoped CSS**

At desktop, use a constrained Dashboard width, four-card row, `minmax(0, 2fr) minmax(300px, 1fr)` middle grid and a compact table. At 1024px use two metric columns and stack trend/readiness. At 767px use one metric column and horizontally scroll only the table viewport. Preserve visible focus, 44px mobile targets, reduced motion, and no full-page horizontal overflow.

- [ ] **Step 7: Run frontend tests and build**

Run: `Set-Location web; npm.cmd test -- src/components/dashboard/DashboardComponents.test.tsx src/pages/OperationsDashboardPage.test.tsx src/App.test.tsx; npm.cmd run build`

Expected: all tests PASS and Vite build succeeds.

- [ ] **Step 8: Run the Impeccable detector for changed UI files**

Run:

```powershell
node C:\Users\18067\.codex\skills\impeccable\scripts\detect.mjs --json web/src/pages/OperationsDashboardPage.tsx web/src/components/dashboard/OperationsMetricGrid.tsx web/src/components/dashboard/OperationsTrendPanel.tsx web/src/components/dashboard/OperationsReadinessPanel.tsx web/src/components/dashboard/RecentRunsTable.tsx web/src/styles/pages/dashboard.css
```

Expected: no unresolved detector findings.

- [ ] **Step 9: Commit the dashboard UI**

```powershell
git add web/src/components/dashboard web/src/pages/OperationsDashboardPage.tsx web/src/pages/OperationsDashboardPage.test.tsx web/src/styles/index.css web/src/styles/pages/dashboard.css
git commit -m "refactor: build truthful operations dashboard"
```

### Task 6: Browser Acceptance And Phase Closure

**Files:**
- Create: `web/e2e/dashboard.spec.ts`
- Create: `docs/superpowers/acceptance/2026-08-27-sectorpulse-reference-ui-phase2.md`
- Modify: `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md`

**Interfaces:**
- Consumes: completed Phase 2 API and dashboard.
- Produces: repeatable viewport assertions and an evidence-backed acceptance record.

- [ ] **Step 1: Add Playwright coverage**

Stub `/api/operations/summary` with deterministic contract fixtures only inside E2E tests. Assert that 1536×1024 and 1440×900 show four metrics, two-column trend/readiness and recent table without page overflow; 1024×768 stacks the middle panels; 390×844 keeps all controls reachable and confines horizontal scrolling to the table wrapper.

- [ ] **Step 2: Run complete frontend verification**

Run:

```powershell
Set-Location web
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e -- e2e/shell.spec.ts e2e/dashboard.spec.ts
Set-Location ..
```

Expected: all Vitest, build and Playwright checks PASS.

- [ ] **Step 3: Run non-live backend verification**

Run:

```powershell
$env:SECTOR_PULSE_DATABASE_URL = ''
.\.venv\Scripts\python.exe -m pytest backend/tests/unit backend/tests/integration -q -p no:cacheprovider -m "not live"
```

Expected: all SQLite and unit tests PASS; PostgreSQL-only tests SKIP because this command intentionally clears the URL.

- [ ] **Step 4: Verify PostgreSQL when the configured service is reachable**

Run without overriding `SECTOR_PULSE_DATABASE_URL`:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_postgres_operations_query.py -q -p no:cacheprovider
```

Expected: PASS when PostgreSQL is reachable. If the configured service refuses connection, record that exact environmental exception; do not report PostgreSQL acceptance as passed.

- [ ] **Step 5: Perform live browser inspection**

Use the actual local page at 1536×1024, 1440×900, 1024×768 and 390×844. Inspect loading, empty database, real-record success, active refresh indicator, stale-data warning and hard failure. Confirm no console errors, clipped actions, invented values or navigation regressions.

- [ ] **Step 6: Run final repository checks**

Run: `git diff --check; git status --short`

Expected: no whitespace errors; only Phase 2 acceptance/master-plan edits remain before the closure commit.

- [ ] **Step 7: Write acceptance evidence and close Phase 2**

The acceptance report records exact command results, viewport outcomes, PostgreSQL result or exception, detector result and remaining non-blocking warnings. Mark Phase 2 tasks complete in the master plan only when evidence exists.

- [ ] **Step 8: Commit Phase 2 acceptance**

```powershell
git add web/e2e/dashboard.spec.ts docs/superpowers/acceptance/2026-08-27-sectorpulse-reference-ui-phase2.md docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md
git commit -m "docs: record reference ui phase 2 acceptance"
```

---

## Plan Self-Review

- Spec coverage: all Phase 2 requirements map to Tasks 1–6, including truthful metrics, 7/30 day trends, readiness, recent runs, active polling, stale-data retention and responsive acceptance.
- Placeholder scan: no `TBD`, `TODO`, “implement later”, fake metric or unspecified error-handling step remains.
- Type consistency: backend `summary.active` drives frontend polling; `trend.available/reason/points` drives truthful chart states; `recent_runs.kind/detail_path/candidate_count` drives table routing and unknown values.
- Scope boundary: candidate selection, news details and content drafting remain Phase 3; review editing and evidence decisions remain Phase 4.
