# 双模式归因实施计划

> 执行方式：当前会话执行，使用 executing-plans，逐阶段验证。用户已授权连续实施，不重复询问执行方式。

**Goal:** 用户可选择节省 Token 的工作流模式，或有工具决策循环的 Agent 归因模式。

**Architecture:** 在现有内容运行输入上增加模式，抽离归因执行策略；工具结果经程序校验、存储和证据门禁后回流到写作。Agent 步骤由模型决定，执行器限制次数、时间、费用及访问范围。

**Tech Stack:** Python/Pydantic/asyncio、现有 LLMPort 与 Provider、SQLite/PostgreSQL、React/TypeScript。

**Spec:** `docs/superpowers/specs/2026-09-10-attribution-agent-modes-design.md`

## 全局约束

> 最新状态：阶段 1–4 的首期功能已接线，阶段 5 正在收尾；以下旧执行记录保留为历史。真实多工具链路、同输入对比及跨重试工具缓存复用尚未验收，不表示总计划全部完成。

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

- [x] 测试旧请求默认、非法模式拒绝、生成请求传播、工作流内容重试保留模式；Agent 执行重试在阶段 3 接线后验收。
- [x] 将模式写入规范化的输入快照及摘要/详情返回值。
- [x] 在 Agent 未接线时同步拒绝该模式，避免误用工作流代替 Agent；接线测试通过后移除临时拒绝。
- [x] 运行相关 API 和服务回归，检查类型与导入，提交阶段结果。

## 阶段 2：工具及新闻详情

Files: `domain/writing/agent_execution.py`、`ports/attribution_tools.py`、`ports/news_detail.py`、`application/writing/agent_tools.py`、`infrastructure/news/news_detail_reader.py`。

接口：`AgentAction` 是 search_news/read_news_detail/inspect_market/finish 的判别联合；工具输入只接受受限查询或已登记 ID；工具返回结构化 `ToolObservation`，包含结果、来源及错误码。

- [x] 定义动作参数和输出边界：拒绝任意工具名、URL、未登记文档 ID、未知板块类型与越界窗口。
- [x] 复用关键词搜索接口与上下文锁定行情；在单板块工具上下文登记检索结果，区分正文和摘要。
- [x] 使用受控站点正文读取适配器，限制跳转、网络地址、大小和超时；不支持的来源返回摘要及不可用原因。
- [x] 测试伪造 ID、正文不可用、恶意网页指令、未来信息及工具错误；实际公开来源进行了小样本验证，不承诺全站支持。

## 阶段 3：有界循环、审计和证据回流

Files: `application/writing/agent_runner.py`、`application/writing/agent_budget.py`、`storage/ports/writing.py`、双方言 `writing/agent_execution_repository.py`、下一编号迁移、`config/prompts/attribution_agent.yaml`、`web/dependencies.py`。

接口：`run_agent_attribution` 消费 contexts/gates/tools/limits 并返回卡片、更新的证据/门禁/来源及停止原因；与工作流策略提供相同下游所需结果。

- [x] 写脚本化模型测试：搜索→阅读→对照行情→结束；检查每轮能看到上一轮结果，次数和动作由响应控制。
- [x] 执行器实现工具验证、去重、时限、取消、次数限制及原子共享预算预留；验证失败输出保守卡片。
- [x] 持久化步骤和工具结果；双方言测试幂等与隔离，运行测试取消与新尝试。新尝试使用新 run_id/retry_of，不具备中间轮次恢复。
- [ ] 新增证据走规范化和归因门禁，引用 ID 必须真实，来源传播到写作和审核。
- [x] 接入 RunService 与 pipeline，关闭阶段 1 的临时模式拒绝；工具不可用时给出真实原因。

## 阶段 4：用户选择与轨迹

Files: `web/src/dataRunsApi.ts`、`web/src/api.ts`、`web/src/pages/data-run/DataRunActionPanel.tsx`、`web/src/pages/DataRunPage.tsx`、`web/src/pages/RunDetailPage.tsx`、新建 `web/src/components/runs/AgentTrace.tsx`、后端轨迹查询路由。

