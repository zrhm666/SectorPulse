# 后端全层目录整理设计

日期：2026-09-08。基线：main / 57adbe3。

状态：用户于 2026-09-09 确认本设计；执行计划见 ../plans/2026-09-09-backend-domain-storage-layout.md。

## 目标与约束

补齐此前未整理的 domain，并整理两套数据库实现内部的业务归属。保留分层，不把整个后端改成垂直业务模块，也不为少量文件强行创建目录。

- Python 3.12+；不新增运行依赖。
- 保持 HTTP 路径、方法、响应、错误码、路由标签和 CLI 命令不变。
- 保持业务类、函数签名、算法、SQL、事务边界和数据库表不变。
- 不改迁移 SQL 的位置、编号、内容或执行顺序；不修改用户业务数据库。
- 不调用真实行情、新闻或 LLM，不启动调度或影子测试。
- 当前会话执行，不使用子代理。合并、推送另行授权。
- 内部 Python 导入路径允许变更；同步仓库代码、测试、字符串 patch 和维护脚本。不创建旧路径转发壳；外部自写脚本需按下表调整。

## Domain：明确的文件迁移清单

路径相对于 backend/src/sector_pulse/domain；除位置外保留文件名和内容，仅更新导入。

| 新目录 | 原文件 | 职责 |
| --- | --- | --- |
| market/ | market.py、candidate.py、candidate_selection.py、quality.py、radar.py | 行情快照、候选及行情质量 |
| news/ | news.py、news_retrieval.py、evidence.py | 新闻、检索关联及写作输入证据 |
| writing/ | article.py、attribution.py | 草稿和归因结果 |
| review/ | editing.py、review.py、review_analytics.py、release_audit.py | 编辑、审核、审核统计和发布审计 |
| runs/ | time.py、real_data_run.py、task.py | 分析运行、时间边界与任务状态 |
| evaluation/ | shadow_acceptance.py、prompt_golden.py | 影子验收和提示词样例评估 |
| 顶层保留 | __init__.py、provider.py、llm.py | 包入口和跨业务供应商调用契约 |

例如 sector_pulse.domain.market.SectorKind 改为 sector_pulse.domain.market.market.SectorKind。保留原文件名便于审阅迁移，不在本轮混入命名重构。各包 __init__.py 仅含职责说明，不批量重导出。

quality.py 当前依赖 AnalysisRun，news_retrieval.py 当前依赖行情与供应商类型；仅保留这些真实依赖，不为了目录整齐新增接口或反转现有模型依赖。domain 不得导入 application、storage、web 或 infrastructure。

## Storage：方言内采用对称业务目录

以下规则同时适用于 storage/sqlite 和 storage/postgres。database.py 与 __init__.py 留在各方言根目录。

| 新目录 | 原文件 |
| --- | --- |
| market/ | market_snapshot_repository.py、candidate_selection_repository.py |
| news/ | news_repository.py、news_retrieval_repository.py、news_evidence_repository.py、evidence_repository.py |
| runs/ | real_data_run_repository.py、phase1b_runs_repository.py、task_repository.py |
| writing/ | phase1b_repository.py、agent_invocation_repository.py |
| review/ | draft_edit_repository.py、governance_repository.py、release_audit_repository.py、review_analytics.py |
| evaluation/ | shadow_acceptance_repository.py、prompt_golden_repository.py |
| 顶层保留 | operations_query.py | 单文件运营聚合查询，不单独增层 |

storage 顶层继续保留 database_config.py、database_runtime.py、runtime_bundle.py、__init__.py、migrations/。runtime_bundle.py 继续负责两套实现的装配。

不拆 task_repository.py 内部事务，也不抽取两套方言的共同 SQL。已有跨方言的类型或异常导入随路径更新，避免在本次目录整理中同时重写异常体系。

## Storage 协议分包

storage/ports.py 改为 storage/ports/；协议定义保留签名、继承、装饰器与语义。

| 新文件 | 协议 |
| --- | --- |
| market.py | MarketSnapshotRepositoryPort、CandidateSelectionRepositoryPort |
| news.py | NewsRepositoryPort、EvidenceRepositoryPort、NewsRetrievalRepositoryPort、NewsEvidenceRepositoryPort |
| runs.py | RealDataRunRepositoryPort、Phase1BRunsRepositoryPort |
| tasks.py | TaskRepositoryPort、ScheduleRepositoryPort、RuntimeTaskRepositoryPort |
| writing.py | Phase1BRepositoryPort、AgentInvocationRepositoryPort |
| review.py | DraftEditRepositoryPort、ReleaseAuditRepositoryPort、GovernanceRepositoryPort、ReviewAnalyticsPort |
| evaluation.py | PromptGoldenRepositoryPort、ShadowAcceptanceRepositoryPort |
| operations.py | OperationsQueryPort |

拆分时仅保留各模块真正使用的导入；所有消费者显式导入对应子模块。__init__.py 不充当聚合兼容层。顶层 sector_pulse/ports 为外部数据和 LLM 接口，与 storage/ports 的持久化协议职责不同，不合并。

## Web：只拆混合路由文件

- web/routers/runs_review.py 中 build_runs_review_router 整体移到 routers/runs.py，保留函数名、签名、路由注册顺序、tags 和运行产物读取端点。
- ReviewRouterDependencies 与 build_review_governance_router 整体移到 routers/review.py，保留审核、编辑、审计与导出行为。
- 同步 dependencies.py、app.py 和测试的实际引用；删除旧混合文件。
- 其余 routers、schemas、services、events、providers 保持现有分组，不再创建一文件一目录。

## 保留不动的目录

application 已有业务分包，仅更新导入。infrastructure 已按 llm/news/providers 分组，保持。config、顶层 ports、reporting 文件较少且职责清楚，保持。resources 是包资源，migrations 是有序迁移，保持。__pycache__ 为 Python 缓存，不属于架构整理对象。

## 实施顺序与验证

1. 建立基线并新增 domain 布局断言，使测试先对现有平铺结构失败；迁移 domain 并同步消费者，验证导入与领域单元测试。
2. 新增存储业务分组、方言对称性及协议导入断言；迁移 storage，验证 SQLite 初始化、仓库测试、运行装配和迁移资源发现。
3. 新增路由拆分断言；迁移两个路由工厂，比较迁移前后路由的方法、路径、操作标识与 schema，运行 Web 合约测试。
4. 同步 README 与目录规范，运行后端非 live 测试、ruff、mypy、打包及 CLI/HTTP 冒烟。前端接口不改，但执行前端测试和构建检查集成影响。
5. PostgreSQL 验证仅使用隔离测试数据库。若没有可用隔离环境，记录未验证项并请求必要条件，不将跳过标为通过，不复用用户业务库。

结构测试覆盖所有 domain 新模块；导入检查禁止网络连接。迁移扫描覆盖 __file__、importlib、mock/monkeypatch 字符串、脚本命令和包资源。历史设计与验收文档不批量替换旧路径，另用本轮迁移文档解释历史关系。

验收记录分别报告代码迁移、SQLite、PostgreSQL、HTTP/CLI、前端和打包结果。未通过项不能以目录已显示为由宣称完成。

## 设计自检

- domain 的 21 个非入口 Python 文件均有归属：19 个进入业务分组，共享 provider.py、llm.py 保留顶层。
- 两套方言按同一迁移表执行，数据库入口和 SQL 资源位置不变。
- 所有 20 个存储协议均有目标文件，复合任务协议与其父协议同包。
- 没有新增接口功能、数据库操作或强行创建的小业务目录。
