# SectorPulse Soft Blue UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SectorPulse 全站重构为暖白、浅蓝、细描边圆角的现代运营后台，同时保留数据密集页面的工作效率和全部现有业务行为。

**Architecture:** 先生成三张代表性页面视觉参考，再以全局设计令牌和少量可复用 UI 组件作为稳定边界。应用外壳和页面按“运营页面—数据工作台—审核与管理”分批迁移；业务请求、路由和后端接口保持不变，视觉变化集中在 React 展示组件与 `web/src/styles.css`。

**Tech Stack:** React 18、TypeScript 5、Vite 5、React Router 6、Vitest、Testing Library、原生 CSS、FastAPI 静态托管

**Spec:** `docs/superpowers/specs/2026-08-26-sectorpulse-soft-blue-ui-redesign-design.md`

**Reusable Style Guide:** `docs/design/soft-blue-operations-ui-system.md`

## Global Constraints

- 采用暖白背景、清透蓝色、细蓝灰描边、16–20px 圆角和极轻阴影。
- 不使用卡通人物、花朵、云朵、Emoji、玻璃拟态或无意义渐变。
- 总览与新建流程使用 `comfortable` 密度；表格、新闻、详情和审核使用 `compact` 密度。
- 成功、警告、失败和中立状态分别保留绿、琥珀、红和蓝灰语义，不全部改成蓝色。
- 不改变现有路由、API 路径、请求时序、轮询、筛选、分页、审核、治理和调度行为。
- 不增加暗色主题，不引入在线字体，不依赖网络加载视觉资产。
- 桌面交互目标不小于 40×40px，窄屏不小于 44×44px。
- 所有交互元素必须有可见焦点；状态不得只依靠颜色表达。
- 实施使用测试先行；视觉样式通过桌面和窄屏截图验收。
- `web/dist` 是本机构建产物且被 Git 忽略，不纳入提交。

---

## File Structure Map

### New files

- `web/src/components/ui/AppIcon.tsx`：项目内唯一线性图标入口，控制尺寸、描边和可访问语义。
- `web/src/components/ui/AppIcon.test.tsx`：图标尺寸、隐藏语义和可访问标题测试。
- `web/src/components/ui/MetricCard.tsx`：运营总览指标卡。
- `web/src/components/ui/SummaryStrip.tsx`：详情页连续摘要带。
- `web/src/components/ui/DashboardComponents.test.tsx`：指标卡与摘要带语义测试。
- `docs/design/references/sectorpulse-soft-blue-dashboard.png`：运营总览视觉参考。
- `docs/design/references/sectorpulse-soft-blue-data-workbench.png`：数据工作台视觉参考。
- `docs/design/references/sectorpulse-soft-blue-review-workspace.png`：审核工作台视觉参考。

### Shared files to modify

- `web/src/styles.css`：令牌、布局、组件、页面、响应式和减少动态规则。
- `web/src/layout/AppShell.tsx`：应用外壳语义和移动导航状态。
- `web/src/layout/SidebarNav.tsx`：分组导航、图标和选中状态。
- `web/src/layout/TopBar.tsx`：轻量顶部栏和移动导航按钮。
- `web/src/layout/navigation.ts`：带分组和图标名称的导航数据模型。
- `web/src/layout/AppShell.test.tsx`：导航、移动展开和当前页面语义。
- `web/src/components/ui/PageHeader.tsx`：标题密度和操作区边界。
- `web/src/components/ui/Panel.tsx`：面板密度属性。
- `web/src/components/ui/StatusBadge.tsx`：状态图标和中文标签结构。
- `web/src/components/ui/InlineAlert.tsx`：错误、警告和提示图标结构。
- `web/src/components/ui/EmptyState.tsx`：清晰的空状态结构。
- `web/src/components/ui/LoadingState.tsx`：稳定加载骨架。
- `web/src/components/ui/ConfirmDialog.tsx`：新视觉和既有焦点行为。
- `web/src/components/ui/UiPrimitives.test.tsx`：通用组件行为测试。

### Page files to modify

