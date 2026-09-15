# Phase 4：唯一入口、历史兼容与产品验收实施计划

状态：**完成。**Phase 2 与 P3a–P3c、P4 单元 A/B/C/D 已放行；单元 E（人工审核、编辑、批准、撤销与导出接线）四项全部完成并验证；单元 F（前端移除双模式并展示动态任务树）五项全部完成并验证；单元 G（清理、回退证据与最终验收）五项全部完成并验证。全部新建入口已证明使用新引擎，父子多 Agent 重构完成。未执行提交、合并或推送。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本项目按用户要求在当前会话直接执行，禁止创建子代理，也不执行计划模板通常建议的提交步骤。

**Goal:** 将 API、定时任务、重试和 CLI 统一切换到父 A0 调度 A1–A4 的唯一执行器，保留 fixture/live 数据来源选择、人工选择/编辑/批准/撤销、全部历史读取和可回退数据库结构，并移除前端与请求中的 workflow/agent 双模式。

**Architecture:** 新建一个应用层 `MultiAgentRunService` 作为所有新运行的组合根，负责创建根任务、选择 fixture 或 live 的确定性业务依赖与框架 LLM provider、驱动等待人工节点及恢复。现有 `/api/runs`、`/api/data-runs`、调度和 CLI 作为薄适配入口；旧 Phase1B/real-data 行只读，不补造任务树。查询层按 `execution_engine` 联合新编排投影与旧表，人工审核 API 继续调用原领域服务但校验当前新草稿版本。P4 最后才删除无调用的旧模式分支和 Prompt，不删除历史表或仍复用的领域函数。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、aidynamic-agent 0.3.0、SQLite、PostgreSQL/SQLAlchemy、React/TypeScript、Vitest、Playwright、pytest、Ruff、Mypy。

**Spec:** `docs/superpowers/specs/2026-09-13-feature-migration-map.md`（M20/M22/M23/M25–M30、T15–T19）

## Global Constraints

- 新建运行只能使用 `execution_engine=multi_agent`；fixture/live 仍是数据与模型依赖选择，不是执行模式。
- 请求显式携带 `attribution_mode`、`workflow` 或 `agent` 时返回 422 和迁移提示，不静默忽略。
- fixture 必须运行真实 `ParentAgent`/`SubAgent` 与预算 Tool，不回落旧 pipeline。
- live 必须显式 consent、完整 provider 配置和已知模型价格；缺一项在落库前失败，不静默使用 fixture。
- 历史运行、稿件、人工补丁、证据决定、批准/撤销与导出保持可读；旧记录不补造新任务或推断未记录状态。
- 人工动作不注册为 Agent Tool；A4 PASS 只进入 `WAITING_USER_REVIEW`。
- PostgreSQL 只连接数据库名含 `_test` 的专用连接；切换前备份由用户或部署流程显式执行，不在测试中操作生产库。
- 每个独立单元先红测，再最小实现，并运行专项、Ruff、Mypy、前端测试（涉及 UI 时）和完整非 live。

## 单元 A：新运行命令与框架 provider 组合根

**Interfaces**

- `MultiAgentRunService.create(request, provider, retry_of_run_id=None) -> UUID`
- `AgentProviderFactory.build(role_runtime, provider) -> LLMProvider`
- `FixtureAgentProvider` 返回脚本化框架响应；`live` 使用 vendor `OpenAIProvider`，不经过旧结构化单次调用适配器。
- 根快照保存 `execution_engine=multi_agent` 所需的可查询元数据、预算、deadline 和 retry_of；不先写旧 Phase1B RUNNING 行。

- [x] 写失败测试：fixture 创建真实 A0 根任务并进入 A1，模型/Tool 审计有 run/task/attempt/role；旧 `run_real_data_workflow`、`run_phase1b_pipeline` 和旧 AgentRuntime 一调用即失败。
- [x] 写失败测试：live consent、API key/base URL/model 和模型价格在任何业务写入前校验；未知价格不允许把人民币预算当作 ¥0。
- [x] 实现 vendor `OpenAIProvider` 的生产构造、fixture 框架 provider 与统一关闭生命周期；保持 config role_routes 为唯一角色路由。
- [x] 用临时 SQLite 跑确定性创建/取消/恢复，并在专用 PostgreSQL 跑相同创建合同。
- [x] 在全部脚本化测试通过后，用已配置 deepseek-flash 做一次有严格 token/调用/金额/deadline 上限的只读 Tool Agent 验收；若价格或连接配置不完整则如实跳过，不修改生产数据。

**单元 A 放行证据（2026-09-14）：** 新增 `MultiAgentRunService`、框架原生 `FixtureAgentProvider` 与 vendor `OpenAIProvider` 组合工厂；新快照明确记录 `execution_engine=multi_agent`、provider 与 retry lineage。SQLite 验证创建、幂等取消及仅过期租约可恢复且生成 attempt 2；专用 `_test` PostgreSQL 验证相同 A0→A1、模型/Tool 审计与取消合同。专项（含 PostgreSQL）150 passed；全量非 live 678 passed、32 skipped；Ruff 通过；Mypy 294 个源文件通过。真实 DeepSeek 验收使用临时 SQLite、只读 `inspect_tasks`、最多 3 次模型调用/12000 tokens/2 次 Tool/¥0.10/60 秒边界，6 项 live/config 测试通过。`deepseek-flash` 按官方高峰价输入 ¥3/百万 token、输出 ¥9/百万 token 保守预留，不推断缓存或低谷折扣。该证据只放行单元 A，不代表 P4 完成。

## 单元 B：人工选择暂停与同根任务恢复

**Interfaces**

- A0 `request_selection` 后根任务为 `WAITING_USER_SELECTION`；确认 API 追加 selection vN 并恢复同一根任务的新 attempt/租约。
- 定时运行只在创建时固化 `manual` 或 `server_default` 策略；父 Agent 不能改变策略。

- [x] 写失败测试：交互运行等待人工确认；确认 3–12 个候选、版本 CAS 和候选集合校验继续由原服务执行。
- [x] 写失败测试：确认后恢复同一 run，不重新采集、不创建竞争根任务；旧等待 attempt 的迟到调用全部拒绝。
- [x] 写失败测试：定时默认选择只使用创建时授权策略，一次触发只创建一个逻辑根任务。
- [x] 实现选择桥、恢复命令和双库事务/幂等合同。

**单元 B 放行证据（2026-09-14）：** 新增人工拥有的 `SelectionResumeService` 与 034 迁移，候选确认继续强制 3–12 个、唯一、属于固定提案并按提案次序固化；选择业务行、`candidate_selection` ArtifactRef 和同一 A0 根任务 attempt 2/lease claim 在一个原生数据库事务中提交。SQLite 双 worker 与 PostgreSQL 双 worker 均只有一个 version/claim 获胜；旧 attempt 模型调用被拒绝。`MultiAgentRunService.confirm_selection` 在同一 run/root 上继续真实框架，`server_default` 只有创建时固化该策略才可用，重复 run ID 不创建第二根任务。专项 54 passed；全量非 live 687 passed、33 skipped；PostgreSQL 标记 28 passed、690 deselected；Ruff 通过；Mypy 297 个源文件通过。该证据只放行单元 B，尚未表示 API、调度或 CLI 已切换。

## 单元 C：API、重试、取消、定时与 CLI 唯一化

**Interfaces**

