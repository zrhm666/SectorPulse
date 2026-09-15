# Phase 3b：A2 研究与证据迁移实施计划

状态：已放行。单元 A–F 均已完成；下一步进入 P3c（A3/A4 写作、修订与独立审校），P4 唯一入口切换仍未开始。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本项目按用户要求在当前会话直接执行，禁止创建子代理，也不执行计划模板通常建议的提交步骤。

**Goal:** 用真实 `vendor/aidynamic-agent` A2 子 Agent 和 T06–T09 替换新运行中的旧单次归因/自建循环，同时复用现有检索、正文读取、归因门禁和卡片校验，产出可恢复、可审计、版本不可变的单板块分析卡。

**Architecture:** A0 仍是唯一父 Agent，每个 A2 子任务只绑定一个已确认板块、明确的输入 ArtifactRef 和 selection 版本。T06/T07 将外部读取结果保存为不可变业务产物以支持幂等恢复；T08 从钉住的行情、新闻、正文和选择版本构建程序证据报告；T09 重新执行资格、引用、数值和因果等级校验后原子保存分析卡。旧 `run_attribution_agents`、`AgentRuntime` 和 `run_agent_loop` 仅保留兼容/等价测试，不被新 A2 工具调用。

**Tech Stack:** Python 3.12、Pydantic、SQLite、PostgreSQL 18、SQLAlchemy、pytest、`vendor/aidynamic-agent`、Ruff、Mypy。

**Spec:** `docs/superpowers/specs/2026-09-13-feature-migration-map.md`（M10–M13、T06–T09、S03/S04）

## Global Constraints

- 保留当前 `codex/attribution-agent-modes` 工作区全部未提交改动；不 pull、reset、checkout、clean、stash、提交、合并或推送。
- 不调用真实 LLM、真实外部数据源或生产数据库；只使用脚本化模型、模拟 Provider、临时 SQLite 和名称明确以 `_test` 结尾的 PostgreSQL 数据库。
- 模型不能提供 run/task/attempt/role/worker/scope/cutoff/selection 版本、Provider、URL、资格结论或权限；这些值从服务端任务上下文和已钉住产物解析。
- 所有外部调用经过 `BudgetedTool`；所有写产物操作在当前 attempt 和有效 worker 租约下通过 `AtomicArtifactCommitter`，旧 attempt 的迟到结果不得覆盖当前状态。
- 新闻正文是数据，不是系统指令；Skill 只包含方法，不包含证据白名单、URL 安全规则、因果等级代码、凭据或权限。
- 每个独立单元遵循红→绿：先运行新增测试并确认因缺契约失败，再写最小实现；随后运行专项、Ruff、Mypy 和完整非 live 回归并记录真实数量。

---

## 文件结构与固定接口

- `domain/orchestration/models.py`：给 `TaskRecord` 增加服务端持久化的 `input_artifact_ids: tuple[UUID, ...]` 和 `selection_version: int | None`；恢复新 attempt 保留这两个输入，但不能由模型修改。
- `domain/news/research.py`：定义不可变 `ResearchSearchBatch`、`ResearchSearchDocumentRef`、`NewsDetailSnapshot`。
- `domain/writing/research.py`：定义不可变 `EvidenceInspectionReport`、`EvidenceDocumentView`、`SectorAnalysisSubmission`、`SectorAnalysisArtifact`。
- `application/orchestration/research_context.py`：解析 A2 scope 和任务钉住输入，输出 `BoundSectorResearchContext`；只接受 `sector:<INDUSTRY|CONCEPT>:<provider_sector_id>`。
- `application/orchestration/research_news_tools.py`：T06/T07 应用服务及原子持久化适配器。
- `application/orchestration/evidence_tools.py`：T08/T09 应用服务及原子持久化适配器。
- `infrastructure/agents/research_tools.py`：T06/T07 的 `aidynamic-agent` Tool 适配。
- `infrastructure/agents/evidence_tools.py`：T08/T09 的 `aidynamic-agent` Tool 适配。
- `storage/ports/news.py`：增加 `ResearchSearchRepositoryPort.get(batch_id)` 与 `NewsDetailSnapshotRepositoryPort.get(detail_id)`。
- `storage/ports/writing.py`：增加 `EvidenceInspectionRepositoryPort.get(report_id)` 与 `SectorAnalysisRepositoryPort.get(analysis_id)`。
- `storage/sqlite/news/research_search_repository.py`、`storage/postgres/news/research_search_repository.py`、`storage/sqlite/news/news_detail_snapshot_repository.py`、`storage/postgres/news/news_detail_snapshot_repository.py`：T06/T07 双库只读恢复实现。
- `storage/sqlite/writing/evidence_inspection_repository.py`、`storage/postgres/writing/evidence_inspection_repository.py`、`storage/sqlite/writing/sector_analysis_repository.py`、`storage/postgres/writing/sector_analysis_repository.py`：T08/T09 双库只读恢复实现。所有写入仍由受控持久化适配器参加原子事务。
- `storage/migrations/025_research_search_batches.sql`、`026_news_detail_snapshots.sql`、`027_evidence_inspections.sql`、`028_sector_analysis_artifacts.sql`：只新增不可变表，不修改 001–024，不复用旧覆盖式 `sector_analysis_cards` 作为新权威产物。