- `web/src/pages/OperationsDashboardPage.tsx`
- `web/src/pages/OperationsDashboardPage.test.tsx`
- `web/src/pages/RunListPage.tsx`
- `web/src/pages/RunListPage.test.tsx`
- `web/src/pages/NewAnalysisPage.tsx`
- `web/src/pages/NewAnalysisPage.test.tsx`
- `web/src/pages/DataRunPage.tsx`
- `web/src/pages/DataRunPage.test.tsx`
- `web/src/pages/data-run/AcquisitionSummary.tsx`
- `web/src/pages/data-run/DataRunTimeline.tsx`
- `web/src/pages/data-run/DataRunActionPanel.tsx`
- `web/src/pages/data-run/MarketPanel.tsx`
- `web/src/pages/data-run/CandidatesPanel.tsx`
- `web/src/pages/data-run/NewsRecordsPanel.tsx`
- `web/src/pages/data-run/EvidencePanel.tsx`
- `web/src/pages/data-run/QualityPanel.tsx`
- `web/src/pages/RunDetailPage.tsx`
- `web/src/pages/RunDetailPage.test.tsx`
- `web/src/pages/tabs/OverviewTab.tsx`
- `web/src/pages/tabs/RadarTab.tsx`
- `web/src/pages/tabs/EvidenceTab.tsx`
- `web/src/pages/tabs/DraftTab.tsx`
- `web/src/pages/tabs/ReviewTab.tsx`
- `web/src/pages/tabs/GovernanceTab.tsx`
- `web/src/pages/ReviewWorkspacePage.tsx`
- `web/src/pages/ReviewWorkspacePage.test.tsx`
- `web/src/components/review/ReviewQueue.tsx`
- `web/src/components/review/DraftWorkspace.tsx`
- `web/src/components/review/EvidenceDecisionPane.tsx`
- `web/src/pages/SchedulePage.tsx`
- `web/src/pages/SchedulePage.test.tsx`
- `web/src/pages/SystemStatusPage.tsx`
- `web/src/pages/SystemStatusPage.test.tsx`
- `web/src/pages/ShadowAcceptancePage.tsx`
- `web/src/components/ShadowAcceptanceCard.tsx`
- `web/src/pages/TaskRunPage.tsx`
- `web/src/pages/TaskRunPage.test.tsx`

---

### Task 1: Generate and lock the visual reference set

**Files:**
- Create: `docs/design/references/sectorpulse-soft-blue-dashboard.png`
- Create: `docs/design/references/sectorpulse-soft-blue-data-workbench.png`
- Create: `docs/design/references/sectorpulse-soft-blue-review-workspace.png`
- Read: `docs/design/soft-blue-operations-ui-system.md`
- Read: `docs/superpowers/specs/2026-08-26-sectorpulse-soft-blue-ui-redesign-design.md`

**Interfaces:**
- Consumes: 用户参考图和两份已确认设计文档。
- Produces: 三张 16:10、1440×900 级别的实现参考图，分别锁定舒展、紧凑和三栏三种页面密度。

- [ ] **Step 1: Capture the current baseline**

启动现有前后端，在 1440×900 视口截取 `/`、一个真实 `/data-runs/:runId` 和 `/review`。基线只用于对照，不提交用户数据截图。

- [ ] **Step 2: Generate the dashboard reference**

使用 `image-to-code` 与 `imagegen`，生成单独的运营总览图。提示词必须包含：

```text
Design a desktop operations dashboard for SectorPulse, an A-share sector analysis assistant.
Use a warm off-white background, crisp white surfaces, fine blue-gray borders,
18px rounded cards, restrained soft shadows, vivid but controlled blue accents,
black editorial headings, muted blue-gray body text, and one consistent set of outline icons.
The layout has a professional left sidebar, a calm top bar, one primary operations overview,
a 2x2 metric-card group, recent analysis runs, and system readiness checks.
Use generous spacing on the overview but no mascot, flowers, clouds, cartoon decoration,
glassmorphism, gradients, or marketing-style hero content. Chinese UI copy, 16:10 canvas.
```

- [ ] **Step 3: Generate the data workbench reference**

```text
Design a compact desktop data-run workbench for SectorPulse using the same warm white and soft blue system.
Include a page title and action, a six-cell summary strip, a five-step horizontal progress timeline,
an acquisition summary, tabs for market sectors, candidates, news records, evidence, and quality,
and a dense but readable market table. Preserve professional financial-data density.
Use fine borders, 16-18px radii, outline icons, semantic status colors, no mascot or decorative illustration.
Chinese UI copy, 16:10 canvas, all key content visible without oversized whitespace.
```

- [ ] **Step 4: Generate the review workspace reference**

```text
Design a three-column content review workspace for SectorPulse in the same soft blue operations UI.
Left column: review queue. Center: readable editable analysis draft. Right: evidence, governance status,
approval and return actions. Warm off-white page, white bordered surfaces, restrained blue accents,
compact professional density, clear keyboard focus states, no mascot, no illustration, no gradients.
Chinese UI copy, 16:10 canvas, center reading area is visually dominant.
```

- [ ] **Step 5: Inspect the references against the spec**

逐张检查以下项目并仅重生成不合格的图：

```text
[ ] 暖白背景而非冷灰背景
[ ] 单一蓝色交互主色
[ ] 无卡通或花草装饰
[ ] 卡片边框比阴影更明显
[ ] 总览舒展、工作台紧凑、审核中栏最宽
[ ] 中文字号在普通笔记本上可读
[ ] 没有三层卡片嵌套
```

- [ ] **Step 6: Commit the visual references**

```powershell
git add docs/design/references
git commit -m "docs: add soft blue ui visual references"
```

---

### Task 2: Establish design tokens, icons, and density primitives

