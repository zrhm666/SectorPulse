# 双模式归因实施计划

> 执行方式：当前会话执行，使用 executing-plans，逐阶段验证。用户已授权连续实施，不重复询问执行方式。

**Goal:** 用户可选择节省 Token 的工作流模式，或有工具决策循环的 Agent 归因模式。

**Architecture:** 在现有内容运行输入上增加模式，抽离归因执行策略；工具结果经程序校验、存储和证据门禁后回流到写作。Agent 步骤由模型决定，执行器限制次数、时间、费用及访问范围。

**Tech Stack:** Python/Pydantic/asyncio、现有 LLMPort 与 Provider、SQLite/PostgreSQL、React/TypeScript。

**Spec:** `docs/superpowers/specs/2026-09-10-attribution-agent-modes-design.md`

## 全局约束

- 默认 workflow，旧输入和旧数据库记录无需业务数据重写。
- 不改变现有手动候选确认和人工批准规则。
- 每板块最多 6 轮决策、5 次工具调用、180 秒，最多 2 个板块并行，且共享整次预算。
- 历史行情只读锁定快照；后来读取的网页不冒充截止前已知全文。
- 价格缺失不能显示免费；无法读取原文不能显示已读全文。
- 执行日志与新增证据支持双方言；失败保留原因和已有产物。
- 当前目录已有其他修改，保留并排除本次提交。分阶段只提交明确文件，不自动合并或推送。

## 阶段 1：模式契约和运行生命周期

Files: `domain/writing/attribution_mode.py`、`application/writing/phase1b_pipeline.py`、`web/schemas/data_run.py`、`web/schemas/runs.py`、`web/services/data_run_writing_service.py`、`web/services/run_service.py`、`web/routers/data_runs.py`。

接口：`AttributionMode` 为 workflow/agent；`Phase1BRequest.attribution_mode` 默认 workflow；生成请求接收同名字段；详情返回模式，重试使用保存的输入。

- [ ] 测试旧请求默认、非法模式拒绝、生成请求传播、内容重试保留模式。
- [ ] 将模式写入规范化的输入快照及摘要/详情返回值。
- [ ] 在 Agent 未接线时同步拒绝该模式，避免误用工作流代替 Agent；接线测试通过后移除临时拒绝。
- [ ] 运行相关 API 和服务回归，检查类型与导入，提交阶段结果。

## 阶段 2：工具及新闻详情

Files: `domain/writing/agent_execution.py`、`ports/attribution_tools.py`、`ports/news_detail.py`、`application/writing/agent_tools.py`、`infrastructure/news/news_detail_reader.py`。

接口：`AgentAction` 是 search_news/read_news_detail/inspect_market/finish 的判别联合；工具输入只接受受限查询或已登记 ID；工具返回结构化 `ToolObservation`，包含结果、来源及错误码。

- [ ] 定义动作参数和输出边界：拒绝任意工具名、URL、未登记文档 ID、未知板块类型与越界窗口。
- [ ] 复用关键词搜索与锁定行情快照；登记检索结果，区分正文和摘要。
- [ ] 使用受控站点正文读取适配器，限制跳转、网络地址、大小和超时；不支持的来源返回摘要及不可用原因。
- [ ] 测试伪造 ID、正文不可用、恶意网页指令、未来信息及工具错误，验证实际公开来源能否读取。

## 阶段 3：有界循环、审计和证据回流

Files: `application/writing/agent_runner.py`、`application/writing/agent_budget.py`、`storage/ports/writing.py`、双方言 `writing/agent_execution_repository.py`、下一编号迁移、`config/prompts/attribution_agent.yaml`、`web/dependencies.py`。

接口：`run_agent_attribution` 消费 contexts/gates/tools/limits 并返回卡片、更新的证据/门禁/来源及停止原因；与工作流策略提供相同下游所需结果。

- [ ] 写脚本化模型测试：搜索→阅读→对照行情→结束；检查每轮能看到上一轮结果，次数和动作由响应控制。
- [ ] 执行器实现工具验证、去重、时限、取消、次数限制及原子共享预算预留；验证失败输出保守卡片。
- [ ] 持久化步骤和工具结果；双方言测试幂等、隔离、异常中断及新 attempt。
- [ ] 新增证据走规范化和归因门禁，引用 ID 必须真实，来源传播到写作和审核。
- [ ] 接入 RunService 与 pipeline，关闭阶段 1 的临时模式拒绝；工具不可用时给出真实原因。

## 阶段 4：用户选择与轨迹

Files: `web/src/dataRunsApi.ts`、`web/src/api.ts`、`web/src/pages/data-run/DataRunActionPanel.tsx`、`web/src/pages/DataRunPage.tsx`、`web/src/pages/RunDetailPage.tsx`、新建 `web/src/components/runs/AgentTrace.tsx`、后端轨迹查询路由。

- [ ] 生成前提供两种模式说明，默认工作流，禁止执行中切换；旧调用兼容。
- [ ] 列表与详情显示模式；按板块显示可展开工具动作、来源、费用可用性和停止原因。
- [ ] 轨迹通过持久化查询恢复，轮询结束后停止；不要展示模型隐含思维链。
- [ ] 验证选择传播、刷新恢复、错误空态和键盘操作；执行相关前端测试与构建。

## 阶段 5：系统验收

- [ ] 同输入 Fixture 比较两种模式，确认下游草稿、审核与版本规则兼容。
- [ ] 完整后端非 Live 回归、Ruff/Mypy、前端测试及构建。
- [ ] 独立 SQLite/PostgreSQL 测试库验证迁移和轨迹查询，不写业务测试记录。
- [ ] 小规模真实模型及受支持新闻详情验证；记录实际调用、来源可读性和未覆盖项，避免无上限费用。
- [ ] 更新 README 和验收文档，对照设计逐项检查后提交。

## 执行记录

2026-09-10：设计和总计划建立，开始阶段 1。其余阶段保持待执行；模式尚未对用户开放。