固定应用接口：`BoundSectorResearchContext` 包含 `run_id`、`task_id`、`attempt`、`worker_id`、`sector_id`、`sector_kind`、`selection_version`、`cutoff_at` 和 `input_artifacts`。`SearchSectorNewsService.search(context, query, now)` 返回 `ResearchSearchBatch`；`ReadBoundNewsDetailService.read(context, document_id, now)` 返回 `NewsDetailSnapshot`；`InspectSectorEvidenceService.inspect(context, artifact_ids, now)` 返回 `EvidenceInspectionReport`；`SubmitSectorAnalysisService.submit(context, inspection_artifact_id, submission, now)` 接收不含服务端身份字段的 `SectorAnalysisSubmission` 并返回 `SectorAnalysisArtifact`。

## 单元 A：A2 输入钉住、scope 与恢复契约

- [x] 在 `backend/tests/integration/test_orchestration_research_context.py` 写失败测试：T16 创建 A2 时把已验证 ArtifactRef ID 和服务器当前 selection 版本写入子任务；模型参数仍只包含 role/goal/scope/artifact refs，不能提供 selection、attempt 或 worker。
- [x] 写失败测试：`BoundSectorResearchContextReader` 要求当前 task/attempt/worker/租约有效；scope 必须精确命中该 selection 中的一个板块，并能从候选批次还原可信 name/kind；其他板块、未确认版本、未知或跨 run 产物均拒绝。
- [x] 写失败测试：租约过期接管产生新 attempt 后保留钉住的 artifact IDs 和 selection 版本；旧 attempt 构造上下文、模型调用、工具调用和产物写入均失败。
- [x] 最小扩展 `TaskRecord`、`TaskCoordinator.delegate_child`、`ParentAgentRuntime` 和 `AgentToolContext`。根运行组合持有服务端 `selection_version`，`_dispatch` 只将已验证引用与该版本写入子任务，不信任 prompt 文本恢复身份。
- [x] 实现 `SectorResearchScope` 与 `BoundSectorResearchContextReader`；使用 `CandidateSelectionRepositoryPort.list_versions`、`CandidateBatchRepositoryPort.get`、`MarketSnapshotRepositoryPort.get_run` 和当前编排快照，不读取“最新”替代钉住版本。
- [x] 扩展 SQLite/PostgreSQL 同合同和恢复测试；旧 JSON 快照没有新字段时使用空引用/无 selection 的安全默认值，但这类旧任务不能运行 T06–T09。
- [x] 运行本单元专项、Ruff、Mypy、完整非 live 回归并记录数量。

### 2026-09-14 单元 A 验证记录

- 红测：委派输入测试先因 `delegate_child` 不接受 `input_artifact_ids` 失败，真实框架测试先因 `ParentAgentRuntime` 不接受 `selection_version` 失败，上下文测试先因 `research_context` 模块不存在而失败。
- 子任务快照现持久化不可重复的输入 ArtifactRef ID 与 selection 版本；恢复只更新 attempt/owner/lease，因此保持原输入。`RunSnapshot` 额外拒绝引用本运行之外的输入产物。
- A2 上下文只解析 `sector:<kind>:<id>`，精确读取钉住 selection 与 candidate batch，要求当前 worker 租约，并使用已锁定 cutoff；不会以最新版替换旧 selection。
- SQLite/框架专项：19 passed、1 skipped；专用 PostgreSQL 恢复合同：1 passed。完整非 live：646 passed、1 skipped、6 deselected；唯一 skip 为需显式真实 LLM 同意的 live 用例。Ruff 通过；Mypy 270 个源文件通过。

