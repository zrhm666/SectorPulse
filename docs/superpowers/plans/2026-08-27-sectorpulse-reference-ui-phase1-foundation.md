# SectorPulse Reference UI Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变后端业务和现有路由的前提下，建立可渐进迁移的分层 CSS 基础、高保真统一应用外壳、完整路由上下文和经过桌面/移动端验证的导航体验。

**Architecture:** 保留当前 `web/src/styles.css` 作为迁移期 `legacy` 层，通过 `web/src/styles/index.css` 引入新的 token、base、shell、component 和 responsive 层；后续页面按阶段迁出 legacy。现有 `AppShell`、`SidebarNav`、`TopBar` 和 UI primitives 原位演进，新增纯函数 `resolveRouteContext()` 与统一 `Button`，避免重写已有页面和 API。

**Tech Stack:** React 18、React Router 6、TypeScript 5.6、CSS Cascade Layers、Vite 5、Vitest 4、Testing Library、Playwright

**Spec:** `docs/superpowers/specs/2026-08-27-sectorpulse-reference-ui-refactor-design.md`

## Global Constraints

- 本阶段不修改 FastAPI、PostgreSQL、API 响应、业务流程和数据库结构。
- 保留所有当前路由和 `NAV_ITEMS` 的真实菜单项，不增加搜索、通知、用户头像或系统就绪假状态。
- 保留当前 `web/src/styles.css`，只把它降为明确的 `legacy` 层；清理 legacy 留到 Phase 5。
- 新 CSS 使用 `--sp-*` 项目令牌，同时提供现有 `--ui-*` 与 `--color-*` 兼容别名。
- 侧边栏桌面宽度保持 224–236px，顶部栏高度 64–68px；侧边栏固定，只有 `.app-main` 承担页面级滚动。
- `<1024px` 使用抽屉导航；390×844 下不能产生页面级横向滚动。
- 不添加 Tailwind、UI 框架、图标依赖或运行时 CSS-in-JS。
- 所有新交互具备可访问名称、可见焦点和键盘路径；移动端触控目标至少 44px。
- 每个任务完成其定向测试、生产构建或浏览器验证后独立提交。
- 执行时使用 `executing-plans`、`test-driven-development`、`design-taste-frontend`、`impeccable`；提交完成声明前使用 `verification-before-completion`。

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `web/src/styles/index.css` | 唯一样式入口和 cascade layer 顺序 |
| `web/src/styles/tokens.css` | SectorPulse 颜色、字体、间距、圆角、阴影及兼容别名 |
| `web/src/styles/base.css` | 文档、字体、焦点、表单和 reduced-motion 基础规则 |
| `web/src/styles/shell.css` | 桌面应用外壳、品牌、导航、顶部栏和主滚动区 |
| `web/src/styles/components/primitives.css` | Button、PageHeader、Panel、状态和反馈组件视觉契约 |
| `web/src/styles/responsive.css` | 1024px、768px 和 390px 外壳/基础组件重排 |
| `web/src/layout/routeContext.ts` | 从 pathname 解析真实页面组和标题的纯函数 |
| `web/src/layout/routeContext.test.ts` | 全部现有路由上下文测试 |
| `web/src/components/ui/Button.tsx` | 统一按钮 variant、size、icon 和 loading 语义 |
| `web/src/components/ui/Button.test.tsx` | 按钮语义、禁用和加载测试 |
| `web/e2e/shell.spec.ts` | 固定侧栏、独立主滚动、抽屉和窄屏溢出验收 |
| `docs/superpowers/acceptance/2026-08-27-sectorpulse-reference-ui-phase1.md` | Phase 1 自动化与浏览器验收证据 |

### Modified files

| File | Responsibility |
|---|---|
| `web/src/main.tsx` | 从旧全局 CSS 切换到新的分层入口 |
| `web/src/layout/AppShell.tsx` | 管理抽屉状态、Escape、主内容和外壳语义 |
| `web/src/layout/SidebarNav.tsx` | 高保真品牌区、真实导航、抽屉焦点与遮罩 |
| `web/src/layout/TopBar.tsx` | 移动菜单、跳转链接和真实路由上下文 |
| `web/src/layout/AppShell.test.tsx` | 导航、上下文、焦点和键盘行为测试 |
| `web/src/components/ui/PageHeader.tsx` | 增加可选元信息区域且保持旧调用兼容 |
| `web/src/components/ui/UiPrimitives.test.tsx` | PageHeader 元信息与已有语义回归 |
| `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md` | 记录 Phase 1 实际退出证据 |

## Task 1: Add A Typed Route Context Contract

**Files:**

- Create: `web/src/layout/routeContext.ts`
- Create: `web/src/layout/routeContext.test.ts`

**Interfaces:**

- Consumes: browser pathname string, including nested detail routes.
- Produces: `RouteGroup`, `RouteContext`, and `resolveRouteContext(pathname: string): RouteContext`.

