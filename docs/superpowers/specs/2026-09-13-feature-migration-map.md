# 旧版 → 父子 Agent 版：功能迁移总说明

状态：Phase 2、P3a、P3b、P3c 与 P4 单元 A/B/C/D 已放行；P4 单元 E（人工审核、编辑、批准、撤销与导出接线）、单元 F（前端移除双模式并展示动态任务树）均已全部完成并验证，待放行。下一步推进 P4 单元 G（清理、回退证据与最终验收）。本文件描述完整目标；除“当前进度”明确列出的部分外，不表示其余目标已经实现。

这是阅读入口。先看第 2 节职责，再看第 3 节旧功能迁移表；工程顺序见 [总计划](../plans/2026-09-12-multi-agent-platform.md)。原 [架构设计](2026-09-12-multi-agent-platform-design.md) 解释框架与安全原则。本文件补齐原文档缺失的功能映射；发生冲突时，以本文件具体迁移决策为准，不能用旧计划的笼统描述跳过功能。

## 1. 到底改变什么

旧版：数据采集链路 → 候选确认 → 内容流水线。内容流水线依次运行归因、编辑、写作、审核，再按条件做修订；归因阶段可以选择单次 LLM 或已有的查证循环。

新版：一个研究负责人 Agent 根据目标、现有产物和失败信息委派专业子任务。专业子 Agent 用工具读取事实、补查及提交结构化产物；父 Agent 根据产物再决定下一步，不由一个 Python 函数提前排完所有模型调用。

不变：行情计算、真实性、来源截止时间、证据资格、版本校验、数据持久化、用户自选和人工批准。把旧 workflow 整段套进一个叫 run_workflow 的 Tool 不算迁移；把旧单次调用函数换名为 Agent 也不算。

例子（可能的一次执行，不是固定 DAG）：父 Agent 委派选题 → 选题调用行情与评分工具 → 用户确认 → 父 Agent 委派三个板块研究 → 其中一个研究发现证据不足，补检索和读正文 → 写作产出草稿 → 审校发现引用问题 → 父 Agent 针对该板块补查或退回写作 → 当前版本重新审校 → 等待人工批准。

用户看见的主要改变：不再选“工作流/Agent”；可以看见谁正在研究哪个板块、调用哪个工具、因何补查或停止。现有行情表、新闻详情、手选板块、草稿编辑、审核和导出不消失。

## 2. 五种归属，不只 Agent

| 类别 | 在本项目中的职责 | 不负责什么 |
| --- | --- | --- |
| Agent | 用模型循环判断下一步、选择工具、根据观察修正行动 | 不算行情数值，不直接写数据库，不越权批准 |
| Tool | 输入明确参数，执行确定性操作并返回结构化结果 | 不暗中启动整套旧 LLM 流水线 |
| Skill | 可按需加载的方法、检查步骤、反例和格式指南 | 不决定权限，不承担计算，不代替可执行校验 |
| 基础服务 / 领域规则 | 预算、证据门禁、事务、状态机、幂等、调度触发、权限 | 不因模型要求而放宽规则 |
| 人工操作 | 板块确认、稿件人工编辑、批准/撤销、证据处置 | 不伪装为 Agent 自动完成 |

### 2.1 Agent 分工（目标）

| ID | Agent | 从旧版接管的决策 | 可用工具组 | 交付物 |
| --- | --- | --- | --- | --- |
| A0 | 研究负责人（唯一父 Agent） | 旧 orchestrator/pipeline 的跨阶段调度、失败后下一步决策 | 委派、读取任务/产物、请求用户选择、提交结束申请 | 调度任务树和结束申请，不直接写最终文章 |
| A1 | 数据与选题 | 判断数据缺口、是否补采、候选的业务解释 | 行情/质量/评分/初始新闻/候选提案 | 快照引用、候选提案及解释 |
| A2 | 板块归因研究 | 单板块查证、反证、证据强弱、不足时补查或停止 | 新闻检索、正文、行情、证据、归因卡提交 | 归因卡与引用；一个板块一个作用域 |
| A3 | 编辑写作 | 旧编辑+写作+修订中的模型决策，合并为一个角色 | 读取归因/证据/审核意见、提交大纲/草稿/修订 | 大纲、文章版本、逐章节来源映射 |
| A4 | 独立审校 | 旧自动审核中的事实/表达判断 | 只读草稿/证据、运行规则检查、提交审校报告 | 针对明确草稿版本的审校报告 |

不设独立“采集 API Agent”“评分 Agent”“去重 Agent”“入库 Agent”“导出 Agent”。这些任务不需要模型自主判断，用 Tool 或基础服务即可。A1 也不重新实现采集库，只决定是否调用和怎样解释结果。A3 合并三个角色减少反复传递全文；A4 独立，避免作者自己宣布审校通过。

父子限制为两层。A2 可以有多个实例，但总数和并发受服务端配置约束。不是每次运行一定启动全部角色：仅采集任务到候选产物即可暂停，但不能声称完整研报已完成。

## 3. 旧功能逐项迁移清单

以下旧代码路径以 backend/src/sector_pulse/ 为前缀。目标 Tool 名称是拟定契约，除“当前进度”明确说明外尚未实现。

