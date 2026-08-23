# Phase 3 分析运行工作台实施计划

> 执行方式：当前会话直接执行；每项先写失败测试，再做最小实现；每个任务完成后提交。

设计依据：`docs/superpowers/specs/2026-08-23-modern-operations-frontend-phase3-design.md`

## Task 1：补齐可重试数据合同

文件：

- 修改 `backend/src/sector_pulse/web/schemas.py`
- 修改 `backend/src/sector_pulse/web/run_service.py`
- 修改 `backend/tests/unit/web/test_run_service.py`
- 修改 `web/src/api.ts`

步骤：

1. 增加失败测试，验证运行中或无输入快照不可重试，已结束且有快照可重试。
2. 为 `RunDetail` 增加 `retryable`。
3. 在查询服务中按重试命令的同一规则计算字段。
4. 运行后端定向测试和类型检查。
5. 提交。

## Task 2：实现三步新建分析

文件：

- 新增 `web/src/pages/NewAnalysisPage.tsx`
- 新增 `web/src/pages/NewAnalysisPage.test.tsx`
- 修改 `web/src/App.tsx`
- 修改 `web/src/pages/RunListPage.tsx`
- 删除 `web/src/components/NewRunDialog.tsx`
- 修改 `web/src/styles.css`

步骤：

1. 写页面测试：三阶段导航、Fixture 创建与跳转、Live 缺条件阻断、重复提交禁用。
2. 实现 `/runs/new` 路由和三阶段页面。
3. 使用 operations summary 完成预检，不显示敏感配置值。
4. Fixture 使用内置输入创建内容运行；Live 创建数据运行。
5. 将运行列表主操作改为新页面链接，移除旧弹窗和 JSON 输入。
6. 运行定向前端测试并提交。

## Task 3：重做响应式运行历史

文件：

- 新增 `web/src/pages/RunListPage.test.tsx`
- 修改 `web/src/pages/RunListPage.tsx`
- 修改 `web/src/styles.css`

步骤：

1. 写过滤、状态中文化、空态和错误恢复测试。
2. 实现桌面表格与移动列表的同一语义结构。
3. 增加状态和 Provider 过滤，保持真实数据来源。
4. 验证窄屏无横向滚动并提交。

## Task 4：完善内容运行详情

文件：

- 修改 `web/src/pages/RunDetailPage.test.tsx`
- 修改 `web/src/pages/RunDetailPage.tsx`
- 修改 `web/src/pages/tabs/OverviewTab.tsx`
- 新增 `web/src/pages/tabs/GovernanceTab.tsx`
- 新增 `web/src/pages/tabs/GovernanceTab.test.tsx`
- 修改 `web/src/styles.css`

步骤：

1. 写加载失败、可重试信号、中文标签和治理标签测试。
2. 实现摘要、阶段轨迹、六个可访问标签页。
3. 仅按 `retryable` 显示重试；失败信息做安全分类。
4. 治理标签复用现有接口和治理卡片。
5. 运行定向测试并提交。

## Task 5：完善数据运行详情

文件：

- 修改 `web/src/pages/DataRunPage.test.tsx`
- 修改 `web/src/pages/DataRunPage.tsx`
- 修改 `web/src/styles.css`

步骤：

1. 写状态轨迹、质量状态、候选展示、生成条件和错误恢复测试。
2. 实现摘要、阶段轨迹、质量与候选区域。
3. 生成操作成功后跳转内容运行详情。
4. 运行定向测试并提交。

## Task 6：Fixture 全链路与视觉验收

文件：

- 修改 `docs/superpowers/plans/2026-08-23-modern-operations-frontend-master.md`
- 新增 `docs/superpowers/reports/2026-08-23-modern-operations-frontend-phase3-acceptance.md`

步骤：

1. 运行全部后端测试、前端测试和生产构建。
2. 启动临时本地服务，通过 UI 完成 Fixture 新建、运行详情和六标签浏览。
3. 在 1280px 与 390px 检查溢出、焦点、加载、空、错误和完成状态。
4. 运行 Impeccable 棭测器和 taste-skill 终检。
5. 记录命令、结果和已知限制，更新总计划并提交。
