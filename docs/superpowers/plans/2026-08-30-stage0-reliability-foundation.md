# SectorPulse Stage 0 Reliability Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scheduling, cancellation, restart recovery, autosave, and SQLite/PostgreSQL behavior reliable and enforceable by one repeatable quality gate.

**Architecture:** Use synchronous typed Repository Protocols for both SQLite and PostgreSQL while keeping external Provider and LLM workflows asynchronous. Route manual and scheduled execution through one coordinator, persist every lifecycle transition, and make the frontend render only persisted task truth.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, psycopg 3, SQLite, PostgreSQL 16, React 18, TypeScript, Vite, Vitest, Playwright, Pytest, Ruff, Mypy.

**Spec:** `docs/superpowers/specs/2026-08-30-stage0-reliability-foundation-design.md`

## Global Constraints

- Continue supporting both SQLite and PostgreSQL; configuring PostgreSQL must never silently fall back to SQLite.
- Keep migrations 001–015 immutable and preserve existing user data through forward-only migrations.
- Ordinary tests must not access Live data or a real LLM and must not consume quota.
- Keep the approved frontend visual system and public routes stable.
- Do not use broad `Any`, blanket `cast`, Mypy ignores, disabled tests, serial-only tests, or longer timeouts to manufacture a passing gate.
- API and persistence errors must not expose API keys, passwords, full connection strings, or raw third-party responses.
- Every task follows red-green-refactor, ends with focused verification, and receives its own commit.

## Target File Structure

| Path | Responsibility |
| --- | --- |
| `backend/src/sector_pulse/storage/ports.py` | Typed storage contracts shared by SQLite and PostgreSQL |
| `backend/src/sector_pulse/application/run_coordinator.py` | Unified manual/scheduled start, cancel, recovery, and retry commands |
| `backend/src/sector_pulse/application/scheduler.py` | Due-plan polling and failure isolation only |
| `backend/src/sector_pulse/storage/migrations/016_reliable_runtime.sql` | Forward-only lifecycle and scheduling fields |
| `backend/src/sector_pulse/storage/postgres.py` | Synchronous SQLAlchemy PostgreSQL engine, migration, and health check |
| `backend/src/sector_pulse/storage/runtime_bundle.py` | Fully typed adapter assembly with no async bridge |
| `backend/src/sector_pulse/web/dependencies.py` | Runtime dependency construction |
| `backend/src/sector_pulse/web/errors.py` | Sanitized API error envelope and exception handlers |
| `backend/src/sector_pulse/web/routers/*.py` | Focused API routers split by business capability |
| `web/src/hooks/draftAutosaveMachine.ts` | Framework-independent autosave state transitions |
| `web/src/hooks/useDraftAutosave.ts` | React binding, timers, and API effects |
| `scripts/verify-stage0.ps1` | One local non-Live quality gate |

---

## Phase A — Contracts and Forward Migration

### Task 1: Add lifecycle fields and migration 016

**Files:**
- Modify: `backend/src/sector_pulse/domain/task.py`
- Modify: `backend/src/sector_pulse/domain/real_data_run.py`
- Modify: `backend/src/sector_pulse/storage/sqlite.py`
- Modify: `backend/src/sector_pulse/storage/postgres.py`
- Create: `backend/src/sector_pulse/storage/migrations/016_reliable_runtime.sql`
- Create: `backend/src/sector_pulse/storage/migrations/sqlite/016_reliable_runtime.sql`
- Create: `backend/src/sector_pulse/storage/migrations/postgres/016_reliable_runtime.sql`
- Modify: `backend/tests/unit/storage/test_sqlite_schema.py`
- Modify: `backend/tests/unit/storage/test_postgres_migrations.py`
- Create: `backend/tests/unit/domain/test_task.py`
- Modify: `backend/tests/unit/domain/test_real_data_run.py`

**Interfaces:**
- Produces: `TaskRunStatus.INTERRUPTED`, persisted `retry_of_run_id`, `cancel_requested_at`, `interrupted_reason`, `heartbeat_at`, and schedule `last_triggered_at` fields.

- [x] **Step 1: Write failing migration and domain tests**

```python
def test_reliable_runtime_migration_adds_lifecycle_columns(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "runtime.db")
    database.initialize()
    with database.connection() as connection:
        task_columns = {row[1] for row in connection.execute("PRAGMA table_info(task_runs)")}
        run_columns = {row[1] for row in connection.execute("PRAGMA table_info(real_data_runs)")}
        schedule_columns = {row[1] for row in connection.execute("PRAGMA table_info(schedules)")}
    assert {"retry_of_run_id", "cancel_requested_at", "interrupted_reason", "heartbeat_at"} <= task_columns
    assert "retry_of_run_id" in run_columns
    assert "last_triggered_at" in schedule_columns

def test_interrupted_task_is_terminal() -> None:
    assert TaskRunStatus.INTERRUPTED.is_terminal
```

- [x] **Step 2: Run tests and verify they fail for missing columns/status**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_sqlite_schema.py backend/tests/unit/domain/test_real_data_run.py -q`

- [x] **Step 3: Add the domain value and migration**

```python
class TaskRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAITING = "RETRY_WAITING"
    DEGRADED = "DEGRADED"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.DEGRADED, self.READY_FOR_HUMAN_REVIEW,
            self.FAILED, self.CANCELLED, self.INTERRUPTED,
        }
```

```sql
ALTER TABLE task_runs ADD COLUMN retry_of_run_id TEXT REFERENCES task_runs(run_id);
ALTER TABLE task_runs ADD COLUMN cancel_requested_at TEXT;
ALTER TABLE task_runs ADD COLUMN interrupted_reason TEXT;
ALTER TABLE task_runs ADD COLUMN heartbeat_at TEXT;
ALTER TABLE real_data_runs ADD COLUMN retry_of_run_id TEXT REFERENCES real_data_runs(run_id);
ALTER TABLE schedules ADD COLUMN last_triggered_at TEXT;
CREATE INDEX IF NOT EXISTS idx_task_runs_retry_of ON task_runs(retry_of_run_id);
CREATE INDEX IF NOT EXISTS idx_real_data_runs_retry_of ON real_data_runs(retry_of_run_id);
CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(enabled, next_run_at);
```

Because migration 007 constrained `task_runs.status` before `INTERRUPTED` existed, keep the additive columns in the common 016 file and apply a same-version dialect supplement before recording version 16. The SQLite supplement transactionally copies `task_runs` into a table with the expanded CHECK constraint, preserves every column/row and child foreign key, then runs `PRAGMA foreign_key_check`; the PostgreSQL supplement drops and recreates only `task_runs_status_check`. Both runners execute the common and dialect statements in one transaction so a failed supplement cannot leave version 16 half-applied.

- [x] **Step 4: Run migration/domain tests and full non-Live backend regression**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage backend/tests/unit/domain/test_real_data_run.py -q`

- [x] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/domain backend/src/sector_pulse/storage/migrations backend/tests/unit/storage backend/tests/unit/domain/test_real_data_run.py
git commit -m "feat: add reliable runtime lifecycle schema"
```

### Task 2: Define typed storage ports and SQLite contract fixtures

**Files:**
- Create: `backend/src/sector_pulse/storage/ports.py`
- Modify: `backend/src/sector_pulse/storage/runtime_bundle.py`
- Create: `backend/tests/contracts/storage_contracts.py`
- Create: `backend/tests/contracts/test_sqlite_runtime_contract.py`
- Modify: `backend/src/sector_pulse/storage/task_repository.py`
- Modify: `backend/src/sector_pulse/storage/real_data_run_repository.py`

**Interfaces:**
- Produces: `TaskRepositoryPort`, `RealDataRunRepositoryPort`, `ScheduleRepositoryPort`, and typed aliases for every `RuntimeStorageBundle` field.
- Consumes: lifecycle fields from Task 1.

- [x] **Step 1: Write a structural contract test**

```python
def test_sqlite_runtime_adapters_satisfy_ports(sqlite_database: SQLiteDatabase) -> None:
    task: TaskRepositoryPort = SQLiteTaskRepository(sqlite_database)
    runs: RealDataRunRepositoryPort = SQLiteRealDataRunRepository(sqlite_database)
    assert isinstance(task, TaskRepositoryPort)
    assert isinstance(runs, RealDataRunRepositoryPort)
