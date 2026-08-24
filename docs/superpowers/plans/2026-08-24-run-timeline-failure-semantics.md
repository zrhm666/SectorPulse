# Run Timeline Failure Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Phase 1B progress events and the operations UI distinguish successful, degraded, failed, skipped, and pending stages accurately.

**Architecture:** The pipeline emits outcome-specific events at the point where an editorial fallback or writing failure is known. `OverviewTab` combines live SSE evidence with the persisted terminal run status through a small deterministic stage-state resolver, so refreshed historical pages remain truthful without persisting the complete SSE stream.

**Tech Stack:** Python 3.12, pytest, React 18, TypeScript, Vitest, Testing Library, CSS.

## Global Constraints

- Do not change database migrations, API response shapes, or existing terminal status values.
- `writing.done` means a valid `ArticleDraft` exists; invalid structured output emits `writing.failed`.
- An editorial fallback emits `editorial.fallback` and remains a completed but degraded stage.
- Existing successful live and Fixture runs retain their current event names.
- Use exact Chinese UI copy: `已完成`, `已降级完成`, `失败`, `未执行`, `等待中`.

---

### Task 1: Correct Phase 1B outcome events

**Files:**
- Modify: `backend/src/sector_pulse/application/editorial_agents.py`
- Modify: `backend/src/sector_pulse/application/phase1b_pipeline.py`
- Test: `backend/tests/integration/test_phase1b_pipeline_progress.py`

**Interfaces:**
- Produces: `run_editorial_agent(...) -> tuple[ArticleOutline, bool]`, where the boolean is true only when a deterministic fallback was used.
- Produces: progress stages `editorial.done`, `editorial.fallback`, `writing.done`, and `writing.failed`.

- [ ] **Step 1: Write failing pipeline event tests**

Add a sink-based failure test that supplies invalid editorial and writing fixture responses and asserts:

```python
assert "editorial.fallback" in stages
assert "writing.failed" in stages
assert "writing.done" not in stages
assert result.status == "DRAFT_GENERATION_FAILED"
```

Keep the existing success test asserting `editorial.done` and `writing.done`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase1b_pipeline_progress.py -q -p no:cacheprovider
```

Expected: the new test fails because the current pipeline emits `editorial.done` and `writing.done` even for fallback/`None` results.

- [ ] **Step 3: Return the editorial fallback outcome and emit accurate events**

Change the editorial result contract and pipeline branching to the equivalent of:

```python
outline, used_fallback = await run_editorial_agent(...)
progress_sink.emit(
    "editorial.fallback" if used_fallback else "editorial.done",
    {"sector_ids": list(outline.sector_ids)},
)

draft = await run_writing_agent(...)
if draft is None or not draft.sources:
    progress_sink.emit("writing.failed", {"reason": "invalid_or_source_less_draft"})
    return Phase1BRunResult(status=PipelineStatus.DRAFT_GENERATION_FAILED, ...)
progress_sink.emit("writing.done", {"version": draft.version})
```

Update direct callers/tests of `run_editorial_agent` to unpack the tuple if any are found by `rg`.

- [ ] **Step 4: Run backend focused tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase1b_pipeline_progress.py backend/tests/integration/test_phase1b_pipeline.py backend/tests/unit/application -q -p no:cacheprovider
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the backend event contract**

```powershell
git add backend/src/sector_pulse/application/editorial_agents.py backend/src/sector_pulse/application/phase1b_pipeline.py backend/tests/integration/test_phase1b_pipeline_progress.py backend/tests/unit/application
git commit -m "fix: report phase1b stage outcomes accurately"
```

---

### Task 2: Render terminal timeline states truthfully

**Files:**
- Modify: `web/src/pages/tabs/OverviewTab.tsx`
- Modify: `web/src/pages/tabs/OverviewTab.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Produces: local `StageState = 'complete' | 'degraded' | 'failed' | 'skipped' | 'pending'`.
- Consumes: `ProgressEvent.stage` and `RunSummary.status` without changing API types.

- [ ] **Step 1: Write failing component tests**

Add a `DRAFT_GENERATION_FAILED` historical-run test asserting the six stage descriptions in order:

```typescript
expect(screen.getAllByTestId('timeline-state').map((node) => node.textContent)).toEqual([
  '已完成', '已完成', '已完成', '已完成', '失败', '未执行',
])
```

Add an SSE test with `editorial.fallback` and assert `已降级完成`. Preserve a generic `FAILED` test that does not invent successful stages.

- [ ] **Step 2: Run the component test and verify RED**

Run:

```powershell
npm.cmd --prefix web test -- OverviewTab.test.tsx
```

Expected: the new tests fail because the component currently uses only `complete` and treats `DRAFT_GENERATION_FAILED` as pending.

- [ ] **Step 3: Implement deterministic stage-state resolution**

Introduce a focused resolver in `OverviewTab.tsx` that applies live events first and uses the terminal status only for facts implied by `DRAFT_GENERATION_FAILED`. Render state text from:

```typescript
const stateLabel = {
  complete: '已完成',
  degraded: '已降级完成',
  failed: '失败',
  skipped: '未执行',
  pending: '等待中',
} satisfies Record<StageState, string>
```

Set `data-state={state}` on each timeline item and `data-testid="timeline-state"` on its `<small>` element.

- [ ] **Step 4: Add failure/degraded node styles**

Extend existing timeline CSS with:

```css
.timeline li[data-state="complete"] > span,
.timeline li[data-state="degraded"] > span { background: var(--color-success); border-color: var(--color-success); }
.timeline li[data-state="failed"] > span { background: var(--color-danger); border-color: var(--color-danger); }
```

Use the repository's actual danger-color token found in `web/src/styles.css`; do not introduce a duplicate token.

- [ ] **Step 5: Run frontend focused tests and build**

Run:

```powershell
npm.cmd --prefix web test -- OverviewTab.test.tsx RunDetailPage.test.tsx
npm.cmd --prefix web run build
```

Expected: focused tests pass and TypeScript/Vite build succeeds.

- [ ] **Step 6: Commit the UI semantics**

```powershell
git add web/src/pages/tabs/OverviewTab.tsx web/src/pages/tabs/OverviewTab.test.tsx web/src/styles.css
git commit -m "fix: render run timeline failures truthfully"
```

---

### Task 3: Regression verification

**Files:**
- Verify only; no planned production changes.

**Interfaces:**
- Confirms the backend event contract and frontend rendering work together without changing public APIs.

- [ ] **Step 1: Run backend regression**

```powershell
.\.venv\Scripts\ruff.exe check backend/src backend/tests
.\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider
```

Expected: Ruff and all non-environment-blocked backend tests pass; live tests remain separately classified.

- [ ] **Step 2: Run frontend regression**

```powershell
npm.cmd --prefix web test
npm.cmd --prefix web run build
```

Expected: all Vitest tests pass and the production bundle builds.

- [ ] **Step 3: Inspect the final diff**

```powershell
git diff HEAD~2 --check
git status --short
```

Expected: no whitespace errors and no uncommitted implementation files.