| ID | 旧功能与定位 | 新归属 | 保留什么 / 改变什么 | 阶段 / 核心验收 |
| --- | --- | --- | --- | --- |
| M01 | 数据整链调度：application/data_runs/real_data_orchestrator.py::run_real_data_workflow；phase1a2_probe.py | A0/A1 + T01–T05 | 拆出已有采集和计算服务；旧固定顺序不再作为新入口执行器 | P3；一次补采不能把全部数据重新采一遍 |
| M02 | 行业/概念行情与来源适配：infrastructure 的现有 Provider、data_runs/phase1a2_probe.py | T01 + 原 Provider | 保留来源和字段可用性；模型不能填补缺失数值或切换未授权来源 | P3；未返回仍是未返回，不变成 0 |
| M03 | 行情/新闻质量：domain/market/quality.py、application/news/news_quality.py | T02 + 领域门禁 | 判断仍由代码执行；Agent 只读报告、决定补采/结束 | P3；核心行情阻塞不能靠文字报告变成功 |
| M04 | 初始新闻计划/获取：application/news/news_retrieval.py | T04（有界采集） | 保留来源配置和查询结果统计；A1 决定何时补采，程序约束窗口和次数 | P3；补采记录实际返回条数及失败源 |
| M05 | 规范化/去重：application/news/news_ingestion.py | 采集工具内部基础服务 | 保留原去重逻辑和原始/规范化引用；不额外加一次 LLM | P3；同新闻重复获取不重复入证据 |
| M06 | 实体映射：application/news/entity_resolution.py、config/sector_entities.yaml | T04/T08 内部解析服务 | 保留别名映射；Skill 不充当实体数据库 | P3；映射的板块 ID 来自真实名单 |
| M07 | 候选评分：application/data_runs/candidate_selection.py | T03 + A1 解释 | 保留数值评分与缺字段处理；Agent 不计算或改写评分，只提案解释 | P3；相同快照评分与旧版一致 |
| M08 | 自选/默认候选：CandidateSelectionService.confirm / confirm_default | 人工入口 + T05 提案 + 选择策略 | 保留 3–12 个、不可重复、必须属于候选集合、版本冲突检查；Agent 无人工确认权限 | P3/P4；确认后不能擅自替换板块 |
| M09 | 数据到写作桥：real_data_writing_bridge.py::build_phase1b_request | 上下文组装服务 + 产物引用 | 提取快照/候选/证据绑定能力；不再构造驱动旧流水线的请求 | P3；写作重试仍用原快照/选择版本 |
| M10 | 单次归因：application/writing/attribution_agents.py | 被 A2 替代 | 复用归因卡结构、校验和无可靠解释结果；下线新运行的单次调用分支 | P3/P4；不再出现模式开关 |
| M11 | 旧归因循环：agent_runner.py、agent_runtime.py | A2 使用内置框架循环 | 旧版已经能查证，不是从零发明；保留动作语义，替换循环和逐板块调度 | P3/P4；真实框架轨迹中有补查动作 |
| M12 | 旧归因工具：agent_tools.py::AttributionTools | T06/T07/T08 Adapter | 复用检索、正文、截止时间、错误脱敏；缓存错误与成功的策略分开验证 | P3；只能读本作用域已知文档 |
| M13 | 证据包/归因门禁：attribution_gate.py、agent_validation.py | T08/T09 内的强制规则 | 资格、反证、排除证据、因果强度继续程序校验；Skill 补充方法解释 | P3；伪造 supporting ID 被拒绝 |
| M14 | 编辑大纲：editorial_agents.py::run_editorial_agent | A3 + T10 | 模型选择结构，大纲保存仍代码校验；保留业务范围和来源约束 | P3；大纲不能含未确认板块 |
| M15 | 草稿写作：editorial_agents.py::run_writing_agent | A3 + T11 | 移走单次调用包装，复用 ArticleDraft/来源验证及入库；正文不是系统日志 | P3；标题、导语、板块主体、章节来源齐全 |
| M16 | 自动修订：revision_agent.py、rewrite_service.py | A0 分派 A3 + T12 | 复用允许修改范围与版本保存；取消流水线里的固定修订 while，保留最多两轮硬上限 | P3；新版本不能覆盖人工已改版本 |
| M17 | 自动审校：editorial_agents.py::run_review_agent | A4 + T13/T14 | 审校意见由独立角色产出；通过还需代码门禁，且绑定当前草稿版本 | P3；v1 报告不能证明 v2 已审校 |
| M18 | 文章质量/主体：draft_quality.py、sector_identity.py | T11/T12/T13 内部领域规则 | 原修复保留；拒绝无主体“该板块”和正文混入复核标记，不由模型自行豁免 | P3；原质量回归继续通过 |
| M19 | 治理：application/review/governance_service.py | T13 + 原服务 | 治理结果仍来自程序检查；与 A4 模型审校分开显示 | P3/P4；治理通过≠自动审校通过≠人工批准 |
| M20 | 人工证据决定、编辑、批准/撤销：web/routers/review.py、EvidenceDecisionService | 原人工 API/服务，不开放为 Agent Tool | 保留权限、版本、审计、导出限制；Agent 不能替用户批准 | P4；界面行为与现有稿件可继续使用 |
| M21 | 重试/检查点：application/tasks/run_executor.py、run_coordinator.py | 新任务状态机 + 可复用幂等/重试策略 | 重试指定任务/attempt，不重新执行整个旧 StageWork 列表 | P2/P4；中断可恢复、迟到结果不能覆盖新 attempt |
| M22 | 创建/取消/重跑：application/runs/run_commands.py、web/routers/runs.py | 新根任务命令服务 | 路由作为适配入口；新建唯一新执行器；旧记录重跑绑定旧快照后创建新根任务 | P4；所有入口含 CLI 均不能绕回旧双模式 |
| M23 | 定时触发：application/tasks/scheduler.py、schedule_service.py、scheduled_data_bridge.py | 原定时基础服务 → 新根任务 | 时钟触发不是 Agent；保留计划和默认选择策略，不让父 Agent 自行修改定时配置 | P4；一次触发只创建一个逻辑运行 |
| M24 | 预算/调用审计：agent_budget.py、invocations.py、config/llm_config.py | SharedBudget + 框架 Provider/Hooks | 新增全父子共享预留；必须保留人民币预算、价格未知语义、实际 usage、角色/task/attempt 关联 | P2；不能只有 token 账本却丢人民币上限 |
| M25 | 进度、查询与历史：writing/progress.py、run_queries.py、data_run_workbench_queries.py | 新任务事件投影 + 旧查询适配 | 新任务显示动态树；旧记录保留原阶段事实，“未记录”不推成失败/完成 | P4；刷新后任务/产物链接一致 |
| M26 | 行情/新闻/候选详情页：web/src/pages/DataRunPage.tsx | 原 UI + 新事件/产物链接 | 保留表格、详情、分页、自选；只改变数据来自新执行器的投影 | P4；无需重新设计整站视觉 |
| M27 | 审核工作台/版本/导出：web/src/pages/tabs、reporting/phase1b_report.py | 人工 UI/渲染服务 | 保留格式和审核语义；逐步解除报表对 Phase1BRunResult 的耦合 | P4；旧稿可读、导出内容无 Agent 调度日志 |
| M28 | 运营总览、运行对比、系统状态、影子验收：application/operations、comparison、web/routers/shadow_prompts.py | 原管理/评测服务 | 不改成 Agent；新增执行引擎与任务统计兼容，影子测试仍由用户选择不自动重启 | P4；不因新状态遗漏运行或错算完成数 |
| M29 | 配置与 Prompt：config/llm.yaml、config/prompts、news_sources.yaml | YAML 角色配置 + 方法 Skill + 原数据配置 | 保留模型/密钥配置入口；阶段路由迁移成角色路由，停止对新 live 运行静默回落 fixture | P2/P3/P4；配置缺失明确报错 |
| M30 | SQLite/PostgreSQL、原业务表与存储边界 | 原 Repository + 新编排表 | 原数据不重建；新表存任务、预算、事件/引用，不能把所有正文复制成多份聊天记录 | P2/P4；增量迁移与双库回归 |

