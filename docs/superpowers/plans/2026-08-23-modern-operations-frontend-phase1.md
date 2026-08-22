# Modern Operations Frontend Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the shared visual system, responsive application shell, route foundation, and polished versions of the currently available operational pages.

**Architecture:** CSS variables own visual tokens; small typed React primitives own repeated UI semantics; `AppShell` owns navigation and page chrome while route pages own only business content. Phase 1 exposes only routes backed by current functionality and redirects `/` to `/runs` until Phase 2 supplies the real operations dashboard.

**Tech Stack:** React 18, React Router 6, TypeScript 5.6, CSS, Vite 5, Vitest 4, Testing Library

**Spec:** `docs/superpowers/specs/2026-08-23-modern-operations-frontend-design.md`

## Global Constraints

- Do not add a UI framework or icon dependency.
- Do not change backend APIs or database behavior in Phase 1.
- Do not display fake metrics, sample runs, or sample Provider status.
- Preserve `/runs/:runId`, `/data-runs/:runId`, `/task-runs/:runId`, `/schedules`, and `/shadow-acceptance`.
- `/` must redirect to `/runs` until the real dashboard is implemented in Phase 2.
- Do not display secrets, raw prompts, or unredacted model responses.
- Use semantic HTML, visible keyboard focus, status text in addition to color, and responsive layouts at 768 px and 390 px.

---

### Task 1: Shared Design Tokens And UI Primitives

**Files:**
- Modify: `web/src/styles.css`
- Create: `web/src/components/ui/PageHeader.tsx`
- Create: `web/src/components/ui/Panel.tsx`
- Create: `web/src/components/ui/StatusBadge.tsx`
- Create: `web/src/components/ui/EmptyState.tsx`
- Create: `web/src/components/ui/InlineAlert.tsx`
- Create: `web/src/components/ui/LoadingState.tsx`
- Create: `web/src/components/ui/UiPrimitives.test.tsx`
- Modify: `web/src/components/Badge.tsx`

**Interfaces:**
- Consumes: React children and existing status strings.
- Produces: `PageHeader`, `Panel`, `StatusBadge`, `EmptyState`, `InlineAlert`, and `LoadingState`; `Badge` remains a compatibility wrapper during migration.

- [ ] **Step 1: Write failing primitive rendering and accessibility tests**

Create `UiPrimitives.test.tsx` with tests equivalent to:

```tsx
import { render, screen } from '@testing-library/react'
import EmptyState from './EmptyState'
import InlineAlert from './InlineAlert'
import PageHeader from './PageHeader'
import StatusBadge from './StatusBadge'

it('renders one page heading and its primary action', () => {
  render(<PageHeader title="分析运行" description="查看全部运行" actions={<button>新建分析</button>} />)
  expect(screen.getByRole('heading', { level: 1, name: '分析运行' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '新建分析' })).toBeInTheDocument()
})

it('exposes status and alert semantics as text', () => {
  render(<><StatusBadge status="FAILED" /><InlineAlert tone="error" title="运行失败">Provider 超时</InlineAlert></>)
  expect(screen.getByText('失败')).toBeInTheDocument()
  expect(screen.getByRole('alert')).toHaveTextContent('Provider 超时')
})

it('renders a guided empty state action', () => {
  render(<EmptyState title="还没有运行记录" description="创建第一次分析。" action={<button>新建分析</button>} />)
  expect(screen.getByRole('button', { name: '新建分析' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the focused test and verify the missing-module failure**

Run: `cd web; npm test -- src/components/ui/UiPrimitives.test.tsx`

Expected: FAIL because the new primitives do not exist.

- [ ] **Step 3: Implement typed primitives with stable contracts**

Use these exported prop contracts:

```tsx
export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'
export type StatusBadgeProps = { status: string; label?: string; tone?: StatusTone }
export type PageHeaderProps = { title: string; description?: string; eyebrow?: string; actions?: React.ReactNode }
export type PanelProps = { title?: string; description?: string; actions?: React.ReactNode; children: React.ReactNode; className?: string }
export type EmptyStateProps = { title: string; description: string; action?: React.ReactNode }
export type InlineAlertProps = { tone: 'info' | 'warning' | 'error' | 'success'; title: string; children?: React.ReactNode }
```

`StatusBadge` must map known backend states to Chinese labels and tones, retain the original status as `data-status`, and fall back to the supplied string with neutral tone. `Badge.tsx` must delegate to `StatusBadge` so old callers continue compiling while pages migrate.

- [ ] **Step 4: Replace `styles.css` with tokenized base and component classes**

Define `:root` variables for background, surface, text, muted text, primary, success, warning, danger, border, focus ring, radii, shadows, spacing, sidebar width, and topbar height. Add semantic classes used by the primitives, including `.page-header`, `.panel`, `.status-badge`, `.empty-state`, `.inline-alert`, `.loading-state`, `.button`, `.button-primary`, `.button-secondary`, and `.button-ghost`.

Keep the existing `.card`, `.tabbar`, `.badge`, `.modal`, and `.modal-inner` selectors as temporary compatibility aliases so untouched detail pages remain usable in Phase 1.

- [ ] **Step 5: Run focused tests and TypeScript build**

Run:

```powershell
cd web
npm test -- src/components/ui/UiPrimitives.test.tsx
npm run build
```

Expected: primitive tests PASS and production build exits 0.

- [ ] **Step 6: Commit the primitive foundation**

```powershell
git add web/src/styles.css web/src/components/Badge.tsx web/src/components/ui
git commit -m "feat: add frontend design system primitives"
```

### Task 2: Responsive Application Shell And Navigation

**Files:**
- Create: `web/src/layout/navigation.ts`
- Create: `web/src/layout/SidebarNav.tsx`
- Create: `web/src/layout/TopBar.tsx`
- Create: `web/src/layout/AppShell.tsx`
- Create: `web/src/layout/AppShell.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: React Router location/navigation and nested route content through `Outlet`.
- Produces: `NAV_ITEMS`, `SidebarNav`, `TopBar`, and `AppShell` for all routable pages.

- [ ] **Step 1: Write failing shell/navigation tests**

Create tests using `MemoryRouter` and `Routes` that assert:

```tsx
it('renders available navigation and marks the current route', () => {
  renderShellAt('/runs')
  expect(screen.getByRole('link', { name: '分析运行' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('link', { name: '定时任务' })).toHaveAttribute('href', '/schedules')
  expect(screen.getByRole('link', { name: '影子验收' })).toHaveAttribute('href', '/shadow-acceptance')
})

it('opens and closes navigation on narrow layouts', async () => {
  renderShellAt('/runs')
  await userEvent.click(screen.getByRole('button', { name: '打开导航' }))
  expect(screen.getByRole('navigation', { name: '主导航' })).toHaveAttribute('data-open', 'true')
  await userEvent.click(screen.getByRole('button', { name: '关闭导航' }))
  expect(screen.getByRole('navigation', { name: '主导航' })).toHaveAttribute('data-open', 'false')
})
```

The helper must render `AppShell` with a child route so `Outlet` is exercised.

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `cd web; npm test -- src/layout/AppShell.test.tsx`

Expected: FAIL because `AppShell` and navigation modules do not exist.

- [ ] **Step 3: Define initial navigation without dead links**

Create `navigation.ts` with:

```ts
export type NavigationItem = {
  label: string
  to: string
  exact?: boolean
}

export const NAV_ITEMS: NavigationItem[] = [
  { label: '分析运行', to: '/runs' },
  { label: '定时任务', to: '/schedules' },
  { label: '影子验收', to: '/shadow-acceptance' },
]
```

Dashboard, review, and system entries are added only when their real pages arrive in later phases, so Phase 1 ships no dead navigation.

- [ ] **Step 4: Implement `AppShell`, `SidebarNav`, and `TopBar`**

`AppShell` owns mobile navigation state and renders:

```tsx
<div className="app-shell">
  <SidebarNav items={NAV_ITEMS} open={navOpen} onClose={() => setNavOpen(false)} />
  <div className="app-shell__body">
    <TopBar onOpenNavigation={() => setNavOpen(true)} />
    <main className="app-main" id="main-content"><Outlet /></main>
  </div>
</div>
```

`SidebarNav` uses semantic `<nav aria-label="主导航">`, `NavLink`, `aria-current`, and a visible close button. `TopBar` includes a mobile menu button, product context, and a skip link to `#main-content`; it must not invent live system status before Phase 2.

- [ ] **Step 5: Add responsive shell CSS**

At desktop widths, use a fixed-width left column and flexible content column. Below 900 px, turn the sidebar into an off-canvas panel with backdrop. At 390 px, page padding must reduce while buttons wrap and remain at least 40 px high. Preserve visible `:focus-visible` styles and respect `prefers-reduced-motion`.

- [ ] **Step 6: Run focused tests and production build**

Run:

```powershell
cd web
npm test -- src/layout/AppShell.test.tsx
npm run build
```

Expected: shell tests PASS and production build exits 0.

- [ ] **Step 7: Commit the application shell**

```powershell
git add web/src/layout web/src/styles.css
git commit -m "feat: add responsive operations shell"
```

### Task 3: Route Foundation And Current Page Migration

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/pages/RunListPage.tsx`
- Modify: `web/src/pages/SchedulePage.tsx`
- Modify: `web/src/pages/ShadowAcceptancePage.tsx`
- Modify: `web/src/pages/SchedulePage.test.tsx`
- Modify: `web/src/components/ShadowAcceptanceCard.test.tsx`
- Create: `web/src/App.test.tsx`

**Interfaces:**
- Consumes: `AppShell`, shared UI primitives, existing `fetchRuns`, `fetchSchedules`, `fetchShadowRuns`, `fetchShadowProgress`, `createDataRun`, and existing detail pages.
- Produces: `/runs` as the canonical list route, `/` redirect, consistent current-page layouts, and explicit paused shadow status.

- [ ] **Step 1: Write failing route and paused-state tests**

Add an `App.test.tsx` test using a memory history or exported route component that verifies visiting `/` resolves to the analysis-run page and that `/runs` renders inside the main navigation shell. Extend the shadow page test to require visible text `影子验收已暂停` while retaining the real `0/20` or API-supplied progress.

Use assertions equivalent to:

```tsx
expect(await screen.findByRole('heading', { name: '分析运行' })).toBeInTheDocument()
expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()
expect(screen.getByText('影子验收已暂停')).toBeInTheDocument()
```

- [ ] **Step 2: Run focused route/page tests and verify failure**

Run:

```powershell
cd web
npm test -- src/App.test.tsx src/pages/SchedulePage.test.tsx src/components/ShadowAcceptanceCard.test.tsx
```

Expected: FAIL because `/runs`, shell integration, and paused copy are absent.

- [ ] **Step 3: Integrate nested routing under `AppShell`**

Refactor `App.tsx` to use one layout route:

```tsx
<Route element={<AppShell />}>
  <Route index element={<Navigate to="/runs" replace />} />
  <Route path="/runs" element={<RunListPage />} />
  <Route path="/runs/:runId" element={<RunDetailPage />} />
  <Route path="/data-runs/:runId" element={<DataRunPage />} />
  <Route path="/schedules" element={<SchedulePage />} />
  <Route path="/task-runs/:runId" element={<TaskRunPage />} />
  <Route path="/shadow-acceptance" element={<ShadowAcceptancePage />} />