- 保留现有资源 URL，`POST /api/runs` 与 data-run generate/retry 内部统一进入 `MultiAgentRunService`。
- 新响应含 `execution_engine: "multi_agent"`；旧查询返回 `execution_engine: "legacy"`。
- CLI 提供一个新建/恢复入口；旧 `phase1b-draft` 仅保留历史诊断或明确拒绝新运行。

- [x] 写失败契约：显式旧 `attribution_mode` 返回 422；fixture/live 都进入新服务；未配置 live 不落库。
- [x] 写失败测试：取消传播到未结束子任务；重跑使用保存的输入/快照创建新 run/root 并记录 retry_of，不修改旧记录。
- [x] 写失败测试：调度、API 和 CLI 不能导入或调用旧执行器；路由错误码与安全信息稳定。
- [x] 实现薄适配器并删除新建路径的双模式分支；保留旧查询依赖。
- [x] 跑 FastAPI、CLI、scheduler、SQLite/PostgreSQL 合同与全量后端回归。

**单元 C 放行证据（2026-09-15）：** 默认 Web 组合根、`POST /api/runs`、定时触发、内容重试/取消、历史 data-run generate/retry 和 CLI 均已接入 `MultiAgentRunService`/`MultiAgentRunCommands`。历史 data-run generate 复用原 run ID，把服务器确认的 selection 版本固化为 A0 根任务输入 ArtifactRef；历史重试创建新 run/root 并保存 `retry_of`。旧 `phase1b-draft` 新建命令已从 CLI 移除，旧 `/api/data-runs` 直接新建端点返回 410 迁移提示；资源查询、人工选择和历史兼容仍保留。新建分析页的 fixture/live 均只调用 `/api/runs`，数据页不再显示或提交 workflow/agent 模式。统一查询同时返回新编排快照和未改写的历史记录，并按 run ID 去重。最终全量离线回归 `697 passed、19 skipped、36 deselected`；本机 PostgreSQL 18 专用 `sector_pulse_run_comparison_test` 标记合同 `28 passed、724 deselected`；前端 Vitest `245 passed` 且生产构建通过；Ruff 全通过，Mypy `301 source files` 全通过。单元 A 已完成的 DeepSeek Flash 有界真实 LLM 验收仍有效，本单元未重复消耗真实 LLM。该证据只放行单元 C，不表示 P4 或完整迁移完成。

## 单元 D：新旧统一查询、任务树和资源双向定位

**Interfaces**

- `GET /api/runs/{run_id}/tasks` 返回任务、parent、role、scope、attempt、lease-safe status、产物和公开错误。
- 新运行详情从编排/业务产物投影；旧运行继续读取原表并明确 `legacy`/`not_recorded`。
- run→sector→draft→review 及 draft/review→run 链接都来自持久化 ID。

- [x] 写失败测试：刷新后任务树、预算、模型/工具审计与产物引用一致；子任务完成不等于根运行完成。
- [x] 写失败测试：旧记录不补造任务树、不把未记录解释成失败；旧稿、版本、批准记录和 retry_of 继续可读。
- [x] 写失败测试：运营、对比、系统状态与影子验收同时统计 legacy/multi_agent，未知成本保持未知。
- [x] 实现查询投影、API schema 和双库索引；不复制正文进编排事件。

**单元 D 放行证据（2026-09-15）：**

发现并修复了两个真实缺陷，都是"读出来的运行和落库的运行不一致"：

1. **刷新后时间漂移。** `MultiAgentRunQueryAdapter.get_run` 每次读取都用 `datetime.now(UTC)` 重新计算 `requested_at`，同一次运行刷新两次会得到两个时间。红测断言 `first == second` 失败后，改为在 `RunSnapshot` 上持久化 `requested_at`（由服务器时钟在 `OrchestrationRunStarter.start` 写入一次），查询层只投影落库值。
2. **运营面板结构性看不到新引擎。** `RunSnapshot` 不记录停止时间，`SQLiteOperationsQuery`/`PostgresOperationsQuery` 也只读 `phase1b_runs` 与 `real_data_runs`，因此多 Agent 运行在 `summary`/`trend`/`recent_runs` 里完全不存在，`completed_today` 对新引擎结构性地不可能。新增 `finished_at`，只由根任务盖章（子任务完成不等于运行结束），并新增 `application/operations/orchestration_projection.py` 把编排快照投影成运营口径。

其余验证结果：

- 新旧引擎按 `run_id` 合并，agent 快照优先于同 ID 的旧行，避免续接到新引擎的数据运行被重复计数（`merge_operational_runs`）。
- 未知成本保持未知：ledger 有未定价/未结算调用时 `total_cost_cny` 投影为 `None`，不回落成 ¥0；`elapsed_ms` 同样为 `None`，因为快照不记录墙钟时长。
- `WAITING`/`WAITING_USER_SELECTION`/`WAITING_USER_REVIEW`/`INTERRUPTED` 计入"需关注"但**不**计入"失败"——等待人不是失败，被中断是可恢复的。
- API schema 新增 `OperationsRecentRun.execution_engine`（`legacy`/`multi_agent`），运营总览与系统状态页共用同一份 `/api/operations/summary` 数据。
- 旧记录不补造任务树：`GET /api/runs/{run_id}/tasks` 对旧运行返回 `recording=not_recorded` 与空任务，不把"没有记录"解释成失败；新增集成测试证明旧运行的草稿 v1/v2、批准记录（含 actor/时间）与 `retry_of_run_id` 在重构后仍逐字可读。
- 影子验收对引擎无依赖：它按 `run_id` 记账，只存在于编排快照里的运行同样能登记并计入进度（新增测试证明，未改动生产代码）。
- 编排事件只存事件名：`event_json` 永远是 JSON 字符串，正文与快照 payload 不会复制进事件表（新增测试在真实 fixture 运行上断言）。

**验证命令与结果：** 专项 `test_operations_query.py`、`test_operations_summary_api.py`、`test_phase3_shadow_api.py`、`test_multi_agent_run_service.py`、`test_legacy_records_stay_readable.py` 全绿；Ruff 通过；Mypy 302 个源文件通过（较单元 C 的 301 增加 1）；前端 Vitest 245 passed（63 文件）；完整非 live 回归 **728 passed、25 skipped**。

**与单元 C 基线口径差异说明（未解释清楚，需后续核实）：** 单元 C 记录的是 `697 passed、19 skipped、36 deselected`。本次无法复现该口径，也**没有**找到能对上差额的可靠解释，因此不把它当成可比基线。已核实的事实：

- 默认 `prepend` 导入模式下本次回归**完全无法运行**：`backend/tests/unit/domain/test_candidate_selection.py` 与 `backend/tests/unit/application/data_runs/test_candidate_selection.py` 同名且目录下无 `__init__.py`，pytest 在收集阶段 `import file mismatch` 并中断整个运行（`Interrupted: 1 error during collection`）。断言和前缀都指向同名冲突，与本次改动无关；这两个文件都在版本库中、且本次未修改。
- 改用 `--import-mode=importlib` 后收集恢复正常。这两个文件合计只有 10 个测试，**不足以解释** 697→728 的 31 个差额，所以本文件先前那句"差额来自此前未被收集的测试"是错的，已删除。
- 本次两种口径的总收集数一致，可互相印证：`728 passed + 25 skipped = 753`，`720 passed + 5 skipped + 28 deselected = 753`。

**结论：** 728/753 是本次实测值；697 是上一会话的记录值，两者口径不同，**不要**把 728 直接读成"比 697 多通过 31 个"。后续回归统一使用下面这条命令，并在单元 E 重新建立一次可信基线：