## 单元 B：T06 有界板块新闻检索（M11、M12）

- [x] 先更新迁移测试期望 001–025 并确认因 025 缺失失败；新增表 `research_search_batches`、`research_search_documents`、`research_search_events`，主键使用不可变 batch ID，保存 run/task/attempt、sector identity、规范化 query、start/cutoff、输入指纹、状态、安全错误码和结构化 payload。
- [x] 在 `backend/tests/integration/test_orchestration_research_tools.py` 写失败测试：Tool schema 只接收 2–120 字符 query；服务端自动添加可信板块名，窗口固定为 cutoff 前 7 天，最多返回 10 篇，cutoff 后和窗口外文档排除。
- [x] 写失败测试：只复用 `KeywordNewsSearchPort.search`、`deduplicate_documents` 和实体/板块关联基础服务；不调用旧 `AgentRuntime`、`run_agent_loop` 或任何 LLM。Provider 失败只保存稳定安全码，不泄露 URL、凭据或异常正文。
- [x] 写失败测试：相同 task/attempt/规范化 query 重放不再次访问 Provider；不同 query 产生新不可变批次；超预算、过期租约和旧 attempt 在 Provider 调用前拒绝；业务行和 `research_search` ArtifactRef 原子可见。
- [x] 实现 `ResearchSearchBatch`、双库 repository、`SearchSectorNewsService` 和 `SearchNewsTool`。模型不能选择 Provider、sector、时间窗、limit、run 或 task；查询结果保存后才能成为 T07 的“已知 document”。
- [x] 用 SQLite 并发/CAS 测试验证同输入只产生一个权威产物；用专用 PostgreSQL 验证迁移、事务、读取和失败回滚。
- [x] 运行本单元专项、Ruff、Mypy、完整非 live 回归并记录数量。

### 2026-09-14 单元 B 验证记录

- 025 迁移红测先出现 5 failed，新增三个不可变检索批次表后为 11 passed；真实 PostgreSQL 初始化已应用该迁移。
- T06 首条业务测试先因 `research_news_tools` 不存在失败；部分结果测试随后先确认旧实现会错误返回成功。最终实现绑定 A2 task/attempt/worker/scope，将可信板块名加入规范化查询，固定 cutoff 前 7 天并最多保存 10 篇，排除 cutoff 后文档；新闻事实、批次和 `research_search` ArtifactRef 原子提交，Tool 只暴露 query 且支持持久化重放。
- `PARTIAL`、`STALE`、`UNAVAILABLE` 和异常均明确降级为失败批次并只暴露稳定安全码；`PARTIAL` 可保留已取得的文档，但不得伪装成功。异常正文、URL 或凭据不会写入 Tool 输出。
- 相同 task/attempt/规范化 query 的顺序重放和并发调用都只访问一次模拟 Provider；旧 attempt 在调用 Provider 前拒绝。`RuntimeStorageBundle` 已在 SQLite/PostgreSQL 两侧接入精确 batch repository。
- SQLite/迁移/存储专项为 29 passed、1 skipped（该次未注入专用 PostgreSQL URL）；专用 PostgreSQL T06 业务合同 1 passed，并验证故障注入时业务批次和 ArtifactRef 同时回滚；完整 PostgreSQL 标记套件 23 passed。完整非 live 为 650 passed、1 skipped、6 deselected；唯一 skip 为需显式真实 LLM 同意的 live 用例。Ruff 通过；Mypy 275 个源文件通过。

## 单元 C：T07 已知新闻正文读取（M12）

- [x] 更新迁移测试期望 001–026 并先确认红测；新增 `news_detail_snapshots`，保存 detail ID、run/task/attempt、sector identity、document ID、原 document content hash、availability、正文 hash、有界正文、截断/历史快照标志、安全错误码和 payload。
- [x] 写失败测试：Tool schema 只允许 `document_id`，拒绝 URL、source、headers、timeout 和 task identity；document 必须来自该 A2 的输入 `news_batch` 或已完成 T06 `research_search` 产物，其他 scope/run/未知 ID 拒绝且不调用读取器。
- [x] 写失败测试：复用 `NewsDetailPort.read` 和现有 SSRF/公共 URL 校验；`summary_only`、`unavailable` 和 `historical_snapshot_verified=False` 保持真实，正文截断上限 12000 字符，不把当前页面伪装为 cutoff 时历史快照。
- [x] 写失败测试：成功、部分和不可用结果都可安全重放而不再次访问 Provider；异常只返回 `TOOL_FAILED`，未知外部结果保留预算预留；旧 attempt 的迟到正文不能登记 ArtifactRef。
- [x] 实现 `NewsDetailSnapshot`、双库 repository、`ReadBoundNewsDetailService` 和 `ReadNewsDetailTool`，原子登记 `news_detail` ArtifactRef。
- [x] 用模拟正文适配器验证新闻正文中伪造的系统指令只作为 data 字段返回，不能改变工具白名单、scope 或下一次服务端参数。
- [x] 运行本单元专项、Ruff、Mypy、完整非 live 回归及专用 PostgreSQL 合同并记录数量。