</Route>
```

Export a router-content component separately from `BrowserRouter` if tests need `MemoryRouter`; do not duplicate route definitions between production and tests.

- [ ] **Step 4: Migrate `RunListPage` to shared presentation components**

Use `PageHeader` with actions for盘中分析、盘后分析和新建运行; use shared button classes; render a semantic list or table panel; use `StatusBadge`; add loading and request error state instead of `catch(console.error)`; render `EmptyState` when the successful response is empty. Keep current creation API behavior unchanged.

- [ ] **Step 5: Migrate schedules and shadow acceptance pages**

`SchedulePage` must use `PageHeader`, `Panel`, loading/error/empty states, and semantic actions while retaining `triggerSchedule`. `ShadowAcceptancePage` must render an `InlineAlert` with title `影子验收已暂停`, explain that no new 20-day records are being pursued, and continue reading real existing progress and runs.

- [ ] **Step 6: Run all focused page and routing tests**

Run:

```powershell
cd web
npm test -- src/App.test.tsx src/pages/SchedulePage.test.tsx src/components/ShadowAcceptanceCard.test.tsx src/useRuns.test.tsx
```

Expected: all focused tests PASS.

- [ ] **Step 7: Commit route and page migration**

```powershell
git add web/src/App.tsx web/src/App.test.tsx web/src/pages/RunListPage.tsx web/src/pages/SchedulePage.tsx web/src/pages/ShadowAcceptancePage.tsx web/src/pages/SchedulePage.test.tsx web/src/components/ShadowAcceptanceCard.test.tsx
git commit -m "feat: migrate current pages into operations shell"
```

### Task 4: Phase 1 Regression And Browser Acceptance

**Files:**
- Modify: `docs/superpowers/plans/2026-08-23-modern-operations-frontend-master.md`
- Modify: `docs/superpowers/plans/2026-08-23-modern-operations-frontend-phase1.md`
- Create: `docs/superpowers/acceptance/2026-08-23-modern-operations-frontend-phase1.md`

**Interfaces:**
- Consumes: completed Phase 1 shell, primitives, routes, and page migrations.
- Produces: fresh automated and visual evidence required before Phase 2 planning.

- [ ] **Step 1: Run the complete frontend test suite**

Run: `cd web; npm test`

Expected: all Vitest files and tests PASS with no unexpected skips.

- [ ] **Step 2: Run the production build**

Run: `cd web; npm run build`

Expected: TypeScript and Vite build exit 0 and `web/dist/index.html` exists.

- [ ] **Step 3: Start the built application against the configured PostgreSQL runtime**

Run from the repository root: `.\.venv\Scripts\sector-pulse-web.exe`

Open `http://127.0.0.1:8000`. Confirm `/` redirects to `/runs`, all visible navigation links resolve, no browser console error appears, and the empty runtime database produces guided empty states rather than blank space.

- [ ] **Step 4: Verify responsive and keyboard behavior**

At 1440 px, 768 px, and 390 px widths, confirm sidebar behavior, wrapped actions, readable content, no horizontal page overflow, and no clipped modal. Using keyboard only, confirm skip link, navigation, page actions, dialog close, and visible focus.

- [ ] **Step 5: Record acceptance evidence**

Create the acceptance file with exact test totals, build result, checked routes, checked widths, known limitations, and screenshots if captured. Do not include secrets, `.env` values, or raw provider payloads.

- [ ] **Step 6: Check repository hygiene**

Run:

```powershell
git diff --check
git status --short
git check-ignore .env web/.npm-cache web/tsconfig.tsbuildinfo
```

Expected: no whitespace errors; local secrets/caches/build metadata remain ignored; only intentional Phase 1 files and pre-existing unrelated changes are present.

- [ ] **Step 7: Commit Phase 1 acceptance evidence**

```powershell
git add docs/superpowers/acceptance/2026-08-23-modern-operations-frontend-phase1.md docs/superpowers/plans/2026-08-23-modern-operations-frontend-master.md docs/superpowers/plans/2026-08-23-modern-operations-frontend-phase1.md
git commit -m "docs: record frontend phase 1 acceptance"
```

## Phase 1 Completion Gate

- Shared primitives replace repeated presentation concerns on current top-level pages.
- All current routes are reachable through `AppShell` and no navigation item points to an absent page.
- `/` redirects to `/runs` only as an explicit temporary boundary until Phase 2 provides the real dashboard.
- Shadow acceptance visibly states that it is paused while preserving real historical progress.
- Full frontend tests and production build pass with fresh evidence.
- Desktop and narrow-screen browser checks pass before Phase 2 planning begins.