**Files:**
- Create: `web/src/components/ui/AppIcon.tsx`
- Create: `web/src/components/ui/AppIcon.test.tsx`
- Create: `web/src/components/ui/MetricCard.tsx`
- Create: `web/src/components/ui/SummaryStrip.tsx`
- Create: `web/src/components/ui/DashboardComponents.test.tsx`
- Modify: `web/src/styles.css:1-120`

**Interfaces:**
- Consumes: no application data.
- Produces: `AppIcon`, `MetricCard`, `SummaryStrip`, global design tokens, `.density-comfortable`, and `.density-compact`.

- [ ] **Step 1: Write failing tests for the new primitives**

```tsx
import { render, screen } from '@testing-library/react'
import AppIcon from './AppIcon'
import MetricCard from './MetricCard'
import SummaryStrip from './SummaryStrip'

it('keeps decorative icons out of the accessibility tree', () => {
  const { container } = render(<AppIcon name="home" />)
  expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
})

it('gives standalone icons an accessible title', () => {
  render(<AppIcon name="refresh" label="刷新" />)
  expect(screen.getByRole('img', { name: '刷新' })).toBeInTheDocument()
})

it('renders one metric with label value and supporting text', () => {
  render(<MetricCard icon="activity" label="今日运行" value="12" description="2 项待处理" />)
  expect(screen.getByRole('article', { name: '今日运行' })).toHaveTextContent('12')
})

it('renders summary items as one named region', () => {
  render(<SummaryStrip label="运行摘要" items={[{ label: '状态', value: '已完成' }]} />)
  expect(screen.getByRole('region', { name: '运行摘要' })).toHaveTextContent('已完成')
})
```

- [ ] **Step 2: Run the tests to verify RED**

Run:

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/components/ui/AppIcon.test.tsx src/components/ui/DashboardComponents.test.tsx
```

Expected: FAIL because the three components do not exist.

- [ ] **Step 3: Implement `AppIcon`**

Use one local SVG component and an explicit icon-name union:

```tsx
export type AppIconName =
  | 'home' | 'runs' | 'review' | 'calendar' | 'system' | 'shield'
  | 'activity' | 'check' | 'clock' | 'folder' | 'refresh' | 'plus'
  | 'arrow-left' | 'arrow-right' | 'menu' | 'close' | 'warning'

export default function AppIcon({ name, size = 20, label }: {
  name: AppIconName
  size?: number
  label?: string
}) {
  return (
    <svg
      className="app-icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? 'img' : undefined}
      aria-hidden={label ? undefined : true}
    >
      {label && <title>{label}</title>}
      {ICON_PATHS[name]}
    </svg>
  )
}
```

`ICON_PATHS` must contain local `<path>`, `<circle>`, `<rect>` or `<polyline>` elements for every union member. Do not add a second icon source.

- [ ] **Step 4: Implement `MetricCard` and `SummaryStrip`**

```tsx
export default function MetricCard(props: {
  icon: AppIconName
  label: string
  value: React.ReactNode
  description: React.ReactNode
  progress?: number
  tone?: 'default' | 'success' | 'warning' | 'danger'
}) {
  const progress = props.progress == null ? null : Math.min(100, Math.max(0, props.progress))
  return (
    <article className="metric-card" data-tone={props.tone ?? 'default'} aria-label={props.label}>
      <span className="metric-card__icon" aria-hidden="true"><AppIcon name={props.icon} /></span>
      <span className="metric-card__label">{props.label}</span>
      <strong className="metric-card__value">{props.value}</strong>
      <span className="metric-card__description">{props.description}</span>
      {progress != null && <progress value={progress} max={100} aria-label={`${props.label}进度`} />}
    </article>
  )
}

export default function SummaryStrip(props: {
  label: string
  items: Array<{ label: string; value: React.ReactNode }>
  className?: string
}) {
  return (
    <section className={`summary-strip ${props.className ?? ''}`} aria-label={props.label}>
      {props.items.map((item) => (
        <div className="summary-strip__item" key={item.label}>
          <span className="summary-strip__label">{item.label}</span>
          <strong className="summary-strip__value">{item.value}</strong>
        </div>
      ))}
    </section>
  )
}
```

Clamp `progress` to 0–100 and render a native progress element only when supplied.

- [ ] **Step 5: Replace the global token block**

Implement the exact color, typography, spacing, radius and shadow tokens from `docs/design/soft-blue-operations-ui-system.md`. Add:

```css
.density-comfortable { --content-gap: 24px; --panel-padding: 24px; }
.density-compact { --content-gap: 16px; --panel-padding: 18px; }
```

Keep compatibility aliases for existing names such as `--color-primary` during migration so intermediate commits remain usable.

- [ ] **Step 6: Run focused tests and build**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/components/ui/AppIcon.test.tsx src/components/ui/DashboardComponents.test.tsx
D:\software\nodejs\npm.cmd run build
```

Expected: all focused tests PASS and Vite production build exits 0.

- [ ] **Step 7: Commit**