```
.venv/Scripts/python.exe -m pytest -q --basetemp=.tmp_pytest -p no:randomly \
  --import-mode=importlib -m "not live and not live_llm" --ignore=backend/tests/live
```

**PostgreSQL：如实跳过。** 环境未配置 `SECTOR_PULSE_TEST_DATABASE_URL`，`.env` 中 `SECTOR_PULSE_DATABASE_URL` 为空。按计划约束，没有名为 `_test` 的专用库就不连接，也绝不使用业务库；双库索引与契约测试留待有 `_test` 库时补跑，本单元结论只对 SQLite 成立。

**未做（有意留到后续单元）：** 前端尚未渲染 `execution_engine`（属单元 F）；`GET /api/runs/{run_id}/tasks` 的 run→sector→draft→review 双向链接来自既有持久化 ID，本单元未新增链接端点。

## 单元 E：人工审核、编辑、批准、撤销与导出接线

**Interfaces**

- 原人工 API 保留，但新草稿操作前校验当前 `draft_id/version` 与根任务状态。
- 人工编辑创建更高不可变版本并使旧 rules/review 失效；批准/撤销仍写独立审计。

- [x] 写失败测试：人工 v2 后 v1 A4 PASS 不能批准、导出或触发旧自动修订；新 A4 必须针对 v2。
- [x] 写失败测试：并发自动修订与人工编辑只允许一个 CAS 获胜，失败方保留可恢复状态。
- [x] 写失败测试：批准/撤销 actor、时间、版本和 evidence decision 审计不被 Agent 伪造；导出不含调度日志。
- [x] 实现新产物到旧审核工作台的兼容适配，保留历史数据原样读取。

**单元 E 完成证据（2026-09-15）：**

**已完成第 1 项。** 发现 `MultiAgentRunQueryAdapter.get_review` 只返回决策、不返回"这次审校看的是哪一版草稿"，因此审核链路上没有任何地方能判断 A4 PASS 是否仍然针对当前版本。红测 `test_approving_a_human_edited_version_needs_a_review_of_that_version` 证实：人工把草稿改成 v2 后，用 v1 的 A4 PASS 批准 v2 返回 **200**——等于批准了一段没有任何审校者读过的文本。

最小实现：

- `get_review` 现在沿 A4 任务的 `input_artifact_ids` 找到它真正消费的那份 `article_draft` 产物，返回该产物的 `draft_id`/`draft_version`。刻意从**产物**而不是从任务 scope 字符串解析，避免依赖 `review:{draft_id}:{version}` 这种拼接格式。无审校记录时返回显式的 `_no_review()`，不含任何"没问题"的暗示。
- 审核路由新增 `require_current_version_review`：仅对 `execution_engine=multi_agent` 的运行生效，要求存在决策且 `draft_version` 等于当前版本，否则 409。旧运行没有编排审校，保留原有"只过治理规则"的闸门，行为不变。

新增 5 个测试全部通过（4 个在 `test_review_version_binding.py`，1 个并发特征测试）。**导出路径的门禁来自既有的"按版本查批准记录"，不是本次新写的**——新增测试只是证明 v2 存在时 v1 的批准不会前移，这一点在改动前就已成立。

**第 2 项：已完成（方向经用户确认为"人工编辑并入编排事务"）。**

先确认了缺陷的两个 CAS 域互相看不见：Agent 侧经 `AtomicArtifactCommitter` 提交草案产物、用**快照 revision** 做 CAS；人工侧经 `apply_patch` 写 `article_drafts`、用**该表自己的 version** 做 CAS。关键是两者写的是**不同的表**（agent 写 `editorial_draft_artifacts`，人工写 `article_drafts`），所以即使放进同一个数据库事务，光看草稿版本也发现不了对方动过——**只有快照 revision 是双方都会推进的那个值**。

实现：新增 `application/review/human_draft_edit.py::HumanDraftEditService`。

- 两个仓储各自拆出 `apply_patch_in_transaction(connection, ...)`（SQLite 用原生连接、PostgreSQL 用 SQLAlchemy 连接，SQL 方言各自保留），由 `apply_patch` 包装调用，原调用点行为不变。
- 服务在有快照时构造 `revision = base_revision + 1` 的快照并走既有的 `save_atomic(claimed, base_revision, "draft.patched", write)`，把人工写入放进**快照 CAS 的同一个事务**：`base_revision` 落后就让 `save_atomic` 抛 `RevisionConflict`，整个事务回滚，人工修改不会半落地。刻意不另造异常类型，复用 `ports.orchestration.RevisionConflict`。
- `base_revision=None` 或运行没有快照（全部旧运行）时直接走原 `apply_patch`，事务边界与行为完全不变。
- API：`DraftPatchRequest` 新增可选 `base_revision`；补丁路由 409 同时捕获 `DraftVersionConflict` 与 `RevisionConflict`。

新增 5 个测试（`test_human_edit_joins_orchestration_cas.py`）覆盖：人工落后于 agent 修订时失败且草稿停在 v1；人工先写成功后快照 revision 前进、agent 手里那个 revision 随即失效；无快照的旧运行照常工作；以及一条 HTTP 层测试证明路由确实接上了这个闸门而不是只在服务层成立。另一个文件 `test_concurrent_human_edit_and_agent_revision.py` 记录的是"两个原生仓储本来就不共享 CAS"这一前提，已改写标题与文档说明，避免被误读成待修缺陷。

**验证命令与结果：** 专项 `test_review_version_binding.py`、`test_review_orchestration_bridge.py`、`test_human_edit_joins_orchestration_cas.py`、`test_concurrent_human_edit_and_agent_revision.py` 与 `backend/tests/unit/web` 全绿（68 passed）；Ruff 通过；Mypy 303 个源文件通过（较单元 D 的 302 增加 `human_draft_edit.py`）；前端 Vitest 245 passed（63 文件）；完整非 live 回归 **729 passed、5 skipped、28 deselected**（较单元 D 的 725 增加 4）。PostgreSQL 仍因无 `_test` 库如实跳过——**注意本单元改动了 PostgreSQL 侧 `apply_patch` 的代码结构（拆出 `apply_patch_in_transaction`），该路径本次没有任何测试执行过，只做了 Ruff 与 Mypy 静态检查**，需在有 `_test` 库时优先补跑。

**第 3 项：已完成，性质是"守卫测试"而非修复——结论必须如实说明。**

先按 TDD 写下红测 `test_agent_cannot_forge_human_release_audit.py`。逐条追查可伪造路径后，**没有找到可以真正伪造的路径**，因此这一项没有产生任何生产代码改动。已核实的不可伪造性来自三处结构性事实：

1. **工具白名单**：`REQUIRED_BUSINESS_TOOL_NAMES`（14 个）与 `A0–A4` 各角色的 `ROLE_TOOL_NAMES` 都不含任何治理动作；`AgentBusinessToolFactory.build` 对白名单之外的 Tool 名直接抛 `unexpected business tools`，所以 builder 也无法偷偷注册一个 `approve_draft`。
2. **端口隔离**：`A3A4ToolDependencies` 只持有 `governance: GovernanceService`（只读检查），**不持有** `ReleaseAuditRepositoryPort`/`GovernanceRepositoryPort`。全仓检索确认 `save_evidence_decision` 的唯一调用方是人工路由经 `EvidenceDecisionService`，`approve`/`revoke`/`record_export`/`record_event` 的唯一调用方是 `web/routers/review.py`。Agent 在进程内没有 HTTP 客户端，够不到这些路由。
3. **actor/时间/版本来源**：批准与撤销路由**没有请求体**，actor 只取自 `X-Actor` 头、时间只取自服务器时钟、版本只取自仓储中当前草稿。实测向 `/approve` 与 `/revoke` 发送 `{"actor":"attacker","version":99,"approved_at":"1999-01-01T00:00:00Z"}`，返回的 actor 仍是请求头值、版本仍是草稿版本、审计时间仍落在本次测试的时间窗内。

