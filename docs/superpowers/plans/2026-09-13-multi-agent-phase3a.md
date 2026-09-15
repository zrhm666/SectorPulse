# Phase 3a：A1 数据与选题迁移实施计划

状态：已放行（2026-09-14）。前置 Phase 2 已放行；本阶段只迁移 M01–M09、T01–T05、S01–S02，不切换生产入口，不删除旧链路。

## 目标与边界

把 `run_phase1a2_probe` 中行情采集、质量判断、确定性评分、初始新闻采集和候选提案拆成可单独审计、可恢复、可幂等重放的 A1 工具。A1 仅决定调用顺序并解释候选，不能计算分数、填补缺失行情、确认用户选择或启动写作。所有 run/task/attempt/role/scope/cutoff 和预算身份均由服务端上下文绑定。

旧 `run_real_data_workflow` 和 `run_phase1a2_probe` 在本阶段保留用于兼容与等价回归，但不得被新 Tool 整体包装调用。测试只用模拟 Provider、临时 SQLite 和专用 `_test` PostgreSQL；不调用真实外部数据或 LLM。

## 契约与文件布局

- 新增 `backend/src/sector_pulse/application/orchestration/data_tools.py`：T01–T05 应用服务、受控输入/输出模型、安全错误码、输入指纹。
- 新增 `backend/src/sector_pulse/infrastructure/agents/data_tools.py`：`aidynamic-agent` Tool 适配器，只暴露模型可填写的业务参数，身份从 `AgentToolContext` 注入，并统一经 `BudgetedTool`。
- 扩展 `backend/src/sector_pulse/storage/ports/market.py`、`storage/ports/news.py`、`storage/ports/runs.py`：仅补充现有事实和候选读取能力；SQLite/PostgreSQL 实现保持相同合同。
- 业务产物通过现有 `AtomicArtifactCommitter` 保存 ArtifactRef，正文仍落原业务表；不得把行情或新闻全文复制进编排快照。
- 新增 `config/agent-skills/data-gap-handling/SKILL.md` 与 `config/agent-skills/sector-selection/SKILL.md`，由框架 `SkillManager`/`SkillTool` 只读加载；硬校验仍在代码中。
- 扩展 `infrastructure/agents/roles.py` 与角色 YAML：A1 精确白名单为 T01–T05、T15 和允许的 Skill；A0 不获得数据写工具。

## 单元 A：T01 行情采集与 T02 质量读取（M02、M03）

- [x] 在 `backend/tests/integration/test_orchestration_data_tools.py` 先写失败测试：T01 只接受批准的 `industry`/`concept` 类型；未返回值保持缺失语义；相同 cutoff、来源版本和输入指纹重放不再次调用 Provider；补采仅请求指定缺口，不重跑全部类型。
- [x] 写失败测试：当前 attempt/租约过期时不得调用 Provider 或写产物；成功时市场业务行与 `market_snapshot` ArtifactRef 同事务可见；异常/CAS 冲突不留虚假引用。（行情专用成功/租约测试，加上既有通用异常/CAS 原子事务回归。）
- [x] 最小实现 `CollectMarketService`，复用 `MarketDataPort.fetch_sector_universe`、`AnalysisRun.lock_live_cutoff`、现有 market repository 和原子产物提交器；来源和模式来自服务器配置，不接受模型指定 Provider。
- [x] 写失败测试：T02 只读取指定当前快照，直接调用 `evaluate_universe`，返回真实字段可用性、阻塞原因和状态；模型输入不能覆盖阈值或质量标签。
- [x] 最小实现 `InspectDataQualityService`，阈值来自运行配置；核心行情阻塞保持 BLOCKED。
- [x] 运行专项测试、Ruff、Mypy 和全量离线回归并记录数量。

## 单元 B：T03 确定性候选评分（M07）

- [x] 先写失败测试：给定与旧测试相同的行业/概念快照和新闻关联，T03 输出与 `select_market_precandidates`/`select_candidates` 的 rank、score、reason 完全一致；缺字段仍按现有 `_dimension_weights` 处理。
- [x] 写失败测试：输入指纹包含快照引用、新闻批次引用和 limit；同输入重放不重复计算/入库，不同输入复用调用身份时报冲突，旧 attempt 迟到提交被拒绝。
- [x] 最小实现 `RankSectorCandidatesService`，直接调用现有评分函数并保存版本化候选业务行及候选 ArtifactRef，不让 Agent 提供分数。
- [x] SQLite 与 PostgreSQL 合同验证候选顺序、Decimal 精度和事务原子性，覆盖 MARKET 与 NEWS_ENRICHED 两阶段。
- [x] 运行专项测试、Ruff、Mypy 和全量离线回归并记录数量。