- [x] 生成前提供两种模式说明，默认工作流，禁止执行中切换；旧调用兼容。
- [x] 列表与详情显示模式；按板块显示可展开工具动作、来源、费用可用性和停止原因。
- [x] 轨迹通过持久化查询恢复，轮询结束后停止；不要展示模型隐含思维链。
- [x] 验证选择传播、持久化轨迹重新读取和轮询停止，提供错误空态及原生键盘控件；前端测试与构建通过。并非所有错误分支均有浏览器用例。

## 阶段 5：系统验收

- [x] 同输入 Fixture 比较两种模式，确认下游草稿独立、初始版本一致、均等待人工审核，且只有 Agent 产生工具结果。
- [x] 完整后端非 Live/非 PostgreSQL 专项回归、Ruff/Mypy、前端测试及构建；数据库专项另测。
- [x] 独立 SQLite/PostgreSQL 测试库验证迁移和轨迹查询，不写业务测试记录。
- [x] 小规模真实模型及受支持新闻详情验证；记录实际调用、来源可读性和未覆盖项，避免无上限费用。
- [ ] 更新 README 和验收文档，对照设计逐项检查后提交。

## 执行记录

2026-09-10：设计和总计划建立，开始阶段 1。其余阶段保持待执行；模式尚未对用户开放。

2026-09-10 首批实现：阶段 1 完成。阶段 2 的工具契约、缓存、时间过滤及正文读取适配代码已实现；HTTP 形状通过模拟响应验证，真实站点尚未验收。阶段 3 的独立决策循环核心已通过脚本化模型测试，但整次预算预留、持久化和新增证据回流未接线。正式入口的 Agent 模式仍同步返回 `AGENT_MODE_UNAVAILABLE`，前端暂不开放。

验证：相关 API/服务 19 passed；工具及循环 20 passed；后端非 Live 全量 499 passed、4 skipped、24 deselected（之后新增的 3 项 HTTP 模拟响应测试已在上述工具组单独通过）；Ruff 通过，Mypy 221 个源文件通过。此轮没有请求真实模型或新闻源，没有业务数据库迁移。工作目录中的原有行情质量和前端修改保留。

下一批顺序：先完善阶段 2 的公开原文源实际验证，再完成阶段 3 的双方言步骤存储、共享预算、证据门禁重算与来源回流，接通 Agent 路由后执行阶段 4 前端和阶段 5 验收。

### 2026-09-10 第二批实现与验收（最新）

已接通 AgentRuntime、配置化 Prompt、共享 BudgetedLLM、019 轨迹迁移、SQLite/PostgreSQL 仓库及查询接口。生成前可选模式，运行详情提供持久化工具轨迹和 2 秒串行轮询。修正了最后一次工具结果未回流的问题，以及并行任务中存储失败后其他任务继续消耗模型额度的问题。

新增来源保存真实事件 ID，传播到写作/审核，但仅作为背景，不提高历史因果门禁；因此阶段 3 的“门禁重算”目标仍未完整勾选。重试是有来源关系的新运行，不是跨尝试恢复缓存。

验证结果：

- 后端：512 passed、5 skipped、24 deselected；跳过的是需专用 PostgreSQL 配置的用例，排除了 live/live_llm/postgres 标记。使用 `--import-mode=importlib -p no:cacheprovider` 和 `.tmp-test` 下全新唯一目录，规避现有同名测试导入与旧临时目录权限问题。
- Ruff 全量通过；Mypy 226 个源文件通过。
- 前端：63 个测试文件、245 项通过；生产构建通过。既有审核页面测试仍输出 React act 警告，不影响本轮通过结果。
- Agent 浏览器专项：1440px 和 390px 两项通过，使用明确标记的合成数据；检查模式请求、展开轨迹和横向溢出。截图位于本地忽略的 `web/test-results`，不冒充真实运行截图。
- SQLite 与已有专用 `sectorpulse_test` 数据库轨迹专项 2 项通过，验证 019 迁移、幂等写入、隔离和重读。仅清理测试生成的精确 UUID 记录，未修改业务库记录。
- 公开正文小样本：东方财富 `https://finance.eastmoney.com/a/202609093869515766.html` 返回 full_text，1770 字符；财联社 `https://www.cls.cn/detail/2412980` 返回 ARTICLE_CONTENT_TYPE_UNSUPPORTED。样本结果不代表这些站点的全部页面。
- 真实模型 `deepseek-v4-flash`：合成行情、最多两轮预算的兼容性探测，实际 1 轮决策、0 次工具、3819 Token、合法保守结论。未生成业务草稿；模型价格缺失，不能将费用当成零。

