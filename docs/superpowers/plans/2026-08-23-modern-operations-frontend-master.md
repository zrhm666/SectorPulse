# Modern Operations Frontend Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved modern light operations frontend through four independently testable phases without disrupting the verified backend workflows.

**Architecture:** Build a small internal design system and application shell first, then add dashboard/system aggregation, the end-to-end analysis workflow, and finally the review/operations surfaces. Each phase must leave the application usable, pass its own automated and browser checks, and define stable interfaces for the next phase.

**Tech Stack:** React 18, React Router 6, TypeScript 5.6, Vite 5, Vitest 4, Testing Library, FastAPI, PostgreSQL

**Spec:** `docs/superpowers/specs/2026-08-23-modern-operations-frontend-design.md`

## Global Constraints

- Use the existing React/TypeScript/Vite stack; do not add Ant Design, MUI, Tailwind, or another component framework.
- Show only real API data; use explicit loading, empty, and error states instead of sample metrics.
- Never expose API keys, database passwords, full connection URLs, raw prompts, or unredacted model responses.
- Preserve existing API and business semantics unless a phase explicitly adds a small, redacted read-only aggregation endpoint.
- Keep Phase 3 shadow acceptance paused and never fabricate progress records.
- Desktop is primary, but every page must remain operable without overlap or clipped controls at 768 px and 390 px widths.
- Every phase requires `npm test`, `npm run build`, focused browser verification, and `git diff --check` before completion.

---

## Delivery Map

| Phase | Deliverable | Depends on | Exit gate |
|---|---|---|---|
| 1 | Design system, application shell, responsive navigation, and visual migration of currently routable pages | Approved frontend design spec | Shared primitives and shell are tested; existing pages remain reachable; production build passes |
| 2 | Real operations dashboard and redacted system-status page | Phase 1 component contracts | Empty PostgreSQL and populated Fixture states render correctly; no secret appears in API or UI |
| 3 | Analysis run list, three-step creation flow, run timeline, details, failure and retry experience | Phase 2 status contracts | Fixture run can be created and followed to a reviewable result without internal JSON input |
| 4 | Review workspace, schedule management, paused shadow page, responsive/accessibility polish, final browser acceptance | Phases 1-3 | All frontend tests/build pass and user accepts the complete desktop workflow |

## Phase 1: Foundation And Application Shell

Detailed plan: `docs/superpowers/plans/2026-08-23-modern-operations-frontend-phase1.md`

- [ ] Establish CSS tokens and reset rules for color, spacing, typography, radius, shadow, focus, and responsive breakpoints.
- [ ] Add typed shared primitives for page headers, panels, status badges, empty states, alerts, loading states, and buttons.
- [ ] Add `AppShell`, responsive `SidebarNav`, and `TopBar` around all existing routes.
- [ ] Introduce `/runs` and redirect `/` to it until the real dashboard is delivered in Phase 2.
- [ ] Migrate the current run list, schedules, and shadow acceptance page away from inline presentation styles.
- [ ] Mark shadow acceptance as paused without altering persisted data.
- [ ] Pass Phase 1 unit, build, desktop, and narrow-screen checks.

## Phase 2: Operations Dashboard And System Status

Phase 2 plan will be written only after Phase 1 contracts are verified. Its required scope is fixed here.

- [ ] Inventory existing endpoints for runs, schedules, shadow progress, provider preflight, LLM audits, and review analytics.
- [ ] Define one redacted `OperationsSummary` frontend type and add a backend aggregation endpoint only for fields that cannot be composed reliably client-side.
- [ ] Add `/` operations dashboard with real status, four metrics, recent runs, current workflow, actionable issues, and guided empty states.
- [ ] Add `/system` with PostgreSQL database name/status, data/news Provider status, LLM provider/model/budget, consent readiness, and recent redacted failures.
- [ ] Add automatic refresh with visible last-updated time and a manual retry action; do not silently poll failed endpoints.
- [ ] Test populated, empty, loading, partial degradation, request failure, and secret-redaction states.
- [ ] Verify the dashboard against an empty PostgreSQL runtime and a Fixture-populated test database.

## Phase 3: Analysis Run Workflow

Phase 3 plan will be written after Phase 2 determines the stable status/preflight interfaces.

- [ ] Replace the current run cards with a responsive table/list supporting status, mode, date, duration, cost, and details.
- [ ] Implement the three-step new-analysis flow: mode, preflight/cutoff/LLM confirmation, submission.
- [ ] Prevent submission when consent or required Provider configuration is unavailable and show a specific resolution.
- [ ] Navigate successful creation directly to the correct real-data or writing-run detail page.
- [ ] Build the run summary, stage timeline, and overview/radar/evidence/draft/review/governance tabs from existing APIs.
- [ ] Show redacted failure cause, impact, and retry only when the backend contract permits retry.
- [ ] Verify a complete Fixture workflow without making a real LLM call.

## Phase 4: Review And Operations Completion

Phase 4 plan will be written after the Phase 3 run/detail contracts are stable.

- [ ] Add `/review` with draft queue, readable/editor center pane, and evidence/compliance decision pane.
- [ ] Preserve append-only draft versions and expose the current version before approve/return actions.
- [ ] Convert schedule management to status summaries plus a responsive table and explicit timezone forms.
- [ ] Finalize the paused shadow acceptance page and retain historical real records read-only.
- [ ] Standardize global success/error feedback, confirmation dialogs, focus handling, keyboard paths, and reduced-motion behavior.
- [ ] Run the entire frontend suite, production build, Fixture browser flow, empty-database flow, and 1440/1024/768/390 px visual checks.
- [ ] Record final browser evidence and obtain user acceptance before declaring the frontend complete.

## Phase Boundary Rules

- A later phase may consume only exported components/types and verified routes from completed phases.
- If implementation reveals that a required API does not exist, document the exact missing field and add the smallest redacted endpoint in that phase; do not redesign unrelated backend repositories.
- Do not mark a phase complete from unit tests alone. Build and browser checks are mandatory.
- Do not begin the next phase while the current phase has failing tests, broken routes, temporary sample data, or unresolved secret exposure.
- At each checkpoint, update this master plan and the active detailed plan with fresh test/build evidence.

