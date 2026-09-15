# Phase 2：调度契约、持久化与框架适配

> **For agentic workers:** 使用 executing-plans 当前会话执行；各单元按 test-driven-development 验证。未要求提交或推送。

**Goal:** 父子任务共享可持久化预算和任务状态，并通过框架适配执行；不提前切换业务入口。

**Architecture:** 领域快照与 CAS Repository 解耦，application 负责原子预留/结算，infrastructure 包装真实框架 Provider。同一运行只有一份预算，不为每个子 Agent 新建预算。

**Tech Stack:** Python 3.12、Pydantic、SQLite、PostgreSQL/SQLAlchemy、内置 aidynamic-agent。

**Spec:** docs/superpowers/specs/2026-09-12-multi-agent-platform-design.md

**迁移依据：** [功能迁移总说明](../specs/2026-09-13-feature-migration-map.md) 的 M21（重试恢复）、M24（完整预算与审计）、M29（模型配置）、M30（双库与事务）。A/B 已实现项仅表示局部能力，不能代表这些旧功能已全部迁移。

## Global Constraints

- 领域不引用框架；框架不引用 SectorPulse。
- 保留全部已有数据；增量建表，测试只使用临时库或专用测试库。
- 每次实际模型调用，包括重试，消耗调用次数；输入估算加最大输出先预留 token。
- 用量未知、超时或取消保留预留，实际用量超过预留记录全部实际值并拒绝后续调用。
- 已结算调用不可二次退款；持久化结果冲突不能静默覆盖。
- 不存模型隐藏思维；审计只记录调用标识、角色、状态、用量与可公开行动摘要。

## A：运行快照与共享预算

文件：domain/orchestration/models.py、ports/orchestration.py、application/orchestration/budget.py；预算行为通过 backend/tests/integration/test_orchestration_storage.py 的真实临时数据库测试，避免只验证内存替身。

接口：BudgetLimits、BudgetReservation、BudgetLedger、TaskRecord、ArtifactRef、RunSnapshot；SnapshotRepository.load(run_id) 和 save(snapshot, expected_revision) -> None；SharedBudget.reserve(call_id, input_tokens, output_tokens) 与 settle(call_id, actual_tokens)。load 返回独立快照，save 原子 CAS 并记录递增 revision 事件。调用 key 由服务端生成。

- [x] 红：额度 100，两个各预留 70 的竞争请求只能一个成功；实际用量 20 结算后还可预留 70。
- [x] 红：settle(None) 不释放；同一次结算不再退款；不同用量重复结算报冲突；实际用量 120 阻止下一次调用。
- [x] 红：调用次数用尽、过 deadline 不能继续；无效负数不进入账本；任务与产物引用不得跨快照。
- [x] 绿：纯领域不可变记录 + Repository CAS 更新，冲突重试有界；持久化预留先于网络调用。

## B：双数据库存储

文件：storage/migrations/020_orchestration.sql（实施前确认上一个编号为 019），storage/orchestration/repository.py、storage/sqlite/orchestration/repository.py、storage/postgres/orchestration/repository.py；测试 backend/tests/integration/test_orchestration_storage.py。

使用两张独立表 orchestration_snapshots(run_id, revision, payload_json) 和 orchestration_events(run_id, revision, event_json)。不改原运行表，不冒用旧模式字段。JSON 快照包含任务、产物引用及预算账本；领域层验证记录，Repository 不自行执行任务。

- [x] 红：创建/重开数据库后账本与任务引用可读；相同 expected_revision 只能一次成功，失败事务不追加事件。
- [x] 红：两个独立 Repository 竞争同一额度，总预留不超预算；事件 revision 连续。
- [x] 绿：SQLite 原生连接和 PostgreSQL SQLAlchemy 连接共用存储语义；PostgreSQL 测试用例拒绝非 _test 数据库。
- [x] 运行 SQLite 迁移重复初始化回归，不删除历史数据。
- [x] PostgreSQL 真实连接验收：使用本机 PostgreSQL 18 程序在仓库 `.tmp` 隔离数据目录启动 55432 端口，并创建专用 `sector_pulse_run_comparison_test`；全部 20 个 PostgreSQL 标记测试通过，未连接现有本机服务的数据目录。

## C：框架预算适配与调度（A/B 后细化执行）

infrastructure/agents/provider.py 的 BudgetedProvider 包装框架 LLMProvider：每次 create 先 reserve，再转发带明确输出上限的模型请求，最后 settle；异常/取消 settle(None)，不吞取消。stream 暂拒绝，避免流式绕过预算。统计只从真实 usage 读取，不能用最终文本长度充当真实计费。

