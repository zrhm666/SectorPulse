# SectorPulse Phase 1D-1 Real Data Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an auditable intraday/post-close A-share sector market and news acquisition workflow that produces candidates, evidence packs, and deterministic quality states without invoking an LLM.

**Architecture:** Reuse existing Phase 1A/1A.2 domain models and provider ports, adding a dedicated real-data run aggregate, orchestrator, repository, and Web boundary. Market scan runs before candidate-scoped news recall; deterministic gates produce `READY_FOR_ATTRIBUTION`, `DEGRADED`, or `BLOCKED` and never fall back to Fixture after a Live failure.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLite, AKShare, asyncio, React 18, TypeScript, Vitest, Playwright.

## Global Constraints

- Scope is A-share industry and concept sectors only.
- Phase 1D-1 does not invoke a real LLM, generate an article, or publish content.
- Real data requires explicit `.live-data-consent`; missing consent returns HTTP 409 before inserting a running row.
- Intraday defaults to a 6-hour news lookback; post-close defaults to 24 hours.
- Market pre-candidates are capped at 30 and final candidates at 12.
- News after the locked cutoff is excluded; discovery-only news cannot become an explicit driver by itself.
- Live failure must not fall back to Fixture.
- API keys, raw confidential responses, and full news bodies must not be logged.
- Existing Fixture Phase 1B behavior remains backward compatible.
- Key classes, state transitions, boundary conversion, and exception paths receive Chinese comments.

---

## File Structure

```text
backend/src/sector_pulse/
  domain/real_data_run.py                 # Phase 1D-1 request, state and quality DTOs
  application/real_data_orchestrator.py   # Deterministic workflow coordination
  application/real_data_queries.py        # Read-only Web DTO assembly
  infrastructure/providers/real_data_factory.py # consent/config/provider composition
  storage/real_data_run_repository.py     # SQLite run and candidate persistence
  storage/migrations/006_phase1d1.sql      # run, candidate and quality tables
  web/data_run_service.py                  # background task and progress facade
  web/data_run_schemas.py                  # HTTP request/response contracts
  web/app.py                               # REST and SSE routes
web/src/
  dataRunsApi.ts                           # typed Phase 1D-1 client
  pages/DataRunPage.tsx                    # quality/candidate/evidence workbench
  components/NewDataRunDialog.tsx          # intraday/post-close launcher
```

### Task 1: Define the real-data run state contract

**Files:**
- Create: `backend/src/sector_pulse/domain/real_data_run.py`
- Test: `backend/tests/unit/domain/test_real_data_run.py`

**Interfaces:**
- Produces: `RealDataRunRequest`, `RealDataRunStatus`, `RealDataRun`, `RealDataQualitySummary`
- Consumes: `AnalysisMode`, `QualityStatus`

- [ ] **Step 1: Write the failing state and default tests**

```python
def test_intraday_defaults_to_six_hour_lookback() -> None:
    request = RealDataRunRequest(mode="intraday")
    assert request.lookback_hours == 6

def test_post_close_defaults_to_twenty_four_hours() -> None:
    request = RealDataRunRequest(mode="post_close")
    assert request.lookback_hours == 24

def test_terminal_statuses_are_explicit() -> None:
    assert RealDataRunStatus.READY_FOR_ATTRIBUTION.is_terminal
    assert not RealDataRunStatus.FETCHING_NEWS.is_terminal
```

- [ ] **Step 2: Run the tests and confirm missing types fail**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_real_data_run.py -v -p no:cacheprovider`

Expected: FAIL because `sector_pulse.domain.real_data_run` does not exist.

- [ ] **Step 3: Implement immutable request and state models**

```python
class RealDataRunStatus(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    FETCHING_MARKET = "FETCHING_MARKET"
    RANKING_PRE_CANDIDATES = "RANKING_PRE_CANDIDATES"
    FETCHING_NEWS = "FETCHING_NEWS"
    BUILDING_EVIDENCE = "BUILDING_EVIDENCE"
    READY_FOR_ATTRIBUTION = "READY_FOR_ATTRIBUTION"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.READY_FOR_ATTRIBUTION, self.DEGRADED, self.BLOCKED,
            self.FAILED, self.CANCELLED, self.INTERRUPTED,
        }

class RealDataRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    mode: Literal["intraday", "post_close"]
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    lookback_hours: int | None = Field(default=None, ge=1, le=168)
    precandidate_limit: int = Field(default=30, ge=1, le=30)
    final_candidate_limit: int = Field(default=12, ge=1, le=12)

    @model_validator(mode="after")
    def apply_mode_default(self) -> "RealDataRunRequest":
        if self.lookback_hours is None:
            object.__setattr__(self, "lookback_hours", 6 if self.mode == "intraday" else 24)
        return self