## 单元 C：T04 有界初始新闻采集（M04–M06）

- [x] 先写失败测试：候选引用限定真实 sector ID；查询窗口、关键词预算、披露代码预算、来源并发和重试上限由服务端配置固定；无效补采原因拒绝。
- [x] 写失败测试：复用 `build_news_query_plan`、`execute_news_query_plan`、`deduplicate_documents`、`resolve_sector_links` 和 `evaluate_news_quality`；重复新闻聚合为一个事件，映射 ID 只来自快照名单。
- [x] 写失败测试：报告逐来源实际调用数、重试数、返回文档数和安全失败码；部分失败不伪装成功，cutoff 后文档保持排除；同一输入已完成重放不再访问 Provider。
- [x] 最小实现 `CollectInitialNewsService`，保存现有 document/event/link/audit 业务事实，并原子登记 `news_batch` ArtifactRef；不运行任何归因或写作模型。
- [x] SQLite 与 PostgreSQL 合同验证去重、审计统计、输入指纹和迟到 attempt 拒绝。
- [x] 运行专项测试、Ruff、Mypy 和全量离线回归并记录数量。

## 单元 D：T05 候选提案和人工边界（M08、M09）

- [x] 先写失败测试：提案 ID 必须来自当前候选产物且不重复，顺序按程序 rank 固定；解释与 score 分字段保存，Agent 不能提交/改写数值分数。
- [x] 写失败测试：提案只产生 `candidate_proposal` ArtifactRef，不写 `CandidateSelection`，`require_confirmed` 仍失败；3–12 限制和候选版本冲突继续由服务端执行。
- [x] 最小实现 `ProposeCandidatesService`；交互运行交给已有 T18 进入 `WAITING_USER_SELECTION`，默认确认仅允许创建根任务时已固化的非交互策略调用原 `confirm_default`。
- [x] 新增上下文组装读取器，只通过快照、候选、新闻/证据和 selection 版本引用供后续 A2/A3 使用；重试必须保持原引用，不构造旧 `Phase1BRequest` 驱动旧流水线。
- [x] 运行专项测试、Ruff、Mypy 和全量离线回归并记录数量。

## 单元 E：A1 角色、受控 Skill 与框架轨迹（S01、S02）

- [x] 先写失败测试：A1 只拥有 T01–T05、T15 和 S01/S02；不能 delegate、confirm、approve、执行 SQL、任意 URL 或加载仓库外 Skill。
- [x] 编写 S01，覆盖可补采缺口、必须终止情形和资料不足表达；不包含阈值、凭据或权限规则。
- [x] 编写 S02，覆盖涨跌幅/换手率/广度解释、避免只追涨和提案说明格式；不包含权重、3–12 校验或用户确认。
- [x] 用框架 `SkillManager`/`SkillTool` 加载受限目录，验证路径穿越、符号链接越界和未授权 Skill 被拒绝。
- [x] 用确定性 Provider 跑真实 A0→A1 框架轨迹：A1 按观察调用 T01–T05，预算/审计绑定正确 task/attempt/role，最终只产生待确认提案；不调用真实 LLM/外部源。
- [x] 运行专项测试、Ruff、Mypy、全量离线回归及专用 PostgreSQL 标记回归并记录数量。

## 放行条件

- [x] M01–M09 的迁移表逐项有代码与测试证据，旧链路只作兼容/等价基线，未被新 Agent 入口调用。
- [x] T01–T05 均经过 `BudgetedTool`、租约/attempt 校验、幂等审计与原子产物登记；无宽泛保存、SQL、文件或网络工具。
- [x] SQLite 并发与 PostgreSQL 合同通过；PostgreSQL 仅使用专用 `_test` 库。若本机现有服务凭据不可用，可使用本机安装程序启动仓库 `.tmp` 下的隔离测试实例，不触碰现有服务数据目录。
- [x] Ruff、Mypy、全量非 live 回归通过，文档记录真实 passed/skipped/deselected 数；不把 P3a 放行描述为整个 P3 或多 Agent 系统完成。
- [x] 更新本计划、总计划和迁移表；未经用户明确要求不提交、合并或推送。

