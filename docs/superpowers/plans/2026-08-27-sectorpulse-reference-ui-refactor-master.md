# SectorPulse Reference UI Refactor Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SectorPulse 现有前后端渐进重构为与 README 三张参考图高度一致、只展示真实能力、可维护且完整响应式的运营后台。

**Architecture:** 先冻结项目级设计规范，再分阶段迁移应用外壳、运营总览、数据运行工作台、审核工作台和管理页面。现有路由、React 组件和 FastAPI 接口保持兼容；新视觉通过分层 CSS 和小型语义组件落地，新数据需求通过增量 API 与可回滚 PostgreSQL 迁移补充。

**Tech Stack:** React 18、React Router 6、TypeScript 5.6、Vite 5、Vitest 4、Testing Library、Playwright、FastAPI、Pydantic 2、SQLAlchemy 2、PostgreSQL、pytest

**Spec:** `docs/superpowers/specs/2026-08-27-sectorpulse-reference-ui-refactor-design.md`

## Global Constraints

- 三张参考图是高保真视觉和布局目标，不是需要逐项复制的功能清单。
- 正式页面禁止静态示意指标、假按钮、假通知、假用户资料和不可追溯趋势。
- 全站只使用一套统一侧边栏；保留 `/`、`/runs`、`/runs/new`、`/runs/:runId`、`/review`、`/data-runs/:runId`、`/schedules`、`/task-runs/:runId`、`/system`、`/shadow-acceptance`。
- 保留 React、TypeScript 和语义 CSS，不引入 Tailwind、Ant Design、MUI 或其他大型 UI 框架。
- API 调整必须增量兼容；数据库调整必须可回滚且不得删除现有运行、草稿、新闻、证据和审核记录。
- API Key、数据库密码、连接串、原始提示词和未脱敏模型响应不得出现在前端、截图和验收报告中。
- 审核稿保留结构化字段、版本、字段哈希和证据锚点，不直接替换为任意富文本。
- 主要桌面验收尺寸固定为 1536×1024 和 1440×900；响应式检查覆盖 1280×800、1024×768、768×1024 和 390×844。
- 每阶段必须先写详细计划、测试先行、通过自动化与浏览器验收、形成可回退提交，再进入下一阶段。
- 当前执行方式为同一会话内使用 `executing-plans` 连续执行，不使用子代理；必要外部条件或重大需求冲突才暂停。

---

## Delivery Map

| 阶段 | 独立交付物 | 依赖 | 退出条件 |
|---|---|---|---|
| Phase 0 | UI 规范、完整设计和布局原型 | 已确认需求 | 文档提交、工作区干净 |
| Phase 1 | 分层设计基础、统一外壳、路由上下文、响应式导航 | Phase 0 | 已验收，PostgreSQL 连通性复测待本机数据库恢复 |
| Phase 2 | 真实运营总览、趋势、就绪状态和聚合接口 | Phase 1 | 指标可追溯，无假数据，空/错/运行中状态通过 |
| Phase 3 | 数据运行工作台、候选选择和新闻详情 | Phase 2 | 从采集到确认候选再生成草稿的真实流程通过 |
| Phase 4 | 三栏审核工作台、连续结构化编辑和治理 | Phase 3 | 版本、证据锚点、审批审计无回归 |
| Phase 5 | 运行列表、新建分析、内容运行和管理页面 | Phase 4 | 全站视觉与交互统一，现有能力无回归 |
| Phase 6 | 全量测试、响应式、无障碍、性能、README 实际截图 | Phase 5 | 前后端完整验收并保留合并决策点 |

## Program Interfaces

- Frontend shell: `AppShell`, `SidebarNav`, `TopBar`, `PageHeader`。
- Frontend API modules: `operations`, `runs`, `dataRuns`, `review`, `schedules`, `system`。
- Backend compatibility boundary: existing HTTP routes and response fields remain valid; new fields are additive。
- Persistence boundary: PostgreSQL stores run state, candidate selections, structured draft versions, evidence decisions and audit events。
- Shared status boundary: `queued | running | waiting_for_selection | waiting_for_draft | waiting_for_review | completed | failed | cancelled`。