```

- [ ] **Step 4: Run tests and Ruff**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_real_data_run.py -q -p no:cacheprovider`

Run: `.\.venv\Scripts\python.exe -m ruff check --no-cache backend/src/sector_pulse/domain/real_data_run.py backend/tests/unit/domain/test_real_data_run.py`

- [ ] **Step 5: Prepare commit**

```powershell
git add backend/src/sector_pulse/domain/real_data_run.py backend/tests/unit/domain/test_real_data_run.py
git commit -m "feat: define real data run states"
```

Do not execute the commit while the user retains Git control.

### Task 2: Persist runs, candidates, and quality summaries

**Files:**
- Create: `backend/src/sector_pulse/storage/migrations/006_phase1d1.sql`
- Create: `backend/src/sector_pulse/storage/real_data_run_repository.py`
- Test: `backend/tests/unit/storage/test_real_data_run_repository.py`
- Modify: `backend/tests/unit/storage/test_sqlite_schema.py`

**Interfaces:**
- Produces: `SQLiteRealDataRunRepository.insert`, `update_status`, `save_candidates`, `get_run`, `list_runs`, `mark_interrupted`
- Consumes: Task 1 domain models and existing `SQLiteDatabase`

- [ ] **Step 1: Write failing persistence and recovery tests**

```python
def test_round_trip_run_and_candidates(tmp_path) -> None:
    repo = SQLiteRealDataRunRepository(SQLiteDatabase(tmp_path / "db.sqlite"))
    repo.insert(run())
    repo.save_candidates(RUN_ID, (candidate("industry-1"),))
    assert repo.get_run(RUN_ID).status is RealDataRunStatus.PREFLIGHT
    assert repo.get_candidates(RUN_ID)[0].sector_id == "industry-1"

def test_non_terminal_rows_become_interrupted(tmp_path) -> None:
    repo = repository_with_status(tmp_path, RealDataRunStatus.FETCHING_NEWS)
    assert repo.mark_interrupted() == 1
    assert repo.get_run(RUN_ID).status is RealDataRunStatus.INTERRUPTED
```

- [ ] **Step 2: Run tests and confirm missing repository fails**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_real_data_run_repository.py -v -p no:cacheprovider`

- [ ] **Step 3: Add migration with explicit status constraint**

```sql
CREATE TABLE real_data_runs (
  run_id TEXT PRIMARY KEY,
  mode TEXT NOT NULL CHECK (mode IN ('intraday', 'post_close')),
  status TEXT NOT NULL CHECK (status IN (
    'PREFLIGHT', 'FETCHING_MARKET', 'RANKING_PRE_CANDIDATES',
    'FETCHING_NEWS', 'BUILDING_EVIDENCE', 'READY_FOR_ATTRIBUTION',
    'DEGRADED', 'BLOCKED', 'FAILED', 'CANCELLED', 'INTERRUPTED'
  )),
  requested_at TEXT NOT NULL,
  cutoff_at TEXT,
  request_json TEXT NOT NULL,
  market_status TEXT,
  news_status TEXT,
  downgrade_reasons_json TEXT NOT NULL DEFAULT '[]',
  error_code TEXT,
  finished_at TEXT
);
CREATE TABLE real_data_candidates (
  run_id TEXT NOT NULL REFERENCES real_data_runs(run_id),
  sector_id TEXT NOT NULL,
  sector_kind TEXT NOT NULL,
  rank INTEGER NOT NULL,
  score TEXT NOT NULL,
  reasons_json TEXT NOT NULL,
  PRIMARY KEY (run_id, sector_id)
);
```

- [ ] **Step 4: Implement JSON-safe repository mapping**

The repository serializes only request parameters, reasons, and quality summaries. It does not store API keys or raw response bodies.

- [ ] **Step 5: Run repository and migration regression tests**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_real_data_run_repository.py backend/tests/unit/storage/test_sqlite_schema.py -q -p no:cacheprovider`

- [ ] **Step 6: Prepare commit**

```powershell
git add backend/src/sector_pulse/storage backend/tests/unit/storage
git commit -m "feat: persist real data runs"
```

Do not execute the commit while the user retains Git control.

### Task 3: Compose real providers and enforce synchronous preflight

**Files:**
- Create: `backend/src/sector_pulse/infrastructure/providers/real_data_factory.py`
- Test: `backend/tests/unit/infrastructure/test_real_data_factory.py`
- Modify: `config/news_sources.yaml`