**过程中的一次失败与修正：** 红测最初断言 `GET /approval` 返回 `approved_at`，实测 `KeyError`——`ApprovalResponse` 只暴露 `draft_id/version/status/actor`，批准时间只存在于 `audit_events.created_at`（服务器 `datetime('now')`）。核实前端与 schema 均无 `approved_at` 消费者后，判定"时间为审计事实、由 append-only 审计轨提供"是既有的合理设计，**没有为迁就测试而新增字段**，而是把断言改到 `/audit` 上。第二次失败是秒级截断（审计表只存整秒，断言用了微秒精度），属测试精度问题，已在断言处显式说明而不是放宽。顺带记录一个**未修的既知不一致**：`audit_events.created_at` 为朴素 UTC 字符串、`draft_approvals.approved_at` 为带时区 ISO，两者精度与编码不同。

**第 4 项：实现早已在前序阶段写入，但从未被执行验证过；本次补上验证。**

`web/routers/review.py::latest_owned_draft` 中的兼容投影（旧编辑表查不到时按 `run_id`+`draft_id` 校验后从编排投影同步一份快照再交给原 CAS 仓储）与 `get_governance` 的回退分支，都不是本次新写的。计划文件早前那条补充记录已写明它当时"因当前环境缺少 FastAPI，未能收集执行"——即**写了但没跑过**。本次新增 `test_agent_draft_reaches_legacy_review_workbench.py`（6 项）首次真正执行它，且是端到端 HTTP 层：

- 纯 Agent 运行（草稿只存在于 `editorial_draft_artifacts`，`article_drafts` 无行）在 `/api/runs/{id}` 读出 `execution_engine=multi_agent` 且 `draft_id` 指向该草稿；`/draft`、`/governance`、`/audit` 均正常返回，审计为空列表而不是 404。
- 带 A4 独立审校的运行可在工作台直接批准并导出（审校经 `get_review` 一并投影，`draft_version` 与批准版本一致）。
- 人工编辑 agent 草稿成功到 v2，但 v2 的批准被第 1 项的闸门挡下（409），证明兼容层没有绕开版本绑定。
- 投影是**读时投影**：读完之后 `editorial_draft_artifacts` 里的 agent 产物逐字段不变（断言的是 `latest_version` 相等），`article_drafts` 则已被写入以供后续人工 CAS 使用。
- 旧运行（无快照、只有 `phase1b_runs` 行）仍读出 `execution_engine=legacy`，行为不变。

**本次新发现、留给单元 F 的缺口（不在本单元修）：** 前端的补丁请求仍未发送 `base_revision`（`web/src/editingApi.ts` 与 `useDraftAutosave.ts` 只发 `base_version`），因此第 2 项实现的"人工编辑并入编排事务"这条 CAS 闸门**目前从产品界面处处走的是 `base_revision=None` 的旧路径**，只在服务层与 HTTP 显式传参时生效。单元 F 接入前端时必须补上，否则该闸门在生产路径上不会被触发。

**验证命令与结果（单元 E 最终）：** 专项 `test_agent_cannot_forge_human_release_audit.py`、`test_agent_draft_reaches_legacy_review_workbench.py`、`test_legacy_records_stay_readable.py`、`test_phase4_review_api.py`、`test_human_edit_joins_orchestration_cas.py` 与 `backend/tests/unit/web` 全绿（89 passed）；Ruff 全通过；Mypy 303 个源文件通过；前端 Vitest 245 passed（63 文件）。

**回归基线（按单元 D 指定的统一命令重建，本节即"单元 E 重新建立一次可信基线"）：**

```
.venv/Scripts/python.exe -m pytest -q --basetemp=.tmp_pytest -p no:randomly \
  --import-mode=importlib -m "not live and not live_llm" --ignore=backend/tests/live
```

结果 **750 passed、25 skipped**（收集总数 775）。与单元 D 同一命令的 728 passed、25 skipped（753）相比增加 22 个，**已逐个对上，无未解释差额**：`test_review_version_binding.py` 4 + `test_human_edit_joins_orchestration_cas.py` 4 + `test_legacy_records_stay_readable.py` 1 + `test_agent_cannot_forge_human_release_audit.py` 7 + `test_agent_draft_reaches_legacy_review_workbench.py` 6 = 22（各文件收集数已单独核对）。此前记录过的 697/725/729 等数字口径不同，不再作为可比基线。

**两个 basetemp 陷阱（都踩过，记下来）。**

1. **`--basetemp` 不可省略。** 本机 `C:\Users\18067\AppData\Local\Temp\pytest-of-18067`（9 月 7 日创建）已变成连 `icacls` 都读不到的目录，pytest 默认 basetemp 会让所有用到 `tmp_path` 的测试在 fixture 阶段报 `PermissionError`——这是**环境问题，不是代码回归**。
2. **不要用 `.pytest-temp` 做 basetemp，尽管它在 `.gitignore` 里。** 该目录里的 15 个文件**已被 git 跟踪**（`.gitignore` 对已跟踪文件无效），而 pytest 会在会话开始时清空 basetemp，于是那 15 个已跟踪文件被当作"工作区删除"出现。本次已用 `git checkout-index -f --` 从索引逐文件恢复，`git status` 中 `.pytest-temp/` 已回到干净状态，**没有残留差异**（其中 `live-data-consent` 在 HEAD 中本就是 0 字节，不是恢复失败）。本次同时把 `.tmp_pytest/` 加入 `.gitignore`，避免它再变成同类隐患。**统一使用 `.tmp_pytest`。**

**PostgreSQL：仍如实跳过。** 环境未配置 `SECTOR_PULSE_TEST_DATABASE_URL`，本单元结论只对 SQLite 成立。**本单元改动的 PostgreSQL 侧代码（`apply_patch` 拆出 `apply_patch_in_transaction`、发布审计仓储）本次无任何测试执行过，只有 Ruff 与 Mypy 静态检查**，需在有 `_test` 库时优先补跑。

## 单元 F：前端移除双模式并展示动态任务树

- [x] 先改 Vitest/Playwright 失败测试：新建页只选择场景与 fixture/live，不出现 workflow/agent；请求不发送 attribution_mode。
- [x] 新运行详情用动态任务树替换固定阶段推断，展示角色、状态、板块 scope、Tool/模型预算与产物链接；旧运行仍显示历史阶段和“未记录”。
- [x] 数据页保留行情、新闻、质量、候选确认；审核工作台保留版本、人工编辑、批准/撤销、导出并显示对应根任务/审校版本。
- [x] 验证刷新恢复、窄屏、键盘操作和错误/空状态；不重做现有视觉系统。
- [x] 运行 `npm test`、`npm run build` 和关键 Playwright 场景。

### 单元 F 完成证据（2026-09-15）：

**F1「新建页只选择场景与 fixture/live」：结论是无代码可改，只补证据。** `grep -rn "attribution_mode\|workflow\|agent"` 在 `web/src` 的请求构造里已无命中——`NewAnalysisPage.tsx` 只有场景（intraday/post_close）与 fixture/live 两处选择，`api.ts` 的 `createRun(inputJson, provider)` 只发 `{ input_json, provider }`。既有 `NewAnalysisPage.test.tsx` 已经在断言请求体的确切形状，因此本轮**没有新增测试也没有改产品代码**，避免用重复断言冒充新进度。