```

- [x] **Step 2: Run the contract test and verify missing ports fail collection**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_sqlite_runtime_contract.py -q`

- [x] **Step 3: Define runtime-checkable ports with exact lifecycle methods**

```python
@runtime_checkable
class TaskRepositoryPort(Protocol):
    def create_or_get_run(self, key: TaskRunKey, provider: str, input_json: dict[str, object], *, retry_of_run_id: UUID | None = None) -> UUID:
        raise NotImplementedError
    def request_cancel(self, run_id: UUID, requested_at: datetime) -> bool:
        raise NotImplementedError
    def transition(self, run_id: UUID, expected: TaskRunStatus, target: TaskRunStatus, *, source: str, summary: str, idempotency_key: str | None = None, error_code: str | None = None) -> bool:
        raise NotImplementedError
    def recover_interrupted(self, now: datetime, reason: str) -> int:
        raise NotImplementedError
    def get_task_detail(self, run_id: UUID) -> dict[str, object] | None:
        raise NotImplementedError

@runtime_checkable
class RealDataRunRepositoryPort(Protocol):
    def insert(self, run: RealDataRun) -> None:
        raise NotImplementedError
    def get_run(self, run_id: UUID) -> RealDataRun | None:
        raise NotImplementedError
    def update_status(self, run_id: UUID, status: RealDataRunStatus, *, cutoff_at: datetime | None = None, quality: RealDataQualitySummary | None = None, error_code: str | None = None, finished_at: datetime | None = None) -> None:
        raise NotImplementedError
    def mark_interrupted(self) -> int:
        raise NotImplementedError
```

Define the remaining ports from the synchronous SQLite public APIs in this exact matrix; private helpers beginning with `_` are excluded:

| Port | `RuntimeStorageBundle` field | Canonical method set |
| --- | --- | --- |
| `MarketSnapshotRepositoryPort` | `market_snapshots` | `SQLiteMarketSnapshotRepository.save/get` |
| `NewsRepositoryPort` | `news` | `SQLiteNewsRepository.save/get_event/get_events/get_documents` |
| `EvidenceRepositoryPort` | `evidence` | `SQLiteEvidenceRepository.save/list_for_run` |
| `NewsRetrievalRepositoryPort` | `news_retrieval` | `SQLiteNewsRetrievalRepository.save_audit/list_links/list_query_documents/list_queries/list_source_metrics` |
| `CandidateSelectionRepositoryPort` | `candidate_selections` | `SQLiteCandidateSelectionRepository.append/latest/list_versions` |
| `Phase1BRunsRepositoryPort` | `phase1b_runs` | `SQLitePhase1BRunsRepository.insert/get_run/update_status/list_runs` |
| `Phase1BRepositoryPort` | `phase1b` | `SQLitePhase1BRepository.save_contexts/save_gate_results/save_cards/save_outline/save_draft/save_review/list_drafts/get_contexts/get_gates/get_cards/get_outline/get_drafts/get_review` |
| `AgentInvocationRepositoryPort` | `invocations` | `SQLiteAgentInvocationRepository.save/list_for_run` |
| `NewsEvidenceRepositoryPort` | `news_evidence` | `SQLiteNewsEvidenceRepository.get_events` |
| `DraftEditRepositoryPort` | `draft_edit` | `SQLiteDraftEditRepository.save_draft/get_version/latest_version/latest_for_run/apply_patch` |
| `PromptGoldenRepositoryPort` | `prompt_golden` | `SQLitePromptGoldenRepository.save/list` |
| `ReleaseAuditRepositoryPort` | `release_audit` | `SQLiteReleaseAuditRepository.approve/revoke/approval/audit/record_export/record_event` |
| `ShadowAcceptanceRepositoryPort` | `shadow` | `SQLiteShadowAcceptanceRepository.save_run/list_runs/update_run/save_recovery/save_compliance` plus `get`, added to SQLite to match the existing PostgreSQL reader |
| `GovernanceRepositoryPort` | `governance` | `SQLiteGovernanceRepository.save_evidence_decision/list_evidence_decisions/save_preference_candidate/adopt_preference` |
| `OperationsQueryPort` | `operations` | `SQLiteOperationsQuery.list_records` |
| `ReviewAnalyticsPort` | `review_analytics` | `for_run/summary` from the current analytics consumers |

`ScheduleRepositoryPort` contains `insert_schedule/list_schedules/get_schedule/update_schedule_next_run`, and `TaskRepositoryPort` contains the remaining public methods of `SQLiteTaskRepository`: `create_or_get_run/claim_run/transition/save_checkpoint/get_latest_valid_checkpoint/list_events/count_runs/get_task_detail/recover_expired_leases/link_data_run/list_linked_runs`. The SQLite task adapter implements both protocols.

- [x] **Step 4: Type `RuntimeStorageBundle` with ports and make SQLite contract pass**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_sqlite_runtime_contract.py backend/tests/unit/storage -q`

- [x] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/storage backend/tests/contracts
git commit -m "refactor: define typed storage ports"
```

## Phase B — Scheduler and Lifecycle Reliability

### Task 3: Persist and consume due schedule windows

**Files:**
- Modify: `backend/src/sector_pulse/application/schedule_service.py`
- Modify: `backend/src/sector_pulse/application/scheduler.py`
- Modify: `backend/src/sector_pulse/storage/task_repository.py`
- Modify: `backend/tests/unit/application/test_schedule_service.py`
- Modify: `backend/tests/unit/application/test_scheduler.py`

**Interfaces:**
- Produces: `ScheduleService.next_after(schedule, after)` and `TaskRepositoryPort.list_due_schedules(now)`.

- [x] **Step 1: Add failing delayed-poll and idempotency cases**

```python
@pytest.mark.parametrize("delay_seconds", [1, 10, 30])
@pytest.mark.asyncio
async def test_scheduler_consumes_plan_after_poll_delay(scheduler, delay_seconds: int) -> None:
    embedded, repository, _ = scheduler
    await embedded.poll_once(datetime(2026, 8, 19, 8, 0, delay_seconds, tzinfo=UTC))
    await embedded.poll_once(datetime(2026, 8, 19, 8, 0, delay_seconds + 1, tzinfo=UTC))
    assert repository.count_runs() == 1
```

