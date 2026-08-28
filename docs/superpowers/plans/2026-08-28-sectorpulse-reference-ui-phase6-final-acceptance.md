# SectorPulse Reference UI Phase 6 Final Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task in the current session. The user explicitly requested no subagents, so review remains in the coordinating session. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 `main...refactoring` 的全项目审查、真实页面截图、README 校准和最终可合并验收，并保留独立合并决策点。

**Architecture:** Phase 6 不扩展业务能力。先从 Git 差异、API 合同、前端状态边界和测试覆盖中寻找回归，再以最小修复关闭 Critical/Important 问题；随后用隔离 SQLite 生产构建生成三张真实产品截图，替换 README 中的历史设计参考图。最终验收同时覆盖前端、后端、浏览器、依赖完整性和敏感信息边界。

**Tech Stack:** Git、React 18、TypeScript 5.6、Vite、Vitest、Playwright、FastAPI、Pytest、Ruff、mypy、SQLite 隔离验收、Markdown。

**Spec:** `docs/superpowers/specs/2026-08-27-sectorpulse-reference-ui-refactor-design.md`

## Global Constraints

- 不调用 Live 数据或真实 LLM，不消耗 API 额度。
- 不写用户 PostgreSQL 或默认 SQLite；浏览器实页检查只使用 `.tmp-test/phase6-browser.db`。
- 不在 README 展示假数据、设计概念图或不存在的功能；截图必须来自当前生产构建。
- 不提交 `.env`、consent、数据库、Playwright 结果、密钥或 Provider 原始响应。
- 不新增无后端合同的按钮；Critical 和 Important 审查问题必须在最终验收前关闭。
- 保留 `refactoring` 分支，不自动合并到 `main`。

---

### Task 1: Audit The Refactor Against Main

**Files:**
- Read: `main...refactoring` 135-file diff
- Create: `docs/superpowers/reports/2026-08-28-reference-ui-final-code-review.md`
- Modify/Test: only files implicated by confirmed findings

**Interfaces:**
- Consumes: master plan exit criteria, Phase 1–5 acceptance reports, existing HTTP schemas and frontend API types.
- Produces: severity-ranked review with concrete file/line evidence, closed findings and accepted residual risks.

- [x] **Step 1: Inventory changed contracts and high-risk surfaces**

  Run `git diff --name-status main...refactoring`, `git diff --check main...refactoring`, route/API searches and targeted reads of operations summary, candidate selection, autosave, review workspace, run launcher and management pages.

- [x] **Step 2: Scan for fake actions and unsafe error handling**

  Search changed TSX for action buttons, `console.error`, swallowed requests, direct `window.location`, raw error rendering, missing loading/error/empty states and unsupported endpoint calls. Verify each visible mutation against an API function and backend route.

- [x] **Step 3: Audit accessibility, polling and state races**

  Inspect dialogs/drawers, tab semantics, focus return, request cancellation, stale-response suppression, polling overlap, terminal stopping and duplicate-submit guards. Re-run focused tests for any uncertain contract.

- [x] **Step 4: Fix confirmed Critical/Important findings with tests first**

  For each confirmed defect, add a focused failing Vitest/Pytest/Playwright assertion, reproduce the failure, implement the smallest correction and verify the focused suite passes. Do not change code for speculative or style-only findings.

- [x] **Step 5: Write and commit the review record**

  Record scope, findings, fixes, residual risks and exact verification in `docs/superpowers/reports/2026-08-28-reference-ui-final-code-review.md`; commit code/tests/report as `fix: close final reference ui review findings` or, when no code fix is required, `docs: record final reference ui code review`.

### Task 2: Audit Dependencies, Performance And Sensitive Boundaries

**Files:**
- Modify: `docs/superpowers/reports/2026-08-28-reference-ui-final-code-review.md`
- Modify/Test: only confirmed configuration or documentation defects

**Interfaces:**
- Consumes: `pyproject.toml`, `web/package.json`, lockfiles, built assets, `.gitignore`, tracked-file list.
- Produces: dependency integrity, bundle-size, tracked-secret and generated-artifact evidence.

- [x] **Step 1: Verify dependency consistency**

  Run `.\.venv\Scripts\python.exe -m pip check`, `npm.cmd ls --depth=0` and non-mutating audit commands available from the existing lock/cache. Record unavailable network advisories as unverified rather than passing.

- [x] **Step 2: Measure production assets**

  Run `npm.cmd run build`, record transformed module count and uncompressed/gzip asset sizes, and inspect for unexpectedly duplicated large dependencies or source maps.