**F2「动态任务树替换固定阶段推断」：新增 [RunTaskTree.tsx](web/src/components/runs/RunTaskTree.tsx)，6 个 Vitest 先红后绿。** 树按 `parent_id` 真实嵌套（子任务挂在派发它的父任务下，不摊平），每行给角色（A0 调度 / A1 行情与候选 / A2 查证 / A3 写作 / A4 审校）、状态、板块 scope、尝试次数、选择版本、租约到期与停止原因码；Tool/模型花费按 `task_id` 归到实际花钱的那个任务上，产物链接接到拥有它的视图（`sector_analysis→radar`、`candidate_selection→overview`、`article_draft→draft`、`independent_review→review`、`draft_rules→governance`）。

两处真实性约束写进了实现而不是注释：

- **未结算的花费不能显示成 ¥0。** 只有 `actual_cny` 存在且（模型调用还需要）`settled` 为真才累加；否则若存在预留金额就显示「费用未知」。测试用 `actual_cny: null` + `reserved_cny: '0.50'` 的失败调用证明这一点。
- **「未记录」不等于「未执行」。** `recording !== 'recorded'` 或根任务为空时，渲染「本次运行没有记录任务树；未记录不等于未执行。」而不是一棵空树；加载失败走 `role="alert"` + 重载按钮，不伪装成"没有任务"。

实现过程中两次自我修正，都记在这里：其一，最初把整行放在 `<li aria-label>` 上，导致 `within(row)` 会把子任务的文本也算进父任务（测试同时看到多个「已完成」）；改成行本身是 `role="group"`、子 `<ul>` 在其外才让"父任务没有租约"这类断言成立。其二，最初把花费段落放在 group 之外，等于把花费从任务行里割出去，已移入。

**F3「保留既有页面能力」+ 补上两处遗留缺口。** 数据页（行情、新闻、质量、候选确认）与审核工作台（版本、人工编辑、批准/撤销、导出）的既有能力本轮没有改动，也未重做视觉系统。但补齐了两处**读路径上的真实缺口**：

*缺口一：前端从不发送 `base_revision`。* 单元 E 记录过这个问题：`HumanDraftEditService` 的共享 CAS 守卫要求人工编辑回报它读到的快照 `revision`，而前端从不发送，于是这个守卫在产品界面上**永远不会被触发**。本轮把它接通：

- 后端 `MultiAgentRunQueryAdapter.get_draft` 现在返回 `revision`（无快照的运行返回 `null`），[query_adapter.py](backend/src/sector_pulse/application/orchestration/query_adapter.py)。
- 前端 `DraftView.revision` → `useReviewWorkspace` 状态 → 工作台 `onSave` 组装 `base_revision`；`DraftTab`/`ReviewEditor` 同样透传。`applyDraftPatch` 在 `base_revision` 为 `undefined` 时不写该字段，保留无快照运行的旧行为。
- 两个新后端测试（`test_agent_draft_reaches_legacy_review_workbench.py`，8 passed）：一个证明草稿载荷给出的 revision 确实等于快照 revision、据此提交的编辑落库并让快照 +1；另一个让 Agent 先推进快照，再断言基于旧 revision 的编辑拿到 **409**，且失败消息里含 `revision`（证明是快照守卫而不是稿件版本守卫拦下的），同时人工改写没有半途写入。
- 前端 `ReviewWorkspacePage.test.tsx` 新增一条断言"保存时带上读到的 revision"。**该测试做过反向验证**：临时摘掉 `base_revision` 透传后它如实失败，恢复后通过——避免留下一条恒真的假绿。

*缺口二：审核结论不说明它审的是哪一版。* 多 Agent 侧的 `/review` 早已返回 `draft_id`/`draft_version`，但**旧运行侧完全不返回**（`RunService.get_review` 只有 decision/revision_round/issues），前端 `ReviewTab` 也一个字都不显示——一个 PASS 看上去像是在给"当前草稿"背书，而它其实只对某一版成立。本轮补齐：旧运行侧读路径补上 `draft_id`/`draft_version`（`ReviewReport` 里本来就有这两个字段，只是没被暴露），`ReviewTab` 增加"审核版本：第 N 版"一行；`draft_version` 缺失或为 null 时显示「未记录」而不是默认成第 1 版。测试：后端在 `test_web_api.py` 断言旧运行的 `draft_version` 落在草稿版本集合内、`draft_id` 与运行详情一致；前端 `ReviewTab.test.tsx` 两条（有版本 / 未记录）先红后绿。

**F4「刷新恢复、窄屏、键盘、错误/空状态」：Playwright 首次在本机真正跑起来。** 此前 65 个 e2e 全部在 2–3ms 内失败，原因是本机**没有安装任何 Playwright 浏览器**（`ms-playwright` 目录为空），并非代码问题；执行 `npx playwright install chromium` 后套件可跑。`attribution-agent.spec.ts` 已补 `/api/runs/{id}/tasks` fixture 与断言：多 Agent 运行的详情页出现任务树、出现 `AGENT_NO_PROGRESS` 的红字停止原因、并且**不再出现「运行阶段」阶段条**；该场景在 1440px 与 390px 两个宽度下都断言无横向溢出。

**本单元的可信数字。**

- `npx vitest run`：**64 files / 259 passed**（本单元新增 6 + 3 + 1 + 1 + 2 = 13；起点 254）。`npm run build` 通过（`tsc -b && vite build`）。
- `npm run test:e2e`：**64 passed / 3 failed**。**这 3 个失败与本单元无关，已用 HEAD 版本对照证明**：把 `RunDetailPage.tsx` 换回 HEAD 内容重新构建后，`review-workspace.spec.ts:91`（×2 宽度）与 `data-workbench.spec.ts:271`（empty）**以完全相同的报错再次失败**（前者 `timeline-state[3]` 期望「未记录」实得「已完成」，后者期望「行情板块尚未产生…」但 `installWorkbenchFixture` 给 empty 场景设了 `terminal: true`，而 `MarketPanel.tsx:35` 在 terminal 时渲染的是另一句文案——断言与代码本来就矛盾）。**它们不是本单元引入的回归，本单元也没有修它们**，留给单元 G 统一处理。
- 后端全量（`-m "not live and not live_llm" --ignore=backend/tests/live --basetemp=.tmp_pytest`）：**752 passed、25 skipped**（起点 750；本单元净增 2 个后端测试——`test_agent_draft_reaches_legacy_review_workbench.py` +2 与 `test_web_api.py` 内新增断言不改变收集数）。
- Ruff、Mypy 对改动文件通过。

**PostgreSQL 仍如实跳过。** 本环境未配置 `SECTOR_PULSE_TEST_DATABASE_URL`；本单元只改了 SQLite 与 PostgreSQL 共用的查询适配器（新增一个返回字段），但**没有对 PostgreSQL 执行过任何测试**，结论只对 SQLite 成立。

## 单元 G：清理、回退证据与最终验收

- [x] 全仓搜索证明所有新建/重试/定时/CLI 入口不调用旧 pipeline、旧归因循环或旧编辑/审校单次函数。
- [x] 删除仅服务双模式的新运行分支、前端类型和无调用旧 Prompt；保留历史查询、导出和领域校验仍需要的代码。
- [x] 验证迁移从旧数据库增量到最新版本，SQLite/PostgreSQL 旧数据和新任务均可读；记录部署备份/回退步骤。
- [x] 运行完整后端非 live、专用 PostgreSQL、Ruff、Mypy、完整前端单测/构建/浏览器验收，以及有界 live Agent 验收结果。
- [x] 更新 README、总计划和迁移表。只有全部新建入口证明使用新引擎后，才宣称父子多 Agent 重构完成；不自动提交、合并或推送。