### 3.1 评分不改，选题解释可以变

当前候选算法在行业/概念组内标准化：行情维度涉及绝对涨跌幅、换手率和涨跌家数广度，按可用字段决定维度；代码中有 MARKET_SCORE_WEIGHT=0.90。迁移不得趁机更换权重或让 LLM 填充缺失指标。T03 直接调用现有算法；A1 可解释“为什么值得研究”，不能把解释写回为数值评分。

提案不等于确认。交互运行在现有选择步骤等待用户；原先允许默认选择的定时/非交互入口，只有在创建任务时固化该策略才能由服务端确认默认集合。父 Agent 的 request_selection 不能伪造用户同意。板块不足三项时保留旧业务限制，报告数据不足，不输出一个伪装完整的三板块文章。

## 4. Tool 清单和边界（拟定）

所有工具的 run_id、task_id、scope、cutoff、selection_version、预算来自服务端绑定上下文，不让模型自行指定其他运行。返回统一包含 status、artifact_refs、summary、safe_error_code；大正文用有界详情读取，不把全库塞进上下文。读取不得增加 LLM 调用。

| ID / 名称 | 谁能用 | 模型提供的主要输入 → 输出 | 写入/约束 |
| --- | --- | --- | --- |
| T01 collect_market | A1 | 已批准数据类型 → 快照引用、来源/字段报告 | 有界外部采集；同一截止时间可复用，重新采集创建新快照版本 |
| T02 inspect_data_quality | A1/A0 | 本次快照引用 → 程序质量报告 | 只读，不允许覆盖质量标签 |
| T03 rank_sector_candidates | A1 | 已就绪快照引用 → 原算法候选及评分明细 | 保存带输入指纹的候选产物；相同输入不重复计算入库 |
| T04 collect_initial_news | A1 | 本次候选引用、允许的补采原因 → 新闻批次报告 | 内含旧查询计划/获取/规范化/去重/实体关联；不隐藏归因或写作 LLM |
| T05 propose_candidates | A1 | 候选内 ID 和解释 → 待确认提案 | 不写“用户已确认”；不改变程序分数 |
| T06 search_news | A2 | 查询词 → 本板块/时间范围的新闻引用 | 复用现有检索；次数受整次运行及子任务限制 |
| T07 read_news_detail | A2/A4 | 已知 document_id → 正文或缺失说明 | 只通过受限来源适配器，禁止任意 URL；不因缺正文伪造完整性 |
| T08 inspect_evidence | A2/A3/A4 | 当前范围证据/行情引用 → 原始事实与资格结果 | 只读，对照行情能力合并于此；每角色可读范围不同 |
| T09 submit_analysis | A2 | 结构化 SectorAnalysisCard → 已验证卡引用 | 在落库前强制 gate/claim/source 校验；不合格回结构化错误供下一轮修正 |
| T10 submit_outline | A3 | 已确认板块内大纲 → 版本化大纲引用 | 校验板块范围与对应归因卡，不自动调用写作模型 |
| T11 submit_draft | A3 | 完整文章及章节映射 → 新稿版本引用 | ArticleDraft/质量/来源校验，通过才入库；保留旧有效稿 |
| T12 submit_revision | A3 | base_version、允许范围修订 → 新版本或冲突 | 最多两轮自动修订；不能覆盖人工新版本；不在正文添加审校标记 |
| T13 check_draft_rules | A3/A4 | 当前稿引用 → 程序质量/治理报告 | 不是 LLM 审稿；结果不可由 Agent 改写 |
| T14 submit_review | A4 | draft_version、结构化意见 → 审校报告引用 | 不能修改草稿、不能人工批准；报告只适用于对应版本 |
| T15 inspect_artifacts | A0及专业角色 | 允许的类型/引用 → 摘要或有界结构化内容 | A3/A4 可读关联材料，A2 不读取其他板块私有上下文；不返回密钥/思维链 |
| T16 delegate | 仅 A0 | 注册角色、目标、作用域、产物引用 → 任务引用/结果摘要 | 真正创建框架 SubAgent；不接受 toolsets、任意 system_prompt 或任意模型提升权限 |
| T17 inspect_tasks | 仅 A0 | 本运行任务引用 → 状态/产物/公开失败原因 | 只读；不把中断/超预算算完成 |
| T18 request_selection | 仅 A0 | 候选提案引用 → WAITING_USER_SELECTION | 等待人工或创建任务时已授权的默认策略；不自动假确认 |
| T19 request_finish | 仅 A0 | 完成目标、产物引用 → 最终策略批准或驳回 | 代码核验目标及当前版本；终态至多待人工审阅，不替用户批准 |