```powershell
git add web/src/components/ui web/src/styles.css
git commit -m "feat: establish soft blue ui primitives"
```

---

### Task 3: Redesign the application shell and navigation

**Files:**
- Modify: `web/src/layout/AppShell.tsx`
- Modify: `web/src/layout/SidebarNav.tsx`
- Modify: `web/src/layout/TopBar.tsx`
- Modify: `web/src/layout/navigation.ts`
- Modify: `web/src/layout/AppShell.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `AppIcon`, global tokens.
- Produces: responsive shell with `aria-expanded` mobile navigation and grouped navigation items.

- [ ] **Step 1: Write failing shell tests**

```tsx
it('renders grouped navigation with consistent icons', () => {
  renderShellAt('/runs')
  expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /分析运行/ })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('link', { name: /审核工作台/ })).toBeInTheDocument()
})

it('opens and closes navigation from the mobile menu button', async () => {
  const user = userEvent.setup()
  renderShellAt('/')
  const button = screen.getByRole('button', { name: '打开导航' })
  await user.click(button)
  expect(button).toHaveAttribute('aria-expanded', 'true')
  await user.click(screen.getByRole('button', { name: '关闭导航' }))
  expect(button).toHaveAttribute('aria-expanded', 'false')
})
```

- [ ] **Step 2: Run the shell tests to verify RED**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/layout/AppShell.test.tsx
```

Expected: FAIL because current shell has no mobile toggle and icon-aware grouped navigation.

- [ ] **Step 3: Implement the shell state and semantic structure**

`AppShell` owns `navOpen: boolean`; `TopBar` receives `navOpen` and `onToggleNav`; `SidebarNav` receives `open` and `onNavigate`. Close the mobile navigation after route selection and on Escape.

Navigation groups:

```ts
const NAV_GROUPS = [
  { label: '运营', items: [
    { to: '/', label: '运营总览', icon: 'home' },
    { to: '/runs', label: '分析运行', icon: 'runs' },
    { to: '/review', label: '审核工作台', icon: 'review' },
  ]},
  { label: '管理', items: [
    { to: '/schedules', label: '定时任务', icon: 'calendar' },
    { to: '/system', label: '系统状态', icon: 'system' },
    { to: '/shadow-acceptance', label: '影子验收', icon: 'shield' },
  ]},
] satisfies Array<{ label: string; items: Array<{ to: string; label: string; icon: AppIconName }> }>
```

- [ ] **Step 4: Implement shell styling**

Add desktop fixed-width sidebar, light top bar, centered content container, mobile overlay, visible focus rings, active navigation pill and reduced-motion behavior. At `< 960px`, hide the sidebar off-canvas until toggled.

- [ ] **Step 5: Run shell and application tests**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/layout/AppShell.test.tsx src/App.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add web/src/layout web/src/styles.css
git commit -m "feat: redesign operations app shell"
```

---

### Task 4: Migrate shared panels, feedback, forms, and status components

**Files:**
- Modify: `web/src/components/ui/PageHeader.tsx`
- Modify: `web/src/components/ui/Panel.tsx`
- Modify: `web/src/components/ui/StatusBadge.tsx`
- Modify: `web/src/components/ui/InlineAlert.tsx`
- Modify: `web/src/components/ui/EmptyState.tsx`
- Modify: `web/src/components/ui/LoadingState.tsx`
- Modify: `web/src/components/ui/ConfirmDialog.tsx`
- Modify: `web/src/components/ui/UiPrimitives.test.tsx`
- Modify: `web/src/components/ui/ConfirmDialog.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `AppIcon`, token system.
- Produces: `Panel density?: 'comfortable' | 'compact'`, icon-aware alerts and badges, consistent form and button classes.

- [ ] **Step 1: Write failing primitive tests**

```tsx
it('applies compact density without changing panel semantics', () => {
  render(<Panel title="新闻记录" density="compact">内容</Panel>)
  expect(screen.getByRole('region', { name: '新闻记录' })).toHaveClass('panel--compact')
})

it('renders a textual status together with its visual indicator', () => {
  render(<StatusBadge status="FAILED" />)
  expect(screen.getByText('失败')).toBeInTheDocument()
  expect(screen.getByText('失败').closest('.status-badge')).toHaveAttribute('data-tone', 'danger')
})

it('keeps alert title and recovery content in one alert region', () => {
  render(<InlineAlert tone="error" title="加载失败"><button>重新加载</button></InlineAlert>)
  expect(screen.getByRole('alert')).toHaveTextContent('加载失败')
  expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run primitive tests to verify RED**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/components/ui/UiPrimitives.test.tsx src/components/ui/ConfirmDialog.test.tsx
```

Expected: FAIL on the missing `density` property and new status structure.

- [ ] **Step 3: Implement component APIs**

Update `Panel`:

```tsx
export default function Panel({ title, description, actions, children, className, density = 'comfortable' }: {
  title?: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
  density?: 'comfortable' | 'compact'
})
```

