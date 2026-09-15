# Phase 3c：A3 写作、修订与 A4 独立审校实施计划

状态：已于 2026-09-14 放行。单元 A–F 均完成；P4 唯一入口、历史迁移与前端验收尚未开始。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本项目按用户要求在当前会话直接执行，禁止创建子代理，也不执行计划模板通常建议的提交步骤。

**Goal:** 用真实 `vendor/aidynamic-agent` A3/A4 子 Agent 和 T10–T14 替换新运行中的旧编辑、写作、修订及审校单次调用，同时保留文章质量、证据映射、版本 CAS、程序治理与人工批准边界。

**Architecture:** A0 只委派和检查产物；A3 从服务端钉住的 selection 与当前 `sector_analysis` 产物生成不可变大纲、草稿和受审校范围约束的修订，A4 从明确草稿版本独立提交审校。所有身份、当前版本、修订轮数、来源资格、质量与治理规则由服务端上下文及 Tool 校验，Agent 不能直接写库、批准、撤销或覆盖人工编辑的新版本。

**Tech Stack:** Python 3.12、Pydantic、aidynamic-agent 0.3.0、SQLite、PostgreSQL/SQLAlchemy、pytest、Ruff、Mypy。

**Spec:** `docs/superpowers/specs/2026-09-13-feature-migration-map.md`（M14–M19、T10–T14、S05/S06）

## Global Constraints

- 不调用真实 LLM、真实外部数据源或生产数据库；模型和业务依赖使用脚本化端点、模拟适配器及临时 SQLite。
- PostgreSQL 只连接数据库名含 `_test` 的专用连接；没有专用连接时如实跳过。
- 新权威产物不可变并通过 ArtifactRef 精确引用；不隐式读取旧表最新版，不覆盖旧有效稿。
- 每个 Tool 继续经过 `BudgetedTool`，绑定 run/task/attempt/role/worker、输入指纹、次数、deadline 和人民币预算。
- 用户编辑、批准、撤销与证据人工决定不开放为 Agent Tool；模型输出 `PASS` 也不等于人工批准。
- 不调用 `run_editorial_agent`、`run_writing_agent`、`run_revision_agent` 或 `run_review_agent` 作为新 Agent 的隐藏旧流水线。
- 保留旧入口供 P4 前兼容读取；本阶段不提交、合并、推送或切换生产入口。

## 文件结构

- `application/orchestration/editorial_context.py`：解析 A3/A4 scope、钉住 selection/analysis/outline/draft/review 引用并校验当前版本与租约。
- `application/orchestration/editorial_tools.py`：T10/T11/T12 的领域服务、程序校验与原子持久化边界。
- `application/orchestration/review_tools.py`：T13 程序检查与 T14 独立审校提交服务。
- `domain/writing/editorial.py`：模型可提交 DTO 与不可变 outline/draft/check/review 产物包装；复用 `ArticleOutline`、`ArticleDraft`、`ReviewReport`，不复制旧领域模型。
- `infrastructure/agents/editorial_tools.py`、`infrastructure/agents/review_tools.py`：aidynamic-agent Tool schema、稳定错误和持久化重放。
- `storage/migrations/029_editorial_outline_artifacts.sql` 及后续按单元递增的 draft/check/review 迁移：每版只新增对应不可变业务表与版本唯一约束，不修改 001–028。
- `storage/{sqlite,postgres}/writing/editorial_repository.py`：按精确产物 ID 与 draft/version 读取；写入由原子持久化适配器完成。
- `config/agent-skills/analysis-writing/SKILL.md`、`config/agent-skills/independent-review/SKILL.md`：只读方法 Skill。
- `infrastructure/agents/roles.py`、`runtime.py`：A3/A4 精确工具、Skill 和上下文构造。

---

## 单元 A：A3 输入钉住与版本所有权

**Interfaces**

- `BoundEditorialContextReader.read(task_id: UUID, attempt: int, worker_id: str) -> BoundEditorialContext`
- `BoundEditorialContext` 包含 `run_id`、`task_id`、`attempt`、`worker_id`、`role`、`scope`、`selection_version`、`input_artifact_ids` 和解析后的精确业务产物；对象冻结且不接受模型身份字段。
- A3 scope 仅允许 `article:<run_id>`；A4 的 draft/version 上下文在单元 D、草稿产物存在后实现。

- [x] 在 `backend/tests/integration/test_orchestration_editorial_context.py` 写失败测试：A3 必须钉住当前 candidate selection 和每个已确认板块的一个当前 `sector_analysis`；遗漏、重复、跨 run、跨 scope、旧 attempt 和自动取最新版全部拒绝。
- [x] 运行上述测试并确认 3 项均因 `editorial_context` 模块不存在而失败。
- [x] 实现 `editorial_context.py`，复用 `TaskRecord.input_artifact_ids`、`selection_version`、租约检查和精确 ArtifactRef，不增加模型参数。
- [x] 运行专项、Ruff、Mypy 和完整非 live；专项 3 passed，完整非 live（含专用 PostgreSQL）665 passed、1 skipped、6 deselected；Ruff 通过，Mypy 285 个源文件通过。