- [x] **Step 3: Verify sensitive and generated files are untracked**

  Confirm `.env`, consent markers, database files, caches, `web/dist`, `web/test-results`, Playwright reports and `tsconfig.tsbuildinfo` are absent from `git ls-files`; scan tracked source for credential-shaped literals while returning filenames only.

- [x] **Step 4: Record accepted boundaries**

  Add dependency, performance and secret-scan evidence to the final code review. Fix only reproducible repository issues and verify after changes.

### Task 3: Capture Real Product Screenshots And Update README

**Files:**
- Create: `docs/screenshots/sectorpulse-operations-dashboard.png`
- Create: `docs/screenshots/sectorpulse-data-workbench.png`
- Create: `docs/screenshots/sectorpulse-review-workspace.png`
- Modify: `README.md`
- Modify: `docs/design/sectorpulse-reference-ui-system.md`

**Interfaces:**
- Consumes: current `web/dist`, fixture provider, isolated SQLite database, production FastAPI static serving.
- Produces: three current-product PNGs and README links that no longer imply design reference images are implementation screenshots.

- [x] **Step 1: Start an isolated production application**

  Build the frontend; start FastAPI on an unused loopback port with PostgreSQL disabled, Fixture LLM selected and database path `.tmp-test/phase6-browser.db`. Create only deterministic fixture content needed for dashboard, data workbench and review workspace screenshots.

- [x] **Step 2: Capture the three real desktop pages**

  At 1536×1024 capture the dashboard, a populated data workbench and a populated review workspace. Verify no root overflow and no browser warning/error entries before each capture. Save PNGs under `docs/screenshots/`.

- [x] **Step 3: Render and inspect saved PNGs**

  Open each local image at original detail and verify crop, readable hierarchy, absence of secrets, correct current navigation and truthful fixture labels. Re-capture any image with clipping, transient loading or empty accidental content.

- [x] **Step 4: Update README and design-reference wording**

  Replace README image links with `docs/screenshots/*`, update the four-step quick-start wording and clarify that `docs/design/references/*` are historical visual targets rather than product screenshots. Keep architecture, safety and startup commands accurate.

- [x] **Step 5: Verify Markdown targets and commit**

  Check every relative README link exists, inspect `git diff --check`, and commit README/screenshots/design wording as `docs: refresh readme with actual product screens`.

### Task 4: Run Final Cross-Project Acceptance

**Files:**
- Create: `docs/superpowers/acceptance/2026-08-28-sectorpulse-reference-ui-final.md`
- Modify: `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md`
- Modify: this plan

**Interfaces:**
- Consumes: all Phase 1–6 commits and acceptance suites.
- Produces: one final evidence document and a clean, reviewable `refactoring` branch.

- [x] **Step 1: Run complete frontend verification**

  Run `npm.cmd test -- --run`, `npm.cmd run build`, all five Playwright specs and the Impeccable detector for changed UI files. Expected: zero failures and no unresolved detector findings.

- [x] **Step 2: Run complete backend verification**

  Run non-Live Pytest with PostgreSQL integration tests excluded only when the local service is unavailable, Ruff, and changed-source strict mypy for all Python files changed from `main`. Record both passing evidence and any legacy baseline errors exactly.

- [x] **Step 3: Recheck repository integrity**

  Run `git diff --check main...HEAD`, verify no untracked generated artifacts, confirm branch name and list commits since `main`. Ensure all temporary browser services and SQLite files are removed.

- [x] **Step 4: Write final acceptance and close plans**

  Record exact test counts, browser coverage, screenshots, review findings, dependency/security results and non-blocking warnings. Mark Phase 6 complete in the master plan and this plan only when every required result has evidence.

- [x] **Step 5: Commit final acceptance**

  Commit plan/report updates as `docs: complete reference ui final acceptance`. Do not merge branches.

## Exit Criteria

- `main...refactoring` has no open Critical or Important review finding.
- Every visible mutation maps to an implemented backend contract and every primary page has loading/error/empty or partial states appropriate to its data.
- Full frontend, Playwright, backend non-Live and Ruff checks pass; changed-source mypy result is recorded without hiding legacy errors.
- README displays three current production screenshots and all referenced paths exist.
- Dependency integrity, bundle size, tracked-secret and generated-artifact checks are documented.
- Worktree is clean on `refactoring`; `main` remains unchanged pending the user's merge decision.