- [x] **Step 2: Verify the current `next_due >= now` logic fails**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_scheduler.py -q`

- [x] **Step 3: Implement persistent due consumption**

```python
async def poll_once(self, now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    for schedule in self._repository.list_due_schedules(current):
        try:
            await self._coordinator.start_scheduled(schedule, current)
            next_run = self._schedules.next_after(schedule, current)
            self._repository.record_schedule_trigger(schedule.schedule_id, current, next_run)
        except Exception as exc:
            self._repository.record_schedule_error(schedule.schedule_id, safe_error_code(exc), current)
```

- [x] **Step 4: Run schedule, scheduler, and repository tests**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_schedule_service.py backend/tests/unit/application/test_scheduler.py backend/tests/unit/storage/test_task_repository.py -q`

- [x] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/application/schedule_service.py backend/src/sector_pulse/application/scheduler.py backend/src/sector_pulse/storage/task_repository.py backend/tests/unit/application backend/tests/unit/storage/test_task_repository.py
git commit -m "fix: consume persisted schedule due windows"
```

### Task 4: Add one coordinator for manual and scheduled starts

**Files:**
- Create: `backend/src/sector_pulse/application/run_coordinator.py`
- Modify: `backend/src/sector_pulse/application/task_run_service.py`
- Modify: `backend/src/sector_pulse/application/scheduled_data_bridge.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Create: `backend/tests/unit/application/test_run_coordinator.py`
- Modify: `backend/tests/integration/test_phase2a_api.py`

**Interfaces:**
- Produces: `RunCoordinator.start_scheduled(schedule, now)`, `start_schedule_now(schedule_id, idempotency_key)`, `request_cancel(run_id)`, and `retry(run_id)`.
- Consumes: typed task/data repositories and schedule behavior from Tasks 2–3.

- [x] **Step 1: Write a failing API integration test proving “立即运行” starts data work**

```python
def test_trigger_schedule_creates_and_starts_linked_data_run(client, schedule_id, fake_data_runs) -> None:
    response = client.post(f"/api/schedules/{schedule_id}/trigger", headers={"Idempotency-Key": "manual-1"})
    assert response.status_code == 202
    detail = client.get(f"/api/task-runs/{response.json()['run_id']}").json()
    assert detail["data_run_id"] == str(fake_data_runs.run_id)
    assert fake_data_runs.started == 1
```

- [x] **Step 2: Run and confirm the current orphan queue record fails**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase2a_api.py -q`

- [x] **Step 3: Implement the coordinator command boundary**

```python
class RunCoordinator:
    def start_schedule_now(self, schedule_id: UUID, idempotency_key: str | None) -> UUID:
        schedule = self._tasks.require_schedule(schedule_id)
        task_run_id = self._tasks.create_scheduled_run(schedule, idempotency_key=idempotency_key)
        data_run_id = self._data_runs.create(self._request_for(schedule), "live")
        self._tasks.link_data_run(task_run_id, data_run_id)
        self._tasks.record_event(task_run_id, "MANUAL_TRIGGER_ACCEPTED", "manual schedule trigger accepted")
        return task_run_id
```

Both manual and timed methods must call one private `_start_schedule()` transaction boundary. If data-run creation fails, transition the task to `FAILED` with a safe code before returning/raising.

- [x] **Step 4: Replace the API and scheduler bridge callers, then run focused tests**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_run_coordinator.py backend/tests/unit/application/test_scheduled_data_bridge.py backend/tests/integration/test_phase2a_api.py -q`

- [x] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/application backend/src/sector_pulse/web/app.py backend/tests/unit/application backend/tests/integration/test_phase2a_api.py
git commit -m "fix: unify manual and scheduled run execution"
```

### Task 5: Persist cancellation and recover interrupted runs

**Files:**
- Modify: `backend/src/sector_pulse/web/data_run_service.py`
- Modify: `backend/src/sector_pulse/web/run_service.py`
- Modify: `backend/src/sector_pulse/application/run_coordinator.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `backend/tests/unit/web/test_data_run_service.py`
- Modify: `backend/tests/unit/web/test_run_service.py`
- Modify: `backend/tests/integration/test_phase2a_recovery.py`

**Interfaces:**
- Produces: persisted cancel request/terminal state and `RunCoordinator.recover_startup(now)`.

- [x] **Step 1: Write cancellation and startup recovery failures**

```python
@pytest.mark.asyncio
async def test_cancelled_data_run_is_persisted(service, repository) -> None:
    run_id = service.create(REQUEST, "fixture")
    assert service.cancel(run_id)
    await service.wait(run_id)
    assert repository.get_run(run_id).status is RealDataRunStatus.CANCELLED

def test_startup_marks_unowned_active_runs_interrupted(coordinator, repository) -> None:
    repository.insert(active_run())
    assert coordinator.recover_startup(NOW) == 1
    assert repository.get_run(RUN_ID).status is RealDataRunStatus.INTERRUPTED

def test_startup_marks_running_task_interrupted(coordinator, task_repository) -> None:
    run_id = task_repository.create_or_get_run(
        TaskRunKey(input_fingerprint="startup-recovery"), "fixture", {}
    )
    assert task_repository.claim_run(
        run_id, "dead-worker", NOW + timedelta(minutes=5), now=NOW
    )
    coordinator.recover_startup(NOW + timedelta(seconds=1))
    assert task_repository.get_task_detail(run_id)["status"] == "INTERRUPTED"
```

- [x] **Step 2: Run and verify cancellation/recovery fail with stale active state**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/web/test_data_run_service.py backend/tests/integration/test_phase2a_recovery.py -q`

- [x] **Step 3: Persist cancellation in the executor and invoke recovery from lifespan**

```python
async def execute() -> None:
    try:
        result = await run_real_data_workflow(
            dependencies_factory(provider),
            request,
            run_id=run_id,
            provider=provider,
            progress_sink=lambda status: self.bus.emit(
                run_id,
                {"type": "progress", "status": status.value},
            ),
        )
        self.bus.finish(result.run.run_id, {"type": "done", "status": result.status.value})
    except asyncio.CancelledError:
        self.repository.update_status(
            run_id, RealDataRunStatus.CANCELLED, finished_at=datetime.now(UTC)
        )
        self.bus.finish(run_id, {"type": "cancelled", "status": "CANCELLED"})
        raise
```

Call `coordinator.recover_startup(datetime.now(UTC))` after database initialization and before scheduler startup. Add `wait(run_id)` for tests and controlled shutdown only; do not expose it as a blocking API.

- [x] **Step 4: Run lifecycle and API tests**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/web backend/tests/integration/test_phase2a_recovery.py backend/tests/integration/test_web_api.py -q`

- [x] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/web backend/src/sector_pulse/application/run_coordinator.py backend/tests/unit/web backend/tests/integration
git commit -m "fix: persist cancellation and startup recovery"
```

### Task 6: Isolate scheduler bridge failures and prevent repeated generation

**Files:**
- Modify: `backend/src/sector_pulse/application/scheduled_data_bridge.py`
- Modify: `backend/src/sector_pulse/application/scheduler.py`
- Modify: `backend/src/sector_pulse/storage/task_repository.py`
- Modify: `backend/tests/unit/application/test_scheduled_data_bridge.py`
- Modify: `backend/tests/unit/application/test_scheduler.py`

**Interfaces:**
- Produces: `claim_ready_linked_run(task_run_id, data_run_id)` and one-shot content generation.

- [x] **Step 1: Add tests for one-shot advance and failure isolation**

```python
def test_bridge_advances_ready_run_once(bridge, writing) -> None:
    assert bridge.advance() == 1
    assert bridge.advance() == 0
    assert len(writing.generated) == 1

@pytest.mark.asyncio
async def test_one_broken_schedule_does_not_stop_other_due_schedules(scheduler) -> None:
    await scheduler.poll_once(NOW)
    assert scheduler.repository.successful_run_count() == 1
    assert scheduler.repository.error_event_count() == 1
```

- [x] **Step 2: Run and confirm duplicate advance/current loop exception behavior fails**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_scheduled_data_bridge.py backend/tests/unit/application/test_scheduler.py -q`

- [x] **Step 3: Add an atomic claim before generation and per-item exception isolation**

```python
if not self._tasks.claim_ready_linked_run(task_run_id, data_run_id):
    continue
try:
    self._writing.generate(data_run_id, selection.selected_sector_ids)
except Exception as exc:
    self._tasks.fail_claimed_run(task_run_id, safe_error_code(exc))
else:
    self._tasks.mark_content_started(task_run_id)
```

- [x] **Step 4: Run scheduler/bridge tests and backend regression**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_scheduler.py backend/tests/unit/application/test_scheduled_data_bridge.py backend/tests/integration/test_phase2a_recovery.py -q`

- [x] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/application backend/src/sector_pulse/storage/task_repository.py backend/tests/unit/application backend/tests/integration/test_phase2a_recovery.py
git commit -m "fix: isolate scheduled workflow advancement"
```

## Phase C — Synchronous PostgreSQL and Typed Runtime

### Task 7: Replace async PostgreSQL engine with synchronous SQLAlchemy/psycopg

**Files:**
- Modify: `pyproject.toml`
- Modify: `backend/src/sector_pulse/storage/postgres.py`
- Modify: `backend/src/sector_pulse/storage/database_config.py`
- Modify: `backend/src/sector_pulse/storage/database_runtime.py`
- Modify: `backend/tests/unit/storage/test_postgres_database.py`
- Modify: `backend/tests/unit/storage/test_database_runtime.py`
- Modify: `backend/tests/unit/storage/test_postgres_migrations.py`

**Interfaces:**
- Produces: `PostgresDatabase.start() -> Engine`, `healthcheck() -> bool`, `initialize() -> None`, `close() -> None`.

- [x] **Step 1: Rewrite the database unit contract first**

```python
def test_postgres_database_builds_sync_engine() -> None:
    database = PostgresDatabase("postgresql+psycopg://user:pass@localhost/db")
    engine = database.start()
    assert isinstance(engine, Engine)
    database.close()
    assert database.engine is None

def test_legacy_asyncpg_url_is_normalized_for_sync_psycopg() -> None:
    config = resolve_database_config(
        "postgresql+asyncpg://user:pass@localhost/db",
        "unused.db",
    )
    assert config.url == "postgresql+psycopg://user:pass@localhost/db"
```

- [x] **Step 2: Run and verify the async engine implementation fails the new contract**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_postgres_database.py backend/tests/unit/storage/test_database_runtime.py -q`

- [x] **Step 3: Change the dependency and database implementation**

```toml
postgres = ["psycopg[binary]>=3.2,<4", "SQLAlchemy>=2.0,<3"]

[tool.pytest.ini_options]
markers = [
  "live: requires explicit live network access",
  "live_llm: requires explicit live LLM access",
  "postgres: requires SECTOR_PULSE_DATABASE_URL and an isolated PostgreSQL database",
]
```

Normalize `postgres://`, `postgresql://`, and the existing `postgresql+asyncpg://` form to `postgresql+psycopg://` in `resolve_database_config`; reject every non-SQLite/non-PostgreSQL scheme and never erase a configured PostgreSQL URL after connection failure.

```python
@dataclass
class PostgresDatabase:
    url: str
    engine: Engine | None = None

    def start(self) -> Engine:
        if self.engine is None:
            self.engine = create_engine(self.url, pool_pre_ping=True)
        return self.engine
```

Normalize accepted configuration URLs from `postgresql+asyncpg://` to `postgresql+psycopg://` in `resolve_database_config` so existing `.env` files remain usable without exposing the URL.

- [x] **Step 4: Install updated editable dependencies and run database tests**

Run: `\.venv\Scripts\python.exe -m pip install -e ".[dev,postgres]"`

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_postgres_database.py backend/tests/unit/storage/test_database_runtime.py backend/tests/unit/storage/test_postgres_migrations.py -q`

- [x] **Step 5: Commit**

```powershell
git add pyproject.toml backend/src/sector_pulse/storage/postgres.py backend/src/sector_pulse/storage/database_runtime.py backend/tests
git commit -m "refactor: use synchronous postgres engine"
```

### Task 8: Convert core data PostgreSQL repositories

**Files:**
- Modify: `backend/src/sector_pulse/storage/postgres_real_data_run_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_market_snapshot_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_news_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_news_retrieval_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_evidence_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_candidate_selection_repository.py`
- Modify: `backend/tests/integration/test_postgres_real_data_run_repository.py`
- Modify: `backend/tests/integration/test_postgres_market_snapshot_repository.py`
- Modify: `backend/tests/integration/test_postgres_news_repository.py`
- Modify: `backend/tests/integration/test_postgres_news_retrieval_repository.py`
- Modify: `backend/tests/integration/test_postgres_evidence_repositories.py`
- Modify: `backend/tests/integration/test_postgres_candidate_selection_repository.py`
- Create: `backend/tests/contracts/test_postgres_data_contract.py`

**Interfaces:**
- Produces: synchronous implementations of the data-run, market, news, evidence, and candidate ports.

- [ ] **Step 1: Parameterize the existing data contract for PostgreSQL**

```python
@pytest.mark.postgres
def test_postgres_real_data_round_trip(postgres_database: PostgresDatabase) -> None:
    repository: RealDataRunRepositoryPort = PostgresRealDataRunRepository(postgres_database)
    assert_real_data_run_contract(repository)
```

- [ ] **Step 2: Run the contract and verify coroutine-returning methods fail**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_postgres_data_contract.py -q`

- [ ] **Step 3: Convert each method to `with engine.begin()/connect()` and typed mappings**

```python
def get_run(self, run_id: UUID) -> RealDataRun | None:
    with self._database.start().connect() as connection:
        row = connection.execute(
            text("SELECT * FROM real_data_runs WHERE run_id = :run_id"),
            {"run_id": str(run_id)},
        ).mappings().first()
    return self._row_to_run(row) if row is not None else None
```

Use `Mapping[str, object]` row decoders with explicit coercion helpers; do not index an `object` or return `Any`.

- [ ] **Step 4: Run PostgreSQL data integration contracts**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_postgres_data_contract.py backend/tests/integration/test_postgres_real_data_run_repository.py backend/tests/integration/test_postgres_market_snapshot_repository.py backend/tests/integration/test_postgres_news_repository.py backend/tests/integration/test_postgres_news_retrieval_repository.py backend/tests/integration/test_postgres_evidence_repositories.py backend/tests/integration/test_postgres_candidate_selection_repository.py -q`

- [ ] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/storage/postgres_* backend/tests/contracts backend/tests/integration/test_postgres_*
git commit -m "refactor: sync postgres data repositories"
```

### Task 9: Convert content, review, and governance PostgreSQL repositories

**Files:**
- Modify: `backend/src/sector_pulse/storage/postgres_phase1b_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_phase1b_runs_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_agent_invocation_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_news_evidence_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_draft_edit_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_governance_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_release_audit_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_prompt_golden_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_shadow_acceptance_repository.py`
- Modify: `backend/src/sector_pulse/application/postgres_review_analytics.py`
- Create: `backend/tests/contracts/test_postgres_content_contract.py`
- Modify: `backend/tests/integration/test_postgres_phase1b_repository.py`
- Modify: `backend/tests/integration/test_postgres_phase1b_runs_repository.py`
- Modify: `backend/tests/integration/test_postgres_agent_invocation_repository.py`
- Modify: `backend/tests/integration/test_postgres_draft_edit_repository.py`
- Modify: `backend/tests/integration/test_postgres_governance_repository.py`
- Modify: `backend/tests/integration/test_postgres_release_audit_repository.py`
- Modify: `backend/tests/integration/test_postgres_prompt_golden_repository.py`
- Modify: `backend/tests/integration/test_postgres_shadow_repository.py`
- Modify: `backend/tests/integration/test_postgres_review_analytics.py`

**Interfaces:**
- Produces: synchronous content/review implementations of the ports defined in Task 2.

- [ ] **Step 1: Add one shared round-trip contract covering draft edit, decision, approval, revoke, export, and audit**

```python
def assert_release_audit_contract(repository: ReleaseAuditRepositoryPort) -> None:
    approval = DraftApproval(
        approval_id=uuid4(), run_id=uuid4(), draft_id=uuid4(), version=1,
        governance_hash="contract-hash", actor="contract-test",
        status=ApprovalStatus.APPROVED_FOR_COPY, approved_at=datetime.now(UTC),
    )
    repository.approve(approval)
    assert repository.approval(approval.draft_id, approval.version) == approval
    repository.revoke(
        approval.run_id, approval.draft_id, approval.version,
        "contract-test", datetime.now(UTC),
    )
    revoked = repository.approval(approval.draft_id, approval.version)
    assert revoked is not None
    assert revoked.status is ApprovalStatus.REVOKED
```

In the same contract module, add separate fixtures for draft save/edit/version conflict, governance evidence decisions, shadow save/get/update, prompt-golden save/list, Phase 1B save/read, invocation save/list, release export/audit, and analytics `for_run/summary`. Parameterize each fixture over SQLite and PostgreSQL adapter factories so the assertions are identical.

- [ ] **Step 2: Run and verify async repositories violate the synchronous contract**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_postgres_content_contract.py -q`

- [ ] **Step 3: Convert every public async method in the listed adapters to the matching synchronous port signature**

Use `Engine.begin()` for every save/update operation and `Engine.connect()` for every read. Convert returned SQLAlchemy rows through `Mapping[str, object]` decoders before constructing domain values. Keep draft version read-check-write inside one `Engine.begin()` block; keep approval/revocation plus their audit event inside one block; keep shadow update and its recovery/compliance append individually atomic. Remove `async`/`await` from `PostgresReviewAnalyticsQueries.for_run/summary` and return `ReviewMetrics`/`ReviewSummary` directly.

- [ ] **Step 4: Run all content/governance PostgreSQL integration tests**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_postgres_phase1b_repository.py backend/tests/integration/test_postgres_phase1b_runs_repository.py backend/tests/integration/test_postgres_agent_invocation_repository.py backend/tests/integration/test_postgres_draft_edit_repository.py backend/tests/integration/test_postgres_governance_repository.py backend/tests/integration/test_postgres_release_audit_repository.py backend/tests/integration/test_postgres_prompt_golden_repository.py backend/tests/integration/test_postgres_shadow_repository.py backend/tests/integration/test_postgres_review_analytics.py -q`

- [ ] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/storage backend/src/sector_pulse/application/postgres_review_analytics.py backend/tests/contracts backend/tests/integration
git commit -m "refactor: sync postgres review repositories"
```

### Task 10: Convert task and operations repositories, then remove the bridge

**Files:**
- Modify: `backend/src/sector_pulse/storage/postgres_task_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_operations_query.py`
- Modify: `backend/src/sector_pulse/storage/runtime_bundle.py`
- Modify: `backend/tests/integration/test_postgres_task_repository.py`
- Modify: `backend/tests/integration/test_postgres_operations_query.py`
- Delete bridge implementation from: `backend/src/sector_pulse/storage/runtime_bundle.py`

**Interfaces:**
- Produces: a bundle containing direct typed repositories only.

- [ ] **Step 1: Add a contract asserting bundle fields are direct ports, not bridge wrappers**

```python
def test_postgres_bundle_uses_direct_repositories(postgres_database: PostgresDatabase) -> None:
    bundle = build_postgres_storage(postgres_database)
    assert isinstance(bundle.task, TaskRepositoryPort)
    assert type(bundle.task).__name__ == "PostgresTaskRepository"
    assert not hasattr(runtime_bundle, "BlockingAsyncRepository")
```

- [ ] **Step 2: Run and verify the current wrapper fails**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/contracts backend/tests/integration/test_postgres_task_repository.py backend/tests/integration/test_postgres_operations_query.py -q`

- [ ] **Step 3: Convert task/operations methods and delete `_run_awaitable`/`BlockingAsyncRepository`**

```python
def build_postgres_storage(database: PostgresDatabase) -> RuntimeStorageBundle:
    return RuntimeStorageBundle(
        market_snapshots=PostgresMarketSnapshotRepository(database),
        news=PostgresNewsRepository(database),
        evidence=PostgresEvidenceRepository(database),
        news_retrieval=PostgresNewsRetrievalRepository(database),
        real_data_runs=PostgresRealDataRunRepository(database),
        review_analytics=PostgresReviewAnalyticsQueries(database),
        task=PostgresTaskRepository(database),
        phase1b_runs=PostgresPhase1BRunsRepository(database),
        phase1b=PostgresPhase1BRepository(database),
        invocations=PostgresAgentInvocationRepository(database),
        news_evidence=PostgresNewsEvidenceRepository(database),
        draft_edit=PostgresDraftEditRepository(database),
        prompt_golden=PostgresPromptGoldenRepository(database),
        release_audit=PostgresReleaseAuditRepository(database),
        shadow=PostgresShadowAcceptanceRepository(database),
        governance=PostgresGovernanceRepository(database),
        operations=PostgresOperationsQuery(database),
        candidate_selections=PostgresCandidateSelectionRepository(database),
    )
```

- [ ] **Step 4: Run every PostgreSQL integration and contract test**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/contracts backend/tests/integration/test_postgres_* -q`

- [ ] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/storage backend/tests/contracts backend/tests/integration
git commit -m "refactor: remove postgres async bridge"
```

### Task 11: Integrate typed dependencies and clear storage/application Mypy errors

**Files:**
- Create: `backend/src/sector_pulse/web/dependencies.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `backend/src/sector_pulse/application/evidence_decision_service.py`
- Modify: `backend/src/sector_pulse/application/news_ingestion.py`
- Modify: `backend/src/sector_pulse/application/phase1a_probe.py`
- Modify: `backend/src/sector_pulse/application/phase1a2_probe.py`
- Modify: `backend/src/sector_pulse/application/phase1b_pipeline.py`
- Modify: `backend/src/sector_pulse/application/real_data_orchestrator.py`
- Modify: `backend/src/sector_pulse/application/real_data_queries.py`
- Modify: `backend/src/sector_pulse/application/real_data_writing_bridge.py`
- Modify: `backend/src/sector_pulse/application/run_executor.py`
- Modify: `backend/src/sector_pulse/application/schedule_service.py`
- Modify: `backend/src/sector_pulse/application/scheduled_data_bridge.py`
- Modify: `backend/src/sector_pulse/application/scheduler.py`
- Modify: `backend/src/sector_pulse/application/task_run_service.py`
- Modify: `backend/src/sector_pulse/web/data_run_service.py`
- Modify: `backend/src/sector_pulse/web/data_run_writing_service.py`
- Modify: `backend/src/sector_pulse/web/run_service.py`
- Create: `backend/tests/unit/web/test_dependencies.py`
- Modify: `backend/tests/unit/application/test_evidence_decision_service.py`
- Modify: `backend/tests/unit/application/test_news_ingestion.py`
- Modify: `backend/tests/unit/application/test_real_data_queries.py`
- Modify: `backend/tests/unit/application/test_real_data_writing_bridge.py`
- Modify: `backend/tests/unit/application/test_run_executor.py`
- Modify: `backend/tests/unit/application/test_schedule_service.py`
- Modify: `backend/tests/unit/application/test_scheduled_data_bridge.py`
- Modify: `backend/tests/unit/application/test_scheduler.py`
- Modify: `backend/tests/unit/web/test_data_run_service.py`
- Modify: `backend/tests/unit/web/test_run_service.py`

**Interfaces:**
- Produces: `RuntimeDependencies` and `build_runtime_dependencies(settings, database_path)`.

- [ ] **Step 1: Add dependency assembly tests for both backends**

```python
def test_sqlite_dependencies_are_fully_typed(tmp_path: Path) -> None:
    dependencies = build_runtime_dependencies(sqlite_settings(tmp_path), tmp_path / "app.db")
    assert isinstance(dependencies.storage.task, TaskRepositoryPort)

def test_postgres_configuration_never_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PostgresDatabase, "healthcheck", Mock(side_effect=ConnectionError))
    with pytest.raises(ConnectionError):
        build_runtime_dependencies(postgres_settings(), Path("unused.db"))