- [ ] **Step 1: Write the failing route-context test**

Create `web/src/layout/routeContext.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { resolveRouteContext } from './routeContext'

describe('resolveRouteContext', () => {
  it.each([
    ['/', { group: '运营', label: '运营总览' }],
    ['/runs', { group: '运营', label: '分析运行' }],
    ['/runs/new', { group: '运营', label: '新建分析' }],
    ['/runs/run-1', { group: '运营', label: '内容运行' }],
    ['/review', { group: '运营', label: '审核工作台' }],
    ['/data-runs/data-1', { group: '运营', label: '数据运行' }],
    ['/schedules', { group: '管理', label: '定时任务' }],
    ['/task-runs/task-1', { group: '管理', label: '任务运行' }],
    ['/system', { group: '管理', label: '系统状态' }],
    ['/shadow-acceptance', { group: '管理', label: '影子验收' }],
  ])('maps %s to its visible context', (pathname, expected) => {
    expect(resolveRouteContext(pathname)).toEqual(expected)
  })

  it('returns a safe product context for an unknown path', () => {
    expect(resolveRouteContext('/missing')).toEqual({ group: 'SectorPulse', label: '页面' })
  })
})
```

- [ ] **Step 2: Run the test and verify the missing-module failure**

Run:

```powershell
Set-Location web
npm.cmd test -- src/layout/routeContext.test.ts
```

Expected: FAIL because `./routeContext` does not exist.

- [ ] **Step 3: Implement the exact route mapping**

Create `web/src/layout/routeContext.ts`:

```ts
export type RouteGroup = '运营' | '管理' | 'SectorPulse'

export type RouteContext = {
  group: RouteGroup
  label: string
}

const EXACT_CONTEXTS: Record<string, RouteContext> = {
  '/': { group: '运营', label: '运营总览' },
  '/runs': { group: '运营', label: '分析运行' },
  '/runs/new': { group: '运营', label: '新建分析' },
  '/review': { group: '运营', label: '审核工作台' },
  '/schedules': { group: '管理', label: '定时任务' },
  '/system': { group: '管理', label: '系统状态' },
  '/shadow-acceptance': { group: '管理', label: '影子验收' },
}

export function resolveRouteContext(pathname: string): RouteContext {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  const exact = EXACT_CONTEXTS[normalized]
  if (exact) return exact
  if (/^\/data-runs\/[^/]+$/.test(normalized)) return { group: '运营', label: '数据运行' }
  if (/^\/runs\/[^/]+$/.test(normalized)) return { group: '运营', label: '内容运行' }
  if (/^\/task-runs\/[^/]+$/.test(normalized)) return { group: '管理', label: '任务运行' }
  return { group: 'SectorPulse', label: '页面' }
}
```

- [ ] **Step 4: Run the focused test**

Run: `npm.cmd test -- src/layout/routeContext.test.ts`

Expected: 11 cases PASS.

- [ ] **Step 5: Commit the route contract**

```powershell
Set-Location ..
git add web/src/layout/routeContext.ts web/src/layout/routeContext.test.ts
git commit -m "feat: add frontend route context contract"
```

## Task 2: Establish The Layered CSS Entry And Tokens

**Files:**

- Create: `web/src/styles/index.css`
- Create: `web/src/styles/tokens.css`
- Create: `web/src/styles/base.css`
- Modify: `web/src/main.tsx`
- Preserve unchanged: `web/src/styles.css`

**Interfaces:**

- Consumes: current selectors and `--ui-*`/`--color-*` variables from `web/src/styles.css`.
- Produces: one imported stylesheet entry and stable `--sp-*` tokens; legacy selectors continue rendering.

- [ ] **Step 1: Change the entry import before creating the new file**

In `web/src/main.tsx`, replace:

```ts
import './styles.css'
```

with:

```ts
import './styles/index.css'
```

- [ ] **Step 2: Run the build and verify the unresolved-import failure**

Run:

```powershell
Set-Location web
npm.cmd run build
```

Expected: FAIL because `src/styles/index.css` does not exist.

- [ ] **Step 3: Create the cascade-layer entry**

Create `web/src/styles/index.css`:

```css
@layer legacy, tokens, base, shell, components, responsive;

@import url("../styles.css") layer(legacy);
@import url("./tokens.css") layer(tokens);
@import url("./base.css") layer(base);
```

The later tasks append `shell.css`, `components/primitives.css`, and `responsive.css` imports in their named layers. Do not move or mechanically rewrite the legacy file in this phase.

- [ ] **Step 4: Create the project tokens and compatibility aliases**

Create `web/src/styles/tokens.css` with this contract:

```css
:root {
  --sp-bg: #f5f8fd;
  --sp-surface: #ffffff;
  --sp-surface-soft: #f8faff;
  --sp-surface-selected: #eaf2ff;
  --sp-text: #10213d;
  --sp-text-secondary: #455873;
  --sp-text-muted: #6f7f99;
  --sp-text-disabled: #9aa8bb;
  --sp-primary: #1768f2;
  --sp-primary-hover: #0e5de0;
  --sp-primary-active: #0b4fc1;
  --sp-primary-soft: #eaf2ff;
  --sp-focus: #8ab5ff;
  --sp-border: #dbe5f3;
  --sp-border-strong: #cbd9ed;
  --sp-border-soft: #edf2f8;
  --sp-success: #159a63;
  --sp-success-soft: #e7f7ef;
  --sp-warning: #d98200;
  --sp-warning-soft: #fff3dd;
  --sp-danger: #e34a58;
  --sp-danger-soft: #ffeaed;
  --sp-font-sans: Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  --sp-font-mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  --sp-radius-sm: 8px;
  --sp-radius-md: 10px;
  --sp-radius-lg: 16px;
  --sp-radius-xl: 20px;
  --sp-shadow-card: 0 10px 30px rgb(35 72 126 / 0.07);
  --sp-shadow-float: 0 18px 48px rgb(35 72 126 / 0.13);
  --sp-sidebar-width: 232px;
  --sp-topbar-height: 68px;

  --ui-bg-warm: var(--sp-bg);
  --ui-surface: var(--sp-surface);
  --ui-surface-subtle: var(--sp-surface-soft);
  --ui-primary: var(--sp-primary);
  --ui-primary-hover: var(--sp-primary-hover);
  --ui-primary-soft: var(--sp-primary-soft);
  --ui-text: var(--sp-text);
  --ui-text-secondary: var(--sp-text-secondary);
  --ui-text-muted: var(--sp-text-muted);
  --ui-border: var(--sp-border);
  --ui-border-strong: var(--sp-border-strong);
  --ui-success: var(--sp-success);
  --ui-warning: var(--sp-warning);
  --ui-danger: var(--sp-danger);
  --color-background: var(--sp-bg);
  --color-surface: var(--sp-surface);
  --color-surface-muted: var(--sp-surface-soft);
  --color-text: var(--sp-text);
  --color-muted-text: var(--sp-text-secondary);
  --color-primary: var(--sp-primary);
  --color-primary-strong: var(--sp-primary-hover);
  --color-border: var(--sp-border);
  --color-focus-ring: var(--sp-focus);
  --radius-sm: var(--sp-radius-sm);
  --radius-md: var(--sp-radius-md);
  --radius-lg: var(--sp-radius-lg);
  --radius-xl: var(--sp-radius-xl);
  --shadow-sm: var(--sp-shadow-card);
  --shadow-md: var(--sp-shadow-float);
  --sidebar-width: var(--sp-sidebar-width);
  --topbar-height: var(--sp-topbar-height);
}
```

- [ ] **Step 5: Create the base document rules**

Create `web/src/styles/base.css`:

```css
* { box-sizing: border-box; }

html { min-width: 320px; background: var(--sp-bg); }

body {
  min-width: 320px;
  margin: 0;
  overflow: hidden;
  color: var(--sp-text);
  background: var(--sp-bg);
  font-family: var(--sp-font-sans);
  font-size: 14px;
  line-height: 1.6;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
}

button, input, textarea, select { font: inherit; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; }
a { color: var(--sp-primary); }

:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--sp-focus) 60%, transparent);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 6: Run the current frontend suite and build**

Run:

```powershell
npm.cmd test
npm.cmd run build
```

Expected: all existing Vitest tests PASS and Vite build exits 0. Existing pages may still have their previous layout because shell/component layers are introduced in later tasks.

- [ ] **Step 7: Commit the layered foundation**

```powershell
Set-Location ..
git add web/src/main.tsx web/src/styles/index.css web/src/styles/tokens.css web/src/styles/base.css
git commit -m "refactor: add layered frontend style foundation"
```

## Task 3: Refine The Unified Shell And Route-Aware Top Bar

**Files:**

- Modify: `web/src/layout/AppShell.test.tsx`
- Modify: `web/src/layout/AppShell.tsx`
- Modify: `web/src/layout/SidebarNav.tsx`
- Modify: `web/src/layout/TopBar.tsx`
- Create: `web/src/styles/shell.css`
- Modify: `web/src/styles/index.css`

**Interfaces:**

- Consumes: `NAV_ITEMS`, `resolveRouteContext()`, React Router `Outlet` and `useLocation()`.
- Produces: a fixed desktop shell, a route-aware top bar, a focus-managed drawer, and unchanged nested route behavior.

- [ ] **Step 1: Extend shell tests with the new semantic contract**

Add routes for `/review` and `/data-runs/:runId` to `renderShellAt()`, then add these tests to `web/src/layout/AppShell.test.tsx`:

```tsx
it('renders the approved product identity and current route context', () => {
  renderShellAt('/runs')
  expect(screen.getByText('智能板块研判平台')).toBeInTheDocument()
  expect(screen.getByLabelText('当前位置')).toHaveTextContent('运营/分析运行')
})