业务工具不暴露 save_anything、execute_sql、bash、write_file、approve_draft。保存不是一个宽泛 Tool，而是各自 submit 工具内部的事务。网络重试与数据库写入幂等分别处理；未知外部调用结果先查询，不重复盲写。

幂等键：run/task/attempt/tool_call，另保存输入指纹。同一键不同参数报冲突；已完成返回原产物。过期 attempt 的写入必须被拒绝。工具数量/时间/花费有独立计数，不能把一个批量工具用于绕过限额。

## 5. Skill 怎么从旧版提炼

不是把全部旧 Prompt 改名 SKILL.md。角色系统 YAML 保留身份、目标、工具使用约定、输出契约；Skill 仅承载可复用方法。Schema 和禁止越权规则必须在代码中再校验。

目标位置：config/agent-skills/<name>/SKILL.md；必要参考放 references/。本次先只读文档，不给脚本自动执行权限。通过内置框架 SkillManager/SkillTool 加载，角色只看到允许的 Skill 清单，不能自动读取本机所有 Codex skills。

| ID / Skill | 取自旧功能 | 供谁、何时加载 | 实际内容 | 不迁进去的内容 |
| --- | --- | --- | --- | --- |
| S01 data-gap-handling | 质量/降级报告的解释 | A1 发现字段或来源缺失时 | 哪些缺口可补采、何时终止、如何说明资料不全 | 核心数据门禁、API 凭据 |
| S02 sector-selection | 候选指标含义/编辑选题方法 | A1 出候选提案前 | 涨跌幅与广度背离的解释、避免只追涨、提案说明格式 | 数值权重、3–12 校验、用户确认权限 |
| S03 causal-evidence | attribution*.yaml 中的研究方法和证据等级解释 | A2 开始查证或证据不足时 | 事件/时间/主体一致性、反证、何时结论为无可靠解释 | 证据 ID 白名单、截止时间比较代码 |
| S04 news-verification | 旧正文阅读与引用方法 | A2/A4 使用简讯或原文时 | 简讯/转载/原文区别、出处核对、正文不可得的表达 | 抓取代码、URL 安全策略、来源资格 |
| S05 analysis-writing | editorial/writing/revision YAML 的风格与修订方法 | A3 写作、修订时 | 主体命名、标题/导语/章节、事实与解释分开、禁止系统标记入正文 | Pydantic Schema、版本 CAS、批准状态 |
| S06 independent-review | review YAML 的审校方法 | A4 审校前 | 逐结论核对、来源映射、因果越级、意见需可执行 | 自动批准、修改作者稿件的权限 |

重试提示词（agent_validation_feedback.yaml）继续是系统纠错模板，不归入知识库。structured_output.yaml 是传输/结构化协议模板，不是业务 Skill。新增角色 YAML 拟放 config/prompts/application/orchestration/；旧六份业务 YAML 在迁移测试期间保留，唯一入口切换并清理调用后再移除不再使用的重复内容。