- [x] 实际框架 ParentAgent/SubAgent 共用同一预算，外部 Provider 使用确定性替身，验证调用被真正拒绝；取消保留预留，强制服务端输出上限。
- [x] 实现角色注册、Phase 2 最小控制工具集合、两层委派、每角色独立上下文；角色不得自定义系统权限。A0–A4 框架角色工厂、精确工具白名单、固定 Prompt、T15/T17–T19 控制工具及 T16 生产任务创建/派发组合已实现。T01–T14 属于后续 P3 业务迁移。
- [x] 任务 CAS 变更与创建事件，父取消传播，重启中断及新 attempt，最多两个研究子任务并发。只有持有有效租约的 A0 当前 attempt 可原子创建 A1–A4；同一 A2 scope 只有一个活动任务，活动 A2 总数最多两个。
- [x] 确定性模拟父子调度已验证 A0→T16 创建 A2→A2 调用受预算业务 Tool→A2 完成→A0 继续；未调用真实模型或外部数据源。Phase 2 仍须通过专用 PostgreSQL 验收后才能放行。

模型与工具预算已绑定 run/task/attempt/role 并持久化安全调用审计，但尚未关联旧用量统计投影。任务状态迁移、恢复新 attempt、工具幂等、角色工厂和父 Agent 控制工具已实现；T16 生产派发组合与生产入口仍未切换，生产数据库未运行迁移。

## D：迁移对照补齐的硬门禁（D1 部分完成，其余未实施）

本轮执行单元 D1（M24 金额账本与 Provider）：在 models.py 增加可选金额上限、预留/实际金额及未知标记；budget.py 在同一 CAS 中同时控制 token 和金额；provider.py 接收服务端价格快照，按输入/输出 usage 结算。已有不含金额字段的开发快照继续可读，但配置了金额上限后缺价格必须在外部请求前拒绝。这里不完成生产配置接线或完整审计，不标记 M24 全部完成。

D1 测试顺序：临时 SQLite 的并发金额竞争→重复/未知/超额结算→真实框架 Provider 配置缺失拦截与分项 usage 计费→现有回归。金额使用 Decimal；明确配置零单价可用于 fixture，缺单价不是免费。

- [x] D1 金额账本：同一 CAS 原子预留 token/金额，按实际金额结算，重复结算无退款，未知用量保留预留，实际超额阻止后续调用。
- [x] D1 Provider：服务端价格快照按输入/输出单价估算；有金额上限却缺价格时拒绝发请求；缺分项 usage 保留金额并标记未知。
- [x] D1 生产接线：角色工厂从现有配置取得角色路由/价格；根任务启动器从同一配置生成 token/call/tool/CNY/deadline 上限；父运行组合把预算、上下文化工具和 T16 派发绑定到真实框架。P4 前不切换现有业务入口。

本轮继续 D2（M21/M24 工具预算与幂等审计）：在同一运行快照中记录工具调用身份、任务/角色/attempt、输入指纹、终态和金额。服务层以 CAS 原子准入；重复调用返回已有记录且不得再次执行，调用号与不同输入冲突，过期 attempt 拒绝，工具金额与模型金额共同占用整次运行人民币额度。

- [x] D2 工具次数：父子任务共享 max_tool_calls，并发准入不能超额。
- [x] D2 幂等与 attempt 隔离：服务端身份+输入指纹固定调用；重放不执行，迟到 attempt 不得写入。
- [x] D2 工具金额：显式免费工具传 0；配置金额上限后未知成本拒绝准入，失败/未知结算保留预留。
- [x] D2 审计契约：只保存公开工具名、状态、任务身份、金额与安全结果引用，不保存凭据或任意结果正文。

D2 通过真实框架 Tool 装饰器接入：先持久化准入再调用内部 Tool；相同任务/attempt/工具/规范化输入生成稳定调用身份，重放从持久化产物引用读取，不重复副作用。已知失败保存 failed，取消或执行结果不确定保存 unknown；价格未知保留预留金额。

实施前细化接口、迁移编号和文件路径，不覆盖已经应用的数据库迁移；以下各项先写失败测试再实现。

