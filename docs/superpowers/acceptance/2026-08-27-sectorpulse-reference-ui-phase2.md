# SectorPulse Reference UI Phase 2 Acceptance

**Date:** 2026-08-27
**Branch:** `refactoring`
**Scope:** 真实运营总览、统一运行聚合、趋势、就绪状态、近期运行与可靠刷新

## Acceptance Result

Phase 2 的代码与 SQLite 路径验收通过。运营总览只展示可由持久化运行记录与当前配置推导的指标；空数据、真实记录契约、活跃刷新、陈旧数据保留和首次请求失败均有明确状态。

PostgreSQL 环境验收未通过：使用 `.env` 中现有 `SECTOR_PULSE_DATABASE_URL` 连接时，服务返回 `ConnectionRefusedError: [WinError 1225]`。该结果记录为本机 PostgreSQL 服务不可达，不计为代码通过，也不阻塞 SQLite 与前端阶段验收。

## Delivered Contract

- `/api/operations/summary` 保留原字段，并增加 `summary`、`trend`、`readiness`、`recent_runs`、`generated_at`。
- 内容运行与数据运行在查询层统一、按运行 ID 去重，状态分类由后端集中维护。
- 趋势只聚合真实运行日期；没有记录时返回原因，不绘制示意曲线。
- 活跃任务每 5 秒无重叠轮询；页面隐藏时暂停；刷新失败保留最后成功数据。
- Dashboard 提供四项真实指标、7/30 天趋势、四项就绪状态和内容/数据统一近期运行表。

## Verification Evidence

### Frontend

Command:

```powershell
Set-Location web
npm.cmd test -- --run
npm.cmd run build
npm.cmd run test:e2e -- e2e/shell.spec.ts e2e/dashboard.spec.ts --reporter=line
```

Result:

- Vitest: 35 files, 115 tests passed.
- TypeScript and Vite production build: passed; 98 modules transformed.
- Playwright: 8 tests passed in 6.1 seconds.
- Responsive assertions covered 1536×1024, 1440×900, 1024×768 and 390×844.
- Mobile root document width remained 390px; the wide recent-runs table scrolls only inside its viewport.

### Backend, non-live

Command:

```powershell
$env:SECTOR_PULSE_DATABASE_URL = ''
.\.venv\Scripts\python.exe -m pytest backend/tests/unit backend/tests/integration -q -p no:cacheprovider -m "not live"
```

Result: 242 passed, 20 PostgreSQL-only tests skipped, 1 existing Starlette deprecation warning.

### PostgreSQL reachability

Command used the configured URL from `.env` without printing it:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_postgres_operations_query.py -q -p no:cacheprovider
```

Result: 1 failed during connection initialization with `ConnectionRefusedError: [WinError 1225]`. No query assertion ran because the configured PostgreSQL service was unreachable.

### Frontend skill checks

- Impeccable detector: `[]`, no findings for the changed Dashboard TSX/CSS set.
- Design direction: Operate mode, light surfaces, restrained blue accent, compact data density, no decorative metrics or fake controls.

## Browser Inspection

The built SPA was opened in the in-app browser against the local FastAPI service using an isolated SQLite run:

- 1536×1024: four metrics in one row; trend/readiness use the approved 2:1 balance; empty trend and empty recent-runs states are readable.
- 390×844: one metric per row, actions remain reachable, no page-level horizontal overflow.
- Empty database: all counters truthfully show zero and the trend explains why no graph is available.
- Refresh after backend shutdown: the last successful Dashboard remains visible with `当前显示上次成功数据`.
- Reload while backend is unavailable: full recovery alert and `重新加载` action appear.
- Browser console: no warnings or errors were captured during the successful desktop/mobile inspection.

The deterministic E2E contract fixture covers a non-empty record state without writing test data into the user's database. It verifies real content/data detail routes, unknown candidate counts, trend rendering and the recent-runs table.

## Non-blocking Notes

- Vite reports existing deprecation notices for `esbuild` options in the React plugin configuration.
- npm reports that a newer major version is available; no dependency upgrade was performed in this phase.
- PostgreSQL must be started and reachable before its integration acceptance can be rerun.

## Exit Decision

Phase 2 is accepted for the refactoring branch with the PostgreSQL environment exception documented above. Phase 3 may proceed without manufacturing PostgreSQL success or modifying the user's stored data.
