# Phase 1A 市场与新闻垂直切片实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 在 Phase 0 行业/概念快照之上，建立可追溯的 SQLite 市场快照、新闻文档/事件、候选板块和证据包垂直切片，为后续 Agent 归因与文案生成提供稳定输入。

**Architecture:** 领域层只使用 Pydantic 不可变对象和 Port；SQLite Repository 负责持久化，Provider Adapter 负责把 RSS/公开新闻响应映射为领域对象。Phase 1A 不调用 LLM、不生成正文、不实现 Web；它只完成“行情快照 + 新闻事件去重 + 候选召回 + 证据包”的可审计数据链路。

**Tech Stack:** Python 3.12+, Pydantic v2, SQLite (`sqlite3`), pytest, Ruff, mypy, AKShare Phase 0 Adapter, RSS/HTTP 新闻 Adapter。

## Global Constraints

- 所有时间使用带时区的 UTC `datetime`；新闻和行情晚于 `run_cutoff_at` 的数据不得进入本轮。
- `FAILED`、`EMPTY`、`PARTIAL`、`STALE`、`UNAVAILABLE` 必须保持不同语义，失败不能伪装成无新闻。
- Provider、Repository、新闻抓取和候选评分都通过 Port/Adapter 接入，领域层不得接触 DataFrame、HTTP 响应或 SQLite 行。
- 原始新闻正文只保留本地受控缓存和哈希；结构化元数据、事件簇、引用片段和来源清单可审计。
- 缺少发布时间的新闻只能作为背景，不能支持明确或可能催化归因。
- Phase 1A 不调用 LLM，不实现 Agent runtime，不实现 FastAPI/React，不实现自动发布。
- 每个任务先写失败测试，再实现最小代码；每个任务独立提交。
- 中文注释说明时间边界、证据降级、去重和安全校验等关键逻辑。

---

### Task 1: SQLite Schema 与迁移边界

**Files:**
- Create: `backend/src/sector_pulse/storage/__init__.py`
- Create: `backend/src/sector_pulse/storage/sqlite.py`
- Create: `backend/src/sector_pulse/storage/migrations/001_phase1a.sql`
- Create: `backend/tests/unit/storage/test_sqlite_schema.py`

**Interfaces:** `SQLiteDatabase(path: Path)`, `initialize() -> None`, `transaction()`, `connection()`；建立 `analysis_runs`、`sector_snapshots`、`news_documents`、`news_events`、`news_event_documents`、`sector_candidates`、`evidence_packs` 表及唯一约束。

- [ ] 写失败测试：初始化后表存在、重复 `run_id` 被拒绝、迁移可重复执行。
- [ ] 运行 `pytest backend/tests/unit/storage/test_sqlite_schema.py -v`，确认缺少模块或表。
- [ ] 实现 SQLite 连接、WAL、外键、参数化 SQL 和迁移版本表；禁止拼接用户输入。
- [ ] 重新运行测试，并用 `ruff`/`mypy` 检查。
- [ ] 提交：`feat: add phase 1a sqlite schema`。

### Task 2: 市场快照持久化 Port

**Files:**
- Create: `backend/src/sector_pulse/ports/market_snapshot.py`
- Create: `backend/src/sector_pulse/storage/market_snapshot_repository.py`
- Create: `backend/tests/unit/storage/test_market_snapshot_repository.py`

**Interfaces:** `MarketSnapshotRepository.save(run: AnalysisRun, result: ProviderResult[SectorUniverseSnapshot]) -> None`；`get(run_id: UUID, kind: SectorKind) -> SectorUniverseSnapshot | None`。

- [ ] 写失败测试：保存行业/概念快照后可恢复，字段和 `observed_at`/`collected_at` 保持不变；晚于 cutoff 的快照被拒绝。
- [ ] 运行测试确认 Repository 不存在。
- [ ] 实现领域对象到 SQLite 行的显式映射；不把供应商 DataFrame 写入数据库。
- [ ] 增加失败、空结果和重复保存测试；运行全部非 live 测试。
- [ ] 提交：`feat: persist phase zero market snapshots`。

### Task 3: 新闻文档与事件领域契约

**Files:**
- Create: `backend/src/sector_pulse/domain/news.py`
- Create: `backend/src/sector_pulse/domain/evidence.py`
- Create: `backend/src/sector_pulse/ports/news.py`
- Create: `backend/tests/unit/domain/test_news.py`
- Create: `backend/tests/unit/domain/test_evidence.py`

**Interfaces:** `NewsDocument`（`document_id`, `source_id`, `url`, `title`, `published_at`, `observed_at`, `content_hash`, `source_grade`）；`NewsEvent`（`event_id`, `canonical_title`, `first_published_at`, `document_ids`）；`EvidencePack`（`run_id`, `sector_id`, `facts`, `events`, `counter_evidence`, `quality_status`）。

- [ ] 写失败测试：无时区发布时间被拒绝；晚于 cutoff 的新闻不能构造为本轮证据；缺失发布时间只能生成背景标记。
- [ ] 运行测试确认领域模块缺失。
- [ ] 实现不可变 Pydantic 模型和 `EvidenceLevel`：`EXPLICIT_DRIVER`、`POSSIBLE_CATALYST`、`MARKET_ASSOCIATION`、`NO_RELIABLE_EXPLANATION`。
- [ ] 测试证据等级降级和反证集合的稳定序列化。
- [ ] 提交：`feat: define phase 1a news and evidence contracts`。

### Task 4: 可替换新闻 Provider 与安全抓取