**Interfaces:**
- Produces: `RealDataProviderBundle`, `RealDataProviderFactory.preflight()`, `build()`
- Consumes: existing AKShare market, constituent, CLS, Eastmoney, CNInfo adapters

- [ ] **Step 1: Write failing consent and registration tests**

```python
def test_missing_consent_is_unavailable(tmp_path) -> None:
    result = factory(consent=tmp_path / "missing").preflight()
    assert not result.available
    assert result.missing == ("live-data-consent",)

def test_preflight_never_returns_secret_values(tmp_path) -> None:
    result = configured_factory(tmp_path).preflight()
    assert "api_key" not in result.model_dump_json().lower()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure/test_real_data_factory.py -v -p no:cacheprovider`

- [ ] **Step 3: Implement provider bundle and preflight**

```python
class RealDataProviderBundle(NamedTuple):
    market: MarketDataPort
    constituents: SectorConstituentPort
    global_news: GlobalNewsDiscoveryPort
    keyword_news: KeywordNewsSearchPort
    disclosure_news: DisclosureSearchPort

class RealDataProviderFactory:
    def preflight(self) -> ProviderPreflightResult:
        if not self._consent_file.is_file():
            return ProviderPreflightResult(available=False, missing=("live-data-consent",))
        return ProviderPreflightResult(available=True, missing=())
```

- [ ] **Step 4: Run unit tests and no-network construction test**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure/test_real_data_factory.py -q -p no:cacheprovider`

- [ ] **Step 5: Prepare commit**

```powershell
git add backend/src/sector_pulse/infrastructure/providers/real_data_factory.py config/news_sources.yaml backend/tests/unit/infrastructure/test_real_data_factory.py
git commit -m "feat: compose real market and news providers"
```

Do not execute the commit while the user retains Git control.

### Task 4: Implement deterministic orchestration and quality states

**Files:**
- Create: `backend/src/sector_pulse/application/real_data_orchestrator.py`
- Test: `backend/tests/integration/test_real_data_orchestrator.py`
- Reuse: `backend/src/sector_pulse/application/phase1a2_probe.py`

**Interfaces:**
- Produces: `run_real_data_workflow(dependencies, request, progress_sink) -> RealDataRunResult`
- Consumes: `Phase1A2Dependencies`, `Phase1A2Request`, Task 1/2/3 interfaces

- [ ] **Step 1: Write failing happy, degraded, and blocked tests**

```python
async def test_ready_when_market_and_news_quality_pass(tmp_path) -> None:
    result = await run_real_data_workflow(healthy_dependencies(tmp_path), intraday_request())
    assert result.status is RealDataRunStatus.READY_FOR_ATTRIBUTION
    assert len(result.candidates) <= 12

async def test_single_news_source_failure_is_degraded(tmp_path) -> None:
    result = await run_real_data_workflow(one_source_failed(tmp_path), intraday_request())
    assert result.status is RealDataRunStatus.DEGRADED
    assert "NEWS_SOURCE_PARTIAL" in result.downgrade_reasons

async def test_missing_concept_market_blocks(tmp_path) -> None:
    result = await run_real_data_workflow(missing_concept_market(tmp_path), post_close_request())
    assert result.status is RealDataRunStatus.BLOCKED

async def test_cutoff_deduplication_and_no_explanation_are_preserved(tmp_path) -> None:
    result = await run_real_data_workflow(boundary_news_dependencies(tmp_path), intraday_request())
    assert result.quality.cutoff_violation_count == 1
    assert result.quality.duplicate_document_count == 1
    assert "NO_RELIABLE_EXPLANATION" in result.evidence[0].gate_reasons
```

- [ ] **Step 2: Run tests and verify missing workflow failure**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_real_data_orchestrator.py -v -p no:cacheprovider`

- [ ] **Step 3: Adapt Phase 1A.2 report into explicit terminal rules**

```python
def decide_terminal_status(report: Phase1A2Report) -> tuple[RealDataRunStatus, tuple[str, ...]]:
    if any(q.status is QualityStatus.BLOCKED for q in report.market_quality.values()):
        return RealDataRunStatus.BLOCKED, ("CORE_MARKET_BLOCKED",)
    if not report.ready_for_phase1b or report.downgrade_reasons:
        return RealDataRunStatus.DEGRADED, tuple(report.downgrade_reasons)
    return RealDataRunStatus.READY_FOR_ATTRIBUTION, ()
```

- [ ] **Step 4: Emit progress before each state transition and persist terminal result**