补充验证（2026-09-14）：A1BusinessToolFactory 已完成 T01–T05 正式构造，专项 4 passed；全量非 live（排除 live/live_llm/postgres）691 passed、5 skipped、36 deselected，Ruff/Mypy 通过。
补充进度：新增 `CompositeBusinessToolFactory`，支持 A1–A4 分角色工厂合并，并在合并边界拒绝重复或不完整注册。
补充验证：A2BusinessToolFactory 已完成研究与证据 Tool 构造；专项 5 passed，全量非 live（排除 live/live_llm/postgres）692 passed、5 skipped、36 deselected，Ruff/Mypy 通过。
补充验证：A3A4BusinessToolFactory 已完成编辑、修订与审校 Tool 构造；专项 6 passed，全量非 live（排除 live/live_llm/postgres）693 passed、5 skipped、36 deselected，Ruff/Mypy 通过。
补充验证：运行时依赖新增显式 `MultiAgentRunService` 注入点；提供该服务时 Web 自动选择 `MultiAgentRunCommands`，未提供时保持旧入口，专项 4 passed；全量非 live 694 passed、5 skipped、36 deselected。
补充验证：`build_runtime_dependencies` 现支持显式传入完整 Tool 工厂和 provider 工厂，只有此条件满足才创建新服务；专项 5 passed，全量非 live 695 passed、5 skipped、36 deselected，Ruff/Mypy 通过。
补充进度：新增无网络 fixture provider bundle 与只读查询适配器草案；验证发现旧 Web 查询仍依赖历史稿件流水线语义，默认入口暂不自动切换，生产切换需先完成新运行查询/稿件投影。
补充验证：查询适配器已能投影根任务状态及 sector analysis、article draft、independent review 产物；专项 1 passed，全量非 live 696 passed、5 skipped、36 deselected，Ruff/Mypy 304 个源文件通过。
补充验证：编排快照仓储新增列表读取，查询适配器可列出新运行；专项 6 passed，全量非 live 696 passed、5 skipped、36 deselected。
补充验证：scheduler bridge 支持显式多 Agent 命令时直接创建 live 根运行并冻结 `server_default` 选择策略；专项 6 passed，全量非 live 697 passed、5 skipped、36 deselected，Ruff/Mypy 304 个源文件通过。
补充进度：运行时依赖新增 `enable_multi_agent=True` 的显式构建开关，CLI 新增 `multi-agent-run` 入口，完成数据库初始化后通过 `MultiAgentRunCommands` 创建并等待 fixture 父 Agent 运行；默认 Web 入口仍不自动切换。当前环境缺少已安装的本地 aidynamic-agent 依赖，新增单测需在项目既有完整依赖环境中执行；本次已完成 Ruff 与 diff 检查。
补充进度：显式多 Agent 运行时现在把 `ApplicationSettings` 中的 live base URL、API key、模型和超时接入 `AgentProviderFactory`；fixture 仍使用确定性 provider，live 仍受 consent、凭据、地址、模型和 pricing 预检约束。专项测试已补充配置透传断言；当前环境的 mypy 仍被既有 `delegation.py` 类型错误阻断，未将其计入本次改动回归结论。
补充验证：新运行查询新增 `/api/runs/{run_id}/tasks`，从不可变快照投影任务树、租约/错误和预算汇总；`agent-trace` 同时返回模型调用与 Tool 调用审计。查询适配器专项 2 passed；路由专项因当前 Anaconda 环境缺少 FastAPI 未能收集，未计入通过数量。
补充验证：查询适配器现可从 `article_draft` ArtifactRef 读取最新 READY_FOR_HUMAN_REVIEW 草稿，并复用既有安全 Markdown/Text 渲染器；非就绪稿件继续返回 404 语义。查询适配器专项 3 passed，Ruff 通过。
补充进度：审核治理查询现在对显式多 Agent 运行优先读取编排中的最新 editorial draft，旧 Phase 1B 运行继续读取历史稿件表；这只扩大读路径，不把 Agent 赋予批准、编辑或撤销权限。查询适配器专项 3 passed，Ruff 通过；当前环境 Mypy 受既有 YAML stub/FastAPI typing 缺失影响，未计入通过数量。
补充进度：新运行稿件首次进入人工审核/编辑路由且旧编辑表尚无该版本时，会先按 run_id/draft_id 校验并同步一份兼容快照，再交给原有 CAS 编辑仓储；后续编辑、批准、撤销继续由人工 actor 和 release audit 控制。路由回归测试已补充，当前环境缺少 FastAPI，未能收集执行。
补充验证：修复 CLI 在当前 Typer 版本上不支持 `Option(min_length=...)` 的导入问题，改为显式空 goal 校验；补齐本机离线依赖后，全量非 live/non-postgres 回归 `689 passed, 19 skipped, 36 deselected`。PostgreSQL 真实标记因未配置专用连接而跳过。
补充验证：本轮全量回归在清空 `SECTOR_PULSE_DATABASE_URL`、使用 `--import-mode=importlib` 后稳定得到 `689 passed, 19 skipped, 36 deselected`；另修复两处 Ruff UP038 基线问题，当前全仓 Ruff 通过。PostgreSQL 专项仍因没有专用测试连接而跳过。
补充验证：确认本机 PostgreSQL 18 服务运行中，并使用隔离数据库 `sectorpulse_test` 完成 PostgreSQL 编排合同 `11 passed`；另创建并使用专用 `sector_pulse_run_comparison_test` 完成比较/新闻元数据合同 `9 passed`。未连接或写入 `.env` 中的业务数据库。
补充验证：在 `.live-llm-consent` 和 `.env` 的 DeepSeek Flash 配置下，运行有界真实 LLM 验收 `backend/tests/live/test_multi_agent_llm_live.py --run-live-llm`，结果 `1 passed`；预算上限 0.10 CNY、最多 3 次模型调用/2 次 Tool 调用，实际只允许 `inspect_tasks` 只读 Tool，未调用真实外部数据源。
补充验证：接入人工编辑版本优先读取后，修正 CLI literal provider 类型与审核路由可空类型；当前 Mypy `301 source files` 全通过，Ruff 全通过。
补充进度：CLI `multi-agent-run` 现支持 `fixture|live`，live 路径读取 `.env`/YAML 运行配置并强制通过既有 provider preflight；fixture CLI 端到端专项 `2 passed`，修复了必须在事件循环内创建后台任务的实际问题。
补充进度：新运行 DTO 新增 `execution_engine`，编排查询固定返回 `multi_agent`，历史 RunService 查询保留 `legacy`；详情页已改用执行引擎展示并决定是否显示 Agent trace，不再用旧 `attribution_mode` 判断新运行。后端专项 3 passed，Mypy/Ruff 全通过；前端 npm 工具在当前 shell 无有效输出，尚未计入前端回归证据。

### 单元 G 第 1–3 项证据（2026-09-15）

单元 G 的前三项已完成并验证；第 4、5 项仍待完成，因此下表结论只覆盖第 1–3 项，**不代表 P4 或父子多 Agent 重构完成**。

