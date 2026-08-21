# PostgreSQL Runtime Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 PostgreSQL 从已验证的独立仓储实现接入应用运行时，同时保留 SQLite 默认兼容路径，并完成 Phase 4 的可重复验收。

**Architecture:** 先统一仓储接口的异步边界，再由应用启动生命周期初始化所选数据库；`SECTOR_PULSE_DATABASE_URL` 存在时选择 PostgreSQL，否则继续选择 SQLite。迁移按业务域逐步完成，每个仓储都有真实 PostgreSQL round-trip 测试，最后再切换 Web 服务和后台任务的依赖注入。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, asyncpg, SQLite, pytest, pytest-asyncio, Ruff, Docker Compose。

## Global Constraints

- 不把 PostgreSQL 密码写入仓库、日志、测试输出或文档。
- 未设置 `SECTOR_PULSE_DATABASE_URL` 时，现有 SQLite 行为和 API 合同必须保持不变。
- PostgreSQL migration 必须幂等；启动重复执行不得重复创建表或重复插入版本。
- 真实数据、真实 LLM 和手工发布边界保持不变；本计划不增加自动发布。
- 每个任务都必须有 focused test；最终必须运行 Ruff 和完整后端回归。

---

### Task 1: 统一数据库运行时选择与生命周期

**Files:**
- Modify: `backend/src/sector_pulse/storage/database_config.py`
- Create: `backend/src/sector_pulse/storage/database_runtime.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Test: `backend/tests/unit/storage/test_database_runtime.py`

**Interfaces:**
- `build_database(settings: ApplicationSettings, database_path: Path) -> SQLiteDatabase | PostgresDatabase`
- `initialize_database(database: SQLiteDatabase | PostgresDatabase) -> Awaitable[None]`
- SQLite 保持同步初始化；PostgreSQL 在 FastAPI lifespan 中异步初始化。

- [x] **Step 1: Write the failing tests**

```python
def test_build_database_defaults_to_sqlite(tmp_path):
    settings = ApplicationSettings(database_path=tmp_path / "app.db")
    database = build_database(settings, settings.database_path)
    assert isinstance(database, SQLiteDatabase)

def test_build_database_selects_postgres(monkeypatch):
    settings = ApplicationSettings(database_url="postgresql+asyncpg://user:pass@localhost/db")
    database = build_database(settings, Path("ignored.db"))
    assert isinstance(database, PostgresDatabase)
```

- [x] **Step 2: Run focused tests and verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_database_runtime.py -q -p no:cacheprovider`

Expected: FAIL because `database_runtime.py` and `build_database` do not yet exist.

- [x] **Step 3: Implement the runtime factory**

```python
def build_database(settings, database_path):
    config = resolve_database_config(settings.database_url, str(database_path))
    if config.backend == "sqlite":
        return SQLiteDatabase(Path(config.url))
    return PostgresDatabase(config.url)
```

Keep initialization separate so the sync SQLite path is not forced through an event loop. In `create_app`, construct the selected backend once and initialize it in lifespan; reject PostgreSQL startup only when the optional `postgres` dependencies are missing, with a clear error naming the extra.