- [x] M24 人民币预算：复用当前预算/价格配置，父子调用共享金额预留与结算；未知价格/usage 不显示为 ¥0，不绕过金额限制。已验证并发预留、失败重试和实际超额。
- [x] M24 工具预算：登记外部请求与工具执行成本/次数，批量调用不得绕过限制；工具超时、取消、重试均有记录。
- [x] M24 调用审计：新 Provider 请求已绑定服务端 run/task/attempt/role、provider/model、调用 ID、起止时间和安全终态，不记录提示正文、密钥或隐藏思维；统一只读投影已关联旧 `agent_invocations` 与新模型/工具账本，按调用 ID 去重并保留未知用量/金额语义。
- [x] M21 执行所有权：SQLite/PostgreSQL 均已验证租约/所有权、过期接管、新 attempt、父取消传播及多 worker CAS 竞争；旧 attempt 的模型、工具和产物迟到写入被拒绝。
- [x] M30 产物一致性：已实现受控业务持久化接口与 ArtifactRef/事件同事务写入；SQLite 验证成功提交、业务写入异常、缺失业务实体和 CAS 冲突，后三者均不会留下业务半成品或虚假索引；PostgreSQL 原子事务合同已真实通过。
- [x] M29 角色路由：现有归因、编辑、写作、审核、修订模型已显式映射 A0–A4；A3 合并角色配置冲突会报错，显式角色配置缺项不回落 fixture；生产组合实际读取这些路由和价格。
- [x] A0–A4/T15–T19：A0–A4 角色白名单、固定系统 Prompt、受限委派参数和两层角色限制已实现。T15/T17–T19 提供范围受控的有界产物读取、精确任务状态、等待人工选择及服务端完成策略；T16 生产组合原子创建子任务并运行真实框架 SubAgent。P3 的 T01–T14 仍按各业务阶段迁移。

Phase 2 放行：A–D 已全部实现，并通过 SQLite、专用 PostgreSQL 和确定性真实框架轨迹验收。Phase 2 于 2026-09-13 放行；下一步进入 P3a，仍不删除或切换旧入口。

## 2026-09-13 验证记录

- 全量非 live/live_llm/postgres 回归：531 passed、5 skipped、25 deselected（包含前 12 项新增测试）。
- 随后增加参数绕过回归，拒绝 n/extra_body/stream 等未审计选项；最新专项测试：13 passed、1 skipped。跳过的是缺少专用 PostgreSQL URL 的合同测试。
- Ruff 通过；Mypy 239 个源文件通过。新增第 020 版迁移后更新原迁移版本断言；仓储实现放入各自 orchestration 子目录，未放宽目录约束测试。
- 测试只使用临时 SQLite 数据库和模拟模型端点；没有消耗真实 LLM 额度。快照可恢复不等于任务自动恢复已经实现。

### D1 金额账本本轮验证

- 测试先行：金额用例首次 5 failed（缺金额契约），Provider 用例首次 3 failed（缺价格适配），随后实现通过。
- 专项：22 passed、1 skipped；全量离线回归：541 passed、5 skipped、25 deselected。
- Ruff 通过；Mypy 242 个源文件通过。跳过项缺专用 PostgreSQL 测试连接，未宣称 PostgreSQL 真实验收。
- 命令：`.venv/Scripts/python.exe -m pytest -q -m 'not live and not live_llm and not postgres' --import-mode=importlib -p no:cacheprovider --basetemp=.tmp-test/cny-regression-0913`。
- 无生产数据库迁移、无真实模型费用、无提交推送。新字段放在现有编排 JSON 快照中，不修改已存在迁移脚本。

### D2 工具预算本轮验证

- 测试先行：核心服务首次 6 failed（模块尚不存在），框架适配首次 3 failed；启用金额上限后的无价格历史首次 2 failed，均按预期证明测试能捕获缺口。
- 专项：33 passed、1 skipped；全量离线回归：552 passed、5 skipped、25 deselected。
- Ruff 通过；Mypy 244 个源文件通过。未调用真实 Tool、网络、LLM 或生产数据库。
- D2 只完成通用预算与适配层；T01–T19 的业务工具、角色白名单和生产金额配置接线仍未完成。

### M21 状态机、角色工厂与调用审计本轮验证