## 6. 是否需要知识库和记忆

| 信息 | 保存/读取方案 | 本轮决定 |
| --- | --- | --- |
| 板块实体与别名 | 现有 sector_entities.yaml + 实体解析服务 | 保留，不用向量检索替代精确 ID |
| 行情、新闻、正文、证据 | 现有 SQLite/PostgreSQL 业务表，由只读工具访问 | 作为事实资料，不必另建一套知识库 |
| 研究/写作方法 | S01–S06 文档及受控参考 | Skill 方法库，不用数据库查向量 |
| 本次任务执行记忆 | 新任务、事件、预算、产物索引；必要的有界上下文快照 | 可恢复执行；不永久共享所有角色的聊天历史 |
| 历史文章 | 原版本表、人工编辑和审核记录 | 用于历史阅读；默认不作为事实或因果证据 |
| 行业政策、研报、公告的长期知识库 | 需要文档来源、授权、版本与检索评测后单独设计 | 本轮不加向量库/RAG，避免引入无维护的数据层 |

## 7. 用户交互和接口怎样迁

| 入口/页面 | 保留 | 变更 |
| --- | --- | --- |
| 新建分析 NewAnalysisPage | 盘中/盘后场景、日期、数据来源、已有业务输入 | 去掉工作流/Agent 开关；唯一创建新根任务 |
| 数据运行 DataRunPage | 板块表、新闻正文、来源质量、候选自选 | 增加来自哪次根任务；确认选择后恢复相同运行，不重新采集 |
| 内容运行 RunDetailPage | 草稿、证据、审核、治理、板块详情 | 新运行阶段条改成任务树；旧记录继续显示旧阶段 |
| 审核工作台 | v1/v2、人工修改、批准、撤销、导出 | 显示根任务、对应板块和本次草稿审校版本；人工编辑造成旧自动审校失效 |
| 运行列表/对比/运营 | 搜索筛选、对比、历史和统计 | 按 execution_engine 投影新旧状态，不把“子任务完成”当作运行完成 |
| 定时任务/CLI | 现有使用场景和调度设置 | 指向新根任务用例，不能保留隐藏旧执行分支 |

执行引擎与数据来源是两件事：删除的是 workflow/agent 双执行模式，不是 fixture/live 的测试/真实数据选择。fixture 将提供真实框架的确定性模拟模型和工具观察，不重新执行旧 pipeline。

API 迁移策略：现有资源查询、选择与人工审核 URL 尽量保留，内部指向适配服务；新增任务树资源拟为 /api/runs/{run_id}/tasks。新建请求显式携带旧 attribution_mode 时返回 422 和迁移提示，不能静默使用旧模式。新运行在响应中明确 execution_engine=multi_agent；旧行保留原值/legacy 标记，仅用于查询和解释。所有改动要列契约测试，不在前端自行猜测完成状态。

历史任务：保留全部原业务表及引用；不把旧运行强行补成新任务树。历史重跑先校验原输入快照是否可复用，创建新的 multi_agent 根任务并记录 retry_of；旧记录本身不改写。若输入不可复用，界面提示需要重新采集，不自动消耗额度。

## 8. 数据、预算与完成判定：旧能力不能丢

1. 预算必须覆盖 token、调用次数、工具次数、截止时间、人民币金额。SharedBudget 已补模型与工具的金额预留/结算、调用次数、幂等身份、框架适配和生产配置根任务组合；P4 完成业务入口切换前仍不得切换生产入口。
2. 新任务绑定 run/task/attempt/role，工具结果和模型调用审计均已关联，旧/新调用通过统一只读投影汇总；未知 usage/价格仍不能显示为确定的 ¥0。
3. 一次根任务至少有明确目标：仅准备数据或完整分析。完成仅准备数据不能设置为报告完成；完整分析需确认候选、合法归因卡、有效稿、当前版本审校及治理结果。
4. 自动审校未通过时应保持已有稿件及可行动意见；不能回退成“从未写作”。人工批准仍单独操作。
5. 任务失败只重试相应范围；生成新 attempt 后旧 attempt 的迟到返回无权修改当前产物。父取消必须取消所属子任务；重启恢复要先取得所有权，不能把其他进程还在运行的任务标为中断。
6. 业务表写入和编排快照/产物索引必须有可恢复的一致性策略。优先共享同库事务；无法原子提交的外部动作使用幂等和显式不确定状态，不能仅写快照就宣称业务产物已保存。

## 9. 迁移顺序和可验收交付