```

- [ ] **Step 2: Run dependency tests and Mypy to capture the focused error baseline**

Run: `\.venv\Scripts\python.exe -m mypy backend/src/sector_pulse/storage backend/src/sector_pulse/application backend/src/sector_pulse/web/dependencies.py`

- [ ] **Step 3: Move assembly from `create_app` and retarget services to ports**

```python
@dataclass(frozen=True)
class RuntimeDependencies:
    database: SQLiteDatabase | PostgresDatabase
    storage: RuntimeStorageBundle
    coordinator: RunCoordinator
    schedule_service: ScheduleService
    data_run_service: DataRunService | None
    run_service: RunService

def build_runtime_dependencies(settings: ApplicationSettings, database_path: Path) -> RuntimeDependencies:
    database = build_database(settings, database_path)
    storage = build_postgres_storage(database) if isinstance(database, PostgresDatabase) else build_sqlite_storage(database)
    coordinator = build_coordinator(storage)
    return RuntimeDependencies(
        database=database,
        storage=storage,
        coordinator=coordinator,
        schedule_service=ScheduleService(storage.task),
        data_run_service=build_data_run_service(settings, storage),
        run_service=build_run_service(settings, storage, coordinator),
    )
```

- [ ] **Step 4: Run focused Mypy and backend regression**

Run: `\.venv\Scripts\python.exe -m mypy backend/src/sector_pulse/storage backend/src/sector_pulse/application backend/src/sector_pulse/web`

Run: `\.venv\Scripts\python.exe -m pytest -m "not live and not live_llm" --import-mode=importlib -q`

- [ ] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse backend/tests
git commit -m "refactor: integrate typed runtime dependencies"
```

