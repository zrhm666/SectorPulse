# Phase 2A Reliable Task Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Phase 1D 的手动运行扩展为基于 SQLite 持久化、可幂等、可重试、可重启恢复的应用内嵌任务调度系统，同时保持人工审核和手动发布边界。

**Architecture:** 在现有 FastAPI lifespan 中启动 `EmbeddedScheduler`；`ScheduleService` 只计算到期计划，`TaskRunService` 负责幂等创建与命令，`RunExecutor` 负责阶段状态机。SQLite migration 新增计划、任务、阶段尝试、检查点和事件表；现有 `RunService` 作为 Phase 1D 兼容适配层逐步委托执行器。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLite WAL、asyncio、pytest/pytest-asyncio、React/TypeScript/Vitest。

## Global Constraints

- 单机单进程部署；不引入 Redis、Celery、消息队列或分布式锁。
- 所有持久化时间使用 UTC；计划展示按计划时区转换。
- 阶段成功结果不可变；重试只能新增 attempt，不能覆盖失败历史。
- 真实数据缺失不能被解释成“暂无可靠解释”；核心行情失败必须阻断可审核草稿。
- 不实现全文编辑、证据人工裁决、局部重写和自动发布。
- API、日志和 SSE 不返回 API Key、完整 Prompt 或敏感模型响应。
- 每个任务结束都必须有可查询的状态、错误码、降级原因和阶段历史。

---

## 文件与职责地图

| 文件 | 职责 |
|---|---|
| `backend/src/sector_pulse/storage/migrations/007_phase2a_tasks.sql` | SQLite 计划、任务、阶段、检查点和事件表及唯一约束 |
| `backend/src/sector_pulse/domain/task.py` | 计划、任务、阶段状态和迁移规则的领域类型 |
| `backend/src/sector_pulse/storage/task_repository.py` | SQLite CRUD、条件状态更新、租约和幂等创建 |
| `backend/src/sector_pulse/application/task_run_service.py` | 手动/计划创建、取消、重试、恢复命令 |
| `backend/src/sector_pulse/application/run_executor.py` | 可恢复阶段执行、检查点读写、重试与降级决策 |
| `backend/src/sector_pulse/application/scheduler.py` | 计划轮询、交易日/时区计算和到期任务提交 |
| `backend/src/sector_pulse/web/task_schemas.py` | 计划、任务、阶段和事件 API schema |
| `backend/src/sector_pulse/web/app.py` | lifespan 启停及任务 API 路由 |
| `backend/tests/unit/storage/test_task_repository.py` | SQLite 幂等、租约和检查点测试 |
| `backend/tests/unit/application/test_task_run_service.py` | 命令和状态迁移测试 |
| `backend/tests/unit/application/test_scheduler.py` | 时区、交易日和重复触发测试 |
| `backend/tests/integration/test_phase2a_recovery.py` | 进程中断、恢复、重试和降级测试 |
| `web/src/schedulesApi.ts` | 计划/任务 HTTP 类型和调用 |
| `web/src/pages/SchedulePage.tsx` | 计划列表、启停和手动触发 |
| `web/src/pages/TaskRunPage.tsx` | 阶段进度、事件、重试/恢复和降级原因 |

## Task 1: Add domain state and SQLite migration

**Files:**
- Create: `backend/src/sector_pulse/domain/task.py`
- Create: `backend/src/sector_pulse/storage/migrations/007_phase2a_tasks.sql`
- Test: `backend/tests/unit/storage/test_task_repository.py`

**Interfaces:**
- Produces `ScheduleMode`, `TaskRunStatus`, `TaskStage`, `TaskRunKey`, `StageAttempt` and `Checkpoint` types used by later tasks.
- Migration is discovered automatically by `SQLiteDatabase.initialize()` because it matches `[0-9][0-9][0-9]_*.sql`.

- [ ] **Step 1: Write failing state and migration tests**

```python
def test_phase2a_migration_creates_tables(tmp_path):
    db = SQLiteDatabase(tmp_path / "phase2a.db")
    db.initialize()
    with db.connection() as conn:
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"schedules", "task_runs", "run_stage_attempts", "run_checkpoints", "task_events"} <= names
```