| 阶段 | 对照 ID | 实际交付，不只是写 Agent 类 | 放行条件 |
| --- | --- | --- | --- |
| P1 框架基础 | M11/M21/M24 的框架底座 | 内置源码、补丁和来源清单 | 核心框架测试通过，已完成 |
| P2 调度底座 | M21/M24/M29/M30 | 角色工厂、注册工具白名单、两层任务、取消恢复、完整预算及审计、双库持久化 | 并发/迟到写入/越权/双库测试；已完成并放行 |
| P3a 数据与选题（已放行） | M01–M09，T01–T05，S01/S02 | 已拆出旧采集与评分服务，A1 通过真实框架自主调用并产生待确认候选提案 | 同输入评分、缺失语义、截止时间和人工确认边界已通过双库验收 |
| P3b 研究与证据 | M10–M13，T06–T09，S03/S04 | 用框架替代旧归因循环，保留检索和强制验证 | 可观察的补查/反证；非法引用拒绝；不足可停止；已完成并放行 |
| P3c 写作与审校（已放行） | M14–M19，T10–T14，S05/S06 | A3 编辑写作修订、A4 独立审校；保留领域校验和版本 | 写作→退回→修订→重新审校，人工修改冲突有处理；已通过双库和真实框架轨迹 |
| P4 入口与历史迁移（已放行，2026-09-15） | M20/M22/M23/M25–M30 | UI/API/CLI/定时入口唯一化，旧记录查询与重跑适配、文档和清理 | 全部入口+双库+前端验收（前端 259 passed、浏览器 67 passed/0 failed）+有界 live 验收已完成；文档已收尾 |

每个 P3 子阶段先写接口/文件级实施清单，必须回指 M/T/S 编号。不能用“完成业务工具”概括全部三个子阶段。P2 代码尚未完工，不能跨过预算/任务恢复硬门禁先删旧入口。

### 切换与回退

先在测试入口完成新引擎全链路，再统一更新生产命令入口；不向用户永久保留双模式开关。不在同一次验证中并行调用旧/新真实模型避免重复花费。切换前保存可回滚代码版本和数据库备份，新增表与旧业务表兼容；失败回退为部署版本回退，不让模型自行改引擎。已创建的新任务仍保留查询依据，回退期间不由旧引擎接管未完成新任务。

### 必须补入计划的测试

- 新旧同快照候选评分一致；3–12、自选、默认确认策略均保持。
- 框架父委派子，子真实调用 Tool，资料不足补查，失败有界停止；不是模拟一条提前写死的全链路。
- Skill 只读/作用域/路径穿越/不可信新闻注入，不能获得 shell/批准权限。
- 当前草稿版本的来源、审校、治理和人工操作相互一致；旧主体缺失/复核标记问题不复发。
- token/CNY/工具次数总预算、未知用量、模型重试、并发竞争、取消、恢复、迟到结果。
- SQLite 与专用 PostgreSQL 增量迁移、旧数据仍可读、资源关联不丢失；无测试连接不算通过。
- 网页、CLI、定时、历史重试全部进入新引擎；旧模式参数行为明确，fixture 也用新框架。
- 前端 task/board/draft 链接可互相定位，刷新恢复，历史“未记录”保持真实。

以上八项截至 2026-09-15 均已落地并验证：前两项由 P3a–P3c 的真实框架轨迹验收；Skill 边界与人工权限由白名单守卫测试固化；草稿版本一致性由单元 E 的版本绑定与共享 CAS 覆盖；预算/并发/取消/恢复/迟到写入由 P2 与单元 B 的专项覆盖；增量迁移与"旧数据仍可读"由单元 G 新增的升级测试覆盖，且全部 PostgreSQL 合同测试已在专用 `_test` 库实跑（790 passed、0 skipped）；入口唯一化由单元 G 的 AST 证明覆盖；前端双向定位与"未记录"语义由单元 F 的组件测试与浏览器验收覆盖。

## 10. 当前真正完成到哪里（更新于 2026-09-15）

