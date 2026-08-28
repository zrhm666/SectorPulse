# SectorPulse Reference UI Phase 4: Review Workspace Implementation Plan

> **Execution mode:** 当前会话连续执行；遵循测试驱动、按任务独立提交和证据验收。除非遇到需要用户提供的新权限或外部条件，不在任务间等待确认。

**Goal:** 将现有审核页升级为高密度、可恢复的三栏审核工作台，完成连续结构化编辑、停止输入/失焦自动保存、版本冲突保护、段落相关证据、治理与审批门禁，并保持现有追加版本与审计合同不变。

**Architecture:** 复用现有草稿版本、补丁、治理、证据决定、批准、撤销、退回与导出 API。前端新增审核工作台状态边界，隔离运行切换、草稿版本、编辑草稿和异步请求；编辑器继续按结构化字段保存，不引入富文本或覆盖式写入。桌面以单个视口内的 22%/53%/25% 三栏呈现，各栏独立滚动；窄屏改为队列/草稿/证据页签。

**Tech Stack:** React 18、TypeScript 5.6、Vitest、Testing Library、Playwright、现有 FastAPI/SQLite/PostgreSQL 合同、SectorPulse 设计令牌与 Impeccable Operate 模式。

**Approved references:**

- `docs/superpowers/specs/2026-08-27-sectorpulse-reference-ui-refactor-design.md` §11
- `docs/design/sectorpulse-reference-ui-system.md`
- `docs/design/references/sectorpulse-soft-blue-review-workspace.png`
- `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md`
- Phase 3 acceptance: `docs/superpowers/acceptance/2026-08-27-sectorpulse-reference-ui-phase3.md`

## Existing Capability Audit

Reliable and retained:

- reviewable run list and default pending-review selection;
- append-only draft versions and optimistic `base_version` patch contract;
- immutable historical version viewing;
- governance report, evidence decisions and affected section IDs;
- approval, revoke, return and approved JSON export audit paths;
- stale run-switch response suppression through sequence IDs;
- shared feedback and confirmation dialog primitives.

Gaps this phase closes:

- current queue sits above a two-column layout instead of the approved desktop three-column workspace;
- long page scrolls as one document rather than keeping queue/editor/evidence independently usable;
- every field requires a manual save button and exposes no unsaved/saving/saved/conflict state;
- a delayed response can complete after additional local typing without a per-field save queue;
- 409 conflicts are shown as a generic failure and do not protect/reload local work explicitly;
- evidence always shows the global source list instead of following the focused section;
- approval can be attempted while local edits are pending;
- narrow screens stack all content rather than exposing an intentional queue/draft/evidence mode switch.

## Global Constraints

- Never overwrite an existing draft version; every successful save creates a new version through the existing patch API.
- Never autosave historical versions.
- Never silently discard local text after a conflict, run switch or refresh.
- Only one save request per field may be in flight; newer local text remains queued and is saved against the refreshed latest version.
- Approval and return actions are disabled while any field is unsaved, saving, failed or conflicted.
- Existing sources, citation URLs, governance status and decisions are rendered as returned; no placeholder source or fake governance result.
- Evidence decisions do not rewrite draft text automatically.
- Desktop uses three independent scroll regions inside the app's existing main scroll shell. Mobile has one active pane and no page-level horizontal overflow.
- Existing API paths remain stable. Additive frontend typing may expose fields already returned by the backend, such as section `source_ids`.

## Target Interaction Model

```text
ReviewWorkspaceState
  queue: reviewable runs + filter
  selected_run_id
  versions + selected_version
  active_pane: queue | draft | evidence
  active_field: path + label + source_ids
  field_edits[path]: value + baseline_hash + state
  governance + approval + evidence_decisions
  load_generation: monotonically increasing request token
```

Field save states:

```text
clean → dirty → saving → saved → clean
                    ↘ failed
                    ↘ conflict (409, local value retained)
```

Autosave waits 800 ms after the last input and saves immediately on blur. `saved` remains visible briefly before returning to `clean`. A conflict offers “重新加载最新版本” while retaining the local text for explicit reapply.

---

## Task 1: Harden Review API And Workspace State

**Files:**

- Modify: `web/src/api.ts`
- Modify: `web/src/editingApi.ts`
- Modify: `web/src/pages/ReviewWorkspacePage.tsx`
- Modify: `web/src/pages/ReviewWorkspacePage.test.tsx`
- Create: `web/src/hooks/useReviewWorkspace.ts`
- Create: `web/src/hooks/useReviewWorkspace.test.tsx`

- [x] Add typed section `source_ids`, safe API errors with status/code and AbortSignal support for review requests.
- [x] Write failing hook tests for initial queue selection, empty/error state, stale run-switch suppression, reload and latest-version refresh.
- [x] Implement one state boundary for queue, selected run, versions, governance, approval and decisions.
- [x] Preserve the selected queue item when it remains reviewable after refresh; otherwise select the first pending item.
- [x] Expose explicit initial loading, pane loading and recoverable errors without clearing the last successful workspace.
- [x] Run focused API/hook/page tests and TypeScript build (9 focused tests; 104-module production build).
- [x] Commit: `refactor: harden review workspace state`.

## Task 2: Build The Three-Pane Review Shell

**Files:**