it('maps detail routes without adding them to primary navigation', () => {
  renderShellAt('/data-runs/data-1')
  expect(screen.getByLabelText('当前位置')).toHaveTextContent('运营/数据运行')
  expect(screen.queryByRole('link', { name: '数据运行' })).not.toBeInTheDocument()
})

it('moves focus into the opened navigation and closes it with Escape', async () => {
  const user = userEvent.setup()
  renderShellAt('/runs')
  const menuButton = screen.getByRole('button', { name: '打开导航' })
  await user.click(menuButton)
  expect(screen.getByRole('button', { name: '关闭导航' })).toHaveFocus()
  await user.keyboard('{Escape}')
  expect(menuButton).toHaveAttribute('aria-expanded', 'false')
  expect(menuButton).toHaveFocus()
})
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```powershell
Set-Location web
npm.cmd test -- src/layout/AppShell.test.tsx src/layout/routeContext.test.ts
```

Expected: FAIL because the subtitle, breadcrumb and focus management are absent.

- [ ] **Step 3: Update `TopBar` to render the real route context**

Keep the existing props and implement this structure:

```tsx
import type { RefObject } from 'react'
import { useLocation } from 'react-router-dom'
import AppIcon from '../components/ui/AppIcon'
import { resolveRouteContext } from './routeContext'

export type TopBarProps = {
  navOpen: boolean
  onToggleNavigation: () => void
  menuButtonRef: RefObject<HTMLButtonElement>
}

export default function TopBar({ navOpen, onToggleNavigation, menuButtonRef }: TopBarProps) {
  const context = resolveRouteContext(useLocation().pathname)
  return (
    <header className="top-bar">
      <a className="skip-link" href="#main-content">跳到主内容</a>
      <button ref={menuButtonRef} className="top-bar__menu" type="button" onClick={onToggleNavigation} aria-label="打开导航" aria-expanded={navOpen} aria-controls="primary-navigation">
        <AppIcon name="menu" /><span>菜单</span>
      </button>
      <div className="top-bar__context" aria-label="当前位置">
        <strong>{context.group}</strong><span aria-hidden="true">/</span><span>{context.label}</span>
      </div>
    </header>
  )
}
```

Do not render readiness, notifications or account controls in Phase 1.

- [ ] **Step 4: Update `SidebarNav` identity and drawer focus**

Add `useEffect` and `useRef`, focus the close button when `open` becomes true, and render this brand structure above the current grouped links:

```tsx
<div className="sidebar-nav__header">
  <div className="sidebar-nav__brand">
    <span className="sidebar-nav__brand-mark"><AppIcon name="activity" size={28} /></span>
    <div>
      <p className="sidebar-nav__product">SectorPulse</p>
      <p className="sidebar-nav__context">智能板块研判平台</p>
    </div>
  </div>
  <button ref={closeButtonRef} className="sidebar-nav__close" type="button" onClick={onClose} aria-label="关闭导航">
    <AppIcon name="close" /><span>关闭</span>
  </button>
</div>
```

Retain the existing `运营` and `管理` groups and all six real links from `NAV_ITEMS`.

- [ ] **Step 5: Keep `AppShell` as the sole scroll owner and restore drawer focus**

Create `menuButtonRef` with `useRef<HTMLButtonElement>(null)`, pass it to `TopBar`, and track the previous `navOpen` value. When an open drawer becomes closed, focus `menuButtonRef.current`; this applies to Escape, close button, backdrop and navigation-link close paths. Retain the Escape listener and nested `Outlet`, add `data-navigation-open={navOpen}` to `.app-shell`, and keep this main contract unchanged:

```tsx
<FeedbackProvider>
  <main className="app-main" id="main-content" tabIndex={0}>
    <Outlet />
  </main>
</FeedbackProvider>
```

The main region remains keyboard reachable because it owns independent scrolling.

- [ ] **Step 6: Create desktop shell styles and import them**

Add this import to `web/src/styles/index.css` after `base.css`:

```css
@import url("./shell.css") layer(shell);
```

Create `web/src/styles/shell.css` with the desktop contract:

```css
.app-shell {
  display: grid;
  grid-template-columns: var(--sp-sidebar-width) minmax(0, 1fr);
  width: 100%;
  height: 100dvh;
  overflow: hidden;
}

.sidebar-nav {
  position: relative;
  width: var(--sp-sidebar-width);
  height: 100dvh;
  padding: 0 12px 20px;
  overflow: hidden;
  background: var(--sp-surface);
  border-right: 1px solid var(--sp-border);
}

.sidebar-nav nav { display: flex; height: 100%; flex-direction: column; }
.sidebar-nav__header { min-height: 88px; padding: 20px 10px 18px; }
.sidebar-nav__brand { display: flex; align-items: center; gap: 11px; }
.sidebar-nav__brand-mark { display: grid; width: 36px; height: 36px; place-items: center; color: var(--sp-primary); }
.sidebar-nav__product { margin: 0; color: var(--sp-primary); font-size: 18px; font-weight: 760; letter-spacing: -0.03em; }
.sidebar-nav__context { margin: 2px 0 0; color: var(--sp-text-muted); font-size: 11px; }
.sidebar-nav__links { display: grid; gap: 22px; }
.sidebar-nav__group h2 { margin: 0 10px 8px; color: var(--sp-text-muted); font-size: 11px; letter-spacing: 0.08em; }
.sidebar-nav__group-links { display: grid; gap: 4px; }
.sidebar-nav__link { min-height: 44px; padding: 0 12px; border-radius: 10px; }
.sidebar-nav__link--active { color: var(--sp-primary); background: var(--sp-primary-soft); box-shadow: inset 3px 0 0 var(--sp-primary); }
.sidebar-nav__close, .sidebar-nav__backdrop, .top-bar__menu { display: none; }

.app-shell__body { display: flex; min-width: 0; min-height: 0; flex-direction: column; overflow: hidden; }
.top-bar { z-index: 5; min-height: var(--sp-topbar-height); padding: 0 30px; background: rgb(255 255 255 / 0.94); border-bottom: 1px solid var(--sp-border); backdrop-filter: blur(12px); }
.top-bar__context { display: flex; align-items: center; gap: 9px; color: var(--sp-text-muted); font-size: 13px; }
.top-bar__context strong { color: var(--sp-text); }
.app-main { flex: 1 1 auto; width: 100%; min-height: 0; padding: 30px clamp(24px, 3vw, 40px) 48px; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
```

Keep selectors focused on shell ownership; page-specific card and table rules remain in legacy until their phases.

- [ ] **Step 7: Run shell tests and production build**

Run:

```powershell
npm.cmd test -- src/layout/AppShell.test.tsx src/layout/routeContext.test.ts
npm.cmd run build
```

Expected: focused tests PASS and build exits 0.

- [ ] **Step 8: Commit the unified shell**

```powershell
Set-Location ..
git add web/src/layout/AppShell.tsx web/src/layout/AppShell.test.tsx web/src/layout/SidebarNav.tsx web/src/layout/TopBar.tsx web/src/styles/index.css web/src/styles/shell.css
git commit -m "refactor: align the unified application shell"
```

## Task 4: Add A Unified Button And Page Header Metadata

**Files:**

- Create: `web/src/components/ui/Button.tsx`
- Create: `web/src/components/ui/Button.test.tsx`
- Modify: `web/src/components/ui/PageHeader.tsx`
- Modify: `web/src/components/ui/UiPrimitives.test.tsx`
- Modify: `web/src/layout/SidebarNav.tsx`
- Modify: `web/src/layout/TopBar.tsx`
- Create: `web/src/styles/components/primitives.css`
- Modify: `web/src/styles/index.css`

**Interfaces:**

- Consumes: native `ButtonHTMLAttributes`, optional `AppIconName`, existing PageHeader callers.
- Produces: `ButtonProps`, `Button`, and additive `PageHeaderProps.meta?: ReactNode` without breaking existing calls.

- [ ] **Step 1: Write failing Button and PageHeader tests**

Create `web/src/components/ui/Button.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import Button from './Button'

it('renders a primary action with an optional decorative icon', () => {
  render(<Button icon="plus">新建分析</Button>)
  const button = screen.getByRole('button', { name: '新建分析' })
  expect(button).toHaveAttribute('data-variant', 'primary')
  expect(button.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
})

it('disables a loading action and announces its state', () => {
  const onClick = vi.fn()
  render(<Button loading loadingLabel="正在保存" onClick={onClick}>保存</Button>)
  const button = screen.getByRole('button', { name: '正在保存' })
  expect(button).toBeDisabled()
  expect(button).toHaveAttribute('aria-busy', 'true')
})
```

Append this test to `web/src/components/ui/UiPrimitives.test.tsx`:

```tsx
it('renders optional page metadata before actions', () => {
  render(<PageHeader title="运营总览" meta={<span>最后更新 21:11</span>} actions={<button>刷新</button>} />)
  expect(screen.getByText('最后更新 21:11')).toBeInTheDocument()
  expect(screen.getByText('最后更新 21:11')).toHaveClass('page-header__meta')
})
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
Set-Location web
npm.cmd test -- src/components/ui/Button.test.tsx src/components/ui/UiPrimitives.test.tsx
```

Expected: FAIL because `Button` and `PageHeaderProps.meta` do not exist.

- [ ] **Step 3: Implement the Button contract**

Create `web/src/components/ui/Button.tsx`:

```tsx
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import AppIcon, { type AppIconName } from './AppIcon'

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'default' | 'compact'
  icon?: AppIconName
  loading?: boolean
  loadingLabel?: string
  children: ReactNode
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({
  variant = 'primary',
  size = 'default',
  icon,
  loading = false,
  loadingLabel = '处理中',
  className,
  disabled,
  children,
  ...buttonProps
}, ref) {
  return (
    <button
      {...buttonProps}
      ref={ref}
      className={['button', `button--${variant}`, `button--${size}`, className].filter(Boolean).join(' ')}
      data-variant={variant}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
    >
      {loading ? (
        <><span className="button__spinner" aria-hidden="true" /><span>{loadingLabel}</span></>
      ) : (
        <>{icon && <AppIcon name={icon} />}<span>{children}</span></>
      )}
    </button>
  )
})

export default Button
```

- [ ] **Step 4: Add PageHeader metadata without breaking existing props**

Extend `PageHeaderProps` with `meta?: ReactNode` and render the action side as:

```tsx
{(meta || actions) && (
  <div className="page-header__aside">
    {meta && <div className="page-header__meta">{meta}</div>}
    {actions && <div className="page-header__actions">{actions}</div>}
  </div>
)}
```

The existing title, description and eyebrow elements remain unchanged.

- [ ] **Step 5: Use Button for shell menu and close actions**

Replace the raw menu and close `<button>` elements with `Button` using `variant="secondary"`, `size="compact"`, existing class names, icons and accessible labels. Do not change their click handlers or ARIA relationships.

- [ ] **Step 6: Add primitive styles and import them**

Add this import to `web/src/styles/index.css` after `shell.css`:

```css
@import url("./components/primitives.css") layer(components);
```

Create `web/src/styles/components/primitives.css` with these contracts:

```css
.button {
  display: inline-flex;
  min-height: 42px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 16px;
  border: 1px solid transparent;
  border-radius: var(--sp-radius-md);
  font-weight: 680;
  line-height: 1;
  transition: color 160ms ease, background-color 160ms ease, border-color 160ms ease, transform 160ms ease;
}
.button--compact { min-height: 38px; padding-inline: 12px; font-size: 13px; }
.button--primary { color: #fff; background: var(--sp-primary); border-color: var(--sp-primary); box-shadow: 0 8px 20px rgb(23 104 242 / 0.18); }
.button--primary:hover { background: var(--sp-primary-hover); }
.button--secondary { color: var(--sp-text-secondary); background: var(--sp-surface); border-color: var(--sp-border-strong); }
.button--ghost { color: var(--sp-primary); background: transparent; }
.button--danger { color: #fff; background: var(--sp-danger); border-color: var(--sp-danger); }
.button:active:not(:disabled) { transform: translateY(1px); }
.button:disabled { color: var(--sp-text-disabled); background: var(--sp-surface-soft); border-color: var(--sp-border); box-shadow: none; }
.button__spinner { width: 15px; height: 15px; border: 2px solid currentcolor; border-right-color: transparent; border-radius: 50%; animation: loading-spin 700ms linear infinite; }

.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.page-header__title { margin: 0; color: var(--sp-text); font-size: clamp(28px, 3vw, 32px); line-height: 1.2; letter-spacing: -0.035em; }
.page-header__description { max-width: 65ch; margin: 8px 0 0; color: var(--sp-text-muted); }
.page-header__aside { display: flex; align-items: center; justify-content: flex-end; gap: 10px; }
.page-header__meta { color: var(--sp-text-muted); font-size: 12px; white-space: nowrap; }
.page-header__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }

.panel { border-color: var(--sp-border); border-radius: var(--sp-radius-lg); background: var(--sp-surface); }
.status-badge { min-height: 24px; font-size: 12px; }
.inline-alert { border-radius: var(--sp-radius-md); }
.empty-state { border-radius: var(--sp-radius-lg); }
```

Keep the existing `@keyframes loading-spin` from legacy available through the layer order; do not duplicate it.

- [ ] **Step 7: Run component, shell and build verification**

Run:

```powershell
npm.cmd test -- src/components/ui/Button.test.tsx src/components/ui/UiPrimitives.test.tsx src/layout/AppShell.test.tsx
npm.cmd run build
```

Expected: all focused tests PASS and build exits 0.

- [ ] **Step 8: Commit primitive contracts**

```powershell
Set-Location ..
git add web/src/components/ui/Button.tsx web/src/components/ui/Button.test.tsx web/src/components/ui/PageHeader.tsx web/src/components/ui/UiPrimitives.test.tsx web/src/layout/SidebarNav.tsx web/src/layout/TopBar.tsx web/src/styles/index.css web/src/styles/components/primitives.css
git commit -m "feat: add reference ui action primitives"
```

## Task 5: Enforce Responsive Shell Behavior With Playwright

**Files:**