Use `AppIcon` inside `InlineAlert`, loading and empty states only when the icon adds meaning. Preserve all existing roles, labels, dialog focus restoration and Escape handling.

- [ ] **Step 4: Consolidate shared CSS**

Define buttons, inputs, selects, textareas, panels, badges, alerts, skeletons, empty states, feedback stack, dialog and focus rings before page-specific selectors. Remove duplicate rules that express the same component state.

- [ ] **Step 5: Run shared component tests**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/components/ui
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add web/src/components/ui web/src/styles.css
git commit -m "feat: migrate shared ui components"
```

---

### Task 5: Redesign daily operations pages

**Files:**
- Modify: `web/src/pages/OperationsDashboardPage.tsx`
- Modify: `web/src/pages/OperationsDashboardPage.test.tsx`
- Modify: `web/src/pages/RunListPage.tsx`
- Modify: `web/src/pages/RunListPage.test.tsx`
- Modify: `web/src/pages/NewAnalysisPage.tsx`
- Modify: `web/src/pages/NewAnalysisPage.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `MetricCard`, `Panel`, `PageHeader`, `StatusBadge`, `AppIcon`.
- Produces: comfortable-density dashboard and creation flow, compact run-history toolbar and table.

- [ ] **Step 1: Write failing dashboard hierarchy tests**

```tsx
it('presents the operations overview as named metric and activity regions', async () => {
  render(<MemoryRouter><OperationsDashboardPage /></MemoryRouter>)
  expect(await screen.findByRole('region', { name: '运营指标' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: '最近运行' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: '运行条件' })).toBeInTheDocument()
})

it('keeps new analysis as the only primary page action', async () => {
  render(<MemoryRouter><OperationsDashboardPage /></MemoryRouter>)
  expect(await screen.findByRole('link', { name: '新建分析' })).toHaveClass('button-primary')
  expect(screen.getByRole('button', { name: '刷新状态' })).toHaveClass('button-secondary')
})
```

- [ ] **Step 2: Write failing run-history and flow tests**

Add assertions that the filter bar is labelled `运行筛选`, the history table keeps all existing columns, the three-step new-analysis indicator has `aria-current="step"`, and mode/provider cards retain `aria-pressed`.

- [ ] **Step 3: Run page tests to verify RED**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/pages/OperationsDashboardPage.test.tsx src/pages/RunListPage.test.tsx src/pages/NewAnalysisPage.test.tsx
```

Expected: FAIL on the new named regions and current-step semantics.

- [ ] **Step 4: Implement the operations dashboard**

Use this hierarchy:

```tsx
<section className="dashboard-page density-comfortable">
  <PageHeader
    title="运营总览"
    description="查看运行、审核、调度和系统准备情况。"
    actions={<Link className="button-primary" to="/runs/new">新建分析</Link>}
  />
  <section className="dashboard-overview" aria-label="运营指标">
    {metricCards.map((metric) => (
      <MetricCard
        key={metric.label}
        icon={metric.icon}
        label={metric.label}
        value={metric.value}
        description={metric.description}
        tone={metric.tone}
      />
    ))}
  </section>
  <div className="dashboard-lower-grid">
    <Panel title="最近运行">{recentRunsContent}</Panel>
    <Panel title="运行条件">{readinessContent}</Panel>
  </div>
</section>
```

`metricCards`、`recentRunsContent` 和 `readinessContent` 只重组当前 `summary` 派生出的 JSX；不得创建静态演示数据。若现有页面没有这些局部变量，在组件内以明确命名的 `const` 提取当前对应渲染分支。

Use four `MetricCard` components for total/recent runs, waiting review, enabled schedules and system readiness. Do not invent values; derive only from `summary` fields already returned.

- [ ] **Step 5: Implement run history and new-analysis layouts**

Keep current request code and state untouched. Add `aria-label="运行筛选"` to the filter region, use compact table styling, and set `aria-current="step"` on the active step. Choice cards receive one icon, title and concise description.

- [ ] **Step 6: Run focused page tests**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/pages/OperationsDashboardPage.test.tsx src/pages/RunListPage.test.tsx src/pages/NewAnalysisPage.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add web/src/pages/OperationsDashboardPage.tsx web/src/pages/OperationsDashboardPage.test.tsx web/src/pages/RunListPage.tsx web/src/pages/RunListPage.test.tsx web/src/pages/NewAnalysisPage.tsx web/src/pages/NewAnalysisPage.test.tsx web/src/styles.css
git commit -m "feat: redesign daily operations pages"
```

---

### Task 6: Redesign the real-data workbench