### 2026-09-14 单元 C 验证记录

- 026 迁移红测先出现 4 failed；新增不可变 `news_detail_snapshots` 后迁移专项恢复为 9 passed。全量首次运行另发现一条旧新闻 schema 测试仍固定到 025，修正版本期望后相关迁移专项为 11 passed。
- T07 业务红测先因 `ReadBoundNewsDetailService` 不存在失败。最终服务只从当前任务钉住的 `news_batch` 或当前 attempt 已提交的 `research_search` 解析已知 document ID；URL、Provider、请求选项、run/task/worker/scope 均不可由模型提供。
- 模拟正文读取验证了 `summary_only`、`unavailable`、12000 字符截断和 `historical_snapshot_verified=False` 的诚实保留；正文中的伪造 system 指令仅作为数据。异常正文不会泄漏，只保存并返回 `TOOL_FAILED`；未知文档、参数注入和旧 attempt 均在 Provider 前拒绝。
- T07/迁移/存储双库专项为 29 passed；专用 PostgreSQL 已实际应用 026 并验证 `news_detail` 业务行与 ArtifactRef 原子可读。完整非 live 为 652 passed、1 skipped、6 deselected；唯一 skip 为需显式真实 LLM 同意的 live 用例。Ruff 通过；Mypy 277 个源文件通过。

## 单元 D：T08 程序证据检查（M12、M13）

- [x] 更新迁移测试期望 001–027 并先确认红测；新增不可变 `evidence_inspection_reports`，保存 report ID、run/task/attempt、sector identity、selection version、输入 ArtifactRef 指纹、context/gate/document views payload 与创建时间。
- [x] 写失败测试：T08 只能读取当前 A2 任务钉住或由该任务产生的 market/news/search/detail 产物；输入顺序不决定指纹，跨板块、跨 run、旧 attempt、未知 kind 和“自动取最新”均拒绝。
- [x] 写失败测试：从可信 selection、候选/行情快照、事件、文档、sector links 和正文快照构建 `EvidencePack`，直接复用 `build_evidence_pack`、`build_attribution_context` 与 `evaluate_attribution_gate`；事件时序、来源等级、正文可用性、板块广度和 broad-market alternative 只由代码判定。
- [x] 写失败测试：eligible/background/excluded、counter evidence、缺发布时间、cutoff 后新闻、无 primary source 和市场先涨后消息的等级上限与旧门禁完全一致；原始事实和资格原因可解释但模型不能覆盖。
- [x] 实现 `EvidenceDocumentView`、`EvidenceInspectionReport`、双库 repository、`InspectSectorEvidenceService` 和 `InspectEvidenceTool`。输出有界摘要，完整报告通过 T15/明确引用读取；原子登记 `evidence_inspection` ArtifactRef 以保证 T09 恢复使用同一报告。
- [x] 增加旧 `attribution/gate_cases.yaml` 参数化等价回归，并验证 T08 本身不调用 LLM、不访问任意 URL。
- [x] 运行本单元专项、Ruff、Mypy、完整非 live 回归及专用 PostgreSQL 合同并记录数量。

### 2026-09-14 单元 D 验证记录