- Create: `web/e2e/shell.spec.ts`
- Create: `web/src/styles/responsive.css`
- Modify: `web/src/styles/index.css`
- Modify: `web/src/styles/shell.css`

**Interfaces:**

- Consumes: built SPA, `.app-shell`, `.sidebar-nav`, `.app-main`, mobile menu and backdrop contracts.
- Produces: executable desktop and responsive shell acceptance at 1536, 960 and 390 widths.

- [ ] **Step 1: Write the failing browser contract**

Create `web/e2e/shell.spec.ts`:

```ts
import { expect, test } from '@playwright/test'

test('desktop sidebar stays still while the main region scrolls', async ({ page }) => {
  await page.setViewportSize({ width: 1536, height: 1024 })
  await page.goto('/')
  const sidebar = page.locator('.sidebar-nav')
  const main = page.locator('.app-main')
  await expect(sidebar).toBeVisible()
  const before = await sidebar.boundingBox()
  await main.evaluate((element) => {
    const spacer = document.createElement('div')
    spacer.style.height = '1800px'
    element.append(spacer)
    element.scrollTop = 600
  })
  await expect.poll(() => main.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
  const after = await sidebar.boundingBox()
  expect(after?.y).toBe(before?.y)
  expect(await page.locator('body').evaluate((body) => getComputedStyle(body).overflow)).toBe('hidden')
})

test('navigation becomes a keyboard-dismissible drawer below 1024px', async ({ page }) => {
  await page.setViewportSize({ width: 960, height: 800 })
  await page.goto('/runs')
  const menu = page.getByRole('button', { name: '打开导航' })
  await expect(menu).toBeVisible()
  await menu.click()
  await expect(page.getByRole('navigation', { name: '主导航' })).toHaveAttribute('data-open', 'true')
  await expect(page.getByRole('button', { name: '关闭导航' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('navigation', { name: '主导航' })).toHaveAttribute('data-open', 'false')
})

test('shell has no page-level horizontal overflow at 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.getByRole('button', { name: '打开导航' })).toBeVisible()
})
```

- [ ] **Step 2: Build and run the new Playwright file**

Run:

```powershell
Set-Location web
npm.cmd run build
npm.cmd run test:e2e -- e2e/shell.spec.ts
```

Expected before responsive implementation: the 960px menu visibility check fails because the current legacy breakpoint is 900px.

- [ ] **Step 3: Import the responsive layer**

Add this final import to `web/src/styles/index.css`:

```css
@import url("./responsive.css") layer(responsive);
```

- [ ] **Step 4: Implement the approved breakpoints**

Create `web/src/styles/responsive.css`:

```css
@media (max-width: 1279px) {
  :root { --sp-sidebar-width: 224px; }
  .app-main { padding-inline: 24px; }
}

@media (max-width: 1023px) {
  .app-shell { display: block; }
  .sidebar-nav {
    position: fixed;
    z-index: 30;
    inset: 0 auto 0 0;
    width: min(320px, calc(100vw - 48px));
    padding-top: 0;
    box-shadow: var(--sp-shadow-float);
    transform: translateX(-105%);
    transition: transform 180ms ease-out;
  }
  .sidebar-nav[data-open="true"] { transform: translateX(0); }
  .sidebar-nav__header { display: flex; align-items: center; justify-content: space-between; }
  .sidebar-nav__close, .top-bar__menu { display: inline-flex; min-width: 44px; min-height: 44px; }
  .sidebar-nav__backdrop[data-open="true"] {
    position: fixed;
    z-index: 20;
    inset: 0;
    display: block;
    width: 100%;
    height: 100%;
    padding: 0;
    background: rgb(16 33 61 / 0.34);
    border: 0;
  }
  .top-bar { padding-inline: 20px; }
  .top-bar__menu { margin-right: 12px; }
  .app-main { padding: 24px 20px 40px; }
}

@media (max-width: 767px) {
  .page-header { flex-direction: column; }
  .page-header__aside { width: 100%; align-items: flex-start; flex-direction: column; }
  .page-header__actions { width: 100%; justify-content: flex-start; }
}

@media (max-width: 390px) {
  .top-bar { padding-inline: 12px; }
  .top-bar__context { min-width: 0; font-size: 12px; }
  .app-main { padding: 20px 12px 32px; }
  .page-header__actions > .button { flex: 1 1 auto; min-height: 44px; }
}
```

If the Playwright test reveals a legacy selector with higher specificity, add the narrowest override to `responsive.css`; do not edit page-specific legacy layout in Phase 1.

- [ ] **Step 5: Run unit, build and browser checks**

Run:

```powershell
npm.cmd test -- src/layout/AppShell.test.tsx src/components/ui/Button.test.tsx src/components/ui/UiPrimitives.test.tsx
npm.cmd run build
npm.cmd run test:e2e -- e2e/shell.spec.ts
```