**Files:**
- Modify: `web/src/pages/DataRunPage.tsx`
- Modify: `web/src/pages/DataRunPage.test.tsx`
- Modify: `web/src/pages/data-run/AcquisitionSummary.tsx`
- Modify: `web/src/pages/data-run/DataRunTimeline.tsx`
- Modify: `web/src/pages/data-run/DataRunActionPanel.tsx`
- Modify: `web/src/pages/data-run/MarketPanel.tsx`
- Modify: `web/src/pages/data-run/CandidatesPanel.tsx`
- Modify: `web/src/pages/data-run/NewsRecordsPanel.tsx`
- Modify: `web/src/pages/data-run/EvidencePanel.tsx`
- Modify: `web/src/pages/data-run/QualityPanel.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `SummaryStrip`, compact `Panel`, `StatusBadge`, current data-run API types.
- Produces: visually unified workbench without changing polling, filters, pagination or generation actions.

- [ ] **Step 1: Write failing summary and tab tests**

```tsx
it('renders the data run metadata as one summary region', async () => {
  renderPage()
  expect(await screen.findByRole('region', { name: '数据运行摘要' })).toHaveTextContent('Provider')
  expect(screen.getByRole('region', { name: '数据运行摘要' })).toHaveTextContent('完成时间')
})

it('keeps every workbench view keyboard-addressable', async () => {
  renderPage()
  const tablist = await screen.findByRole('tablist', { name: '数据运行详情' })
  expect(within(tablist).getAllByRole('tab')).toHaveLength(5)
})
```

- [ ] **Step 2: Write failing news-record semantics tests**

For a saved news item, assert one article includes title, summary, publisher, source grade, publish time, collection time, query lineage and a source link when `citation_url` exists. Assert the filter region is labelled `新闻筛选`.

- [ ] **Step 3: Run the data-run test to verify RED**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/pages/DataRunPage.test.tsx
```

Expected: FAIL because the current metadata container and news toolbar lack the new region labels.

- [ ] **Step 4: Replace the detail summary with `SummaryStrip`**

Pass exactly six items: 状态、场景、Provider、Cutoff、候选板块、完成时间. Preserve current formatting and loading fallbacks.

- [ ] **Step 5: Restyle acquisition and timeline sections**

Keep all counts and capability notices. Use one three-column count strip, then source cards. Timeline nodes must include text labels (`已完成`, `进行中`, `未开始`, `失败`) in addition to color.

- [ ] **Step 6: Restyle tabs, tables, candidates, evidence, quality, and news**

Use compact density. News items use a two-level header, readable summary with a sensible line length, metadata grid, query chips and a secondary `查看原文` link. Do not add full-body fields because the current API does not provide them.

- [ ] **Step 7: Verify behavior**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/pages/DataRunPage.test.tsx src/dataRunsApi.test.ts
```

Expected: PASS, including existing polling, retry, filter and pagination assertions.

- [ ] **Step 8: Commit**

```powershell
git add web/src/pages/DataRunPage.tsx web/src/pages/DataRunPage.test.tsx web/src/pages/data-run web/src/styles.css
git commit -m "feat: redesign real data workbench"
```

---

### Task 7: Redesign content-run detail and preserve failure recovery

**Files:**
- Modify: `web/src/pages/RunDetailPage.tsx`
- Modify: `web/src/pages/RunDetailPage.test.tsx`
- Modify: `web/src/pages/tabs/OverviewTab.tsx`
- Modify: `web/src/pages/tabs/RadarTab.tsx`
- Modify: `web/src/pages/tabs/EvidenceTab.tsx`
- Modify: `web/src/pages/tabs/DraftTab.tsx`
- Modify: `web/src/pages/tabs/ReviewTab.tsx`
- Modify: `web/src/pages/tabs/GovernanceTab.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `SummaryStrip`, current run detail and tab APIs.
- Produces: content-run workbench consistent with Task 6, including access to preserved drafts after downstream failures.

- [ ] **Step 1: Write failing recovery-oriented tests**

```tsx
it('keeps a stored draft reachable when the run status is failed', async () => {
  vi.mocked(fetchRun).mockResolvedValue({
    run_id: 'run-1',
    requested_at: '2026-08-17T00:00:00Z',
    provider: 'live',
    status: 'FAILED',
    elapsed_ms: 120,
    total_cost_cny: '0',
    draft_id: 'draft-1',
    sector_count: 8,
    retryable: true,
  })
  render(
    <MemoryRouter initialEntries={['/runs/run-1']}>
      <Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes>
    </MemoryRouter>,
  )
  expect(await screen.findByRole('tab', { name: '草稿' })).toBeEnabled()
  await userEvent.click(screen.getByRole('tab', { name: '草稿' }))
  expect(await screen.findByText('草稿内容')).toBeInTheDocument()
})

it('renders content metadata as one summary region', async () => {
  render(
    <MemoryRouter initialEntries={['/runs/run-1']}>
      <Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes>
    </MemoryRouter>,
  )
  expect(await screen.findByRole('region', { name: '内容运行摘要' })).toHaveTextContent('板块数')
})
```