- [ ] **Step 2: Run test and verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_task_repository.py -q -p no:cacheprovider`

Expected: FAIL because migration `007_phase2a_tasks.sql` does not exist.

- [ ] **Step 3: Add the migration and domain enums**

Implement tables with foreign keys, UTC text timestamps, JSON payload columns, `UNIQUE(schedule_id, trading_date, planned_slot, input_fingerprint)` on `task_runs`, unique `(run_id, stage, attempt_no)`, and a unique valid-checkpoint key `(run_id, stage, input_fingerprint, implementation_version)`. Define statuses `QUEUED`, `RUNNING`, `RETRY_WAITING`, `DEGRADED`, `READY_FOR_HUMAN_REVIEW`, `FAILED`, `CANCELLED`; define stages `FETCHING_MARKET`, `FETCHING_NEWS`, `QUALITY_CHECKED`, `ATTRIBUTING`, `WRITING`.

```python
class TaskRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAITING = "RETRY_WAITING"
    DEGRADED = "DEGRADED"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class TaskStage(str, Enum):
    FETCHING_MARKET = "FETCHING_MARKET"
    FETCHING_NEWS = "FETCHING_NEWS"
    QUALITY_CHECKED = "QUALITY_CHECKED"
    ATTRIBUTING = "ATTRIBUTING"
    WRITING = "WRITING"
```

- [ ] **Step 4: Run migration tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_task_repository.py::test_phase2a_migration_creates_tables -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/sector_pulse/domain/task.py backend/src/sector_pulse/storage/migrations/007_phase2a_tasks.sql backend/tests/unit/storage/test_task_repository.py
git commit -m "feat: add phase 2a task state storage"
```

## Task 2: Implement repository-level idempotency, leases and checkpoints

**Files:**
- Create: `backend/src/sector_pulse/storage/task_repository.py`
- Modify: `backend/src/sector_pulse/storage/sqlite.py` only if transaction helpers need explicit conditional updates
- Test: `backend/tests/unit/storage/test_task_repository.py`

**Interfaces:**
- `create_or_get_run(key: TaskRunKey, provider: str, input_json: dict[str, object]) -> UUID`
- `claim_run(run_id: UUID, worker_id: str, lease_until: datetime) -> bool`
- `record_stage_attempt(...) -> int`
- `save_checkpoint(...) -> Checkpoint`
- `get_latest_valid_checkpoint(run_id: UUID, stage: TaskStage, input_fingerprint: str, implementation_version: str) -> Checkpoint | None`
- `transition(run_id: UUID, expected: TaskRunStatus, target: TaskRunStatus, ...) -> bool`

- [ ] **Step 1: Write failing repository tests**

```python
def test_duplicate_schedule_trigger_returns_same_run_id(repository, key):
    first = repository.create_or_get_run(key, "live", {"mode": "intraday"})
    second = repository.create_or_get_run(key, "live", {"mode": "intraday"})
    assert first == second

def test_checkpoint_is_immutable_and_ordered(repository, run_id):
    checkpoint = repository.save_checkpoint(run_id, TaskStage.FETCHING_MARKET, "hash", "v1", {"count": 1})
    assert repository.get_latest_valid_checkpoint(run_id, TaskStage.FETCHING_MARKET, "hash", "v1") == checkpoint
    with pytest.raises(sqlite3.IntegrityError):
        repository.save_checkpoint(run_id, TaskStage.FETCHING_MARKET, "hash", "v1", {"count": 2})
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_task_repository.py -q -p no:cacheprovider`

Expected: FAIL because `SQLiteTaskRepository` is not defined.

- [ ] **Step 3: Implement conditional SQL operations**

Use one transaction per command. `create_or_get_run` must insert with `ON CONFLICT DO NOTHING` and then select the existing ID. `claim_run` must update only when `lease_until` is expired or the same worker owns the lease. `transition` must include `WHERE status = expected` and append a `task_events` record in the same transaction. Checkpoint writes must be insert-only and validate the stored SHA-256 before returning.

