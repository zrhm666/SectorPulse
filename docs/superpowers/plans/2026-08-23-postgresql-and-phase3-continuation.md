# PostgreSQL And Phase 3 Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Initialize the local PostgreSQL runtime safely, verify the complete PostgreSQL application path, and start the real 20-trading-day Phase 3 shadow acceptance.

**Architecture:** Use the installed PostgreSQL 18 service as the persistent runtime and the project's existing `PostgresDatabase.initialize()` implementation as the sole migration runner. Keep credentials only in local `.env`, verify all repositories and Web endpoints against PostgreSQL, then begin Phase 3 without fabricating historical shadow records.

**Tech Stack:** PostgreSQL 18, SQLAlchemy 2, asyncpg, FastAPI, pytest, React/Vite

**Spec:** `docs/superpowers/specs/2026-08-20-phase-4-self-hosted-evolution-design.md`; `docs/superpowers/specs/2026-08-20-phase-3-shadow-acceptance-design.md`

## Global Constraints

- Never print, commit, or copy the PostgreSQL password into tracked files or command output.
- Use `SECTOR_PULSE_DATABASE_URL` to select PostgreSQL; retain SQLite only as a local backup/fallback.
- Run the existing 12 idempotent migrations; do not hand-create application tables.
- Phase 3 records must come from real trading-day runs and must not trigger automatic publication.
- Preserve the existing SQLite backup and do not import stale data unless its provenance is confirmed.

---

### Task 1: Create The PostgreSQL Runtime

**Files:**
- Modify: `.env` (local and ignored)
- Verify: `backend/src/sector_pulse/storage/postgres.py`

**Interfaces:**
- Consumes: local PostgreSQL administrator authentication on `localhost:5432`
- Produces: clean runtime database `sectorpulse_runtime`, isolated test database `sectorpulse_test`, login role `sectorpulse_app`, and local `SECTOR_PULSE_DATABASE_URL`

- [x] **Step 1: Verify PostgreSQL service readiness**

Run: `D:\software\postgresql18\bin\pg_isready.exe -h localhost -p 5432`

Expected: `accepting connections`.

- [x] **Step 2: Create a least-privilege application role and database**

Connect as the local PostgreSQL administrator, create `sectorpulse_app` with a user-supplied password, and create database `sectorpulse` owned by that role. Re-running the operation must first query `pg_roles` and `pg_database` so existing objects are preserved.

- [x] **Step 3: Configure the ignored environment file**

Set `SECTOR_PULSE_DATABASE_URL=postgresql+asyncpg://sectorpulse_app:<URL-encoded-password>@localhost:5432/sectorpulse` in `.env`. Do not echo the resulting line.

- [x] **Step 4: Run the project migration initializer**

Run `PostgresDatabase.initialize()` using the URL loaded from `.env`.

Expected: `schema_migrations` contains 12 rows and `MAX(version) = 12`.

### Task 2: Verify PostgreSQL Persistence

**Files:**
- Test: `backend/tests/integration/test_postgres_*_repository.py`
- Verify: `backend/src/sector_pulse/storage/runtime_bundle.py`

**Interfaces:**
- Consumes: migrated `sectorpulse` database
- Produces: verified PostgreSQL repository and runtime bundle

- [x] **Step 1: Run PostgreSQL repository integration tests**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_postgres_*_repository.py -q -p no:cacheprovider`

Expected: all selected tests pass with no PostgreSQL skips.

- [x] **Step 2: Run the full backend regression suite**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider`

Expected: all tests pass; only tests requiring separately opted-in live providers may skip.

### Task 3: Verify The PostgreSQL Web Runtime

**Files:**
- Verify: `backend/src/sector_pulse/web/app.py`
- Verify: `web/src/pages/ShadowAcceptancePage.tsx`

**Interfaces:**
- Consumes: PostgreSQL runtime bundle
- Produces: successful health and Phase 3 API smoke evidence

- [x] **Step 1: Start the FastAPI app with `.env` loaded**

Expected: lifespan initialization succeeds without falling back to SQLite.

- [x] **Step 2: Smoke-test runtime endpoints**

Verify HTTP 200 from `/api/health`, `/api/shadow-runs/summary`, and `/api/prompt-golden`.

- [x] **Step 3: Confirm initial Phase 3 progress**

Expected for a new database: `trading_days = 0`, `remaining = 20`, and `complete = false`.

### Task 4: Start Phase 3 Real Shadow Acceptance

**Files:**
- Modify: `docs/superpowers/acceptance/2026-08-20-phase-3-shadow-acceptance.md`

**Interfaces:**
- Consumes: verified real-data and real-LLM execution path
- Produces: one auditable shadow record per real trading day and an eventual 20-day decision

- [ ] **Step 1: Run one real trading-day workflow without publication**

Use the configured providers and explicit consent files. Record cutoff, provider status, elapsed time, token/cost metrics, review result, degradation reason, and failure reason.

- [ ] **Step 2: Register and finalize the shadow run**

Create the record through `POST /api/shadow-runs`, then finalize it through `PATCH /api/shadow-runs/{shadow_id}`. Do not create records for dates on which no real run occurred.

- [ ] **Step 3: Review the daily acceptance evidence**

Verify no cutoff boundary violation, no secret in persisted audit data, and no automatic publication. Add the real result to the acceptance table.

- [ ] **Step 4: Repeat until 20 distinct trading days are recorded**

After day 20, evaluate runtime P90, median review duration, projected monthly cost, recovery evidence, compliance reviewer/rules version, and all exit gates before marking PASS or BLOCKED.

### Task 5: Record The Execution Checkpoint

**Files:**
- Modify: `docs/superpowers/plans/2026-08-23-postgresql-and-phase3-continuation.md`
- Modify: `docs/superpowers/acceptance/2026-08-20-phase-3-shadow-acceptance.md`

**Interfaces:**
- Consumes: test and smoke outputs from Tasks 1-4
- Produces: reproducible checkpoint distinguishing code completion from elapsed trading-day completion

- [x] **Step 1: Check completed boxes only after fresh verification**

Record migration count, test totals, endpoint status, and Phase 3 trading-day count without credentials or raw model responses.

- [x] **Step 2: Review repository changes**

Run: `git status --short` and `git diff --check`

Expected: only intentional source/document changes remain; `.env`, caches, databases, and credentials remain ignored.