- [ ] **Step 2: Run detail tests to verify RED**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/pages/RunDetailPage.test.tsx
```

Expected: FAIL on the named summary region or draft recovery fixture.

- [ ] **Step 3: Implement the shared workbench hierarchy**

Use `SummaryStrip`, consistent tabs, compact panels and the same timeline/status language as the data-run page. Do not duplicate the data-run CSS under new selectors when a shared workbench selector can serve both.

- [ ] **Step 4: Preserve current tab data flows**

Leave fetch calls inside existing tab components. Improve only headings, metadata layout, cards and action hierarchy. A failed run with stored draft data must still allow the draft tab to render.

- [ ] **Step 5: Run run-detail and tab tests**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/pages/RunDetailPage.test.tsx src/pages/tabs
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add web/src/pages/RunDetailPage.tsx web/src/pages/RunDetailPage.test.tsx web/src/pages/tabs web/src/styles.css
git commit -m "feat: redesign content run workbench"
```

---

### Task 8: Redesign the three-column review workspace

**Files:**
- Modify: `web/src/pages/ReviewWorkspacePage.tsx`
- Modify: `web/src/pages/ReviewWorkspacePage.test.tsx`
- Modify: `web/src/components/review/ReviewQueue.tsx`
- Modify: `web/src/components/review/DraftWorkspace.tsx`
- Modify: `web/src/components/review/DraftWorkspace.test.tsx`
- Modify: `web/src/components/review/EvidenceDecisionPane.tsx`
- Modify: `web/src/components/review/EvidenceDecisionPane.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: existing editing, governance, approval and evidence-decision APIs.
- Produces: desktop three-column and narrow-screen stacked review workflow.

- [ ] **Step 1: Write failing layout semantics tests**

```tsx
it('labels the queue, editor, and evidence regions', async () => {
  render(
    <MemoryRouter>
      <FeedbackProvider><ReviewWorkspacePage /></FeedbackProvider>
    </MemoryRouter>,
  )
  expect(await screen.findByRole('region', { name: '审核队列' })).toBeInTheDocument()
  expect(screen.getByRole('main', { name: '草稿编辑区' })).toBeInTheDocument()
  expect(screen.getByRole('complementary', { name: '证据与治理' })).toBeInTheDocument()
})
```

Update component roots to expose these semantics without changing button labels or request callbacks.

- [ ] **Step 2: Run review tests to verify RED**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/pages/ReviewWorkspacePage.test.tsx src/components/review
```

Expected: FAIL because the existing panes are not all named landmarks.

- [ ] **Step 3: Implement queue and editor hierarchy**

Queue width 280px, evidence pane width 360px, center editor flexible. Queue items show title or run ID, Provider, sector count and status. Editor uses a readable maximum line length inside the flexible pane; textareas keep existing save semantics.

- [ ] **Step 4: Implement evidence and approval hierarchy**

Order sections as 来源、证据决定、当前决定、治理与发布操作. Keep approval disabled when governance fails. Preserve confirm dialogs and focus behavior.

- [ ] **Step 5: Add narrow-screen ordering**

At `< 960px`, render queue, editor, evidence as one column. Do not use horizontal scrolling for the complete workspace; only inner wide data structures may scroll.

- [ ] **Step 6: Run review tests**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/pages/ReviewWorkspacePage.test.tsx src/components/review
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add web/src/pages/ReviewWorkspacePage.tsx web/src/pages/ReviewWorkspacePage.test.tsx web/src/components/review web/src/styles.css
git commit -m "feat: redesign review workspace"
```

---

### Task 9: Migrate schedules, system status, task runs, and shadow acceptance

**Files:**
- Modify: `web/src/pages/SchedulePage.tsx`
- Modify: `web/src/pages/SchedulePage.test.tsx`
- Modify: `web/src/pages/SystemStatusPage.tsx`
- Modify: `web/src/pages/SystemStatusPage.test.tsx`
- Modify: `web/src/pages/ShadowAcceptancePage.tsx`
- Modify: `web/src/components/ShadowAcceptanceCard.tsx`
- Modify: `web/src/components/ShadowAcceptanceCard.test.tsx`
- Modify: `web/src/pages/TaskRunPage.tsx`
- Modify: `web/src/pages/TaskRunPage.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: shared cards, summary strips, tables, badges and alerts.
- Produces: consistent compact management surfaces with no business changes.

- [ ] **Step 1: Write failing management-page semantics tests**

Add assertions for:

```tsx
expect(screen.getByRole('region', { name: '调度概览' })).toBeInTheDocument()
expect(screen.getByRole('region', { name: '系统连接状态' })).toBeInTheDocument()
expect(screen.getByRole('region', { name: '影子验收进度' })).toBeInTheDocument()
expect(screen.getByRole('region', { name: '任务阶段' })).toBeInTheDocument()
```

Retain existing assertions for schedule creation, triggering, safe status output and task progress.

