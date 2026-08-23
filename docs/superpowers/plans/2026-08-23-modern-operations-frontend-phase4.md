# Phase 4 Review And Operations Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the review workspace and finish schedule, shadow-history, feedback, accessibility, and responsive operations surfaces.

**Architecture:** Add two narrowly scoped backend decision endpoints over existing append-only repositories. Build `/review` as a route-level workspace with queue, editor, and evidence/compliance components; share one feedback provider and confirmation dialog across review and schedule actions.

**Tech Stack:** FastAPI, Pydantic, SQLite/PostgreSQL repository adapters, React 18, TypeScript, React Router, Vitest, Testing Library, vanilla CSS.

**Spec:** `docs/superpowers/specs/2026-08-23-modern-operations-frontend-phase4-design.md`

## Global Constraints

- No new UI framework, rich-text editor, account system, or real LLM call.
- Draft edits remain append-only and use `{base_version, operations:[{path, old_value_hash, value}]}`.
- Shadow acceptance remains paused and read-only.
- Never display secrets, internal JSON, raw stack traces, or unsafe backend exception text.
- Desktop and 1440/1024/768/390px layouts must have no horizontal page overflow.

---

### Task 1: Evidence decisions and return audit API

**Files:**
- Create: `backend/src/sector_pulse/web/review_schemas.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `backend/src/sector_pulse/storage/runtime_bundle.py`
- Modify: `backend/src/sector_pulse/storage/release_audit_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_release_audit_repository.py`
- Test: `backend/tests/integration/test_phase4_review_api.py`

**Interfaces:**
- Consumes: latest draft from `storage.draft_edit`, evidence decisions from a new `storage.governance` bundle field.
- Produces: GET/POST evidence-decision routes and POST return route defined in the design spec.

- [x] Write an integration test that creates a Fixture run, posts `{"source_id":"event-1","decision":"KEEP","reason":"来源可信"}`, and asserts the persisted response and list route.
- [x] Run `python -m pytest backend/tests/integration/test_phase4_review_api.py -q`; verify failure is 404 because the route is absent.
- [x] Add `governance` to `RuntimeStorageBundle` using `SQLiteGovernanceRepository` and `BlockingAsyncRepository(PostgresGovernanceRepository(...))`.
- [x] Add Pydantic request/response models with `reason: Field(min_length=1)` and decision validation through `EvidenceDecisionKind`.
- [x] Implement list/create routes, verify run/draft ownership, call `EvidenceDecisionService.record`, and serialize only safe fields.
- [x] Write a failing test that posts `{"reason":"需要补充证据"}` to `/return` and expects `RETURNED` for the latest version plus an audit event.
- [x] Add public `record_event(...)` methods to SQLite and PostgreSQL release-audit repositories; implement `/return` without mutating or deleting a draft.
- [x] Run the integration test and the release-audit repository tests; commit.

### Task 2: Shared feedback and confirmation primitives

**Files:**
- Create: `web/src/components/ui/FeedbackProvider.tsx`
- Create: `web/src/components/ui/FeedbackProvider.test.tsx`
- Create: `web/src/components/ui/ConfirmDialog.tsx`
- Create: `web/src/components/ui/ConfirmDialog.test.tsx`
- Modify: `web/src/layout/AppShell.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Produces: `useFeedback(): {success(message): void; error(message): void}` and `ConfirmDialog` props `{open,title,description,confirmLabel,tone,onConfirm,onCancel}`.

- [x] Write failing tests for `aria-live` success/error messages, manual dismissal, Escape cancellation, initial cancel focus, and focus restoration.
- [x] Run the two test files and verify missing-module failures.
- [x] Implement the provider with generated notification IDs and 5-second timers; implement native `<dialog>` confirmation with cancel-first focus.
- [x] Add restrained notification stack and dialog styles with reduced-motion handling.
- [x] Wrap the AppShell outlet with `FeedbackProvider`, rerun tests, and commit.