- [ ] **Step 4: Run repository tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_task_repository.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/sector_pulse/storage/task_repository.py backend/tests/unit/storage/test_task_repository.py
git commit -m "feat: add task idempotency and checkpoint repository"
```

## Task 3: Extract resumable execution and failure policy

**Files:**
- Create: `backend/src/sector_pulse/application/run_executor.py`
- Create: `backend/src/sector_pulse/application/task_run_service.py`
- Modify: `backend/src/sector_pulse/web/run_service.py`
- Modify: `backend/src/sector_pulse/application/phase1b_pipeline.py` only to expose stage-safe boundaries, without changing Phase 1D output contracts
- Test: `backend/tests/unit/application/test_run_executor.py`

**Interfaces:**
- `RunExecutor.execute(run_id: UUID, provider: str, worker_id: str) -> None`
- `RunExecutor.resume(run_id: UUID, worker_id: str) -> None`
- `TaskRunService.create_manual(input_json: dict[str, object], provider: str, idempotency_key: str | None) -> UUID`
- `TaskRunService.trigger_schedule(schedule_id: UUID, idempotency_key: str | None) -> UUID`
- `TaskRunService.cancel(run_id: UUID, idempotency_key: str | None) -> bool`
- `TaskRunService.retry(run_id: UUID, idempotency_key: str | None) -> UUID`
- `TaskRunService.resume(run_id: UUID, idempotency_key: str | None) -> bool`
- `class RetryPolicy: classify(error) -> RetryDecision`
- `RetryDecision(retryable: bool, delay_seconds: int, terminal_status: TaskRunStatus, error_code: str)`

- [ ] **Step 1: Write failing stage/checkpoint tests**

```python
async def test_resume_skips_successful_market_stage(executor, repository, fake_bridge):
    repository.save_checkpoint(run_id, TaskStage.FETCHING_MARKET, "input", "phase2a-v1", {"market": "ok"})
    await executor.resume(run_id, "worker-1")
    assert fake_bridge.market_calls == 0

def test_timeout_is_retryable_but_integrity_error_is_not():
    policy = RetryPolicy(max_attempts=3, backoff_seconds=2)
    assert policy.classify(TimeoutError()).retryable is True
    assert policy.classify(IntegrityError("bad cutoff")).retryable is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_run_executor.py -q -p no:cacheprovider`

Expected: FAIL because executor and retry policy do not exist.

- [ ] **Step 3: Implement stage execution**

Before each stage, calculate `input_fingerprint`; read a matching checkpoint; if present, emit a progress event and continue. Otherwise insert a stage attempt, call the existing Phase 1D bridge, write a checkpoint on success, and transition to the next stage. Catch only classified exceptions: retryable failures enter `RETRY_WAITING` with capped exponential delay; integrity/configuration/budget failures enter `FAILED`; allowed partial-news failures enter `DEGRADED`. Catch `asyncio.CancelledError` separately and preserve the current non-terminal state.

Implement `TaskRunService` as the only command facade for the repository and executor. It normalizes the input fingerprint before creating a run, passes the caller's idempotency key into `task_events`, and rejects retry/resume requests that target terminal `READY_FOR_HUMAN_REVIEW` runs.

- [ ] **Step 4: Run executor tests and existing Phase 1B tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_run_executor.py backend/tests/unit/web/test_run_service.py backend/tests/integration/test_phase1b_pipeline.py -q -p no:cacheprovider`

Expected: PASS; existing Phase 1D manual/Fixture behavior remains unchanged.

- [ ] **Step 5: Commit**

```bash
git add backend/src/sector_pulse/application/run_executor.py backend/src/sector_pulse/application/task_run_service.py backend/src/sector_pulse/web/run_service.py backend/src/sector_pulse/application/phase1b_pipeline.py backend/tests/unit/application/test_run_executor.py
git commit -m "feat: add resumable phase 2a execution"
```

## Task 4: Add schedules and embedded scheduler

**Files:**
- Create: `backend/src/sector_pulse/application/scheduler.py`
- Create: `backend/src/sector_pulse/application/schedule_service.py`
- Create: `backend/tests/unit/application/test_scheduler.py`
- Create: `backend/tests/unit/application/test_schedule_service.py`
- Modify: `backend/src/sector_pulse/config/settings.py`

**Interfaces:**
- `ScheduleService.create(request: ScheduleCreate) -> ScheduleView`
- `ScheduleService.next_due(schedule: ScheduleView, now: datetime) -> datetime | None`
- `EmbeddedScheduler.start() -> None`, `stop() -> None`, `recover() -> None`

- [ ] **Step 1: Write failing scheduling tests**

```python
def test_next_due_converts_plan_timezone_to_utc(schedule_service):
    schedule = schedule_service.create(ScheduleCreate(
        name="盘后", mode="post_close", timezone="Asia/Shanghai",
        local_time="16:00", trading_days="weekdays", enabled=True,
    ))
    assert schedule_service.next_due(schedule, datetime(2026, 8, 19, 7, 0, tzinfo=UTC)).hour == 8

async def test_scheduler_duplicate_poll_creates_one_run(scheduler, repository):
    await scheduler.poll_once(datetime(2026, 8, 19, 8, 0, tzinfo=UTC))
    await scheduler.poll_once(datetime(2026, 8, 19, 8, 0, tzinfo=UTC))
    assert repository.count_runs() == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_scheduler.py backend/tests/unit/application/test_schedule_service.py -q -p no:cacheprovider`