## 单元 B：T10 submit_outline

**Interfaces**

- `ArticleOutlineSubmission` 只含 `sector_ids`、`order_reasons`、`title_directions`、`thesis`、`section_character_budgets`、`excluded_sector_reasons`。
- `SubmitOutlineService.submit(context: BoundEditorialContext, submission: ArticleOutlineSubmission, now: datetime) -> EditorialOutlineArtifact`
- `SubmitOutlineTool` schema 只暴露 `submission`；Tool 名固定为 `submit_outline`，重放引用为 `article-outline:<outline_id>`。

- [x] 写失败测试：sector 必须来自钉住分析、顺序唯一且为 3–6 个、预算键精确匹配、run/outline/task/attempt/worker 不可由模型提供；未确认板块和跨 run 分析拒绝。
- [x] 写失败测试：相同 task/attempt/指纹可由 `BudgetedTool`/精确 repository 重放，不同修订创建新不可变 ID且旧版继续可读；业务行、ArtifactRef 和事件原子提交，迟到 attempt 由通用 committer 门禁拒绝。
- [x] 先运行并确认 2 项因 `editorial_tools` 模块不存在而失败，迁移/仓储合同随后因 029 和 repository 不存在而失败；再最小实现 DTO、校验、双库 repository、迁移 029 和框架 Tool。
- [x] 运行 T10/迁移/仓储专项、PostgreSQL 合同、Ruff、Mypy 和完整非 live。专项 35 passed；完整非 live（含专用 PostgreSQL）670 passed、1 skipped、6 deselected；Ruff 通过，Mypy 290 个源文件通过。

## 单元 C：T11 submit_draft

**Interfaces**

- `ArticleDraftSubmission` 不含 `draft_id`、`run_id`、`version`、`status`；只含 titles/introduction/sections/conclusion/risk_notice，来源由服务器根据钉住分析与新闻证据重建。
- `SubmitDraftService.submit(context: BoundEditorialContext, outline_artifact_id: UUID, submission: ArticleDraftSubmission, now: datetime) -> EditorialDraftArtifact`
- `SubmitDraftTool` 只暴露 `outline_artifact_id` 与 `submission`，成功引用 `article-draft:<artifact_id>`。

- [x] 写失败测试：章节集合必须精确匹配大纲且 section/sector 唯一；标题、导语、结语、风险提示、字符数和主体命名执行 `ArticleDraft`、`draft_quality_issues`、`sector_subject` 与禁止语言规则。
- [x] 写失败测试：claim/source 只能引用对应 `sector_analysis` 的 supporting/background 证据及服务器可验证来源；未知来源、因果越级、正文系统审核标记、模型伪造 READY/版本/来源元数据均拒绝。
- [x] 写失败测试：首稿固定 version=1、status=UNREVIEWED；同指纹由预算 Tool 重放，不覆盖现有 v1；旧有效稿和旧表继续可读。
- [x] 确认 2 项先因 `SubmitDraftService` 不存在而失败后，实现 T11 服务、原子持久化、双库精确读取、迁移 030 和框架 Tool；不调用旧 `run_writing_agent`。
- [x] 运行 T10/T11/迁移/仓储专项、专用 PostgreSQL、Ruff、Mypy 和完整非 live。专项 41 passed；完整非 live（含专用 PostgreSQL）674 passed、1 skipped、6 deselected；Ruff 通过，Mypy 290 个源文件通过。

## 单元 D：T13 check_draft_rules 与 T14 submit_review

**Interfaces**

- `DraftRulesReport` 绑定 `draft_id`/`draft_version`，分别保存 `quality_issues` 与 `GovernanceReport`；检查结果不可由模型提供。
- `CheckDraftRulesService.check(context: BoundEditorialContext, draft_artifact_id: UUID, now: datetime) -> DraftRulesArtifact`
- `ReviewSubmission` 只含 `decision`、`issues`；`SubmitReviewService.submit(context, draft_artifact_id, rules_artifact_id, submission, now) -> IndependentReviewArtifact`。
- Tool 名分别为 `check_draft_rules`、`submit_review`，重放引用为 `draft-rules:<id>`、`independent-review:<id>`。

- [x] 写失败测试：T13 精确读取明确草稿版本并实际调用 `draft_quality_issues` 与 `GovernanceService.check`；不能接受模型提供的检查结果或规则版本。
- [x] 写失败测试并实现 A4 的 `review:<draft_id>:<version>` 服务端上下文：必须钉住一个明确 draft ArtifactRef；人工编辑产生 v2 后，绑定 v1 的 A4 仍只能读 v1，不能将 v1 审校用于 v2。
- [x] 写失败测试：T14 只能由 A4 提交，报告必须绑定当前上下文的 draft/version 和 T13 报告；PASS 遇程序问题拒绝，意见引用未知 section/claim 时拒绝。
- [x] 写失败测试：同一 A4 attempt 可修正无效提交；成功审校不可变，v1 报告不能证明 v2 已审校，任何结果都不创建批准/撤销记录。
- [x] 确认红测后实现领域 DTO、服务、原子业务写入、双库读取、迁移 031/032 和 Tool；复用治理服务但不调用旧 `run_review_agent`。
- [x] 运行专项、PostgreSQL 合同、Ruff、Mypy 和完整非 live。专项 48 passed；完整非 live（含专用 PostgreSQL）681 passed、1 skipped、6 deselected；Ruff 通过，Mypy 292 个源文件通过。