**第 1 项——所有新建入口证明使用新引擎。** 证据不是 grep，而是 `backend/tests/integration/test_every_new_run_entry_uses_the_multi_agent_engine.py`（6 项，全部通过）：

- 用 AST 遍历 `backend/src/sector_pulse` 的全部 `*.py`，找出**真正调用**旧引擎每个函数的模块，与 `LEGACY_SURFACE` 逐字比对：`run_phase1b_pipeline` → 仅 `web/services/run_service.py`；`run_revision_agent` → 仅 `application/writing/phase1b_pipeline.py`；`run_agent_loop` → 仅 `application/writing/agent_runtime.py`；`build_live_provider` → 仅 `web/services/run_service.py`；`RunCommandService` → 仅 `web/dependencies.py`。注释或字符串里提到名字不算调用，新增调用点会立即失败。
- 默认接线（`create_app` 在无 override 时走的同一对构造函数）产出 `MultiAgentRunCommands` 而非 `RunCommandService`，`execution_engine == "multi_agent"`；数据运行续写产出 `MultiAgentDataRunWritingService` 而非 `DataRunWritingService`；调度器实际运行的 bridge（`scheduler._bridge._multi_agent_commands`）不为空。
- 生产侧 `build_runtime_dependencies` 的每个调用点都必须显式传 `enable_multi_agent=True`（该参数默认 `False`），当前为 `cli.py:151` 与 `web/app.py:43` 两处，新增一处忘记传即失败。
- CLI 以 `isinstance(commands, MultiAgentRunCommands)` 断言引擎，缺失时报 `multi-agent runtime was not enabled`。
- 已做反向验证：把 `enable_multi_agent` 改为 `False` 时上述三项接线断言确实失败，说明断言对引擎敏感、非恒真。

**第 2 项——删除仅服务双模式的代码。** 前端已无 `attribution_mode`/`workflow`/`agent` 双模式类型（全仓搜索零命中），每个 Prompt 文件均有存活调用方。本轮唯一的合格删除是 `build_runtime_dependencies` 中**休眠的第二套 scheduler/coordinator/bridge**：它构造的 `ScheduledDataRunBridge` 没有 `multi_agent_commands`，即一条无人使用的旧引擎路径，而 `web/app.py:51-52` 读取的是 router bundle 里的那一套。已先行写红测（`test_the_runtime_bundle_does_not_carry_a_second_scheduler`：断言 runtime bundle 不再有 `scheduler`/`coordinator` 属性）再删除。历史表、导出与领域校验代码一律保留。

**第 3 项——增量迁移。** 新增 `backend/tests/integration/test_incremental_migration_from_an_old_database.py`（2 项，全部通过），是本仓第一个真正从旧 schema 升级的测试——其余测试都从当前 schema 起步，因此一个在带数据的旧文件上会失败的迁移可以骗过整套测试。测试用 `sector_pulse.storage.migrations.MIGRATIONS_DIR` 把 `NNN_*.sql`（含 `sqlite/` 方言覆盖）复制到一个临时目录，按文件名前缀截断出「某版本之前」的真实迁移集，并断言复制数量确实介于 0 和总数之间（否则升级路径等于没测）。

- 测试一从**017 之前**起步。017 会 `DROP TABLE phase1b_runs` 再重建改名，是最容易丢数据的一步，所以夹具写入了 005 才引入的 `input_json`，让这一步有东西可丢。升级到最新（34）后，旧行仍可读，`status`、`total_cost_cny` 原样保留，`input_json` 在重建中存活，而 018 才加入的 `retry_of_run_id` 为 `None`——升级补列，但不得把「本就没记录」变成某个值。
- 测试二在同一份升级后的文件上跑完整应用：`schema_migrations` 等于全部 34 个版本（不是只升到能启动的程度）；旧运行以 `execution_engine == "legacy"` 提供且金额不变；新建运行 `execution_engine == "multi_agent"` 并离开 `RUNNING`；`/tasks` 返回 `recording == "recorded"` 且角色为 `["A0"]`，证明父 Agent 确实在这份升级后的文件上跑过而不只是插了一行；最后旧行仍是 `legacy`。

**本轮顺带修复的两个真实缺陷（均由引擎切换引入，非既有基线）：**

1. **重试历史运行返回 500。** 多 Agent 引擎只能重试自己拥有的运行，历史行没有可重建的快照，`KeyError` 直接冒到顶层。现捕获后返回 409 与迁移提示 `该运行由旧引擎创建，无法重试为多 Agent 运行；请新建一次运行`。
2. **`retryable` 标志误导。** `execution_engine` 说的是「这次运行是怎么产生的」，能否重试取决于**将要执行重试**的引擎（即 `commands`）。历史运行因此在 `_retryable()` 中清除该标志，而不是给用户一个点了就 409 的按钮。

**新增的业务库防护（属于 Global Constraints 的硬约束，此前存在漏洞）：** `create_app()` 会把 `.env` 载入进程环境，其中 `SECTOR_PULSE_DATABASE_URL` 指向业务库 `sectorpulse_runtime`；本机 PostgreSQL 可达，而约 27 个合同测试（分布在 11 个文件，多数不带 `postgres` 标记）会读取该变量并写行。新增 `backend/tests/postgres_isolation.py` 并在 `conftest.py` 中挂**会话级 autouse** 夹具（不带标记的测试同样受保护）：变量未设置时置空，已设置但不以 `_test` 结尾时抛 `BusinessDatabaseRefused`。由 `backend/tests/unit/test_postgres_isolation.py` 三项测试从「未设置被置空」「`_test` 连接不受影响」「业务连接被拒」三个方向验证。

**本轮实测数字**（命令为项目既有规范：`SECTOR_PULSE_DATABASE_URL="" SECTOR_PULSE_LLM_PROVIDER=fixture SECTOR_PULSE_SCHEDULER_ENABLED=false`，`-m "not live and not live_llm" --import-mode=importlib --basetemp=.tmp_pytest`，在仓库根目录执行）：

| 范围 | 结果 |
| --- | --- |
| 全量离线（SQLite） | **743 passed, 47 skipped, 8 deselected**（47 项跳过均因 `SECTOR_PULSE_DATABASE_URL` 被防护置空或比较库未配置） |
| 专用 `sectorpulse_test` | **790 passed, 0 skipped**（对最终代码重跑；0 跳过即全部 PostgreSQL 合同测试确实执行） |
| 专用 `sector_pulse_run_comparison_test` | 比较类用例已并入上一条的同一次执行，全部通过 |
| `mypy --config-file pyproject.toml backend/src` | **Success: no issues found in 304 source files** |
| `ruff check backend/src backend/tests` | **All checks passed!** |

**诚实说明：** 前述 `752 passed / 25 skipped` 的旧基线在当前环境**无法复现**。差额可由那批 PostgreSQL 测试完全解释——它们在配置了专用 `_test` 连接时执行，未配置时跳过；本机 `.env` 指向业务库 `sectorpulse_runtime`，因此没有证据表明曾写入业务库。此处记录的是本轮实际测得的数字。`ruff format --check` 全仓有 192 个文件待格式化，属既有基线状态，本项目未把 `ruff format` 作为门禁；本轮改动到的文件已单独格式化并复核。

### 单元 G 第 4 项证据（2026-09-15）：全量验收

| 验收项 | 命令 | 结果 |
| --- | --- | --- |
| 前端单元测试 | `npm --prefix web test -- --run` | **259 passed / 64 files** |
| 前端生产构建（含 `tsc -b` 类型检查） | `npm --prefix web run build` | **通过**，`dist/assets/index-BF4m0GVA.js` 365.42 kB |
| 浏览器验收（Playwright，`dist/` 产物） | `node e2e/run-e2e.mjs` | **67 passed / 0 failed** |
| 有界 live Agent 验收 | `backend/tests/live/test_multi_agent_llm_live.py --run-live-llm` | **1 passed** |