## 2026-09-13 P3a 首个子步骤验证

- 测试先行：新增测试首次在收集阶段因 `application.orchestration.data_tools` 不存在而失败，随后最小实现通过。
- 专项：4 passed；Ruff 全项目通过；Mypy 251 个源文件通过。
- 全量离线回归：592 passed、5 skipped、27 deselected。跳过项仍是需要专用 PostgreSQL URL 的非 postgres 标记合同；本子步骤未调用真实 Provider、LLM 或数据库。
- 当前仅完成 T01/T02 的纯应用核心，不代表单元 A、P3a 或整个 P3 完成；下一步是 cutoff、租约、幂等和原子业务产物接线。

## 2026-09-13 P3a T01/T02 持久化子步骤验证

- 测试先行：行情事务/租约测试首次因 `MarketCollectionContext` 不存在而失败；框架适配首次因 `CollectMarketTool` 不存在而失败；默认重放测试首次返回“已记录但结果不可用”；质量读取首次因 `InspectDataQualityTool` 不存在而失败。
- T01 已绑定当前 run/task/attempt/worker，租约过期时在 Provider 调用前拒绝；成功快照与 `market_snapshot` ArtifactRef 同事务保存。每次预算调用只允许一个行情类型，防止批量绕过工具次数限制。
- `BudgetedTool` 可自动使用业务 Tool 的受控 `replay` 合同；相同 T01/T02 输入读取持久化结果，不重复执行外部副作用。T02 只接受 ArtifactRef，阈值不在模型参数中。
- SQLite/框架专项：12 passed；新增 PostgreSQL 行情原子合同：1 passed、4 deselected。
- 完整非 Live（含 PostgreSQL）回归：623 passed、7 deselected；Ruff 全项目通过；Mypy 252 个源文件通过。
- 尚未完成：初次行业+概念采集后的 cutoff 固化/恢复读取，因此单元 A 继续保持执行中；T03 发现旧覆盖式 `sector_candidates` 不满足不可变产物，下一步以 021 版本化候选批次迁移处理。

## 2026-09-13 P3a 单元 A 放行与 T03 市场阶段验证

- 单元 A 已完成：首次 T01 必须在一次有界调用中取得行业与概念，全部返回后执行观测偏差门禁并锁定 cutoff；超限不发布产物。已锁定运行的后续补采每次仅允许一个类型。
- `analysis_runs` 增加同合同恢复读取，SQLite 和 PostgreSQL 都能在新连接中还原完整 cutoff；T01 批次重放使用真实 ArtifactRef 集合。
- 021 增量迁移新增不可变 `candidate_batches`/`sector_candidate_versions`，不修改或覆盖旧 `sector_candidates`。迁移红测首次 4 failed，随后通过。
- T03 市场阶段直接调用原 `select_market_precandidates`，保存 Decimal 分数、名称、rank、reason 和输入指纹；不同 limit 产生不同批次，旧批次保持可读。模型参数不包含分数或 limit。
- 全量首次发现并修正两个合同问题：遗漏历史迁移数量断言，以及错误新增顶层 candidates port；CandidateBatch 协议现归属既有 market 存储边界。
- PostgreSQL：T01 合同 1 passed、T03 合同 1 passed；完整非 Live（含 PostgreSQL）回归最终为 631 passed、7 deselected。Ruff 全项目通过；Mypy 257 个源文件通过。
- T03 仍为部分完成：`NEWS_ENRICHED` 阶段必须在 T04 产出真实、版本化 news_batch 后再测试和实现，不能用虚构事件引用提前宣称完成。

## 2026-09-13 P3a T03/T04 放行验证