| 项目 | 当前状态 |
| --- | --- |
| 框架源码内置及基础权限/超时/计费补丁 | 已实现并测试 |
| 任务/产物引用/预算数据契约 | 已实现合法迁移、父取消、worker 租约/续期、过期接管、新 attempt、迟到写入隔离和 A2 并发门禁；业务产物、ArtifactRef 与事件同事务提交已通过 SQLite 与专用 PostgreSQL 合同 |
| 快照 CAS、预算预留/结算、SQLite 恢复读取 | 已实现并测试 |
| PostgreSQL 仓储适配 | 已用本机 PostgreSQL 18 的隔离数据目录和专用 `_test` 数据库完成 28 项标记回归；未触碰现有服务数据 |
| 框架模型/工具预算适配 | 已实现 token、模型/工具次数、deadline、金额预留/结算、Tool 重放保护及新 Provider 的 task/attempt/role/provider/model/终态审计；P4 单元 A 新增框架原生 fixture 与 vendor OpenAI live 组合、live 写前预检，并用 `deepseek-flash` 完成 ¥0.10/60 秒只读 Tool Agent 真实验收 |
| A0–A4 业务角色工厂、完整委派/恢复 | 框架角色工厂、精确白名单、固定 Prompt、受限 delegate、上下文化工具、T16 真实子任务创建/运行及 T15/T17–T19 控制工具已实现；A0→A1、A0→两个 A2 和 A0→A3→A4→A3→A4 的真实框架轨迹均已验收 |
| T01–T19 业务工具目录 | T01–T19 已实现并由预算/attempt/租约边界保护；T01–T14 均有 SQLite 与专用 PostgreSQL 证据，写作、程序治理、独立审校和修订产物不可变且绑定明确版本 |
| S01–S06 业务 Skill | S01–S06 已通过受限 `SkillManager`/`SkillTool` 落地，方法内容不承载权限、数据库身份或人工决定 |
| 运营/系统状态同时统计新旧引擎 | 新增 `orchestration_projection` 把编排快照投影成运营口径，`SQLiteOperationsQuery`/`PostgresOperationsQuery` 按 `run_id` 合并两套来源（新引擎优先，避免续接运行重复计数）；`OperationsRecentRun` 新增 `execution_engine`。未知成本与未知时长保持 `None`，不回落成 0；`WAITING_USER_REVIEW` 计入完成与需关注但不算失败。仅 SQLite 有验证，PostgreSQL 因无 `_test` 库未跑 |
| 旧记录只读语义 | `GET /api/runs/{run_id}/tasks` 对旧运行返回 `recording=not_recorded` 与空任务树，不补造、不把未记录解释成失败；旧草稿多版本、批准记录（actor/时间）与 `retry_of_run_id` 经集成测试确认逐字可读 |
| 人工审核链路的版本绑定与 CAS | A4 审校经 `get_review` 返回其真正消费的 `draft_id`/`draft_version`；批准前校验当前版本，人工改版后旧 PASS 不能放行（409）。人工编辑经 `HumanDraftEditService` 与快照 revision 同一个 CAS：落后方失败且不半落地，无快照的旧运行行为不变 |
| 人工审计不可被 Agent 伪造 | 已核实并加守卫测试：Agent 工具白名单与 A0–A4 角色集合都不含治理动作，`AgentBusinessToolFactory` 会拒绝注入；`A3A4ToolDependencies` 不持有发布审计/治理仓储；批准与撤销路由无请求体，actor 只来自请求头、时间只来自服务器时钟、版本只取当前草稿。导出为批准版本的正文本身，字段集等于草稿模型字段，不含调度/预算/租约信息 |
| 新产物进入旧审核工作台 | 兼容投影经 HTTP 端到端验证：只有编排产物、`article_drafts` 无行的多 Agent 运行可被读取、批准、导出；投影为读时投影，agent 产物逐字段不变；无快照的旧运行仍读 `legacy` |
| 唯一入口/旧 UI 模式移除/历史迁移 | P4 单元 A/B/C 已完成新运行/provider 组合根、人工选择同根新 attempt 恢复，以及 Web/API/定时/重试/CLI 唯一化；单元 D 已完成新旧统一查询、任务树投影与运营统计兼容；单元 E 已完成人工审核/编辑/批准/撤销/导出的接线、版本绑定、共享 CAS 与审计守卫。新建页和数据页已移除 workflow/agent 模式。完整任务树 UI 与前端补发 `base_revision` 已在单元 F 完成；最终清理在单元 G 第 1–3 项完成（见下方各行），第 4–5 项（前端/浏览器最终验收与文档收尾）待完成 |
| 运行详情页的动态任务树 | 多 Agent 运行的详情页以真实任务记录取代固定阶段推断：按 `parent_id` 嵌套展示 A0–A4 角色、状态、板块 scope、尝试次数、选择版本、租约与停止原因码，Tool/模型花费按 `task_id` 归到实际花费方，产物链接直达拥有它的视图。未结算花费显示「费用未知」而不是 ¥0；`recording=not_recorded` 显示「本次运行没有记录任务树；未记录不等于未执行」而不是空树；旧运行继续显示历史阶段条。Vitest 6 项、Playwright 1440/390 两个宽度均已验证 |
| 前端补发 `base_revision` | 草稿读取载荷新增 `revision`（无快照运行返回 `null`），审核工作台保存时把它作为 `base_revision` 回传，共享 CAS 守卫因此从产品界面真正可达。HTTP 级测试证明：基于最新 revision 的编辑落库并推进快照；Agent 先推进后，基于旧 revision 的编辑被快照守卫以 409 拒绝（报错含 `revision`，区别于稿件版本守卫），且人工改写没有半途写入 |
| 审核结论标注它审的是哪一版 | 多 Agent 侧 `/review` 早已返回 `draft_id`/`draft_version`，旧运行侧此前完全不返回，前端也不显示，于是 PASS 看上去像在给"当前草稿"背书。现在两侧读路径都返回被审版本，`ReviewTab` 显示「审核版本：第 N 版」，缺失时显示「未记录」而不默认成第 1 版 |
| 所有新建入口只走新引擎（P4 单元 G 第 1 项） | 用 AST 而非文本搜索证明：旧引擎每个函数的真实调用点唯一且固定在既有老路径（`run_phase1b_pipeline`/`build_live_provider` → `web/services/run_service.py`；`run_revision_agent` → `phase1b_pipeline.py`；`run_agent_loop` → `agent_runtime.py`；`RunCommandService` → `web/dependencies.py`）。默认接线产出 `MultiAgentRunCommands`、`MultiAgentDataRunWritingService`，调度器实际运行的 bridge 持有 `multi_agent_commands`；生产侧 `build_runtime_dependencies` 的每个调用点必须显式传 `enable_multi_agent=True`（默认 `False`），当前两处。反向验证过：改成 `False` 时断言确实失败，非恒真 |
| 双模式残留清理（P4 单元 G 第 2 项） | 前端已无双模式类型，Prompt 均有存活调用方。删除了 `build_runtime_dependencies` 中休眠的第二套 scheduler/coordinator/bridge——它的 bridge 没有 `multi_agent_commands`，即一条无人使用的旧引擎路径，而 `web/app.py:51-52` 读取的是 router bundle 那一套。历史表、导出与领域校验代码保留 |
| 旧库增量升级（P4 单元 G 第 3 项） | 本仓第一个从旧 schema 升级的测试：把真实迁移集按文件名前缀截断出「017 之前」，写入含 `input_json` 的旧行（017 会 DROP 并重建 `phase1b_runs`，是最容易丢数据的一步），再指向完整迁移集初始化。升级后旧行可读、金额与 `input_json` 原样保留、018 才引入的 `retry_of_run_id` 为 `None`（补列不补造历史）；同一份升级后的文件上，旧运行以 `legacy` 提供，新运行以 `multi_agent` 创建并留下 `recording=recorded` 的 `["A0"]` 任务树 |
| 引擎切换引入的两个缺陷已修 | ① 重试历史运行返回 500：多 Agent 引擎只能重试自己的运行，历史行没有可重建快照，`KeyError` 冒到顶层——现返回 409 与迁移提示。② `retryable` 标志误导：`execution_engine` 说的是运行**如何产生**，能否重试取决于**将要重试**的引擎，历史运行因此清除该标志，而不是给出一个点了就 409 的按钮 |
| 业务数据库不可达（硬约束，此前有漏洞） | `create_app()` 会把 `.env` 载入进程环境，其中 `SECTOR_PULSE_DATABASE_URL` 指向业务库 `sectorpulse_runtime`；约 27 个合同测试（11 个文件，多数不带 `postgres` 标记）会读取该变量并写行。新增会话级 autouse 防护：变量未设置时置空，已设置但不以 `_test` 结尾时抛 `BusinessDatabaseRefused` |