Expected: FAIL because schedule service and scheduler do not exist.

- [ ] **Step 3: Implement schedule calculation and polling**

Parse `HH:MM`, IANA timezone and weekday/holiday rule at creation. Store UTC `next_run_at`. `poll_once` selects enabled due schedules, creates an idempotent `TaskRun`, advances the schedule slot, and submits the run to `RunExecutor`; it must never call the LLM directly. `start` loops using `SECTOR_PULSE_SCHEDULER_POLL_SECONDS`; `stop` cancels only the poll loop.

- [ ] **Step 4: Add and validate environment settings**

Extend `ApplicationSettings` with defaults for `scheduler_enabled`, `scheduler_poll_seconds`, `task_lease_seconds`, `task_max_attempts`, `task_deadline_seconds`, and `task_retry_backoff_seconds`; reject non-positive values and invalid booleans during startup.

- [ ] **Step 5: Run scheduler tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_scheduler.py backend/tests/unit/application/test_schedule_service.py backend/tests/unit/config/test_settings.py -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/sector_pulse/application/scheduler.py backend/src/sector_pulse/application/schedule_service.py backend/src/sector_pulse/config/settings.py backend/tests/unit/application/test_scheduler.py backend/tests/unit/application/test_schedule_service.py backend/tests/unit/config/test_settings.py
git commit -m "feat: add embedded phase 2a scheduler"
```

## Task 5: Wire lifespan, commands, queries and API contracts

**Files:**
- Create: `backend/src/sector_pulse/web/task_schemas.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `backend/src/sector_pulse/application/run_commands.py`
- Modify: `backend/src/sector_pulse/application/run_queries.py`
- Create: `backend/tests/integration/test_phase2a_api.py`

**Interfaces:**
- `POST /api/schedules`, `GET /api/schedules`, `PATCH /api/schedules/{schedule_id}`
- `POST /api/schedules/{schedule_id}/enable`, `/disable`, `/trigger`
- `GET /api/task-runs/{run_id}`, `/stages`, `/events`
- `POST /api/task-runs/{run_id}/cancel`, `/retry`, `/resume`

- [ ] **Step 1: Write failing API tests**

```python
def test_duplicate_trigger_returns_existing_run_id(client):
    schedule = client.post("/api/schedules", json={"name": "盘后", "mode": "post_close", "timezone": "Asia/Shanghai", "local_time": "16:00", "trading_days": "weekdays", "enabled": True}).json()
    first = client.post(f"/api/schedules/{schedule['schedule_id']}/trigger").json()
    second = client.post(f"/api/schedules/{schedule['schedule_id']}/trigger", headers={"Idempotency-Key": "same"}).json()
    assert first["run_id"] == second["run_id"]

def test_task_detail_contains_stage_history(client, run_id):
    response = client.get(f"/api/task-runs/{run_id}")
    assert response.status_code == 200
    assert {"run_id", "status", "stages", "events"} <= response.json().keys()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase2a_api.py -q -p no:cacheprovider`

Expected: FAIL with 404 because the new routes do not exist.

- [ ] **Step 3: Add schemas and routes**

Use Pydantic request models that validate mode, timezone, local time, and enabled state. Every command accepts an `Idempotency-Key` header, returns the existing operation result on duplicate, maps missing resources to 404 and invalid transitions to 409. Start/stop the scheduler in FastAPI lifespan after `database.initialize()` and call `recover()` before serving requests.

- [ ] **Step 4: Run API and existing web tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase2a_api.py backend/tests/integration/test_web_api.py backend/tests/unit/web -q -p no:cacheprovider`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/sector_pulse/web/task_schemas.py backend/src/sector_pulse/web/app.py backend/src/sector_pulse/application/run_commands.py backend/src/sector_pulse/application/run_queries.py backend/tests/integration/test_phase2a_api.py
git commit -m "feat: expose phase 2a task APIs"
```

## Task 6: Add schedule and task status views

**Files:**
- Create: `web/src/schedulesApi.ts`
- Create: `web/src/pages/SchedulePage.tsx`
- Create: `web/src/pages/TaskRunPage.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/styles.css`
- Test: `web/src/pages/SchedulePage.test.tsx`, `web/src/pages/TaskRunPage.test.tsx`

**Interfaces:**
- `fetchSchedules(): Promise<ScheduleView[]>`
- `createSchedule(input: ScheduleCreate): Promise<ScheduleView>`
- `triggerSchedule(id: string): Promise<{ run_id: string }>`
- `fetchTaskRun(id: string): Promise<TaskRunView>`