- 迁移测试先因缺少 027 出现 5 failed；新增不可变 `evidence_inspection_reports` 后相关迁移专项为 11 passed。领域/Tool 红测分别先因 `evidence_tools` 模块不存在而失败；双库合同也先因 repository port 和实现不存在而收集失败。
- T08 只接受当前 A2 输入或当前 task/attempt 产生的授权 ArtifactRef；候选批次必须是任务钉住版本，跨 scope、未知 ID、遗漏候选输入和旧 attempt 均拒绝。ArtifactRef 排序后再生成指纹，因此输入顺序不产生新权威报告。
- 实现直接复用 `build_evidence_pack`、`build_attribution_context` 与 `evaluate_attribution_gate`。现有 `gate_cases.yaml` 的参数化回归继续覆盖发布时间、来源等级、市场先涨、板块广度和归因上限；T08 不调用 LLM、不读取任意 URL，模型不能提交门禁结论。
- SQLite 原子持久化和 JSON 往返测试发现并修复了 `AttributionContext.market_facts` 中 Decimal 反序列化为字符串的问题。T08/门禁/迁移/双库合同专项为 39 passed、1 skipped（未注入专用 PostgreSQL URL）；专用 PostgreSQL 实际事务已验证 report 与 ArtifactRef 原子可读，完整 PostgreSQL 标记套件为 23 passed。完整非 live 为 655 passed、1 skipped、6 deselected；唯一 skip 为需显式真实 LLM 同意的 live 用例。Ruff 与 Mypy（282 个源文件）通过。

## 单元 E：T09 分析卡提交与不可变版本（M10、M13）

- [x] 更新迁移测试期望 001–028 并先确认红测；新增 `sector_analysis_artifacts` 与 `sector_analysis_claims`，analysis ID 为不可变主键，保存 inspection ID、input fingerprint、card payload/hash 和创建时间；不得 `INSERT OR REPLACE` 覆盖旧卡。
- [x] 写失败测试：Tool schema 接收 inspection ArtifactRef 与 `SectorAnalysisSubmission`，后者只含 attribution level、confidence、conclusion、引用、claims、不确定性和禁止推断；run/sector/kind/name/allowed_max_level 必须由报告构造。伪造 supporting/claim/background ID、引用 excluded 证据作 supporting、跨 scope ID 和证据不足却宣称强因果均返回稳定校验码。
- [x] 写失败测试：直接复用并补强 `validate_analysis_card`。每个 `NEWS_FACT`/`ATTRIBUTION` claim 必须有合格 evidence；BACKGROUND 只能引用 background IDs；claim 的 attribution level 不得高于报告 gate；市场数字继续由 `validate_claim_numbers` 校验，投资建议语言继续拒绝。
- [x] 写失败测试：无可靠解释是合法卡片而非工具失败；其 supporting IDs 为空、confidence/level 受控并保留 uncertainties/counter evidence。无效提交不写业务行或 ArtifactRef，Agent 可在下一轮根据结构化错误修正。
- [x] 实现 `SectorAnalysisArtifact`、双库 repository、`SubmitSectorAnalysisService` 和 `SubmitAnalysisTool`；成功时原子登记 `sector_analysis` ArtifactRef，重放返回相同 analysis ID，旧 attempt 迟到提交不能覆盖当前卡。
- [x] 保持旧 `sector_analysis_cards` 和 Phase1B 查询可读；新权威 repository 提供按 analysis ID 精确读取，P3c 上下文只消费 ArtifactRef，不隐式选择旧表或最新版本。
- [x] 用 SQLite 并发提交验证同指纹幂等、不同修正产生新版本且旧版本可读；用专用 PostgreSQL 验证同合同。
- [x] 运行本单元专项、Ruff、Mypy、完整非 live 回归并记录数量。

### 2026-09-14 单元 E 验证记录

- 028 迁移红测先出现 5 failed；新增不可变 `sector_analysis_artifacts` 与 `sector_analysis_claims` 后迁移专项为 11 passed。
- 首条 T09 提交测试先因 `SubmitSectorAnalysisService` 不存在失败。当前核心服务已从当前 task/attempt 的 `evidence_inspection` 恢复服务器身份与归因上限，复用并补强 `validate_analysis_card`：excluded 证据不能作为 supporting，NEWS_FACT/ATTRIBUTION claim 必须引用 eligible 证据，BACKGROUND claim 只能引用 background，投资建议语言和市场数字继续由原校验器拒绝。
- 双库精确 repository、RuntimeStorageBundle、`SubmitAnalysisTool`、稳定校验错误和持久化重放均已接入。counter evidence 由 inspection 报告强制恢复，模型不能覆盖；run/task/attempt/sector/name/selection/allowed max 同样全部由服务器上下文构造。
- “无可靠解释”以空 supporting、受控等级和较低 confidence 合法提交并保留 uncertainties/counter evidence。无效、跨 scope 和旧 attempt 提交不会调用 committer；SQLite 并发同指纹仅产生一个权威产物，不同修订生成新 ID 且旧版本继续可读。
- T09 相关专项为 41 passed、1 skipped（未注入专用 PostgreSQL URL）；专用 PostgreSQL 完整标记套件为 23 passed，并实际验证 T06→T07→T08→T09 业务行与 ArtifactRef。完整非 live 为 657 passed、1 skipped、6 deselected；唯一 skip 为需显式真实 LLM 同意的 live 用例。Ruff 通过；Mypy 284 个源文件通过。

