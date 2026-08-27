# SectorPulse Reference UI Phase 1 Acceptance

## Scope

- 分层 CSS 入口和旧样式兼容边界
- 统一侧边栏、路由感知顶部栏和独立主滚动区
- Button 与 PageHeader 元信息契约
- 桌面、1024px 抽屉和 390px 窄屏外壳行为

## Automated Verification

2026-08-27 执行并通过：

| Command | Result |
| --- | --- |
| `web: npm.cmd test` | 33 个文件，102 项通过 |
| `web: npm.cmd run build` | TypeScript 与 Vite 成功，生成 `web/dist/index.html` |
| `web: npm.cmd run test:e2e` | 5 项通过，包括 SPA smoke、独立主滚动、1024px 抽屉、390px 无横向溢出和旧主操作可读性 |
| `backend: $env:SECTOR_PULSE_DATABASE_URL = ''; pytest backend/tests/e2e backend/tests/integration backend/tests/test_package_smoke.py -q -p no:cacheprovider -m "not live"` | 45 项通过，19 项 PostgreSQL 集成用例按设计跳过 |
| `backend: $env:SECTOR_PULSE_DATABASE_URL = ''; pytest backend/tests/unit -q -p no:cacheprovider -m "not live"` | 193 项通过 |
| `backend: $env:SECTOR_PULSE_DATABASE_URL = ''; pytest backend/tests/live/test_phase1b_llm_live.py -q -p no:cacheprovider -m "not live"` | 1 项按 live consent 设计跳过 |

总计 238 项非 live 后端测试通过，20 项依赖 PostgreSQL 或 live LLM consent 的用例跳过。

使用当前环境提供的 PostgreSQL URL 直接运行集成测试时，`test_postgres_agent_invocation_round_trip` 在连接初始化阶段收到 `ConnectionRefusedError`。这是本机配置的数据库地址不可达，不是 Phase 1 前端改造造成的失败；本阶段未改动后端或数据库结构。

## Browser Verification

使用本地构建应用完成以下检查，控制台未发现 error 或 warning：

| Viewport / route | Observed result |
| --- | --- |
| 1536x1024 `/` | 侧边栏稳定，`body` 禁止页面滚动，`.app-main` 独立滚动；桌面端菜单按钮隐藏；旧的“新建分析”操作保持白字蓝底。 |
| 1440x900 `/runs`、`/review`、`/schedules`、`/system`、`/shadow-acceptance` | 顶部栏均显示真实的“运营/页面”或“管理/页面”上下文，菜单在桌面端隐藏。 |
| 1024x768 `/runs` | 菜单可打开抽屉，导航状态为 open，焦点进入“关闭导航”按钮；Escape 可关闭并按单元与 Playwright 测试恢复焦点。 |
| 390x844 `/runs` | 菜单可见，主内容内边距为 `20px 12px 32px`，根文档无横向溢出。 |

浏览器还发现并修复了两项兼容问题：

1. Button 组件层曾覆盖外壳层，使桌面菜单错误可见。最终由响应式最终层统一控制菜单显示。
2. 通用链接色曾覆盖旧 `.button-primary` 的白色文字。最终在 primitives 层保留旧 class 别名，并由 Playwright 覆盖其可读性。

## Data And Security

- 未引入假就绪状态、假指标或假业务入口。
- 未在前端、测试或文档中写入 API key、数据库密码、连接 URL、提示词或原始模型响应。
- 本阶段未调用实时数据源或 LLM。

## Remaining Scope

运营总览的真实聚合数据和趋势属于 Phase 2；数据工作台的候选选择与分页属于 Phase 3；审核工作台重构属于 Phase 4。PostgreSQL 集成用例将在本机可达数据库恢复后单独执行。