## Phase 0: Design Baseline

**Delivered files:**

- `docs/design/sectorpulse-reference-ui-system.md`
- `docs/superpowers/specs/2026-08-27-sectorpulse-reference-ui-refactor-design.md`
- `docs/design/prototypes/operations-dashboard-layout.html`

- [x] 固定真实性、统一导航、三类页面模板和响应式规则。
- [x] 逐节确认运营总览、数据工作台、审核工作台、接口与迁移策略。
- [x] 提交 `c6c0d68 docs: define high fidelity frontend refactor`。

## Phase 1: Foundation And Unified Shell

**Detailed plan:** `docs/superpowers/plans/2026-08-27-sectorpulse-reference-ui-phase1-foundation.md`

**Primary files:**

- `web/src/styles/index.css`
- `web/src/styles/tokens.css`
- `web/src/styles/base.css`
- `web/src/styles/shell.css`
- `web/src/styles/components/primitives.css`
- `web/src/styles/responsive.css`
- `web/src/layout/routeContext.ts`
- `web/src/layout/AppShell.tsx`
- `web/src/layout/SidebarNav.tsx`
- `web/src/layout/TopBar.tsx`
- `web/src/components/ui/Button.tsx`

- [x] 建立新 CSS 分层入口并将现有 `styles.css` 作为迁移期 `legacy` 层保留。
- [x] 建立所有已知路由的页面上下文解析，不增加死链接。
- [x] 高保真重构统一侧边栏、品牌区、导航高亮、顶部上下文和独立主滚动区。
- [x] 增加统一按钮与页面标题元信息契约，保持现有组件调用兼容。
- [x] 通过 Vitest、TypeScript/Vite build、Playwright 桌面和抽屉导航检查。
- [x] 使用浏览器工具在 1536×1024、1024×768、390×844 下完成视觉验收并记录报告。

**Exit commands:**

```powershell
Set-Location web
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e -- e2e/shell.spec.ts
Set-Location ..
git diff --check
git status --short
```

## Phase 2: Operations Dashboard

**Detailed plan boundary:** 在 Phase 1 验证后的组件和路由契约上编写，不提前假设聚合接口字段。

**Expected file areas:**

- `web/src/pages/OperationsDashboardPage.tsx`
- `web/src/operationsApi.ts`
- `web/src/components/dashboard/`
- `backend/src/sector_pulse/web/`
- `backend/tests/unit/web/`
- `backend/tests/integration/`

- [ ] 审计当前 `/api/operations/summary` 与 PostgreSQL 运行字段。
- [ ] 先写后端聚合失败测试，再增量增加 `summary`、`trend`、`readiness`、`recent_runs`、`generated_at`。
- [ ] 先写前端加载、空、部分降级、失败和运行中测试，再实现指标、趋势、状态与近期表格。
- [ ] 只有数据库可可靠计算时才显示变化值；未知值返回 `null` 和原因。
- [ ] 存在运行中任务时每 5 秒刷新，页面隐藏时暂停，失败时保留最后成功数据。
- [ ] 在空数据库和已有真实记录两种状态下浏览器验收。