- 测试先行：T04 首测先因新闻编排服务/框架 Tool 不存在而失败；来源返回数红测先因 `SourceRunMetric` 缺少字段失败；重试红测证明旧聚合错误地把查询数当成实际 Provider 调用数；T03 新闻增强红测先因服务和 Tool 不接受 news ArtifactRef 失败。
- T04 使用服务器固定窗口、关键词/披露预算、并发与重试限制，复用旧查询、去重、映射和质量函数；保存 document/event/link/query/source audit 与不可变 news batch，并与 ArtifactRef 原子登记。无效补采原因、重放、部分失败、cutoff 排除和恢复后旧 attempt 均有 SQLite 证据。
- T03 的 MARKET 与 NEWS_ENRICHED 阶段分别直接调用 `select_market_precandidates` 与 `select_candidates`；新闻增强输入指纹包含真实 news ArtifactRef，框架重放不重复保存，模型仍不能提交 score 或 limit。
- 专项：33 passed；PostgreSQL 候选＋新闻原子合同 1 passed。使用仓库 `.tmp` 隔离 PostgreSQL 18 实例、端口 55433 和专用 `sector_pulse_run_comparison_test`，未触碰系统 PostgreSQL 服务数据目录。
- 完整非 Live（含 PostgreSQL）回归：635 passed、1 skipped、6 deselected；唯一 skip 是需显式真实 LLM 授权的 live 用例。Ruff 全项目通过；Mypy 262 个源文件通过。本结果只放行 T03/T04，不代表 P3a 或多 Agent 系统完成；下一步为 T05 候选提案与人工边界。

## 2026-09-13 P3a T05 放行验证

- 测试先行：迁移红测首次 5 failed；T05 主测试首次因提案服务不存在失败；显式引用上下文红测首次因读取器不存在失败，随后均以最小实现通过。
- 023 增量迁移新增不可变 `candidate_proposals` 与明细表。Agent 只提交候选 ID 和解释；name/kind/rank/score 均从当前 CandidateBatch 复制，3–12、唯一 ID、当前 task/attempt/租约与未知 ID 由服务端拒绝。
- 提案只原子登记 `candidate_proposal` ArtifactRef，不写 `data_run_candidate_selections`；原 `require_confirmed` 在没有用户确认时仍抛出 `CANDIDATE_SELECTION_REQUIRED`。交互暂停继续由既有 T18 控制，默认确认继续只在既有非交互调度策略中调用。
- `ReferencedContextReader` 只解析调用方明确钉住的 ArtifactRef 和 selection 版本，不自动替换最新产物，也不构造旧 `Phase1BRequest`。
- SQLite/框架/迁移与仓储专项通过；PostgreSQL 行情→新闻→增强候选→提案原子合同 1 passed。完整非 Live（含 PostgreSQL）回归：637 passed、1 skipped、6 deselected；Ruff 全项目通过；Mypy 268 个源文件通过。本结果只放行 T05，P3a 仍等待 S01/S02、A1 权限接线与完整框架轨迹。

## 2026-09-14 P3a 最终放行验证

- A1 的框架工具白名单精确为 T01–T05、T15 与 `skill`，不含委派、确认、批准、SQL、文件或任意网络能力；S01/S02 通过真实 `aidynamic-agent` 的 `SkillManager`/`SkillTool` 只读加载，未授权名称、路径穿越、符号链接根目录及越界目标均被拒绝。
- 真实 A0→A1 框架轨迹使用脚本化模型端点与模拟行情/新闻 Provider，依次执行 T01–T05 并加载受控 Skill；工具审计保持正确 task/attempt/role，最终只产生 `candidate_proposal`，未产生用户选择。
- 最终轨迹红测发现 T02 尚未登记完成策略要求的 `data_quality` 产物；024 迁移和最小持久化实现使质量业务行与 ArtifactRef 原子提交，旧 attempt、阈值注入和重放边界保持不变。
- P3a 专项为 43 passed、1 skipped（未注入专用 PostgreSQL URL 时按设计跳过）；显式绑定仓库隔离的 `sector_pulse_run_comparison_test` 后，PostgreSQL 标记回归为 22 passed、626 deselected。反复运行还暴露并修正了对照列表测试只读取首 100 条的隔离缺陷，现按公开分页合同读取全部结果。
- 最终完整非 live 回归为 641 passed、1 skipped、6 deselected；唯一 skip 是需显式真实 LLM 授权的 live 用例。Ruff 全项目通过；Mypy 269 个源文件通过。P3a 据此放行；P3b、P3c、P4 和整个多 Agent 业务系统仍未完成，下一步是 P3b 的 A2 研究与证据迁移。
