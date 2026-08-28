# SectorPulse Reference UI Final Code Review

**Date:** 2026-08-28
**Branch:** `refactoring`
**Diff reviewed:** `main...refactoring`
**Status:** no open Critical or Important findings after the fixes recorded below

## Review Scope

The review covered the changed frontend and backend contracts, visible actions, async state boundaries, polling, duplicate-submit protection, focus management, error disclosure, and the repository diff itself. Every mutation exposed by the refactored pages was checked against an implemented API route; unsupported task retry/recovery actions had already been removed in Phase 5.

## Closed Findings

### Important — request failures were rendered as truthful empty content

The legacy radar, evidence, draft, and review tabs initialized their data to empty values and swallowed rejected requests through `console.error`. A failed request therefore rendered messages such as “暂无草案” or “无审核问题”, which incorrectly asserted that a successful empty response had been received.

Fixed by adding explicit loading, failure, retry, and successful-empty boundaries with stale-response suppression in:

- `web/src/pages/tabs/RadarTab.tsx`
- `web/src/pages/tabs/EvidenceTab.tsx`
- `web/src/pages/tabs/DraftTab.tsx`
- `web/src/pages/tabs/ReviewTab.tsx`

Focused tests reproduce the rejected request first, verify that no empty-state claim is shown, retry, and then verify a real empty response. Draft copy feedback now uses the shared non-blocking feedback system instead of `alert()`.

### Important — Fixture launcher displayed a scene parameter that was not submitted

The four-step launcher displayed the selected “盘中分析 / 盘后复盘” scene during Fixture confirmation even though Fixture starts the fixed content sample returned by `/api/fixture-input`; the scene only affects Live data-run creation.

Fixed in `web/src/pages/NewAnalysisPage.tsx`: Fixture confirmation and the sticky summary now state “固定内容样例（不使用盘中 / 盘后参数）”. Live continues to submit the selected mode to the data-run API. The launcher test asserts the truthful Fixture wording.

### Important — missing evidence URL produced a fake `#` link

The legacy evidence tab rendered a clickable source even when `citation_url` was absent. It now renders plain source text unless a stored URL exists. A focused test protects this boundary.

### Minor — Markdown metadata introduced branch diff whitespace warnings

Phase 2–5 acceptance metadata used trailing spaces for hard line breaks. They were removed so final repository integrity checks can pass without suppressing warnings.

## Confirmed Existing Safeguards

- Polling stops on terminal states and uses request guards to prevent overlapping stale updates.
- Analysis submission uses a synchronous ref lock to prevent duplicate requests.
- The management drawer traps focus, restores focus, supports Escape, and locks background scrolling.
- Stored backend error messages are shown only in explicit details or error states; transient exceptions are not invented as persisted facts.
- External source links use `rel="noreferrer"`; a link is shown only when the backend supplied a URL.

## Focused Verification

- `npm.cmd test -- --run src/pages/tabs/RadarTab.test.tsx src/pages/tabs/EvidenceTab.test.tsx src/pages/tabs/ReviewTab.test.tsx src/pages/tabs/DraftTab.test.tsx src/pages/NewAnalysisPage.test.tsx`
  - 5 files, 9 tests expected after the missing-URL assertion
- `npm.cmd run build`
  - TypeScript build succeeded; Vite transformed 108 modules
  - JavaScript: 285.78 kB raw / 91.26 kB gzip
  - CSS: 73.81 kB raw / 13.21 kB gzip

The complete suite, dependency boundary audit, screenshot inspection, and final branch-level `diff --check` are recorded during the remaining Phase 6 tasks below in this same report and in the final acceptance record.

## Residual Risks

- External advisory freshness depends on the local package-manager cache or network availability; an unavailable advisory lookup must be recorded as unverified, not passing.
- PostgreSQL-specific integration tests depend on the local PostgreSQL service. The final acceptance distinguishes an unavailable service from an application test failure.
- Fixture is intentionally a deterministic content-generation sample. It does not validate live market-data providers or consume a real LLM allowance.

## Dependency, Performance, And Sensitive-Boundary Audit

### Dependency integrity

- `python -m pip check`: passed with “No broken requirements found.”
- `npm.cmd ls --depth=0`: passed; all declared frontend dependencies resolved from `web/package-lock.json`.
- `npm.cmd audit --offline`: completed from the local advisory cache with 0 vulnerabilities.

### Production asset budget

The production build transformed 108 modules and emitted no source maps:

| Asset | Raw | Gzip |
| --- | ---: | ---: |
| JavaScript | 285.78 kB | 91.26 kB |
| CSS | 73.81 kB | 13.21 kB |
| HTML | 0.41 kB | 0.28 kB |

The application remains a single modest JavaScript entry rather than duplicating a large chart, icon, or UI framework runtime.

### Sensitive and generated files

`git ls-files` returned no tracked `.env`, `.live-data-consent`, `.live-llm-consent`, database, `web/dist`, Playwright output, or TypeScript build-info file. `.gitignore` explicitly covers those paths as well as virtual environments, caches, logs, backups, and local worktrees.

A credential-shaped literal scan of tracked non-Markdown source found no API key, bearer token, or credential-bearing PostgreSQL URL. The initial broad `sk-` scan matched only the CSS class fragment `task-stage-list__index`; inspection confirmed it was a false positive and contained no secret.

No dependency, performance, or sensitive-boundary defect required a repository change.