## Phase D — Frontend Reliability and Accessibility

### Task 12: Replace autosave ref timing with a deterministic state machine

**Files:**
- Create: `web/src/hooks/draftAutosaveMachine.ts`
- Create: `web/src/hooks/draftAutosaveMachine.test.ts`
- Modify: `web/src/hooks/useDraftAutosave.ts`
- Modify: `web/src/hooks/useDraftAutosave.test.tsx`
- Modify: `web/src/components/review/DraftWorkspace.tsx`

**Interfaces:**
- Produces: `reduceAutosave(state, event) -> AutosaveMachineState` and React hook commands `setValue`, `flush`, `retry`.

- [ ] **Step 1: Add deterministic rapid-blur and queued-save tests**

```typescript
it('flushes the newest value when change and blur happen in one turn', async () => {
  vi.useFakeTimers()
  const onSave = vi.fn().mockResolvedValue({
    draft_id: 'draft-1', version: 2,
    status: 'READY_FOR_HUMAN_REVIEW', content: {},
  })
  render(<Harness onSave={onSave} />)
  fireEvent.change(screen.getByLabelText('导语'), { target: { value: '最新值' } })
  fireEvent.blur(screen.getByLabelText('导语'))
  await act(async () => undefined)
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ value: '最新值' }))
})

it('submits queued text against the returned server version', async () => {
  vi.useFakeTimers()
  let resolveFirst: ((value: DraftPatchResponse) => void) | undefined
  const first = new Promise<DraftPatchResponse>((resolve) => { resolveFirst = resolve })
  const onSave = vi.fn()
    .mockReturnValueOnce(first)
    .mockResolvedValueOnce({ draft_id: 'draft-1', version: 3, status: 'READY_FOR_HUMAN_REVIEW', content: {} })
  render(<Harness onSave={onSave} />)
  fireEvent.change(screen.getByLabelText('导语'), { target: { value: '第一版' } })
  await act(() => vi.advanceTimersByTimeAsync(800))
  fireEvent.change(screen.getByLabelText('导语'), { target: { value: '第二版' } })
  await act(() => vi.advanceTimersByTimeAsync(800))
  await act(async () => resolveFirst?.({ draft_id: 'draft-1', version: 2, status: 'READY_FOR_HUMAN_REVIEW', content: {} }))
  expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ base_version: 2, value: '第二版' }))
})
```