## 单元 F：A2 角色、S03/S04 与真实框架轨迹

- [x] 先写失败测试：A2 精确拥有 T06–T09、T15 和 `skill`；不能 delegate、request_selection、approve、写稿、执行 SQL/文件/任意 URL，也不能读取其他 A2 scope 的私有 research/detail/inspection/analysis 产物。
- [x] 创建 `config/agent-skills/causal-evidence/SKILL.md`：只包含主体/事件/时间一致性、反证、替代解释、因果等级和何时输出“无可靠解释”的研究方法；不包含证据 ID 白名单和等级比较代码。
- [x] 创建 `config/agent-skills/news-verification/SKILL.md`：只包含原文/转载/简讯区别、出处核对、正文不可得和历史快照不确定性的表达方法；不包含抓取、URL、凭据、来源资格或权限规则。
- [x] 把 A2 的 `AllowedSkillManager` 限定到 S03/S04；复用已验证的路径穿越、未授权 Skill 和符号链接越界拒绝测试。
- [x] 用真实 `ParentAgent`/`SubAgent` 和脚本化模型跑 A0→两个 A2 的轨迹：各 A2 至少观察 T08，证据不足的实例调用 T06→T07→T08，再先提交一张非法引用卡得到结构化拒绝，最后提交合格卡；两个 scope 的上下文、预算和审计不混淆，并发活动 A2 不超过 2。
- [x] 在轨迹中 monkeypatch 旧 `run_attribution_agents`、`AgentRuntime.run`、`run_agent_loop` 为一旦调用即失败，证明新入口真实使用 `aidynamic-agent` Tool 循环而非包装旧归因模式。
- [x] 验证父任务只能在每个已确认板块各有一个当前 `sector_analysis` 产物后申请研究阶段完成；研究阶段只进入通用等待态，不等于写作完成、审校完成或人工批准。
- [x] 运行 P3b 专项、Ruff、Mypy、完整非 live 和专用 PostgreSQL 标记回归；更新本计划、总计划与迁移表的真实数量。只放行 P3b，不宣称 P3/P4 或整个多 Agent 系统完成。

单元 F 验证记录：白名单/Skill/T15/T19 与真实框架专项 22 passed；P3b 汇总专项 50 passed、1 skipped（该次未注入 PostgreSQL URL）；随后使用本机隔离 PostgreSQL 18、55434 端口及专用 `sector_pulse_run_comparison_test` 运行正确的 `postgres` 标记，23 passed、646 deselected。完整非 live（含专用 PostgreSQL）为 662 passed、1 skipped、6 deselected；唯一 skip 仍是要求显式真实 LLM 同意的 live 用例。Ruff 通过；Mypy 284 个源文件通过。测试未调用真实 LLM、真实外部数据源或生产数据库。

P3c 接线前复核发现并修复 T06–T09 Tool 内容中业务对象 ID 与 orchestration ArtifactRef ID 混用：四个 Tool 现在返回下一工具/父委派可直接验证的 ArtifactRef ID，同时保留 `result_reference` 用于业务 repository 重放。四段链路契约通过；迁移 029 后完整非 live 更新为 670 passed、1 skipped、6 deselected。该修复补强 P3b 可组合性，不改变 P3c/P4 未完成状态。

## 放行检查

- [x] M10–M13、T06–T09、S03/S04 均能指向代码、红绿测试和不可变产物证据。
- [x] A2 只能研究一个已确认 scope；恢复保持输入版本，跨 run/scope 和旧 attempt 迟到结果均拒绝。
- [x] T06/T07 外部读取有预算、超时、安全错误和持久化重放；T08/T09 资格与提交规则完全由程序执行。
- [x] SQLite 并发和专用 PostgreSQL 合同通过；真实框架轨迹不调用真实 LLM/外部源/生产库，也不经过旧单次归因或旧自建循环。
- [x] Ruff、Mypy 和完整非 live 回归通过；文档记录真实 passed/skipped/deselected 数。
- [x] 未提交、合并、推送或切换生产入口；P3c/P4 保持未完成。
