# Modern Operations Frontend Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a real-data operations dashboard and a redacted system-status page.

**Architecture:** Add a small read-only `OperationsSummary` API owned by FastAPI that aggregates database, Provider preflight, LLM configuration and consent readiness without exposing secrets. React fetches this summary with explicit loading/error/refresh states; the dashboard and system page share the API client and Phase 1 primitives.

**Tech Stack:** FastAPI, Pydantic, React 18, TypeScript, Vitest, pytest

**Spec:** `docs/superpowers/specs/2026-08-23-modern-operations-frontend-design.md`

## Global Constraints

- No secrets, passwords, API keys, complete connection strings, raw prompts, or raw model output in this endpoint or UI.
- All summary values come from real database/configuration state; absent values are unavailable, not fabricated zeroes.
- Keep PostgreSQL and SQLite paths working.
- Dashboard and system pages must show loading, populated, empty, partial-degradation and error states.
- Run backend and frontend tests plus production build before acceptance.

---

### Task 1: Redacted Operations Summary API

**Files:**
- Create: `backend/src/sector_pulse/web/operations_schemas.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Create: `backend/tests/integration/test_operations_summary_api.py`

- [ ] Write failing API tests asserting `GET /api/operations/summary` returns database backend/name, LLM provider/model/budget, consent booleans, run/review summaries, provider availability and no secret-bearing field.
- [ ] Run the focused test and observe 404.
- [ ] Implement Pydantic response schemas and the route; use only database type/name, configured provider/model/budget, file existence flags, preflight status/error codes, run repository records and review analytics.
- [ ] Run focused backend tests and Ruff; assert serialized JSON does not contain configured API-key test values.
- [ ] Commit: `feat: add redacted operations summary api`.

### Task 2: Dashboard And System API Client

**Files:**
- Create: `web/src/operationsApi.ts`
- Create: `web/src/operationsApi.test.ts`
- Create: `web/src/pages/OperationsDashboardPage.tsx`
- Create: `web/src/pages/OperationsDashboardPage.test.tsx`
- Create: `web/src/pages/SystemStatusPage.tsx`
- Create: `web/src/pages/SystemStatusPage.test.tsx`

- [ ] Write failing API-client and page tests for loading, populated, unavailable metric and failed request states.
- [ ] Run focused tests and observe missing-module failures.
- [ ] Implement typed `OperationsSummary`, safe fetch/error handling, dashboard stat cards/recent runs/actions/last-updated refresh, and system status cards with no secret fields.
- [ ] Run focused frontend tests and production build.
- [ ] Commit: `feat: add operations dashboard and system status`.

### Task 3: Route And Navigation Integration

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/layout/navigation.ts`
- Modify: `web/src/layout/AppShell.test.tsx`

- [ ] Write failing route tests for `/` dashboard and `/system` navigation.
- [ ] Run focused tests and observe failure.
- [ ] Add dashboard and system routes, make `/` dashboard instead of redirect, and include `运营总览` and `系统状态` navigation entries.
- [ ] Run focused tests, full frontend tests and build.
- [ ] Commit: `feat: route operations dashboard`.

### Task 4: Phase 2 Acceptance

**Files:**
- Create: `docs/superpowers/acceptance/2026-08-23-modern-operations-frontend-phase2.md`
- Modify: `docs/superpowers/plans/2026-08-23-modern-operations-frontend-master.md`

- [ ] Verify summary endpoint and UI against empty PostgreSQL runtime and a Fixture-populated database.
- [ ] Verify no response or rendered DOM contains test secrets.
- [ ] Run backend tests, frontend tests, build and `git diff --check`.
- [ ] Record exact evidence and update Phase 2 checkboxes.
- [ ] Commit: `docs: record frontend phase 2 acceptance`.