**当前状态：迁移完成。** Phase 2 调度基础、P3a–P3c 业务 Agent 阶段及 P4 单元 A–G 均已完成并验证。新建入口已唯一化，新旧引擎已能在同一查询口径下共同统计，人工审核链路已能同时服务新旧运行，运行详情页已展示真实任务树，前端已补发 `base_revision`，README 已把双模式说明改写为单一的父子 Agent 执行引擎。

**唯一入口与清理的证据不是搜索而是 AST：**旧引擎每个函数的真实调用点唯一且固定在既有老路径（见下方表格「所有新建入口只走新引擎」一行）；默认接线产出 `MultiAgentRunCommands` 与 `MultiAgentDataRunWritingService`；调度器实际运行的 bridge 持有 `multi_agent_commands`；生产侧两个 `build_runtime_dependencies` 调用点都显式传 `enable_multi_agent=True`（默认 `False`），反向验证过改为 `False` 时断言确实失败。

**关于 PostgreSQL，此前这里的记述已过时，现更正：** 该文档先前写着单元 E/F 的结论「只对 SQLite 成立」，理由是环境未配置名为 `_test` 的专用库。实际情况是本机已存在 `sectorpulse_test` 与 `sector_pulse_run_comparison_test` 两个专用库，并已在其上完整执行过：全量套件对 `sectorpulse_test` 得 **790 passed, 0 skipped**（对最终代码重跑；0 跳过即意味着全部 PostgreSQL 合同测试确实执行，包括单元 E 的 `test_postgres_release_audit_repository.py`、`test_postgres_review_analytics.py` 与单元 F 的 `test_postgres_draft_edit_repository.py`），比较类用例在同一轮对 `sector_pulse_run_comparison_test` 一并通过。因此单元 E 的 `apply_patch` 拆分/发布审计仓储与单元 F 的草稿 `revision` 字段**已经跑过 PostgreSQL**，该缺口关闭。

**浏览器验收：**本机此前未安装 Playwright 浏览器，单元 F 才第一次真正跑通。该套件当时为 **64 passed / 3 failed**，3 个失败已用 HEAD 版本对照确认与单元 F 无关，并在单元 G 逐一定性为**断言与自身夹具矛盾**后修正：`review-workspace.spec.ts` 曾要求「写作完成」而「编辑未记录」——夹具的 `draft_id` 使这两者不可能同时成立，且 `RunDetailPage.test.tsx:96-106` 覆盖同一场景并断言 index 3 为「已完成」；`data-workbench.spec.ts`（empty）曾要求「可能仍在采集阶段」，而该夹具自身声明运行已结束（`finished_at` 有值、`terminal: true`）。修正后套件为 **67 passed / 0 failed**。

**一处必须如实记录的收窄：**「历史重跑创建带 retry_of 的新根任务」在**数据运行**路径上成立（`retry_data_run` 新建根任务并记录 `retry_of`），但在**历史内容运行**（旧 Phase1B）路径上不成立——该动作返回 409 与迁移提示，而非伪造。原因是旧行没有编排快照，而 `phase1b_runs.input_json` 里没有多 Agent 所需的 `goal`；`create_run` 在 goal 缺失时会写入 `"full sector analysis"`，等于替用户编造他未提出的请求。因此这里选择拒绝：代价是"重试一次旧内容运行"不再可用，需改为新建运行。同一原因使 `retryable` 对这类运行显示为 `false`，不再给出点了就 409 的按钮。