- [ ] **Step 2: Run the test repeatedly with default workers and verify the current race reproduces**

Run: `npm.cmd test -- src/hooks/useDraftAutosave.test.tsx --run`

- [ ] **Step 3: Implement pure transitions and synchronize the ref before React rendering**

```typescript
export function reduceAutosave(state: AutosaveMachineState, event: AutosaveEvent): AutosaveMachineState {
  switch (event.type) {
    case 'changed': return changeField(state, event.key, event.value)
    case 'save-started': return startSave(state, event.key)
    case 'save-succeeded': return finishSave(state, event.key, event.snapshot, event.version)
    case 'save-failed': return failSave(state, event.key, event.conflict)
    default: return state
  }
}
```

`setValue()` must compute `next = reduceAutosave(machineRef.current, event)`, assign `machineRef.current = next`, and only then call `setState(next)`.

- [ ] **Step 4: Run autosave tests 10 times and the complete default-parallel suite**

Run: `1..10 | ForEach-Object { npm.cmd test -- src/hooks/useDraftAutosave.test.tsx --run; if ($LASTEXITCODE) { exit $LASTEXITCODE } }`

Run: `npm.cmd test -- --run`

- [ ] **Step 5: Commit**

```powershell
git add web/src/hooks web/src/components/review
git commit -m "fix: make draft autosave deterministic"
```

### Task 13: Reflect persisted cancellation/recovery and fix mobile navigation focus

**Files:**
- Modify: `web/src/dataRunsApi.ts`
- Modify: `web/src/pages/DataRunPage.tsx`
- Modify: `web/src/pages/TaskRunPage.tsx`
- Modify: `web/src/layout/SidebarNav.tsx`
- Modify: `web/src/layout/AppShell.tsx`
- Create: `web/src/hooks/useMediaQuery.ts`
- Create: `web/src/hooks/useMediaQuery.test.tsx`
- Modify: `web/src/layout/AppShell.test.tsx`
- Modify: `web/src/pages/DataRunPage.test.tsx`
- Modify: `web/src/pages/TaskRunPage.test.tsx`
- Modify: `web/e2e/shell.spec.ts`

**Interfaces:**
- Consumes: cancellation and `INTERRUPTED` API states from Task 5.

- [ ] **Step 1: Add failing status and keyboard tests**

```typescript
it('keeps cancelling state until persisted CANCELLED arrives', async () => {
  await user.click(screen.getByRole('button', { name: '取消运行' }))
  expect(screen.getByText('正在取消')).toBeVisible()
  expect(screen.queryByText('已取消')).not.toBeInTheDocument()
})

it('removes the closed mobile navigation from the tab order', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: '运营总览' })).not.toBeFocused()
})
```

- [ ] **Step 2: Run focused component and shell E2E tests and verify failure**

Run: `npm.cmd test -- src/layout/AppShell.test.tsx src/pages/DataRunPage.test.tsx src/pages/TaskRunPage.test.tsx --run`

- [ ] **Step 3: Add `inert`, focus restoration, and persisted status copy**

```tsx
const isNarrow = useMediaQuery('(max-width: 1024px)')
const sidebarRef = useRef<HTMLElement>(null)

useEffect(() => {
  if (sidebarRef.current) sidebarRef.current.inert = isNarrow && !open
}, [isNarrow, open])

<aside
  ref={sidebarRef}
  className="sidebar-nav"
  data-open={open}
  aria-hidden={isNarrow && !open ? true : undefined}
>
```

`useMediaQuery` must subscribe with `MediaQueryList.addEventListener('change', listener)`, remove that exact listener on cleanup, and initialize from `window.matchMedia(query).matches`. When the drawer closes, return focus to the menu trigger; when Escape is pressed inside an open drawer, close it. Do not hide the desktop sidebar. After `POST /cancel` succeeds, keep polling the run resource every two seconds until `CANCELLED`, `FAILED`, `INTERRUPTED`, or another terminal status is persisted; render retryable request-error copy if polling fails.