The orchestrator emits `FETCHING_MARKET`, `RANKING_PRE_CANDIDATES`, `FETCHING_NEWS`, and `BUILDING_EVIDENCE`. It keeps intraday wording observational, enforces the post-close cutoff rule, records missing optional ranking fields as a downgrade instead of zero, and preserves counter-evidence in evidence packs. Exception paths store a safe `error_code` and transition to `FAILED`.

- [ ] **Step 5: Run integration regression**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_real_data_orchestrator.py backend/tests/integration/test_phase1a2_probe.py -q -p no:cacheprovider`

- [ ] **Step 6: Prepare commit**

```powershell
git add backend/src/sector_pulse/application/real_data_orchestrator.py backend/tests/integration/test_real_data_orchestrator.py
git commit -m "feat: orchestrate real data acceptance runs"
```

Do not execute the commit while the user retains Git control.

### Task 5: Add Web command, query, SSE, retry, and cancellation boundaries

**Files:**
- Create: `backend/src/sector_pulse/web/data_run_service.py`
- Create: `backend/src/sector_pulse/web/data_run_schemas.py`
- Create: `backend/src/sector_pulse/application/real_data_queries.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Test: `backend/tests/integration/test_data_run_api.py`

**Interfaces:**
- Produces: `/api/data-runs` endpoints defined in the spec
- Consumes: Task 2 repository, Task 3 factory, Task 4 orchestrator, existing `ProgressBus` and `RunTaskRegistry`

- [ ] **Step 1: Write failing preflight and lifecycle API tests**

```python
def test_missing_consent_returns_409_without_insert(client, repository) -> None:
    response = client.post("/api/data-runs", json={"mode": "intraday"})
    assert response.status_code == 409
    assert repository.list_runs() == []

def test_fixture_data_run_reaches_ready(client) -> None:
    response = client.post("/api/data-runs", json={"mode": "intraday", "provider": "fixture"})
    run_id = response.json()["run_id"]
    assert poll_terminal(client, run_id)["status"] == "READY_FOR_ATTRIBUTION"

def test_retry_creates_a_new_run_and_cancel_is_terminal(client) -> None:
    original_id = create_running_fixture_run(client)
    assert client.post(f"/api/data-runs/{original_id}/cancel").json()["status"] == "CANCELLED"
    retried_id = client.post(f"/api/data-runs/{original_id}/retry").json()["run_id"]
    assert retried_id != original_id
```

- [ ] **Step 2: Run API tests and verify routes are absent**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_data_run_api.py -v -p no:cacheprovider`

- [ ] **Step 3: Implement typed request and response schemas**

```python
class NewDataRunRequest(BaseModel):
    mode: Literal["intraday", "post_close"]
    provider: Literal["fixture", "live"] = "live"
    lookback_hours: int | None = Field(default=None, ge=1, le=168)
    precandidate_limit: int = Field(default=30, ge=1, le=30)
    final_candidate_limit: int = Field(default=12, ge=1, le=12)
```

- [ ] **Step 4: Implement service using shared task registry and bounded ProgressBus**

Preflight occurs before insert. Retry copies mode and numeric parameters into a new run ID. Cancellation stores `CANCELLED`. Startup calls `mark_interrupted()` once.

- [ ] **Step 5: Add REST/SSE routes and run tests**

Add the complete boundary from the approved spec: `POST /api/data-runs`, `GET /api/data-runs`, `GET /api/data-runs/{run_id}`, `GET /api/data-runs/{run_id}/events`, `GET /api/data-runs/{run_id}/candidates`, `GET /api/data-runs/{run_id}/evidence`, `GET /api/data-runs/{run_id}/quality`, `POST /api/data-runs/{run_id}/cancel`, and `POST /api/data-runs/{run_id}/retry`. Query routes return persisted DTOs; they never trigger provider calls.

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_data_run_api.py backend/tests/integration/test_web_api.py -q -p no:cacheprovider`

- [ ] **Step 6: Prepare commit**

```powershell
git add backend/src/sector_pulse/web backend/src/sector_pulse/application/real_data_queries.py backend/tests/integration/test_data_run_api.py
git commit -m "feat: expose real data run API"
```

Do not execute the commit while the user retains Git control.

### Task 6: Build the intraday/post-close Web workbench

**Files:**
- Create: `web/src/dataRunsApi.ts`
- Create: `web/src/components/NewDataRunDialog.tsx`
- Create: `web/src/pages/DataRunPage.tsx`
- Create: `web/src/pages/DataRunPage.test.tsx`
- Modify: `web/src/pages/RunListPage.tsx`
- Modify: `web/src/App.tsx`

**Interfaces:**
- Produces: `/data-runs/:runId` page and launcher buttons
- Consumes: Task 5 HTTP API