- [x] **Step 4: Run focused tests and app tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_database_runtime.py backend/tests/unit/web/test_app.py -q -p no:cacheprovider`

Expected: PASS; SQLite app tests continue to use temporary SQLite files.

- [x] **Step 5: Commit**

```bash
git add backend/src/sector_pulse/storage/database_runtime.py backend/src/sector_pulse/storage/database_config.py backend/src/sector_pulse/web/app.py backend/tests/unit/storage/test_database_runtime.py
git commit -m "feat: add runtime database selection"
```

### Task 2: 完成剩余 PostgreSQL 业务仓储

**Files:**
- Create: `backend/src/sector_pulse/storage/postgres_phase1b_repository.py`, `postgres_task_repository.py`, `postgres_news_repository.py`, `postgres_evidence_repository.py`, `postgres_governance_repository.py`, `postgres_agent_invocation_repository.py`, `postgres_market_snapshot_repository.py`, and `postgres_release_audit_repository.py`
- Modify: `backend/src/sector_pulse/storage/__init__.py` only if public exports are needed
- Test: matching integration files under `backend/tests/integration/` for the eight repositories listed above

**Interfaces:**
- Each PostgreSQL repository mirrors its SQLite repository method names and domain return models.
- All methods are `async def` and accept `PostgresDatabase`.
- Required domains: phase1b drafts/runs, tasks/schedules, news/evidence, governance/audit, agent invocations, market snapshots, and release audit.

- [ ] **Step 1: Inventory each SQLite repository and migration columns**

For every repository, record its exact methods and SQL columns before editing. Run:

```powershell
rg -n "^class SQLite|^    def " backend/src/sector_pulse/storage
Get-ChildItem backend/src/sector_pulse/storage/migrations/*.sql | Sort-Object Name
```

- [ ] **Step 2: Add one failing round-trip test per domain**

Each test must set `SECTOR_PULSE_DATABASE_URL` only in the process environment, call `await database.initialize()`, write one minimal valid domain object, read it back, and assert identity plus one domain field.

- [ ] **Step 3: Implement the minimal async repository**

Use parameterized SQLAlchemy `text()` statements, ISO-8601 strings for migration text timestamp columns, `ON CONFLICT` only where SQLite uses replace/upsert semantics, and no password-bearing logging.

- [ ] **Step 4: Run real PostgreSQL integration tests**

```powershell
$env:SECTOR_PULSE_DATABASE_URL=$env:SECTOR_PULSE_DATABASE_URL
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_postgres_*_repository.py -q -p no:cacheprovider
```

Expected: all repository round-trips pass; tests skip when the variable is absent.

- [ ] **Step 5: Commit each independently reviewable domain group**

```bash
git add backend/src/sector_pulse/storage backend/tests/integration
git commit -m "feat: migrate business repository to postgres"
```

### Task 3: 将 Web 服务依赖注入改为异步仓储边界

**Files:**
- Modify: `backend/src/sector_pulse/web/data_run_service.py`
- Modify: `backend/src/sector_pulse/application/real_data_queries.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: all application services that directly call migrated repositories
- Test: `backend/tests/integration/test_postgres_web_api.py`

**Interfaces:**
- Service methods that access PostgreSQL become `async def`; SQLite adapters expose the same async interface using `asyncio.to_thread`.
- FastAPI handlers await service calls; existing response JSON remains unchanged.

- [ ] **Step 1: Add an async repository protocol**

Define protocols for `get_run`, `insert`, status updates, candidate operations, and list operations. Type both SQLite adapter and PostgreSQL implementation against the protocol.

- [ ] **Step 2: Add SQLite async adapter tests**

Verify existing temporary-database API tests still pass when repository calls are awaited.

- [ ] **Step 3: Wire selected repository set from the runtime factory**

When backend is SQLite, use the SQLite adapters. When backend is PostgreSQL, use only PostgreSQL adapters; startup must fail fast if a required domain adapter is not available, instead of silently mixing databases.

- [ ] **Step 4: Run PostgreSQL Web API smoke test**

Start the app with `SECTOR_PULSE_DATABASE_URL` and call health plus one data-run read endpoint. Assert HTTP success and that the inserted run is read from PostgreSQL.

- [ ] **Step 5: Commit**

```bash
git add backend/src/sector_pulse backend/tests/integration/test_postgres_web_api.py
git commit -m "feat: wire postgres repositories into web runtime"
```

### Task 4: Docker/Compose PostgreSQL profile

**Files:**
- Modify: `docker-compose.yml`
- Modify: `Dockerfile`
- Modify: `.env.example`
- Test: `scripts/verify_postgres_compose.ps1`
- Modify: `docs/superpowers/acceptance/2026-08-20-phase-4-self-hosted-acceptance.md`

**Interfaces:**
- Default Compose remains SQLite-compatible.
- Optional `postgres` profile starts PostgreSQL and passes `SECTOR_PULSE_DATABASE_URL` to the app.

- [ ] **Step 1: Add a disabled-by-default PostgreSQL profile**

Use a named volume, healthcheck, non-secret default database/user, and environment substitution for the password. Do not commit the user’s real password.

- [ ] **Step 2: Build the image with the PostgreSQL extra**

Install `.[postgres]` only in the PostgreSQL profile image path or document the image variant; keep the base image reproducible.

- [ ] **Step 3: Verify startup, migration count, and health**

```powershell
docker compose --profile postgres up -d --build
docker compose --profile postgres ps
Invoke-RestMethod http://127.0.0.1:8010/api/health
```

Expected: PostgreSQL healthy, migration count remains 12, app health is successful.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml Dockerfile .env.example scripts/verify_postgres_compose.ps1 docs/superpowers/acceptance/2026-08-20-phase-4-self-hosted-acceptance.md
git commit -m "feat: add postgres compose profile"
```

### Task 5: Phase 4 final acceptance and rollback evidence

**Files:**
- Modify: `docs/superpowers/acceptance/2026-08-20-phase-4-self-hosted-acceptance.md`
- Create: `docs/superpowers/acceptance/2026-08-21-postgres-runtime-acceptance.md`

- [ ] **Step 1: Run static and full regression checks**

```powershell
.\.venv\Scripts\ruff.exe check backend/src backend/tests
.\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider
```

Expected: Ruff passes; all non-live tests pass; live tests are reported separately as skipped or environment-dependent.

- [ ] **Step 2: Run PostgreSQL acceptance**

Record database backend, migration count, health response, repository round-trip results, and one API smoke result without recording credentials.

- [ ] **Step 3: Verify SQLite rollback**

Unset `SECTOR_PULSE_DATABASE_URL`, start the app against a temporary SQLite database, and assert health plus existing API smoke tests pass.

- [ ] **Step 4: Mark only verified items complete**

Document any remaining repository or deployment limitation explicitly; do not mark Phase 4 complete while runtime selection or required adapters remain unavailable.

- [ ] **Step 5: Commit acceptance evidence**

```bash
git add docs/superpowers/acceptance
git commit -m "docs: record postgres runtime acceptance"
```

## Self-review checklist

- [ ] No real credentials appear in source, tests, docs, logs, or commits.
- [ ] PostgreSQL is never silently downgraded to SQLite when explicitly configured.
- [ ] SQLite default path remains green.
- [ ] Every migrated repository has a real round-trip test.
- [ ] Docker profile and local process startup use the same environment variable.
- [ ] Phase 4 status distinguishes completed code, passed acceptance, and deferred work.