- [ ] **Step 4: Run component, E2E shell, and full frontend tests**

Run: `npm.cmd test -- --run`

Run: `npm.cmd run test:e2e -- shell.spec.ts`

- [ ] **Step 5: Commit**

```powershell
git add web/src web/e2e/shell.spec.ts
git commit -m "fix: align run status and mobile focus"
```

## Phase E — Routing, Test Harness, and Quality Gate

### Task 14: Split FastAPI app into capability routers

**Files:**
- Create: `backend/src/sector_pulse/web/routers/{operations,data_runs,runs_review,schedules_tasks,shadow_prompts}.py`
- Create: `backend/src/sector_pulse/web/routers/__init__.py`
- Create: `backend/src/sector_pulse/web/errors.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `backend/src/sector_pulse/web/dependencies.py`
- Modify: `backend/tests/integration/test_operations_summary_api.py`
- Modify: `backend/tests/integration/test_phase2a_api.py`
- Modify: `backend/tests/integration/test_phase2b_api.py`
- Modify: `backend/tests/integration/test_phase3_prompt_golden_api.py`
- Modify: `backend/tests/integration/test_phase3_shadow_api.py`
- Modify: `backend/tests/integration/test_phase3_shadow_progress_api.py`
- Modify: `backend/tests/integration/test_phase3_shadow_records_api.py`
- Modify: `backend/tests/integration/test_phase3_shadow_update_api.py`
- Modify: `backend/tests/integration/test_phase4_review_api.py`
- Modify: `backend/tests/integration/test_web_api.py`
- Create: `backend/tests/unit/web/test_errors.py`

**Interfaces:**
- Produces: `build_*_router(dependencies) -> APIRouter`; public paths and response models remain unchanged.

- [ ] **Step 1: Add a route manifest test before moving handlers**

```python
EXPECTED_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/operations/summary"),
    ("POST", "/api/data-runs"),
    ("POST", "/api/schedules/{schedule_id}/trigger"),
    ("GET", "/api/runs/{run_id}"),
}

def test_public_route_manifest(app: FastAPI) -> None:
    actual = {(method, route.path) for route in app.routes for method in getattr(route, "methods", set())}
    assert EXPECTED_ROUTES <= actual

def test_internal_error_response_is_sanitized(app: FastAPI) -> None:
    @app.get("/api/test-only/raise-secret-error")
    def raise_secret_error() -> None:
        raise RuntimeError("secret-token")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/test-only/raise-secret-error")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "服务暂时不可用", "retryable": True}
    }
    assert "secret-token" not in response.text
```

- [ ] **Step 2: Run API tests for the baseline**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_web_api.py backend/tests/integration/test_phase2a_api.py backend/tests/integration/test_phase2b_api.py backend/tests/integration/test_phase4_review_api.py -q`

- [ ] **Step 3: Move handlers without changing signatures or behavior**

```python
def build_data_runs_router(dependencies: RuntimeDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/data-runs", tags=["data-runs"])
    @router.post("")
    async def create_data_run(request: NewDataRunRequest) -> dict[str, object]:
        if dependencies.data_run_service is None:
            raise HTTPException(status_code=503, detail="real-data service unavailable")
        run_id = dependencies.data_run_service.create(
            RealDataRunRequest(
                mode=request.mode,
                lookback_hours=request.lookback_hours,
                precandidate_limit=request.precandidate_limit,
                final_candidate_limit=request.final_candidate_limit,
            ),
            request.provider,
        )
        return {"run_id": run_id}
    return router
```

`create_app()` remains responsible only for environment loading, dependency assembly, lifespan, router inclusion, and SPA mounting.

Register exception handlers from `errors.py` for domain conflicts, missing resources, unavailable dependencies, and unexpected failures. Every response uses `{"error": {"code": str, "message": str, "retryable": bool}}`; unexpected exception details go only to timestamped server logs, after redacting URL credentials and configured API-key values.

- [ ] **Step 4: Run all backend web/API tests and Mypy for web routers**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/unit/web backend/tests/integration/test_*api.py backend/tests/integration/test_web_api.py -q`

Run: `\.venv\Scripts\python.exe -m mypy backend/src/sector_pulse/web`

- [ ] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/web backend/tests
git commit -m "refactor: split fastapi capability routers"
```

### Task 15: Make Playwright reject backend leaks and exit cleanly

**Files:**
- Modify: `web/playwright.config.ts`
- Create: `web/e2e/fixtures.ts`
- Modify: `web/e2e/dashboard.spec.ts`
- Modify: `web/e2e/data-workbench.spec.ts`
- Modify: `web/e2e/remaining-pages.spec.ts`
- Modify: `web/e2e/review-workspace.spec.ts`
- Modify: `web/e2e/shell.spec.ts`
- Modify: `web/e2e/smoke.spec.ts`
- Modify: `web/package.json`

**Interfaces:**
- Produces: a shared test fixture that fails on page errors, console errors, and unhandled `/api` requests.

- [ ] **Step 1: Add a failing unhandled-request guard**

```typescript
export const test = base.extend({
  page: async ({ page }, use) => {
    const failures: string[] = []
    page.on('pageerror', error => failures.push(error.message))
    page.on('console', message => { if (message.type() === 'error') failures.push(message.text()) })
    page.on('requestfailed', request => failures.push(`${request.method()} ${request.url()}`))
    await use(page)
    expect(failures).toEqual([])
  },
})
```

- [ ] **Step 2: Run E2E and verify existing 9000 proxy errors are caught**

Run: `npm.cmd run test:e2e`

- [ ] **Step 3: Route every E2E API call through deterministic fixtures and let Playwright own Chromium/preview**

Move the response maps currently duplicated in specs into `e2e/fixtures.ts`, register `page.route('**/api/**', ...)` before navigation, and fail the fixture when a request has no declared method/path response. Remove the machine-specific Edge `executablePath`; use Playwright's installed `chromium`. Keep only Vite preview in `webServer`, set `reuseExistingServer: !process.env.CI`, and set the preview command to `npm.cmd run preview -- --host 127.0.0.1 --port 4173` on Windows or `npm run preview -- --host 127.0.0.1 --port 4173` elsewhere via a small `process.platform` constant in the config. API cross-layer behavior remains covered by FastAPI integration tests, while E2E tests own all browser-visible API state.

- [ ] **Step 4: Run E2E twice and verify exit code 0 without manual termination**

Run: `npm.cmd run test:e2e`

Run: `npm.cmd run test:e2e`

- [ ] **Step 5: Commit**

```powershell
git add web/playwright.config.ts web/e2e web/package.json
git commit -m "test: harden browser integration harness"
```

### Task 16: Upgrade React Router and remove known production audit findings

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`

**Interfaces:**
- Produces: supported React Router version with unchanged public routes.

- [ ] **Step 1: Preserve route behavior with existing App/router tests**

Run: `npm.cmd test -- src/App.test.tsx src/layout/AppShell.test.tsx --run`

- [ ] **Step 2: Upgrade to the chosen supported major after reading its official migration guide**

Run: `npm.cmd install react-router-dom@7.18.3`

Use the current supported v7 compatibility package and keep Declarative Mode. Do not move to React Router v8 in Stage 0 because it would also require the separate React 19, Node 22.22+, and Vite 7 baseline migration; do not introduce SSR/RSC/Data Router.

Execution references: `https://www.npmjs.com/package/react-router-dom?activeTab=versions` and `https://reactrouter.com/upgrading/v7`.

- [ ] **Step 3: Fix compile/test incompatibilities with the smallest API changes**

Run: `npm.cmd test -- --run`

Run: `npm.cmd run build`

- [ ] **Step 4: Verify production audit**

Run: `npm.cmd audit --omit=dev`