Expected: focused Vitest tests PASS, build exits 0, and all three shell Playwright tests PASS.

- [ ] **Step 6: Commit responsive shell enforcement**

```powershell
Set-Location ..
git add web/e2e/shell.spec.ts web/src/styles/index.css web/src/styles/shell.css web/src/styles/responsive.css
git commit -m "test: enforce responsive application shell"
```

## Task 6: Complete Phase 1 Regression And Browser Acceptance

**Files:**

- Create: `docs/superpowers/acceptance/2026-08-27-sectorpulse-reference-ui-phase1.md`
- Modify: `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md`
- Modify: `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-phase1-foundation.md`

**Interfaces:**

- Consumes: all Phase 1 commits and current configured local frontend/backend runtime.
- Produces: fresh automated and visual evidence; Phase 2 may consume only the verified shell, token and component contracts.

- [ ] **Step 1: Run the complete frontend unit suite**

Run:

```powershell
Set-Location web
npm.cmd test
```

Expected: every Vitest file passes with no unexpected skipped test. Record the actual file and test totals.

- [ ] **Step 2: Run the production build**

Run:

```powershell
npm.cmd run build
```

Expected: TypeScript and Vite exit 0; `web/dist/index.html` exists.

- [ ] **Step 3: Run all Playwright tests**

Run:

```powershell
npm.cmd run test:e2e
```

Expected: existing smoke test and new shell tests pass.

- [ ] **Step 4: Run backend non-live regression because the built frontend is served by FastAPI**

Run from repository root:

```powershell
Set-Location ..
.\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider -m "not live"
```

Expected: all collected non-live backend tests pass. Do not run quota-consuming live data or LLM tests in Phase 1.

- [ ] **Step 5: Perform browser visual acceptance with the approved frontend skills**

Use `browser:control-in-app-browser` to inspect the actual built application. Use `design-taste-frontend` for visual hierarchy review and `impeccable` for responsive, accessibility and interaction review.

Check these routes:

```text
/
/runs
/review
/data-runs/<an existing real run id when available>
/schedules
/system
/shadow-acceptance
```

At 1536×1024 confirm sidebar width, topbar height, brand hierarchy, active navigation, independent main scroll and no duplicated product header. At 1024×768 and 390×844 confirm drawer focus, Escape close, backdrop close, 44px controls, no clipped action and no page-level horizontal overflow.

- [ ] **Step 6: Record actual evidence**

Create `docs/superpowers/acceptance/2026-08-27-sectorpulse-reference-ui-phase1.md` containing:

```markdown
# SectorPulse Reference UI Phase 1 Acceptance

## Scope

- Layered CSS entry and compatibility boundary
- Unified sidebar and route-aware topbar
- Button and PageHeader contracts
- Desktop and responsive shell behavior

## Automated Verification

Record each exact command, exit status, and observed test total from Steps 1–4.

## Browser Verification

Record each inspected route and viewport, the shell behavior observed, console errors, and screenshots captured.

## Data And Security

Confirm that no fake readiness state, fake metric, API key, database password, connection URL, prompt, or raw model response was introduced.

## Remaining Scope

State that dashboard content redesign and new aggregation fields belong to Phase 2; data and review workspaces remain Phase 3 and Phase 4.
```

Write observed values, not predicted totals.

- [ ] **Step 7: Update plan tracking from evidence only**

Mark completed checkboxes in this Phase 1 plan and the Phase 1 section of the master plan only when their corresponding test or browser evidence exists. Do not mark Phase 2 work complete.

- [ ] **Step 8: Check repository hygiene**

Run:

```powershell
git diff --check
git status --short
git check-ignore .env web/node_modules web/dist web/tsconfig.tsbuildinfo
```

Expected: no whitespace errors; secrets, dependencies and generated build outputs are ignored; only the Phase 1 acceptance and plan tracking files remain uncommitted.

- [ ] **Step 9: Commit Phase 1 acceptance**

```powershell
git add docs/superpowers/acceptance/2026-08-27-sectorpulse-reference-ui-phase1.md docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-refactor-master.md docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-phase1-foundation.md
git commit -m "docs: record reference ui phase 1 acceptance"
```

## Phase 1 Completion Gate

- The new layered stylesheet is the only import from `main.tsx`; legacy styles remain isolated and functional.
- All current routes resolve to a truthful group/label context without adding detail routes to primary navigation.
- The unified sidebar displays the approved identity and six real navigation entries.
- The sidebar remains stationary while `.app-main` scrolls independently.
- The drawer activates below 1024px, receives focus, closes via Escape and backdrop, and does not create horizontal overflow at 390px.
- Button and PageHeader additive contracts are tested and do not break existing callers.
- Full Vitest, Vite build, Playwright and backend non-live regression pass with fresh evidence.
- Browser checks pass at 1536×1024, 1024×768 and 390×844 before Phase 2 planning begins.