- Modify: `web/src/pages/ReviewWorkspacePage.tsx`
- Modify: `web/src/components/review/ReviewQueue.tsx`
- Create: `web/src/components/review/ReviewPaneTabs.tsx`
- Create: `web/src/components/review/ReviewPaneTabs.test.tsx`
- Create: `web/src/styles/pages/review-workspace.css`
- Modify: `web/src/styles/index.css`

- [x] Write layout semantics tests for queue/editor/evidence ownership and narrow-screen pane controls.
- [x] Implement desktop `22% / 53% / 25%` columns with min widths, aligned headers and independent vertical scrolling.
- [x] Make the queue compact and filterable by pending/approved/all without inventing missing metadata.
- [x] Keep the editor's effective reading width between roughly 680–820 px at wide desktop sizes.
- [x] At 1024 px and below switch to queue/draft/evidence pane tabs; retain the selected run and active field when changing panes.
- [x] Keep all key actions keyboard reachable and maintain one shell-level scroll contract without root overflow.
- [x] Run component/page tests, build and Impeccable detector (43 files / 143 tests; 105-module build; detector `[]`).
- [x] Commit: `refactor: build three pane review shell`.

## Task 3: Add Continuous Structured Autosave

**Files:**

- Modify: `web/src/components/review/DraftWorkspace.tsx`
- Modify: `web/src/components/review/DraftWorkspace.test.tsx`
- Create: `web/src/hooks/useDraftAutosave.ts`
- Create: `web/src/hooks/useDraftAutosave.test.tsx`
- Modify: `web/src/styles/pages/review-workspace.css`

- [x] Write failing tests for dirty state, 800 ms debounce, immediate blur save, no-op unchanged text, one in-flight request, queued newer text and cleanup.
- [x] Write failing tests for success, network failure and 409 conflict with local text retained.
- [x] Render title, introduction, sections, conclusion and risk notice as one continuous document surface with subtle focus boundaries.
- [x] Replace per-field save buttons with a persistent save-state indicator and explicit retry/reload controls only when needed.
- [x] Keep historical versions read-only and prevent autosave when browsing them.
- [x] On successful save, refresh versions and rebase untouched fields without replacing another dirty field.
- [x] Run focused tests, full frontend tests and build (44 files / 149 tests; 106-module build; detector `[]`).
- [x] Commit: `feat: add structured draft autosave`.

## Task 4: Make Evidence Contextual And Governance Actions Safe

**Files:**

- Modify: `web/src/components/review/DraftWorkspace.tsx`
- Modify: `web/src/components/review/EvidenceDecisionPane.tsx`
- Modify: `web/src/components/review/EvidenceDecisionPane.test.tsx`
- Modify: `web/src/pages/ReviewWorkspacePage.tsx`
- Modify: `web/src/styles/pages/review-workspace.css`

- [x] Emit the focused field/section context and its persisted `source_ids` from the editor.
- [x] Show related sources first; when no field-level mapping exists, label the global fallback explicitly.
- [x] Add source/governance/audit subviews without nested card stacks or hidden actions.
- [x] Keep evidence decision reason and return reason independent and require both frontend/backend-valid input.
- [x] Disable approval while governance fails, an edit is pending, a historical version is open or a save conflict exists; explain the exact reason.
- [x] After approve/revoke/return/decision, reload only affected state and retain editor/queue context.
- [x] Verify safe links, focus return for confirmations and no automatic text rewriting after evidence decisions.
- [x] Run focused tests, build and detector (44 files / 154 tests; 106-module build; detector `[]`).
- [x] Commit: `refactor: connect review evidence and governance`.

## Task 5: Browser Acceptance And Phase Closure

**Files:**

- Create: `web/e2e/review-workspace.spec.ts`
- Create: `docs/superpowers/acceptance/2026-08-28-sectorpulse-reference-ui-phase4.md`
- Modify: `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md`
- Modify: this plan

- [x] Add deterministic empty, loading, pending, approved, governance-blocked, save-failed and conflict fixtures without writing the user's database.
- [x] Verify 1536×1024 and 1440×900 three-column proportions and independent scrolling.
- [x] Verify 1024×768, 768×1024 and 390×844 pane switching, focus visibility and no root overflow.
- [x] Verify run switch cancellation, historical read-only view, autosave debounce/blur, queued edits and conflict recovery.
- [x] Verify contextual sources, evidence decision, approve, revoke and return confirmation contracts.
- [x] Run full Vitest, build, shell/review Playwright, backend non-live tests, Ruff and changed-source mypy.
- [x] Inspect the isolated built page in the in-app browser and record console/layout evidence.
- [x] Run `git diff --check`, write exact acceptance evidence and commit `docs: record reference ui phase 4 acceptance`.

## Phase Exit Criteria

- Desktop users can review queue, draft and evidence concurrently without losing their place.
- Mobile/tablet users can reach the same functions through explicit panes without compressed three-column content.
- Editing remains structured and append-only; stopped typing and blur save reliably without duplicate requests.
- Local text survives network errors and version conflicts.
- Historical versions never autosave and cannot be approved as if they were latest.
- Evidence follows the focused section when mapping exists and truthfully falls back to all sources otherwise.
- Governance, pending saves and conflicts jointly gate approval.
- All actions reflect implemented backend capabilities and persisted state.