**Files:**
- Create: `backend/src/sector_pulse/infrastructure/news/__init__.py`
- Create: `backend/src/sector_pulse/infrastructure/news/rss_client.py`
- Create: `backend/src/sector_pulse/infrastructure/news/rss_adapter.py`
- Create: `backend/tests/fixtures/news/rss_items.json`
- Create: `backend/tests/unit/infrastructure/test_rss_adapter.py`

**Interfaces:** `NewsPort.fetch_since(cutoff: datetime, source_ids: Sequence[str]) -> ProviderResult[tuple[NewsDocument, ...]]`。

- [ ] 写失败测试：fixture RSS 可映射；发布时间晚于 cutoff 的条目被过滤；非法协议、内网 IP、超大响应和危险重定向被拒绝。
- [ ] 运行测试确认 Adapter 缺失。
- [ ] 实现固定来源配置、连接超时、响应大小上限、URL 解析和内容哈希；不执行新闻正文中的指令。
- [ ] 真实网络只在显式 `--run-live-news` 和本地 consent 文件存在时执行，默认使用 fixture。
- [ ] 提交：`feat: add governed news provider adapter`。

### Task 5: 新闻事件去重与 SQLite Repository

**Files:**
- Create: `backend/src/sector_pulse/application/news_ingestion.py`
- Create: `backend/src/sector_pulse/storage/news_repository.py`
- Create: `backend/tests/unit/application/test_news_ingestion.py`
- Create: `backend/tests/integration/test_news_ingestion_sqlite.py`

**Interfaces:** `ingest_news(provider: NewsPort, repository: NewsRepository, run: AnalysisRun) -> ProviderResult[tuple[NewsEvent, ...]]`。

- [ ] 写失败测试：同一 URL、相同内容哈希和高度相似标题进入同一事件簇；不同发布时间和主题保留为不同事件；事件不得跨 cutoff。
- [ ] 运行测试确认编排模块缺失。
- [ ] 实现规范化标题、URL canonicalization、内容哈希优先、标题相似度作为次级规则；保留合并理由和来源文档列表。
- [ ] 集成 SQLite 持久化、幂等重跑和 `PARTIAL` 状态。
- [ ] 提交：`feat: ingest and deduplicate news events`。

### Task 6: 候选板块召回与证据包构建

**Files:**
- Create: `backend/src/sector_pulse/domain/candidate.py`
- Create: `backend/src/sector_pulse/application/candidate_selection.py`
- Create: `backend/tests/unit/application/test_candidate_selection.py`
- Create: `backend/tests/integration/test_evidence_pack.py`

**Interfaces:** `select_candidates(industry: SectorUniverseSnapshot, concept: SectorUniverseSnapshot, events: Sequence[NewsEvent], limit: int = 12) -> tuple[SectorCandidate, ...]`；`build_evidence_pack(candidate, snapshots, events) -> EvidencePack`。

- [ ] 写失败测试：行业和概念分别标准化后再合并；走势异动、成交活跃、涨跌家数扩散和新闻丰富度进入可解释分数；高度重叠板块去重。
- [ ] 运行测试确认候选模块缺失。
- [ ] 实现 8～12 个候选召回、同主题最多保留两个正文候选、排序依据可追溯；社区热度不可用时标记降级而不是伪造。
- [ ] 构建证据包：行情事实、事件、来源等级、反证、缺失字段和允许的归因等级。
- [ ] 提交：`feat: select sector candidates and evidence packs`。

### Task 7: Phase 1A 端到端探测与验收报告

**Files:**
- Create: `backend/src/sector_pulse/application/phase1a_probe.py`
- Modify: `backend/src/sector_pulse/cli.py`
- Create: `backend/tests/integration/test_phase1a_probe.py`
- Create: `docs/phase1a/latest-market-news-validation.md`

**Interfaces:** `run_phase1a_probe(provider, news_provider, database, requested_at, mode) -> Phase1AReport`；CLI `sector-pulse phase1a-probe`。

- [ ] 写失败集成测试：一次运行保存行情、新闻、事件、候选和证据包；所有对象不晚于 `run_cutoff_at`；失败 Provider 不污染成功结果。
- [ ] 运行测试确认 Phase 1A 编排模块缺失。
- [ ] 实现先复用 Phase 0 快照，再采集新闻、去重事件、召回候选和构建证据包；输出只含摘要和哈希，不含完整正文。
- [ ] 默认 fixture 模式；真实新闻模式要求显式 consent，CLI 输出安全错误码和阶段进度。
- [ ] 运行：`.venv\Scripts\python.exe -m pytest backend/tests -m "not live" --basetemp .test-tmp -q`、Ruff、mypy。
- [ ] 生成并人工检查 Phase 1A 验收摘要；提交：`feat: add phase 1a market news vertical slice`。

## Phase 1A Exit Checklist

- [ ] SQLite 可幂等保存行情快照、新闻文档、事件簇、候选和证据包。
- [ ] 新闻时间、行情 cutoff、Provider 状态和证据等级可追溯。
- [ ] `FAILED` 不会被解释为“没有新闻”；缺失发布时间不能支持因果归因。
- [ ] 8～12 个候选可由明确分数组成；重叠概念有去重理由。
- [ ] 默认 fixture 测试和真实 Provider consent 流程分离。
- [ ] 未调用 LLM、未生成社区文案、未实现 Web 或自动发布。
- [ ] 用户审核 Phase 1A 验收报告后，才开始 Phase 1B 文案归因切片。
