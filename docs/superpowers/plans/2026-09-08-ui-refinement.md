# UI Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans；用户选择当前会话连续执行，不使用子代理。

**Goal:** 在已确认蓝白主题下，提高全站状态可信度、可读性与高频工作效率。

**Architecture:** 在共享样式和显示纯函数修正基础问题；列表使用 URL 管理已加载近期记录的过滤分页；数据与审核工作台局部渐进披露，不改写持久化链路。

**Tech Stack:** React 18、TypeScript、现有 Vite/Vitest/Playwright，Python/FastAPI 后端保持兼容。

**Spec:** [设计](../specs/2026-09-08-ui-refinement-design.md)。已批准方向：先 Phase 1、后 Phase 2。

## Global Constraints

- React 18、TypeScript、现有 Vite/Vitest/Playwright；不新增运行时依赖。
- 保留现有路由、SQLite/PostgreSQL 兼容与数据库结构；不修改业务数据库、.env 或 consent，不调用 Live/LLM、不恢复影子测试。
- 保留统一蓝白视觉与本机系统字体；无营销动画、无新主题、无虚构字段。
- 普通文字在实际背景上至少 4.5:1；桌面主要控件至少 40px、手机至少 44px，错误与状态不能仅靠颜色。
- 0、未知、不适用、进行中分别显示；已结束但缺耗时/成本应显示未记录，不写待完成。
- 分阶段测试与提交；最终在功能分支验收，不自动合并或推送。

## 任务与验证

### Task 1 / Phase 1：公共视觉和状态

Files：`web/src/styles/{tokens.css,components/primitives.css,responsive.css}`；`web/src/runPresentation.ts`；`web/src/pages/{RunListPage.tsx,DataRunPage.tsx}`；`web/src/pages/data-run/AcquisitionSummary.tsx`。测试：新增 `runPresentation.test.ts`、扩充 `RunListPage.test.tsx`、`DataRunPage.test.tsx`、`web/e2e/ui-refinement.spec.ts`。

Interfaces：新增 `providerLabel(value?: string): string`、`isActiveRun(status: string): boolean`、`runCost(value: string|null, status: string, dataRun?: boolean): string`；`formatDuration(value: number|null, status?: string)` 兼容既有单参数调用。数据候选读取使用 null 检查而非真值判断。

- [ ] 写失败测试：断言 `runCost(null, 'COMPLETED') === '未记录'`、`runCost('0', 'COMPLETED') === '¥0'`、`runCost(null, 'FAILED', true) === '不适用'`；页面筛选 live 时保留 live 数据运行，0 个候选显示 0。浏览器计算 muted 色与实际背景对比至少4.5，错误区域为水平布局、非透明语义背景。
- [ ] 红灯执行：`npm test -- src/runPresentation.test.ts src/pages/RunListPage.test.tsx src/pages/DataRunPage.test.tsx --maxWorkers=2`；`npm run test:e2e:dev -- ui-refinement.spec.ts`。
- [ ] 实现：使用 `value ?? '未记录'` 保留0；active 状态枚举涵盖排队/采集/验证/候选/就绪前阶段，未知状态不当作运行中。CSS 为 `.panel` 显式 border/padding、`.inline-alert` grid 两列、tone 背景与边框；控件移动端44px。
- [ ] 绿灯运行同上并构建；同步 DESIGN token 和组件约定，提交 `fix: clarify runtime states and restore shared UI styling`。

### Task 2 / Phase 2：近期运行查询与恢复

Files：新增 `web/src/pages/run-registry/registryModel.ts` 和测试；修改 `RunListPage.tsx`、页面测试、`styles/pages/operations-pages.css`，扩充浏览器用例。

Interfaces：`registryRows(runs: RunSummary[], dataRuns: DataRunView[]): RegistryRow[]`；`selectRegistry(rows: RegistryRow[], params: URLSearchParams, now: number)` 返回 `{items,total,page,pages}`；每页20，q/status/scene/provider/time/order/page 为 URL 字段。保留旧筛选控件的可访问名称兼容自动化，source筛选不再使用 data。