- 测试先行：任务状态/租约首次 6 failed（协调模块不存在）；续租与模型 attempt 绑定首次 2 failed；中断租约首次 1 failed。角色工厂/配置首次 6 failed；生产角色配置组合首次 1 failed；模型完整审计首次 2 failed。
- SQLite 状态机验证合法迁移、父取消向未结束子任务传播、worker 所有权、租约续期、仅租约过期接管、新 attempt，以及旧 attempt 的模型、工具和产物迟到结果拒绝。PostgreSQL 同合同已加入，因未配置专用 `SECTOR_PULSE_TEST_DATABASE_URL` 跳过。
- A0–A4 角色工厂实际构造内置框架 `ParentAgent`/`SubAgent`；真实模拟轨迹执行 A0 模型→受限 delegate→A2 模型→A0 继续。角色工具采用精确白名单，子角色不能获得 delegate，模型输入不能提供 system prompt/toolsets 扩权。
- Provider 审计新增 provider/model、run/task/attempt/role、调用 ID、起止时间与 succeeded/failed/unknown 安全终态。取消保留预算并记 unknown；未记录消息正文、凭据或隐藏思维。
- 真实父子轨迹发现并修复模型预算更新丢失工具审计的缺陷；新增交错账本回归确保模型 reserve/settle 保留已有 ToolInvocation。
- 随后补齐原子子任务创建、同 scope 隔离和最多两个活动 A2 的 SQLite 三方竞争测试，并把 A0 白名单工具名严格对齐 T15–T19。最新专项：54 passed、2 skipped；全量离线回归：573 passed、5 skipped、26 deselected。Ruff 通过；Mypy 244 个源文件通过。未调用真实 LLM、网络、生产数据库，也未提交或推送。
- 尚未完成：T15/T17–T19 生产工具、旧用量统计投影、生产入口组合，以及专用 PostgreSQL 真实验收；Phase 2 继续保持部分完成。

### M30 业务产物原子事务本轮验证

- 测试先行：4 个 SQLite 场景首次均因原子产物模块和 Repository `save_atomic` 契约不存在而失败；随后以最小实现通过。
- 业务持久化由受控 `ArtifactPersistence` 适配器执行，不向 Agent 暴露通用保存或 SQL 能力。提交前校验当前 task/attempt/role、worker 所有权和有效租约；业务写入、存在性确认、快照 CAS 与事件处于同一事务。
- 专项：18 passed、2 skipped；全量离线回归：577 passed、5 skipped、27 deselected。Ruff 通过；Mypy 245 个源文件通过。
- 两个专项跳过项和新增 PostgreSQL 原子合同均要求专用 `_test` 数据库；当前未提供连接，因此没有宣称 PostgreSQL 真实验收。未调用真实 LLM、网络或生产数据库。

### T15/T17–T19 父 Agent 控制工具本轮验证

- 测试先行：控制服务首次 6 failed（模块不存在）；框架交互适配首次 1 failed（类不存在）；A2 按类型读取的跨 scope 隔离及 T17 公开失败码也分别先失败再实现。
- T15 返回有界摘要和安全结构化数据，显式请求越权产物会拒绝，按类型浏览会隐藏其他 A2 scope；T17 仅允许当前 A0 attempt 读取精确状态、当前 attempt 产物引用和公开错误码。
- T18 只把根任务转为 `waiting_user_selection`，不会创建用户确认；T19 的目标和当前版本校验由服务端策略绑定，数据准备目标可完成，完整分析至多进入 `waiting_user_review`，不会替用户批准。策略与任务转移在 CAS 重试的同一快照上再次校验。
- 专项：37 passed、2 skipped；全量离线回归：584 passed、5 skipped、27 deselected。Ruff 通过；Mypy 247 个源文件通过。未调用真实 LLM、网络、外部数据源或生产数据库。
- 尚未完成：P3 的 T01–T14 业务工具和 P4 业务入口切换；这些不再阻塞已经完成的 Phase 2。

### M24 旧用量统计关联本轮验证

- 测试先行：统一投影首次因模块不存在失败；运行存储暴露投影的合同也先因字段不存在失败。
- 投影同时读取旧 `agent_invocations` 与新编排账本，调用 ID 相同以新权威记录覆盖旧行，避免双计；模型和工具分别保留 task/attempt/role、终态、已知成本及安全结果引用，不复制 prompt、输入哈希或结果正文。
- 未知模型 usage/金额继续为 `None` 并设置 unknown 标志；汇总只累计已知值，同时显式报告是否存在未知项，不把保守预留伪装成实际 ¥0。
- 专项：18 passed；全量离线回归：585 passed、5 skipped、27 deselected。Ruff 通过；Mypy 248 个源文件通过。SQLite 运行存储已接线，PostgreSQL 复用同一投影与仓储协议但仍缺专用库实测。

### T16 生产组合与预算配置接线本轮验证