- [ ] **Step 1: Write failing launcher and quality rendering tests**

```tsx
it('starts an intraday run without internal JSON', async () => {
  renderLauncher()
  await user.click(screen.getByRole('button', { name: '盘中分析' }))
  expect(createDataRun).toHaveBeenCalledWith(expect.objectContaining({ mode: 'intraday' }))
})

it('shows degraded reasons and source states', async () => {
  renderDataRunPage('run-1')
  expect(await screen.findByText('DEGRADED')).toBeVisible()
  expect(screen.getByText('NEWS_SOURCE_PARTIAL')).toBeVisible()
})
```

- [ ] **Step 2: Run Vitest and verify missing components fail**

Run: `cd web; npm.cmd test -- --run`

- [ ] **Step 3: Implement typed API client and launcher**

```typescript
export interface NewDataRunRequest {
  mode: 'intraday' | 'post_close'
  provider: 'fixture' | 'live'
  lookback_hours?: number
  precandidate_limit: number
  final_candidate_limit: number
}
```

The default buttons use `live`; a visibly labeled Fixture option remains available for offline validation.

- [ ] **Step 4: Implement loading, error, empty, running, degraded, blocked, and ready states**

The page renders market quality, news source status, candidates, evidence links, exclusion counts, and downgrade reasons. It never shows an article in Phase 1D-1.

- [ ] **Step 5: Run tests and production build**

Run: `cd web; npm.cmd test -- --run`

Run: `cd web; npm.cmd run build`

- [ ] **Step 6: Prepare commit**

```powershell
git add web/src
git commit -m "feat: add real data analysis workbench"
```

Do not execute the commit while the user retains Git control.

### Task 7: Add offline E2E, Live acceptance, and validation reports

**Files:**
- Create: `web/e2e/data-run.spec.ts`
- Create: `backend/tests/live/test_phase1d1_live.py`
- Create: `scripts/verify-phase1d1.ps1`
- Create: `docs/phase1d1/README.md`
- Create: `docs/phase1d1/latest-live-validation.md`
- Modify: `web/playwright.config.ts`

**Interfaces:**
- Produces: repeatable offline gate and opt-in Live acceptance report
- Consumes: Tasks 1-6

- [ ] **Step 1: Write Fixture browser E2E**

```typescript
test('fixture intraday run reaches attribution-ready evidence', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Fixture 盘中分析' }).click()
  await expect(page.getByText('READY_FOR_ATTRIBUTION')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/候选板块/)).toBeVisible()
})

test('fixture post-close run exposes locked quality and evidence', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Fixture 盘后分析' }).click()
  await expect(page.getByText('READY_FOR_ATTRIBUTION')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/盘后/)).toBeVisible()
})
```

- [ ] **Step 2: Write opt-in Live test guarded by consent**

```python
@pytest.mark.live
def test_real_market_and_two_news_sources(live_consent) -> None:
    report = run_live_acceptance()
    assert set(report.market_quality) == {"INDUSTRY", "CONCEPT"}
    assert sum(m.document_count > 0 for m in report.source_metrics.values()) >= 2
```

- [ ] **Step 3: Add validation script with writable temp directories**

The PowerShell script sets `PYTHONPATH=backend/src`, `TEMP`, `TMP`, disables pytest and Ruff caches, runs backend tests, Ruff, Vitest, Vite build, and Playwright. It only removes a generated directory after resolving it beneath the system temp directory.

- [ ] **Step 4: Run the offline final gate**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider`

Run: `.\.venv\Scripts\python.exe -m ruff check --no-cache backend/src backend/tests`

Run: `cd web; npm.cmd test -- --run; npm.cmd run build; npm.cmd run test:e2e`

Expected: all offline tests and Fixture E2E pass; Live tests skip without explicit flags.

- [ ] **Step 5: Run Live acceptance only after explicit consent**

Run: `$env:PYTHONPATH='backend/src'; .\.venv\Scripts\python.exe -m pytest backend/tests/live/test_phase1d1_live.py --run-live -v -p no:cacheprovider`

Expected: the command exits successfully only when both sector snapshots and at least two usable news sources satisfy the assertions. If an external source or network blocks acceptance, write its safe error code and timestamp to `latest-live-validation.md`, keep the command non-zero, and do not substitute Fixture data or claim Live acceptance passed.

- [ ] **Step 6: Prepare commit**

```powershell
git add backend/tests/live web/e2e scripts/verify-phase1d1.ps1 docs/phase1d1 web/playwright.config.ts
git commit -m "test: validate real data acceptance workflow"
```

Do not execute the commit while the user retains Git control.