- [ ] **Step 1: Write failing component and API tests**

```tsx
it('shows next trigger and allows manual trigger', async () => {
  render(<SchedulePage />)
  expect(await screen.findByText('下一次触发')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '立即运行' }))
  expect(triggerSchedule).toHaveBeenCalledWith('schedule-1')
})

it('shows retryable error and stage history', async () => {
  render(<TaskRunPage />)
  expect(await screen.findByText('阶段历史')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run frontend tests to verify failure**

Run: `npm.cmd test -- --run web/src/pages/SchedulePage.test.tsx web/src/pages/TaskRunPage.test.tsx`

Expected: FAIL because the API module and pages do not exist.

- [ ] **Step 3: Implement API module, pages and routes**

Keep Chinese labels exact: `下一次触发`, `立即运行`, `阶段历史`, `重试`, `恢复`, `降级原因`. Use existing `useRunSSE` only for run progress; task detail polling must stop on terminal state. Never render provider secrets or raw LLM responses.

- [ ] **Step 4: Run frontend tests and build**

Run: `npm.cmd test -- --run; npm.cmd run build`

Expected: all existing and new Vitest tests pass and Vite build succeeds.

- [ ] **Step 5: Commit**

```bash
git add web/src/schedulesApi.ts web/src/pages/SchedulePage.tsx web/src/pages/TaskRunPage.tsx web/src/App.tsx web/src/styles.css web/src/pages/SchedulePage.test.tsx web/src/pages/TaskRunPage.test.tsx
git commit -m "feat: add phase 2a schedule views"
```

## Task 7: Recovery, failure and end-to-end acceptance

**Files:**
- Create: `backend/tests/integration/test_phase2a_recovery.py`
- Modify: `backend/tests/e2e/test_web_run.py`
- Modify: `docs/superpowers/specs/2026-08-19-phase-2a-reliable-task-scheduling-design.md` only if implementation reveals a contract correction

- [ ] **Step 1: Add failure-injection acceptance tests**

```python
async def test_restart_resumes_after_news_checkpoint(runtime):
    run_id = await runtime.start_until(TaskStage.FETCHING_NEWS)
    runtime.kill_worker()
    await runtime.restart_and_recover()
    detail = runtime.task_detail(run_id)
    assert detail.status in {TaskRunStatus.READY_FOR_HUMAN_REVIEW, TaskRunStatus.DEGRADED}
    assert runtime.calls_for(TaskStage.FETCHING_MARKET) == 1

async def test_rate_limit_retries_with_bounded_attempts(runtime):
    runtime.provider.fail_with_429(times=2)
    run_id = await runtime.start()
    detail = await runtime.wait_terminal(run_id)
    assert detail.attempts[0].attempt_no == 1
    assert detail.status == TaskRunStatus.READY_FOR_HUMAN_REVIEW
```

- [ ] **Step 2: Run focused acceptance tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase2a_recovery.py backend/tests/e2e/test_web_run.py -q -p no:cacheprovider`

Expected: PASS, including restart recovery, duplicate trigger, bounded retry, core-market blocking and non-core-news degradation.

- [ ] **Step 3: Run complete regression suite**

Run:

```powershell
$env:TEMP = (Join-Path (Get-Location) '.pytest-temp')
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -m pytest backend/tests/unit backend/tests/integration backend/tests/e2e -q -p no:cacheprovider
.\.venv\Scripts\ruff.exe check backend/src backend/tests
Push-Location web
npm.cmd test -- --run
npm.cmd run build
Pop-Location
git diff --check
```

Expected: all tests pass, Ruff reports `All checks passed!`, frontend tests/build succeed, and `git diff --check` is clean.

- [ ] **Step 4: Perform manual service recovery smoke test**

Start `python -m uvicorn sector_pulse.web.app:create_app --factory --host 127.0.0.1 --port 8010`, create one schedule through `/api/schedules`, trigger it, stop the process during a non-terminal stage, restart on the same SQLite file, and verify `/api/task-runs/{run_id}` exposes the prior attempt plus a resumed attempt. Do not use real LLM or real market calls for this smoke test; use the fixture provider.

- [ ] **Step 5: Commit acceptance evidence**

```bash
git add backend/tests/integration/test_phase2a_recovery.py backend/tests/e2e/test_web_run.py
git commit -m "test: verify phase 2a recovery and retry"
```

## Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-19-phase-2a-reliable-task-scheduling.md`. Execute tasks in order, keeping each task commit independently reviewable. Before any real-data or real-LLM acceptance, obtain explicit user consent and report whether a call and cost occurred.