**单元 F 遗留的 3 个失败已全部处理，套件从 64/3 变为 67/0。**这 3 个失败此前被用 HEAD 版本对照证明与单元 F 无关、留给单元 G，现逐一定性为**断言与其自身夹具相矛盾**，属于过时断言而非代码缺陷：

1. `review-workspace.spec.ts`（1440/390 两个宽度）断言 `timeline-state[3]`（`editorial.done`，即「编辑完成」）为「未记录」，却在同一份夹具上断言 `timeline-state[4]`（`writing.done`，即「写作完成」）为「已完成」。夹具的 `run()` 带 `draft_id: 'draft-1'`，而草稿只能产生于编辑阶段落库之后——**写作完成却编辑未记录**在因果上不可能同时成立。证据不止是这条推理：`web/src/pages/RunDetailPage.test.tsx:96-106` 覆盖**完全相同的场景**（`status: 'UNREVIEWED'`、`draft_id: 'draft-1'`、`review_decision: null`、同一句状态说明），且断言 index 3 为「已完成」并通过。因此 e2e 那一行才是异类，已改为「已完成」并加注释说明；`review_decision` 为 `null` 时 index 5 仍断言「未记录」，即「未记录不等于未执行」的语义没有被这次修改放宽。
2. `data-workbench.spec.ts`（empty）断言「行情板块尚未产生，当前运行可能仍在采集阶段。」，但 `empty` 夹具本身声明该运行**已结束**：`finished_at: '2026-08-27T08:03:00Z'`、`/summary` 返回 `terminal: state !== 'active'` → `true`、状态 `READY_FOR_ATTRIBUTION`，而 `DataRunPage.tsx:396` 正是按 `terminal={!isActiveRun(run.status)}` 传给 `MarketPanel` 的。代码渲染的「本次运行已结束，没有保存可展示的行情快照」才是真话；原断言会让界面在一个已结束的运行上说「可能仍在采集」。已改为断言 terminal 文案。**没有**把夹具改成 active 来迁就旧断言——那会抹掉「已结束但没有任何行情快照」这一真实场景的覆盖。

**有界 live Agent 验收的边界（实测自 `test_multi_agent_llm_live.py`）：** 人民币预算上限 ¥0.10、最多 3 次模型调用、12000 tokens、2 次工具调用、60 秒编排超时；断言实际工具调用序列恰为 `["inspect_tasks"]`（只读），且 `charged_tokens` 与 `charged_cny` 均在界内。未调用真实外部数据源。

### 单元 G 第 5 项证据（2026-09-15）：文档收尾

**README。**原文第 40–70 行仍以「归因方式：工作流 / Agent」为标题给出双模式对照表，并把"生成分析稿时选择归因方式"写进首次使用步骤——这些描述的是已被移除的能力。现改写为「执行引擎：父 Agent 调度子 Agent」：A0–A4 角色表、旧双模式移除并返回 422 的说明、`fixture`/`live` 是数据来源而非执行模式、任务树与花费归属、A4 PASS 只到 `WAITING_USER_REVIEW`、Agent 无批准/编辑/撤销权限、预算配置项，以及历史运行只读（`recording: "not_recorded"` 与"未记录不等于未执行"）。工作流程 mermaid 图同步从"选择归因方式"的分叉改为 A0→A1→A2→A3→A4 的单链。全仓复核后 README 内已无残留的双模式表述（仅剩本次新增的"已被移除"说明本身）。

**总计划。**`2026-08-13-...-master-delivery-plan.md` 中没有任何多 Agent 相关表述，不需要改动；「总计划」指的是 `2026-09-12-multi-agent-platform.md`。该文件 Phase 4 的 9 个复选框此前有 6 个为未勾选状态，现逐项按其真实状态更新，并补入单元 D/E/F/G 的结论与单元 G 五项证据。

**一处必须如实记录的收窄（不是"完成"，是有意拒绝）：**Phase 4 复选框第 6 条要求"历史重跑创建带 retry_of 的新根任务"。这在**数据运行**路径上成立——`MultiAgentRunCommands.retry_data_run` 会新建根任务并记录 `retry_of_run_id`。但在**历史内容运行**（旧 Phase1B）路径上**不成立**：该动作被拒绝（409 + 迁移提示），而非伪造。

原因是技术性的，不是遗漏：`retry_run` 从编排快照读取根任务 `scope` 作为新目标（`commands.py:109-119`），旧 Phase1B 行没有编排快照；而唯一可用的替代输入 `phase1b_runs.input_json` 中**没有 `goal` 字段**，`MultiAgentRunCommands.create_run` 遇到缺失 goal 时会写入 `"full sector analysis"`（`commands.py:47-49`）——那等于替用户编造一个他从未提出的请求，正是本项目一条硬约束所禁止的。因此这里选择拒绝：代价是"重试一次旧内容运行"不再可用，用户需改为新建运行；界面上该运行也不再显示可点的重试按钮（见下方缺陷 2）。

### 部署备份与回退步骤

升级会在启动时对现有库原地施加 001–034 号迁移，**升级前必须先备份**。仓库提供了两个脚本：

**备份（SQLite）：**

```powershell
pwsh scripts/backup_sqlite.ps1                                    # 默认 data/sector-pulse.db
pwsh scripts/backup_sqlite.ps1 -DatabasePath <库文件> -BackupDirectory <目录>
```

脚本把库文件复制为 `<BackupDirectory>/sector-pulse-<yyyyMMdd-HHmmss>.db` 并把目标路径打印到标准输出。

**回退（SQLite）：**

```powershell
pwsh scripts/restore_sqlite.ps1 -BackupPath data/backups/sector-pulse-<时间戳>.db
```

脚本会先把当前库另存为 `<库文件>.before-restore-<时间戳>`，再覆盖回备份——即**回退本身也可回退**，不会因为选错备份而丢掉现状。

**两点必须如实说明的限制：**

1. **SQLite 运行在 WAL 模式**（`backend/src/sector_pulse/storage/sqlite/database.py:19` 与 `:50` 均为 `PRAGMA journal_mode = WAL`）。`Copy-Item` 只复制主库文件，**已提交但仍在 `-wal` 里的数据不会被带走**。因此备份前应停止应用，或先执行 `PRAGMA wal_checkpoint(TRUNCATE)`；否则不排除备份缺少最近若干次写入。本项目 11 个测试文件的 PostgreSQL 部分与 WAL 无关，但这条对 SQLite 部署是硬限制。
2. **PostgreSQL 的备份/恢复不在本仓库脚本范围内**，这是有意为之：生产库操作由用户或部署流程用 `pg_dump`/`pg_restore` 显式执行，测试与脚本都不接触业务库。本仓库的测试只连接数据库名以 `_test` 结尾的专用库，且由 `backend/tests/postgres_isolation.py` 强制校验。

回退能力取决于 schema 兼容性：迁移只做加列与重建（`sqlite/016` 重建 `task_runs`、`sqlite/017` 重建 `phase1b_runs`），**不回补**历史行缺失的字段（如 018 之前的 `retry_of_run_id` 读作 `None`）。因此恢复到旧备份后，新引擎在那份数据上创建的新运行会随之消失——这正是备份的意义，但也意味着**回退不保留升级后产生的数据**。