**Exit commands:**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/web backend/tests/integration -q -p no:cacheprovider -m "not live"
Set-Location web
npm.cmd test -- src/operationsApi.test.ts src/pages/OperationsDashboardPage.test.tsx
npm.cmd run build
Set-Location ..
```

## Phase 3: Data Run Workbench

**Expected file areas:**

- `web/src/pages/DataRunPage.tsx`
- `web/src/pages/data-run/`
- `web/src/dataRunsApi.ts`
- `backend/src/sector_pulse/web/`
- `backend/src/sector_pulse/storage/`
- `backend/tests/unit/application/`
- `backend/tests/integration/`

- [ ] 统一运行摘要、五阶段进度、采集统计和 Provider 状态。
- [ ] 候选板块支持搜索、排序、全选、取消和确认，并持久化选择版本。
- [ ] 生成草稿读取已确认候选版本；未确认时后端和前端共同阻止提交。
- [ ] 行情、新闻、证据、质量使用服务端分页和稳定页签。
- [ ] 新闻明确区分正文、摘要、快讯和原文 URL；只为真实链接提供入口。
- [ ] 运行中每 2 秒轮询，终态停止，刷新后恢复阶段与选择。
- [ ] 通过真实 PostgreSQL 流程验证“采集→选择→生成草稿”。

## Phase 4: Review Workspace

**Expected file areas:**

- `web/src/pages/ReviewWorkspacePage.tsx`
- `web/src/components/review/`
- `web/src/editingApi.ts`
- `backend/src/sector_pulse/application/`
- `backend/src/sector_pulse/storage/`
- `backend/tests/unit/`
- `backend/tests/integration/`

- [ ] 桌面使用 22%/53%/25% 三栏工作区并保证中栏阅读宽度。
- [ ] 草稿视觉连续但继续保存结构化字段、版本、哈希和证据链接。
- [ ] 自动保存覆盖未保存、保存中、成功、失败和版本冲突。
- [ ] 来源随当前字段或段落变化，证据决策支持保留、降权、排除和理由。
- [ ] 批准、退回和撤销严格服从后端可执行操作与审计。
- [ ] 窄屏使用“队列/草稿/证据”页签，不压缩三栏。
- [ ] 通过并发版本冲突、证据判定和审批回归测试。

## Phase 5: Remaining Pages

**Expected file areas:**

- `web/src/pages/RunListPage.tsx`
- `web/src/pages/NewAnalysisPage.tsx`
- `web/src/pages/RunDetailPage.tsx`
- `web/src/pages/TaskRunPage.tsx`
- `web/src/pages/SchedulePage.tsx`
- `web/src/pages/SystemStatusPage.tsx`
- `web/src/pages/ShadowAcceptancePage.tsx`

- [ ] 分析运行迁移为筛选工具条和紧凑表格。
- [ ] 新建分析按场景、配置、确认、启动四步组织。
- [ ] 内容运行统一展示归因、编辑、写作、审核、治理和恢复动作。
- [ ] 定时任务采用列表和编辑抽屉，并为删除提供确认。
- [ ] 系统状态展示安全的检查时间、耗时、错误和建议，不暴露配置内容。
- [ ] 影子验收保留能力和历史记录，未运行时显示真实空状态。
- [ ] 清理被新分层替代的 `legacy` 样式，确保无未使用兼容选择器。

## Phase 6: Full Acceptance And Documentation

- [ ] 运行全量非 live 后端测试、Ruff 和 mypy。
- [ ] 运行全量 Vitest、TypeScript/Vite build 和 Playwright。
- [ ] 浏览器逐页覆盖 1536×1024、1440×900、1280×800、1024×768、768×1024、390×844。
- [ ] 使用键盘完成新建分析、候选选择、草稿保存和审核关键路径。
- [ ] 检查加载、空、部分数据、失败、重试、禁用、冲突和无配置状态。
- [ ] 检查页面隐藏时轮询暂停、终态停止和请求去重。
- [ ] 进行最终代码审查和依赖、性能、敏感信息检查。
- [ ] 用实际产品页面重新截取 README 图片，并明确设计参考图的历史用途。
- [ ] 形成最终验收报告；保留 `refactoring` 到 `main` 的独立合并决策。

**Final commands:**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider -m "not live"
.\.venv\Scripts\python.exe -m ruff check backend/src backend/tests
.\.venv\Scripts\python.exe -m mypy backend/src
Set-Location web
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
Set-Location ..
git diff --check
git status --short
```

## Phase Boundary Rules

- 阶段开始时必须读取本总计划、完整设计、UI 规范和该阶段详细计划。
- 阶段实现只依赖已经通过验收的导出接口，不依赖未提交工作。
- 新 API 需求必须先证明现有接口无法可靠表达，并使用最小兼容扩展。
- 数据库迁移必须先测试迁移与旧数据读取，再启用新写入。
- 单元测试通过不能替代生产构建和浏览器检查。
- 当前阶段存在失败测试、死链接、示意数据、未处理敏感信息或数据库不一致时，不得进入下一阶段。
- 每阶段至少形成一个实现提交和一个验收提交，便于独立回退。