界面复查采用当前会话内联方式，使用 impeccable 的局部扩展准则：沿用现有设计规范，原生单选框与展开控件保留键盘能力，修正隐藏的展开指示符，不重做全站设计系统。复查范围限模式选择与查证轨迹，不代表整站独立审计。

待完成：同输入双模式比较、真实模型主动检索/阅读/行情对照的完整闭环及质量评估；可验证历史全文与门禁提升、跨重试缓存复用另列后续能力。README、设计边界与本记录已同步，但尚未提交、合并或推送本批改动。

### 后续验收：同输入比较与真实工具决策

新增 `test_same_input_modes_keep_drafts_isolated_and_require_human_review`：复用完全相同的 contexts/gates，分别执行 workflow 和 agent。两者均停在 READY_FOR_HUMAN_REVIEW，草稿 ID 不同，初始版本均为 1，章节对应板块一致；workflow 无 Agent 轨迹，agent 有实际工具结果。整个 AgentRuntime 集成测试文件 4 项通过。该用例是既有行为的补充验收，不是一次新增生产逻辑的红绿修复。

真实模型探测：`deepseek-v4-flash`，生产 AgentRuntime/新闻检索/行情工具，单板块合成行情，独立 SQLite 数据库 `.tmp-test/agent-live-urol_z3d/probe.db`。使用标记为 isolated-probe 的提示词补充说明演练目标，工具选择不由脚本预设。限制最多 4 轮决策、3 次工具、120 秒、200000 Token 预留；价格未知，未将金额视作可靠硬上限。

实际结果：3 次模型决策，18016 Token；依次自主调用 search_news、inspect_market，然后合法 finish。检索成功，8 条背景事件及 8 条来源回流，因果门禁未提高。模型没有选择 read_news_detail，因此不能据此宣称真实模型阅读原文分支已验收。数据库与轨迹仅保存在隔离测试目录，未创建业务运行/草稿，没有修改业务 PostgreSQL。

剩余验收收窄为：再次验证真实模型在“仅摘要可用”观察后的纠正决策、真实同输入双模式的最终草稿质量/耗时/用量对比。受控原文读取适配器的独立公开页面验证已有记录，但不能替代模型决策链路验证。

### 原文读取专项结果（2026-09-10）

隔离探测中模型自主执行了 `search_news → read_news_detail`。详情读取按站点能力返回 `summary_only` 与 `UNSUPPORTED_ARTICLE_SOURCE`，没有伪装成全文；随后模型提交了不符合证据门禁的引用，执行器返回 `AGENT_INVALID_CONCLUSION` 并生成保守回退卡片，没有写入错误草稿。该结果验证了“详情不可用”和“非法引用拦截”两道防线，但暴露出 Prompt/观察反馈仍需增强：模型需要明确把不可用详情当作背景、不得放入 supporting_evidence_ids，并在失败后重新决策或直接提交合法的无证据结论。

随后已修正执行器：非法结论现在作为 `validation_feedback` 观察交回模型，剩余决策轮次内允许纠正；轮次耗尽仍保守回退。回归测试覆盖“先非法引用、再合法结论”，与 AgentRuntime 合计 13 项通过；完整非 Live 回归为 514 passed、5 skipped、24 deselected。此前真实探测仍作为失败前基线保留，尚未消耗额度重复运行。