- 测试先行：根任务启动器和父运行组合首次 2 failed（模块不存在）；角色过期租约构造首次未拒绝，随后补齐门禁。
- 根任务启动器从生产 LLM 配置创建 A0、共享预算和统一 deadline/租约；父运行组合按 task/attempt/role/scope/worker 动态构造工具，避免把服务端身份交给模型。
- T16 要求模型提供注册角色、目标、明确 scope 和产物引用，拒绝 system prompt/toolset/权限覆盖；派发通过任务 CAS 原子创建新 attempt=1 子任务，运行内置框架 SubAgent，并以公开安全错误码结束失败任务。
- 确定性轨迹实际执行 A0 模型→Budgeted delegate→新 A2 SubAgent→Budgeted `submit_analysis` Tool→A2 完成→A0 继续；父子共享同一账本且审计分别绑定正确任务。
- 专项：26 passed、1 skipped；全量离线回归：588 passed、5 skipped、27 deselected。Ruff 通过；Mypy 250 个源文件通过。未调用真实 LLM、网络、外部数据源或生产数据库。
- 首次真实 PostgreSQL 全套运行发现 3 个可重复失败：原子产物夹具表名漂移、恢复合同沿用旧 `supervisor` 角色、运营查询测试假设共享库只有一行。逐项定位后分别修正测试契约与自清理，三个专项各自通过。
- 最终 PostgreSQL 标记回归：20 passed、600 deselected；完整非 Live（含 PostgreSQL）回归：613 passed、7 deselected。Ruff 通过；Mypy 250 个源文件通过。

## 2026-09-14 后续整体验证注记

Phase 2 的历史放行结论不变。完成 P3b 后，使用本机隔离 PostgreSQL 18、55434 端口和专用 `sector_pulse_run_comparison_test` 重新运行全项目合同：PostgreSQL 标记 23 passed、646 deselected；完整非 live 为 662 passed、1 skipped、6 deselected；Ruff 通过，Mypy 284 个源文件通过。新增数量来自后续 P3a/P3b 业务迁移，不把它们倒算为 Phase 2 的实施范围，也不表示 P3/P4 已完成。

## 2026-09-15 后续整体验证注记

Phase 2 的历史放行结论继续不变。P4 单元 C 唯一入口切换后，全量离线回归为 697 passed、19 skipped、36 deselected；本机 PostgreSQL 18 专用 `sector_pulse_run_comparison_test` 标记合同为 28 passed、724 deselected；Ruff 通过，Mypy 301 个源文件通过。新增数量属于 P3/P4，不倒算为 Phase 2 实施范围，也不表示 P4 或完整迁移已经完成。

## 2026-09-15 当前工作区验证注记

本轮继续补齐父 Agent 恢复入口：应用启动时通过 `MultiAgentRunCommands.recover_expired` 扫描编排快照，仅对根任务租约已过期且仍为 `running`/`interrupted` 的任务调度 `MultiAgentRunService.recover`；恢复使用新的 worker 和 attempt，未过期租约不会接管。新增 SQLite 集成测试覆盖过期恢复及重复恢复保护。

当前工作区后端离线回归为 748 passed、55 skipped；Ruff 和 Mypy 通过。55 个跳过项包含未配置专用 PostgreSQL 测试连接、真实数据和真实 LLM 场景，因此本轮没有宣称 PostgreSQL 或真实 LLM 重新验收。文档中的历史 PostgreSQL 数字保留为历史记录，不代表当前环境已经重新执行。

### 2026-09-15 真实 A0→A4 长链路验收

- 新增显式 opt-in 的 `live_llm` 长链路验收：真实 `deepseek-flash` 负责 A0 调度、A1 选题、三个 A2 归因、A3 大纲与草稿、A4 独立审校；行情、新闻仍使用确定性 sandbox，持久化使用临时 SQLite。最终验收 1 passed，136.99 秒，根任务进入 `waiting_user_review`，没有自动批准。
- 真实运行暴露并修复：A3 输入产物服务端规范化、证据检查跨任务 ID 冲突、编辑产物身份比较、角色按 scope 精确装配工具、A3 权威板块 ID 注入、A3 8192 输出上限、可操作的提纲/草稿校验反馈，以及 A3/A4 缺必需产物时同一租约/attempt 内最多两次纠错回合。
- A4 的 review scope 不再信任父模型填写；生产组合从唯一草稿产物及草稿仓库生成精确 `draft_id/version`，错误或多份输入仍拒绝。A4 PASS 仍只进入人工审阅状态。
- 当前代码全量离线回归为 750 passed、25 skipped、31 deselected；Ruff 全仓通过；Mypy 306 个源文件通过。跳过项是未在该命令中注入数据库变量的 PostgreSQL合同及真实外部数据场景。
- 本机 PostgreSQL 18 服务真实验收使用两个专用库：核心合同 `sectorpulse_test` 19 passed，比较合同 `sector_pulse_run_comparison_test` 9 passed，共 28 passed；未连接或写入 `sectorpulse_runtime`。
- 本轮未提交、未合并、未推送。当前检出分支实际为 `main`（ahead 7），与早期记录中的 `codex/attribution-agent-modes` 不一致；为保护未提交有效改动，未执行 checkout/reset/stash。
