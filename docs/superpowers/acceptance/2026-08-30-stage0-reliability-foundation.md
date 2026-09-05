# Stage 0 Reliability Foundation — Acceptance Record

Date: 2026-08-31  
Branch: `codex/stage0-reliability`  
Scope: SQLite/PostgreSQL runtime parity, durable execution lifecycle, scheduler recovery, API composition, frontend reliability, and repeatable non-Live quality gates.

## Acceptance status

Historical record: current status and PostgreSQL 18 evidence are in the [2026-09-05 closeout](2026-09-05-reliability-closeout.md).

**SQLite and Web gate: passed.**  
**Local PostgreSQL round-trip gate: pending host administrator action.**

The repository-level quality gate completed successfully without Live market/news access and without real LLM calls. The installed PostgreSQL 18 Windows service was detected but remained stopped; attempting to start it was denied by the host service manager. No database was created, dropped, truncated, reset, migrated, or backed up during this blocked attempt.

## Verified evidence

| Gate | Result |
| --- | --- |
| Ruff | Passed — all backend checks |
| Mypy strict | Passed — 163 source files |
| Python dependency audit | Passed — no known vulnerabilities after upgrading pip to 26.2.1 |
| Backend non-Live tests | Passed — 336 passed, 22 PostgreSQL tests skipped, 7 Live/Live-LLM tests deselected |
| Frontend unit tests | Passed — 50 files, 174 tests |
| Frontend production build | Passed — 116 modules transformed |
| Frontend browser tests | Passed — 40 Playwright tests |
| npm production audit | Passed — 0 vulnerabilities |
| Impeccable detector | Passed — 0 findings |
| Repository whitespace check | Passed |

Production build artifacts:

- HTML: 0.41 kB (0.28 kB gzip)
- CSS: 56.94 kB (10.31 kB gzip)
- JavaScript: 303.58 kB (97.58 kB gzip)

The authoritative schema migration head is `017_content_interrupted`, following `016_reliable_runtime`. Both SQLite and PostgreSQL dialect-specific migration files are present. SQLite migration and runtime contracts are included in the passing non-Live suite, including preservation of existing content snapshots and draft identifiers.

## Reliability behavior accepted

- Manual and scheduled starts share one coordinator and execution path.
- Schedule due windows are persisted and consumed once.
- A broken scheduled run does not stop other due schedules.
- Cancellation intent is persisted and observed at safe execution checkpoints.
- Startup recovery marks abandoned active work as interrupted instead of leaving false running state.
- Correction (2026-09-05): this gate only covered storage-level retry fields; service retries did not yet persist their lineage. End-to-end lineage was implemented in `28a4312` and verified in the [closeout acceptance](2026-09-05-reliability-closeout.md).
- Draft autosave is deterministic and protects newer local edits from stale responses.
- Closed mobile navigation is removed from accessibility and keyboard focus order.
- FastAPI capability routers preserve the public API while keeping the composition root small.
- The frontend uses one modular token/style system; the legacy stylesheet was removed.
- Linked tasks inherit terminal data/content outcomes instead of remaining queued or running forever.
- Manual work continues advancing when automatic schedule dispatch is disabled.
- Abandoned content runs are marked interrupted while preserving their input snapshots and draft metadata.

## PostgreSQL boundary

Resolved configuration, with credentials omitted:

- Driver in existing `.env`: legacy `postgresql+asyncpg`, normalized by the application to synchronous psycopg
- Host: `localhost`
- Port: `5432`
- Database: `sectorpulse_runtime`
- Installed service: `postgresql-x64-18`
- Service state during acceptance: `Stopped`
- Port state during acceptance: closed
- `pg_dump`: available at `D:\software\postgresql18\bin\pg_dump.exe`

The service start request failed because the current host process could not open the Windows service. Consequently, no safe backup could be taken and the 22 PostgreSQL round-trip tests were not run locally. The new CI workflow runs PostgreSQL contracts against a disposable PostgreSQL 16 service, so no user database is required or mutated in CI.

To complete the local evidence later:

1. Start `postgresql-x64-18` from an Administrator terminal or Windows Services.
2. Confirm `sectorpulse_runtime` as the business database and create a custom-format backup with `pg_dump` as documented in the README.
3. Use a separate, explicitly designated test database for PostgreSQL contracts; do not point tests at the business database.
4. Export that test database's `SECTOR_PULSE_DATABASE_URL` only in the test process.
5. Run the PostgreSQL contract and integration files; do not reset the business database.

## Known upstream warnings

- Starlette emits a deprecation warning for its current `httpx`-based test client compatibility path.
- Vite reports that an `esbuild` option supplied by the React transform plugin is deprecated in favor of Oxc/Rolldown options.
- These warnings did not suppress failures, skip ordinary tests, or affect production dependency audits.

## Final review fixes

Review was performed inline as requested by the user, not by an independent subagent. The review found and fixed:

1. The ordinary quality gate could inherit a business PostgreSQL URL. Its test child process now explicitly overrides the connection and provider; the complete gate also passed with a deliberately unusable inherited URL.
2. Linked task status did not follow terminal data/content results. Reconciliation now persists one terminal transition and does not duplicate it on later polls.
3. Disabling automatic schedules also disabled advancement of manually triggered work. Dispatch and maintenance are now separate concerns.
4. Content startup recovery lacked an interrupted state. Forward-only migration 017 and recovery methods now preserve old snapshots and completed records.

The full quality gate was rerun after these fixes. PostgreSQL host verification and final merge remain pending; this record does not claim that either occurred.

## Reproduce the non-Live gate

From a normal repository checkout with `.venv` in the root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify-stage0.ps1
```

From an isolated worktree that shares another virtual environment:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify-stage0.ps1 `
  -PythonPath D:\path\to\shared\.venv\Scripts\python.exe
```

The script fails fast and does not weaken security, typing, test, build, or browser gates when an upstream vulnerability service is unavailable.