- [ ] **Step 2: Run tests to verify RED**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/pages/SchedulePage.test.tsx src/pages/SystemStatusPage.test.tsx src/components/ShadowAcceptanceCard.test.tsx src/pages/TaskRunPage.test.tsx
```

Expected: FAIL on the new named regions.

- [ ] **Step 3: Migrate the schedule page**

Use `SummaryStrip` for total/enabled/timezone. Keep the create form inside one comfortable panel and the schedule table inside one compact panel. Preserve all form values and trigger callbacks.

- [ ] **Step 4: Migrate system and shadow pages**

System cards receive outline icons and semantic status badges but continue hiding secrets. Shadow acceptance keeps the 20-day labels and history table; do not re-enable an operational requirement that the user has paused.

- [ ] **Step 5: Migrate task-run progress**

Use the same timeline primitives as other run pages. Preserve current event and polling behavior. Show last known stage text when a task is terminal.

- [ ] **Step 6: Run focused tests**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test -- src/pages/SchedulePage.test.tsx src/pages/SystemStatusPage.test.tsx src/components/ShadowAcceptanceCard.test.tsx src/pages/TaskRunPage.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add web/src/pages/SchedulePage.tsx web/src/pages/SchedulePage.test.tsx web/src/pages/SystemStatusPage.tsx web/src/pages/SystemStatusPage.test.tsx web/src/pages/ShadowAcceptancePage.tsx web/src/components/ShadowAcceptanceCard.tsx web/src/components/ShadowAcceptanceCard.test.tsx web/src/pages/TaskRunPage.tsx web/src/pages/TaskRunPage.test.tsx web/src/styles.css
git commit -m "feat: migrate management pages to soft blue ui"
```

---

### Task 10: Complete responsive, accessibility, and visual QA

**Files:**
- Modify: `web/src/styles.css`
- Modify only if defects are found: files changed in Tasks 2–9
- Create: `docs/superpowers/reports/2026-08-26-soft-blue-ui-acceptance.md`

**Interfaces:**
- Consumes: all redesigned pages.
- Produces: verified desktop and narrow-screen UI plus an acceptance report.

- [ ] **Step 1: Run the complete frontend test suite**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test
```

Expected: all Vitest tests PASS with no unhandled errors.

- [ ] **Step 2: Run the production build**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd run build
```

Expected: TypeScript and Vite exit 0 and create fresh `web/dist` assets.

- [ ] **Step 3: Start the integrated server**

```powershell
cd D:\work\SectorPulse
.\.venv\Scripts\python.exe -m sector_pulse.web.server
```

Open `http://127.0.0.1:9000`. If 9000 is already occupied, identify the exact listener and restart only the SectorPulse backend process.

- [ ] **Step 4: Perform one batched desktop and narrow-screen inspection**

Inspect at 1440×900 and 390×844:

```text
/                         运营总览
/runs                     运行历史
/runs/new                 新建分析
/data-runs/<real-run-id>  数据工作台
/runs/<content-run-id>    内容运行详情
/review                   审核工作台
/schedules                定时任务
/system                   系统状态
/shadow-acceptance        影子验收
```

Record all defects in one list covering overflow, alignment, spacing, focus, contrast, copy wrapping, loading, empty and error states.

- [ ] **Step 5: Fix the complete defect list in one batch**

Only change defects observed in Step 4. Do not introduce a new visual direction. Re-run the focused tests for each component or page changed.

- [ ] **Step 6: Perform one confirmation inspection**

Repeat the same desktop and narrow-screen routes once. Stop visual iteration after this confirmation pass unless a functional blocker remains.

- [ ] **Step 7: Write the acceptance report**

The report must include:

```markdown
# Soft Blue UI Acceptance

## Automated verification
- Frontend tests: command and result
- Production build: command and result

## Visual verification
- Desktop viewport and routes checked
- Narrow viewport and routes checked
- Defects fixed in the bounded QA pass

## Functional invariants
- Routes and APIs unchanged
- Polling, filtering, pagination, review and scheduling verified
- No backend change required

## Remaining warnings
- List only real non-blocking warnings observed during verification
```

- [ ] **Step 8: Run final verification**

```powershell
cd D:\work\SectorPulse\web
D:\software\nodejs\npm.cmd test
D:\software\nodejs\npm.cmd run build
```

Expected: both commands exit 0 after the final visual fixes.

- [ ] **Step 9: Commit**

```powershell
git add web/src docs/superpowers/reports/2026-08-26-soft-blue-ui-acceptance.md
git commit -m "feat: complete soft blue ui redesign"
```

---

## Final Completion Gate

Before declaring the redesign complete, verify every item:

- [ ] Three visual reference images exist and match the approved non-cartoon direction.
- [ ] All routes use the same token system and icon language.
- [ ] Dashboard and creation flow use comfortable density.
- [ ] Tables, news, details and review use compact density.
- [ ] No API path, route, polling interval or business mutation changed.
- [ ] Desktop and narrow-screen critical flows are usable by keyboard.
- [ ] No status relies only on color.
- [ ] Full frontend tests pass.
- [ ] Production build passes and `web/dist` is fresh locally.
- [ ] Acceptance report contains concrete commands and results.