Expected: no fixable production dependency vulnerability. If an upstream advisory has no available patch and does not apply to Declarative Mode, document the exact advisory and applicability in the acceptance report rather than suppressing it.

- [ ] **Step 5: Commit**

```powershell
git add web/package.json web/package-lock.json web/src
git commit -m "chore: upgrade supported react router"
```

### Task 17: Clear Mypy and remove legacy style/reduced-motion drift

**Files:**
- Modify: `backend/src/sector_pulse/config/settings.py`
- Modify: `backend/src/sector_pulse/infrastructure/providers/akshare/adapter.py`
- Delete: `web/src/styles.css` after migrating every selector still referenced by JSX
- Modify: `web/src/styles/base.css`
- Modify: `web/src/styles/components/primitives.css`
- Modify: `web/src/styles/index.css`
- Modify: `web/src/styles/pages/dashboard.css`
- Modify: `web/src/styles/pages/data-run.css`
- Modify: `web/src/styles/pages/operations-pages.css`
- Modify: `web/src/styles/pages/review-workspace.css`
- Modify: `web/src/styles/responsive.css`
- Modify: `web/src/styles/shell.css`
- Modify: `web/src/styles/tokens.css`
- Modify: `web/src/layout/AppShell.test.tsx`
- Modify: `web/e2e/shell.spec.ts`

**Interfaces:**
- Produces: zero strict Mypy errors and one authoritative modular CSS system.

- [ ] **Step 1: Capture exact type and legacy selector baselines**

Run: `\.venv\Scripts\python.exe -m mypy backend/src/sector_pulse`

Run: `rg -n "styles.css|--color-|!important|0.01ms" web/src`

- [ ] **Step 2: Fix type errors by narrowing rows and depending on ports**

```python
def require_str(row: Mapping[str, object], key: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value
```

Use explicit helpers for `str`, `int`, `datetime`, JSON mappings, and optional values. Do not replace errors with `Any` or unverified casts.

- [ ] **Step 3: Migrate remaining used legacy selectors and remove the legacy import**

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto;
  }
  [data-decorative-motion="true"] {
    animation: none;
    transform: none;
  }
}
```

Remove `@import url("../styles.css") layer(legacy);` only after `rg` confirms every rendered class is defined in modular CSS. Delete `web/src/styles.css` in the same commit.

- [ ] **Step 4: Run strict typing, frontend tests, build, and detector**

Run: `\.venv\Scripts\python.exe -m mypy backend/src/sector_pulse`

Expected: `Success: no issues found`.

Run: `npm.cmd test -- --run`

Run: `npm.cmd run build`

Run: `node C:\Users\18067\.codex\skills\impeccable\scripts\detect.mjs --json web\src`

- [ ] **Step 5: Commit**

```powershell
git add backend/src web/src
git commit -m "refactor: enforce typed runtime and modular styles"
```

## Phase F — Integrated Acceptance

### Task 18: Add the Stage 0 quality script and final acceptance report

**Files:**
- Create: `scripts/verify-stage0.ps1`
- Create: `.github/workflows/quality.yml`
- Create: `docs/superpowers/acceptance/2026-08-30-stage0-reliability-foundation.md`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `.env.example`

**Interfaces:**
- Produces: one non-Live local gate and documented PostgreSQL/Live boundaries.

- [ ] **Step 1: Write the verification script with fail-fast commands**

```powershell
$ErrorActionPreference = 'Stop'
& .\.venv\Scripts\python.exe -m ruff check backend
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m mypy backend\src\sector_pulse
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m pip_audit
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m pytest -m 'not live and not live_llm' --import-mode=importlib -q
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Push-Location web
try {
  & npm.cmd test -- --run
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
  & npm.cmd run build
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
  & npm.cmd run test:e2e
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
  & npm.cmd audit --omit=dev
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
} finally { Pop-Location }
```

Add `pip-audit>=2.9,<3` to the `dev` extra, then add this CI workflow so the same checks run from a clean checkout and PostgreSQL contracts run against an ephemeral database:

```yaml
name: quality

on:
  push:
  pull_request:

jobs:
  sqlite-and-web:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: python -m pip install -e ".[dev,postgres]"
      - run: python -m ruff check backend
      - run: python -m mypy backend/src/sector_pulse
      - run: python -m pip_audit
      - run: python -m pytest -m "not live and not live_llm" --import-mode=importlib -q
      - run: npm ci
        working-directory: web
      - run: npx playwright install --with-deps chromium
        working-directory: web
      - run: npm test -- --run
        working-directory: web
      - run: npm run build
        working-directory: web
      - run: npm run test:e2e
        working-directory: web
      - run: npm audit --omit=dev
        working-directory: web

  postgres-contracts:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: sectorpulse_test
          POSTGRES_USER: sectorpulse
          POSTGRES_PASSWORD: sectorpulse_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U sectorpulse -d sectorpulse_test"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      SECTOR_PULSE_DATABASE_URL: postgresql+psycopg://sectorpulse:sectorpulse_test@127.0.0.1:5432/sectorpulse_test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - run: python -m pip install -e ".[dev,postgres]"
      - run: python -m pytest backend/tests/contracts/test_postgres_data_contract.py backend/tests/contracts/test_postgres_content_contract.py backend/tests/integration/test_postgres_*.py -q
```

- [ ] **Step 2: Run the gate without PostgreSQL and record that boundary explicitly**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify-stage0.ps1`

- [ ] **Step 3: Start/confirm PostgreSQL, back up the database, then run migrations and all PostgreSQL contracts**

Run: `\.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_postgres_* backend/tests/integration/test_postgres_* -q`

Before this command, verify the resolved database name and backup target without printing credentials. Do not create, drop, truncate, or reset the user's database during acceptance.

- [ ] **Step 4: Update README and acceptance evidence**

Document the synchronous psycopg URL compatibility, backup command, Stage 0 gate, cancellation/recovery behavior, and actual MIT license link. Record exact test counts, build sizes, PostgreSQL migration version, skipped Live tests, and any upstream-only advisory.

- [ ] **Step 5: Run repository integrity checks and commit**

Run: `git diff --check`

Run: `git status --short`

```powershell
git add scripts/verify-stage0.ps1 .github/workflows/quality.yml pyproject.toml README.md .env.example docs/superpowers/acceptance/2026-08-30-stage0-reliability-foundation.md
git commit -m "docs: complete stage 0 reliability acceptance"
```

## Final Review Gate

After Task 18:

1. Request a code review against the Stage 0 spec and this plan.
2. Fix every Critical and Important finding with focused tests and separate commits.
3. Re-run `scripts/verify-stage0.ps1` and PostgreSQL contracts.
4. Confirm `git diff --check` and a clean worktree.
5. Use `finishing-a-development-branch` to decide local merge/push; do not push without explicit user authorization.

## Spec Coverage Index

| Approved requirement | Implemented and verified by |
| --- | --- |
| Forward-only lifecycle schema, retry links, persisted schedule cursor | Tasks 1, 3, 5 |
| SQLite/PostgreSQL parity through synchronous typed ports | Tasks 2, 7–11 |
| One command path for manual and scheduled execution | Tasks 4, 6, 14 |
| Durable cancellation and interrupted-startup recovery | Tasks 5, 13 |
| Scheduler due-window correctness and per-run failure isolation | Tasks 3, 6 |
| Deterministic autosave with no stale-success race | Task 12 |
| Mobile navigation removed from focus order while closed | Task 13 |
| Smaller FastAPI composition root with stable public API | Task 14 |
| Stable Playwright lifecycle and backend-leak detection | Task 15 |
| Supported React Router and zero production audit findings | Task 16 |
| Full backend Mypy, reduced-motion, and obsolete-style cleanup | Task 17 |
| No ordinary Live/LLM quota use; repeatable local and CI gates | Task 18 |
| PostgreSQL backup/migration evidence without destructive reset | Task 18 |