## 单元 E：T12 submit_revision 与最多两轮自动修订

**Interfaces**

- `SubmitRevisionService.submit(context, base_draft_artifact_id: UUID, review_artifact_id: UUID, changes: RevisionChanges, now: datetime) -> EditorialDraftArtifact`
- 服务端从持久化审校计算 `_scope`，用现有 `_apply` 等价的纯规则校验允许字段，但不调用旧 `run_revision_agent`；新版本为 base+1、status=UNREVIEWED。
- `SubmitRevisionTool` 只暴露 base draft、review 引用和 changes；不暴露版本、轮数、actor 或批准字段。

- [x] 写失败测试：只有 decision=REVISE 的当前审校可触发，修改必须落在 issue 指定 section/claim 或全局范围；未知来源、因果越级、无变化与质量失败返回稳定错误。
- [x] 写失败测试：服务器自动修订轮数最多 2；v1→v2 后旧 review 不可再次生成竞争 v2，v2→v3 需要 v2 新审校，第三轮拒绝。
- [x] 写失败测试：人工先产生更高版本时旧 base CAS 失败，不覆盖人工稿；旧 attempt 迟到提交由通用 committer 门禁拒绝，不改变当前版本或 ArtifactRef。
- [x] 确认红测后复用 `_scope`/`_apply` 的纯规则实现 T12 原子版本提交与重放，补强板块来源隔离；旧 `run_revision_agent` 保留兼容但新路径不调用。
- [x] 运行 SQLite 多 worker 竞争、PostgreSQL 合同、Ruff、Mypy 和完整非 live。专项 64 passed；完整非 live（含专用 PostgreSQL）685 passed、1 skipped、6 deselected；Ruff 通过，Mypy 292 个源文件通过。

## 单元 F：A3/A4 Skill、精确权限与真实框架闭环

**Interfaces**

- A3 精确拥有 T08、T10–T13、T15、`skill`；A4 精确拥有 T07、T08、T13–T15、`skill`。两者均无 delegate/request_selection/request_finish/approve/revoke/SQL/file/arbitrary URL。
- A3 Skill 仅 `analysis-writing`；A4 Skill 仅 `independent-review` 与 `news-verification`。

- [x] 创建 `analysis-writing/SKILL.md`：主体命名、标题/导语/章节、事实与解释分离、修订方法；不含 schema、版本 CAS、证据白名单或批准规则。
- [x] 创建 `independent-review/SKILL.md`：逐结论核对、来源映射、因果越级、可执行意见；不含自动批准或修改作者稿权限。
- [x] 写失败测试并收紧 A3/A4 工具与 Skill 白名单，复用路径穿越、未授权 Skill 和符号链接越界测试；显式验证 A3/A4 不能读取不相关 task 的私有草稿/审校产物。
- [x] 用真实 `ParentAgent`/`SubAgent` 和脚本化模型执行 A0→A3 大纲/草稿→A4 检查/REVISE→A3 限域修订→A4 对新版本重新检查/PASS→A0 申请完成。
- [x] 轨迹中把 `run_editorial_agent`、`run_writing_agent`、`run_revision_agent`、`run_review_agent` 设为一调用即失败；验证共享预算与 Tool 审计按 task/attempt/role 分离，A4 PASS 仅让根任务进入 `WAITING_USER_REVIEW`。
- [x] 运行 P3c 专项、Ruff、Mypy、完整非 live 和专用 PostgreSQL 标记回归；P3c 专项 90 passed，完整非 live 689 passed、1 skipped、6 deselected，PostgreSQL 标记 26 passed、670 deselected；Ruff 通过，Mypy 292 个源文件通过。只放行 P3c，不宣称 P4 或整个系统完成。

## 放行检查

- [x] M14–M19、T10–T14、S05/S06 均有代码、红绿测试、不可变产物和双库证据。
- [x] A3/A4 只读明确引用与版本；人工编辑、跨 run/task、旧 attempt 和旧 review 均不能覆盖当前状态。
- [x] 写作质量、来源、因果等级、治理、修订范围和两轮上限由程序执行；Skill 只承载方法。
- [x] 真实框架闭环不调用真实 LLM/外部源/生产库，也不经过旧编辑/写作/修订/审校单次调用。
- [x] 专用 PostgreSQL、Ruff、Mypy 和完整非 live 通过并记录真实数量。
- [x] 未提交、合并、推送或切换生产入口；P4 仍未完成。