- [ ] 写失败测试：45条记录第三页5条；q大小写搜索ID；非法page回1，超出总页数夹取；FETCHING_MARKET匹配运行中；切换筛选URL页码回1；错误后就地重试保留筛选。
- [ ] 运行：`npm test -- src/pages/run-registry src/pages/RunListPage.test.tsx --maxWorkers=2`。
- [ ] 实现：`useSearchParams` 承载条件，纯函数在原始记录中过滤后排序再 `slice((page-1)*20,page*20)`；重试使用请求序号避免晚响应覆盖。列表显式“每类最近50条”，没有全库total。详情 Link 使用 React Router state 携带安全的本地 `/runs?...` 返回地址；数据和内容详情返回链接复用该地址，刷新丢失state时回 `/runs`。
- [ ] 重跑单元、页面与浏览器，提交 `feat: streamline recent run discovery and return navigation`。

### Task 3 / Phase 2：数据结果优先

Files：`DataRunPage.tsx`、`DataRunPage.test.tsx`、`styles/pages/data-run.css`、浏览器用例。

- [ ] 写失败测试：READY运行默认详情收起，错误告警可见；打开详情后进度和采集可见；FETCHING_MARKET默认展开；标签方向键改变激活tab。
- [ ] `npm test -- src/pages/DataRunPage.test.tsx --maxWorkers=2` 确认红灯。
- [ ] 将进度和采集组合进受控 details：`open={!terminal || expanded}`；用依赖run_id/status的effect处理终态变化，保留外部告警与操作面板。tab使用键盘事件选择相邻索引并聚焦对应按钮，inactive tabindex=-1。
- [ ] 复验生成/重试/取消/候选原有测试与浏览器，提交 `feat: prioritize completed data run results`。

### Task 4 / Phase 2：审核专注、定位和操作空间

Files：`ReviewWorkspacePage.tsx`、`components/review/{DraftWorkspace.tsx,EvidenceDecisionPane.tsx}`、对应测试、`styles/pages/review-workspace.css`、浏览器用例。

- [ ] 写失败测试：专注开关不卸载草稿；章节选择后输入获得焦点；退回理由初始隐藏、点击出现、取消后值保留、提交仍需原确认；批准禁用边界不改变。
- [ ] 执行 `npm test -- src/components/review src/pages/ReviewWorkspacePage.test.tsx --maxWorkers=2` 确认红灯。
- [ ] 专注由父page data-focus驱动大屏隐藏两侧，不卸载组件。章节select对应稳定输入ID，通过 `scrollIntoView({block:'center'})` 与 focus定位。textarea在layout effect按scrollHeight调整高度，保留手工resize和原autosave逻辑。退回用局部展开按钮显示已存在字段，不复制API流程。
- [ ] 验证保存失败、冲突、历史只读、审批门禁和移动分区；提交 `feat: improve review focus and document navigation`。

### Task 5 / Phase 3：全量验收

- [ ] 前端 `npm test -- --maxWorkers=2`、`npm run test:tooling`、`npm run build`，生产/开发 `npm run test:e2e`、`npm run test:e2e:dev`。
- [ ] 主Python环境，PYTHONPATH指向功能工作区；非Live pytest使用 `--import-mode=importlib -p no:cacheprovider --basetemp <该工作区.tmp下全新路径> -m 'not live and not live_llm and not postgres'`。不继承业务URL。
- [ ] 1440/1024/390浏览器截图一轮批量检查，有问题集中修正，最多再确认一轮；不重跑已经完成的impeccable context/detector。
- [ ] 更新设计规范、验收MD与本计划真实状态；说明搜索仅近期、PostgreSQL/Live本轮未实测、未合并。`git diff --check`，只提交本轮文件，不提交.env、缓存、临时库或dist。

## 自审

5项任务覆盖已选两阶段；当前URL搜索不冒充后端全历史，所有交互只调用既有接口；退回/批准/生成仍由用户点击，不触发自动操作。暂无新数据库接口，无迁移任务。