### Task 3: Review API client and three-pane workspace

**Files:**
- Modify: `web/src/editingApi.ts`
- Create: `web/src/pages/ReviewWorkspacePage.tsx`
- Create: `web/src/pages/ReviewWorkspacePage.test.tsx`
- Create: `web/src/components/review/ReviewQueue.tsx`
- Create: `web/src/components/review/DraftWorkspace.tsx`
- Create: `web/src/components/review/EvidenceDecisionPane.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/layout/navigation.ts`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `fetchRuns`, `fetchDraft`, `fetchEvidence`, governance, approval, evidence-decision, return and patch clients.
- Produces: `/review`, queue selection, version-safe editing, evidence decisions, approve/revoke/return actions.

- [x] Write a failing route test that loads two real run summaries, filters the queue, and selects the first reviewable run.
- [x] Add typed API clients; fix `applyDraftPatch` to send `{base_version, operations:[{path,old_value_hash,value}]}`.
- [x] Implement the route, navigation entry and loading/error/empty states.
- [x] Write a failing editor test proving an old version is read-only and the latest version saves one operation with the current hash.
- [x] Implement title, introduction, section, conclusion and risk-notice selection with append-only refresh after save.
- [x] Write failing tests for evidence reason validation, approve confirmation showing `vN`, return confirmation and current approval loading.
- [x] Implement the compliance pane and actions using shared feedback/confirmation; never render a missing citation as `href="#"`.
- [x] Run review tests and commit.

### Task 4: Schedule operations page

**Files:**
- Modify: `web/src/schedulesApi.ts`
- Modify: `web/src/pages/SchedulePage.tsx`
- Modify: `web/src/pages/SchedulePage.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Adds: `createSchedule(input: NewScheduleInput): Promise<ScheduleView>`.

- [x] Write failing tests for four status summaries, explicit timezone form submission, responsive table semantics, trigger busy state and safe error feedback.
- [x] Implement the typed create client with `input_template: {}` and the existing POST endpoint.
- [x] Implement inline progressive creation form with `Asia/Shanghai` default, `type="time"`, mode and trading-day controls.
- [x] Replace cards with a responsive table and shared feedback; disable only the schedule currently being triggered.
- [x] Run schedule tests and commit.

### Task 5: Read-only shadow history

**Files:**
- Modify: `web/src/pages/ShadowAcceptancePage.tsx`
- Modify: `web/src/components/ShadowAcceptanceCard.tsx`
- Modify: `web/src/components/ShadowAcceptanceCard.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes only `fetchShadowRuns()` and `fetchShadowProgress()`; produces no mutation calls.

- [x] Write failing tests for paused copy, five historical summary values, complete run table and absence of mutation controls.
- [x] Implement the summary strip and responsive historical table with Chinese status labels.
- [x] Ensure remaining target copy says historical gap, not active progress.
- [x] Run shadow tests and commit.

### Task 6: Full acceptance and documentation

**Files:**
- Modify: `docs/superpowers/plans/2026-08-23-modern-operations-frontend-master.md`
- Create: `docs/superpowers/reports/2026-08-23-modern-operations-frontend-phase4-acceptance.md`

**Interfaces:**
- Consumes all completed Phase 4 routes and components.

- [x] Run `python -m pytest backend/tests -q` with worktree `PYTHONPATH`; record passed and skipped counts.
- [x] Run `npm.cmd test -- --run` and `npm.cmd run build`; record exact results.
- [x] Run Impeccable detector on `/review`, `/schedules`, and `/shadow-acceptance`; fix all findings in one batch.
- [x] Use a Fixture run in the production build to edit one section, verify version increment, record an evidence decision, return it, approve it, and verify export availability.
- [x] Verify empty and Fixture-populated states at 1440, 1024, 768 and 390px, including keyboard focus and no horizontal overflow.
- [x] Record browser evidence, update all Phase 4 master checkboxes, commit, and leave only known cache artifacts untracked.
