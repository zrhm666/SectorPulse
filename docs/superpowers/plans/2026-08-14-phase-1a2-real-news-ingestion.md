# Phase 1A.2 Real News Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Phase 1A fixture 链路上接入财联社、东方财富和巨潮资讯真实新闻，完成双通道两阶段召回、可审计板块映射及盘中/盘后真实数据验收。

**Architecture:** 领域层新增不可变的来源、查询计划和事件关联契约；Application 先生成市场预候选，再由三个能力 Port 执行受控检索，最后通过确定性实体映射和质量门禁生成最终候选。Infrastructure 只映射 AKShare/SQLite/YAML，CLI 通过显式依赖注入装配，不把 DataFrame、密钥或供应商异常带入领域层。

**Tech Stack:** Python 3.12+、Pydantic v2、PyYAML 6、SQLite、AKShare、Typer、pytest/pytest-asyncio、Ruff、mypy。

## Global Constraints

- 本阶段默认来源固定为财联社全局快讯、东方财富关键词新闻和巨潮资讯公告，授权状态均为 `RESEARCH_ONLY`。
- 默认运行总时长不超过 5 分钟；财联社 1 次、东方财富最多 24 次、巨潮最多 12 个股票代码、单 Provider 并发上限 4、失败最多重试 2 次。
- 所有时间进入领域层前转换为带时区 UTC；`published_at` 或非空 `source_observed_at` 晚于 `run_cutoff_at` 的数据不得进入本轮；`collected_at` 只用于审计且允许晚于 cutoff。
- `FAILED`、`EMPTY`、`PARTIAL`、`STALE`、`UNAVAILABLE` 保持不同语义；失败不能解释为没有新闻。
- 缺少发布时间的新闻只能作为背景；缺少可核验 URL 的财联社条目只能作为发现信息。
- 确定性实体映射最多允许 `MARKET_ASSOCIATION`；本阶段不得产生 `POSSIBLE_CATALYST` 或 `EXPLICIT_DRIVER`。
- 不调用 LLM，不生成正文，不实现 Web、调度或自动发布。
- 不持久化完整新闻正文、密钥、Cookie、完整请求头或供应商异常栈。
- 关键类、边界转换、状态降级和异常分支添加中文注释。
- 默认测试不访问网络；live 测试必须同时指定 `--run-live` 且存在 `.live-data-consent`。

---

## File Structure

- `config/news_sources.yaml`：固定来源运行参数与授权状态。
- `config/sector_entities.yaml`：板块别名、产业链词、歧义词及规则版本。
- `backend/src/sector_pulse/domain/news.py`：扩展新闻文档的媒体、摘要、来源侧时间和引用 URL 契约。
- `backend/src/sector_pulse/domain/news_retrieval.py`：来源定义、查询计划、映射关联和运行指标。
- `backend/src/sector_pulse/ports/news_sources.py`：全局快讯、关键词新闻、公告和成分股能力 Port。
- `backend/src/sector_pulse/config/news_config.py`：安全加载 YAML 并拒绝未注册 Provider 类型。
- `backend/src/sector_pulse/infrastructure/news/akshare_client.py`：隔离同步 AKShare DataFrame API。
- `backend/src/sector_pulse/infrastructure/news/akshare_adapters.py`：三个真实新闻 Adapter 与字段映射。
- `backend/src/sector_pulse/infrastructure/providers/akshare/constituents.py`：候选板块成分股 Adapter。
- `backend/src/sector_pulse/application/news_retrieval.py`：两阶段查询规划、限并发执行和状态汇总。
- `backend/src/sector_pulse/application/entity_resolution.py`：确定性板块实体映射。
- `backend/src/sector_pulse/application/news_quality.py`：cutoff、引用资格和来源降级门禁。
- `backend/src/sector_pulse/application/phase1a2_probe.py`：Phase 1A.2 编排。
- `backend/src/sector_pulse/storage/migrations/002_real_news.sql`：来源执行、查询、板块事件关联和新闻字段迁移。
- `backend/src/sector_pulse/storage/news_retrieval_repository.py`：Phase 1A.2 审计记录 Repository。
- `backend/src/sector_pulse/reporting/phase1a2_report.py`：确定性 JSON/Markdown 验收报告。
- `backend/src/sector_pulse/cli.py`：新增 `phase1a2-news-probe` 命令。

---

### Task 1: 领域契约、配置模型和安全 YAML 加载

**Files:**
- Modify: `pyproject.toml`
- Modify: `backend/src/sector_pulse/domain/news.py`
- Modify: `backend/src/sector_pulse/domain/provider.py`
- Create: `backend/src/sector_pulse/domain/news_retrieval.py`
- Create: `backend/src/sector_pulse/ports/news_sources.py`
- Create: `backend/src/sector_pulse/config/__init__.py`
- Create: `backend/src/sector_pulse/config/news_config.py`
- Create: `config/news_sources.yaml`
- Create: `config/sector_entities.yaml`
- Test: `backend/tests/unit/config/test_news_config.py`
- Test: `backend/tests/unit/domain/test_news_retrieval.py`
- Modify: `backend/tests/unit/domain/test_provider.py`

**Interfaces:**
- Consumes: `SectorKind`, `ProviderManifest`, `ProviderResult`, `NewsDocument`。
- Produces: `NewsSourceDefinition`、`NewsQuery`、`NewsQueryPlan`、`SectorEventLink`、`SourceRunMetric`、四个能力 Port 和 `load_news_config()`。

- [ ] **Step 1: 写配置与领域失败测试**

```python
from pathlib import Path

import pytest

from sector_pulse.config.news_config import load_news_config
from sector_pulse.domain.news_retrieval import MappingConfidence, QueryType


def test_load_news_config_rejects_unregistered_provider(tmp_path: Path) -> None:
    path = tmp_path / "news.yaml"
    path.write_text(
        "sources:\n  - source_id: bad\n    provider_type: arbitrary.import.Path\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unregistered provider_type"):
        load_news_config(path, frozenset({"akshare_cls"}))


def test_query_and_mapping_enums_are_explicit() -> None:
    assert QueryType.GLOBAL.value == "GLOBAL"
    assert MappingConfidence.HIGH.value == "HIGH"
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/config/test_news_config.py backend/tests/unit/domain/test_news_retrieval.py -q`

Expected: FAIL，错误包含 `ModuleNotFoundError: No module named 'sector_pulse.config'`。

- [ ] **Step 3: 增加 PyYAML、领域模型和 Ports**

在 `pyproject.toml` 的 dependencies 中增加 `"PyYAML>=6,<7"`。在 `news.py` 将现有 `url` 重命名为 `canonical_locator: str`，并新增 `citation_url: str | None = None`、`publisher: str | None = None`、`summary: str | None = None`、`source_observed_at: datetime | None = None`、`collected_at: datetime`；`summary` 使用 `Field(default=None, max_length=500)`。迁移期间所有构造点一次性改名，不保留两个含义相同的字段。

`NewsDocument.use_at()` 固定实现为：

```python
def use_at(self, cutoff: datetime) -> NewsUse:
    if cutoff.tzinfo is None or cutoff.utcoffset() != timedelta(0):
        raise ValueError("cutoff must use UTC")
    if self.published_at is not None and self.published_at > cutoff:
        return NewsUse.EXCLUDED
    if self.source_observed_at is not None and self.source_observed_at > cutoff:
        return NewsUse.EXCLUDED
    if self.published_at is None:
        return NewsUse.BACKGROUND
    return NewsUse.EVIDENCE
```

同时修正 `ProviderResult` 的 `PARTIAL` 不变量，使部分有效数据和结构化错误可以共存：

```python
if self.status is DataStatus.PARTIAL and (self.data is None or self.error is None):
    raise ValueError("partial result requires both data and error")
if self.status is DataStatus.SUCCESS and (self.data is None or self.error is not None):
    raise ValueError("successful result requires data without error")
if self.status is DataStatus.FAILED and (self.data is not None or self.error is None):
    raise ValueError("failed result invariant")
if self.status not in {DataStatus.PARTIAL, DataStatus.FAILED} and self.error is not None:
    raise ValueError("error only allowed for partial or failed results")
```

在 `test_provider.py` 增加 `PARTIAL + data + error` 合法、`PARTIAL` 缺少任一字段非法的测试。

在 `news_retrieval.py` 定义以下不可变模型：

```python
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.news import SourceGrade
from sector_pulse.domain.provider import AuthorizationStatus, DataStatus


class QueryType(StrEnum):
    GLOBAL = "GLOBAL"
    KEYWORD = "KEYWORD"
    DISCLOSURE = "DISCLOSURE"


class MappingConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class NewsSourceDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_id: str
    provider_type: str
    enabled: bool = True
    authorization_status: AuthorizationStatus
    default_source_grade: SourceGrade
    timeout_seconds: float = Field(gt=0, le=30)
    max_retries: int = Field(ge=0, le=2)
    rate_limit_per_second: float = Field(gt=0, le=10)
    max_results_per_query: int = Field(gt=0, le=200)


class NewsQuery(BaseModel):
    model_config = ConfigDict(frozen=True)
    query_id: str
    query_type: QueryType
    source_id: str
    value: str
    sector_ids: tuple[str, ...] = ()
    priority: int = Field(ge=1, le=100)
    start_at: datetime
    cutoff_at: datetime


class NewsQueryPlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule_version: str
    queries: tuple[NewsQuery, ...]
    keyword_budget: int = 24
    disclosure_code_budget: int = 12
    concurrency_per_provider: int = 4


class SectorEntityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str
    aliases: dict[str, tuple[str, ...]]
    industry_terms: dict[str, tuple[str, ...]]
    ambiguous_terms: tuple[str, ...]


class SectorEventLink(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    event_id: str
    sector_id: str
    sector_kind: SectorKind
    relation_type: str
    matched_entities: tuple[str, ...]
    mapping_confidence: MappingConfidence
    mapping_reason: str
    rule_version: str


class SourceRunMetric(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    source_id: str
    started_at: datetime
    completed_at: datetime
    call_count: int
    retry_count: int
    status: DataStatus
    duration_ms: int
    error_code: str | None = None
```

为 `NewsQuery.start_at/cutoff_at`、`SourceRunMetric.started_at/completed_at` 和新闻领域时间字段增加 UTC validator；`cutoff_at < start_at`、`completed_at < started_at` 必须拒绝。

在 `ports/news_sources.py` 定义四个 Protocol：

```python
from datetime import datetime
from typing import Protocol

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.news import NewsDocument
from sector_pulse.domain.provider import ProviderManifest, ProviderResult


class GlobalNewsDiscoveryPort(Protocol):
    @property
    def manifest(self) -> ProviderManifest: ...
    async def fetch_global(self, cutoff: datetime) -> ProviderResult[tuple[NewsDocument, ...]]: ...


class KeywordNewsSearchPort(Protocol):
    @property
    def manifest(self) -> ProviderManifest: ...
    async def search(
        self, query: str, start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]: ...


class DisclosureSearchPort(Protocol):
    @property
    def manifest(self) -> ProviderManifest: ...
    async def search_disclosures(
        self, stock_codes: tuple[str, ...], start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]: ...


class SectorConstituentPort(Protocol):
    async def fetch_constituents(
        self, sector_name: str, kind: SectorKind
    ) -> ProviderResult[tuple[tuple[str, str], ...]]: ...
```

- [ ] **Step 4: 实现安全配置加载和默认配置**

`load_news_config()` 必须使用 `yaml.safe_load`，验证根节点为 mapping，并拒绝未注册 Provider：

```python
from pathlib import Path
from typing import Any

import yaml

from sector_pulse.domain.news_retrieval import NewsSourceDefinition, SectorEntityConfig


def load_news_config(
    path: Path, registered_provider_types: frozenset[str]
) -> tuple[NewsSourceDefinition, ...]:
    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ValueError("news source config must contain a sources list")
    sources = tuple(NewsSourceDefinition.model_validate(item) for item in payload["sources"])
    unknown = {item.provider_type for item in sources} - registered_provider_types
    if unknown:
        raise ValueError(f"unregistered provider_type: {sorted(unknown)}")
    return sources


def load_entity_config(path: Path) -> SectorEntityConfig:
    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("sector entity config must be a mapping")
    return SectorEntityConfig.model_validate(payload)
```

`config/news_sources.yaml` 使用以下完整初始内容：

```yaml
sources:
  - source_id: cls
    provider_type: akshare_cls
    enabled: true
    authorization_status: RESEARCH_ONLY
    default_source_grade: DISCOVERY_ONLY
    timeout_seconds: 10
    max_retries: 2
    rate_limit_per_second: 2
    max_results_per_query: 20
  - source_id: eastmoney
    provider_type: akshare_eastmoney_news
    enabled: true
    authorization_status: RESEARCH_ONLY
    default_source_grade: DISCOVERY_ONLY
    timeout_seconds: 10
    max_retries: 2
    rate_limit_per_second: 2
    max_results_per_query: 100
  - source_id: cninfo
    provider_type: akshare_cninfo
    enabled: true
    authorization_status: RESEARCH_ONLY
    default_source_grade: PRIMARY
    timeout_seconds: 10
    max_retries: 2
    rate_limit_per_second: 2
    max_results_per_query: 200
```

`config/sector_entities.yaml` 使用以下完整初始内容，不加入未经审核的业务词：

```yaml
version: "2026-08-14.1"
aliases: {}
industry_terms: {}
ambiguous_terms: []
```

- [ ] **Step 5: 运行目标测试和静态检查**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/config/test_news_config.py backend/tests/unit/domain/test_news_retrieval.py backend/tests/unit/domain/test_news.py -q`

Expected: PASS。

Run: `.\.venv\Scripts\ruff.exe check backend/src/sector_pulse/domain backend/src/sector_pulse/config backend/src/sector_pulse/ports backend/tests/unit/config backend/tests/unit/domain`

Expected: `All checks passed!`

- [ ] **Step 6: 提交**

```powershell
git add pyproject.toml config backend/src/sector_pulse/domain/news.py backend/src/sector_pulse/domain/provider.py backend/src/sector_pulse/domain/news_retrieval.py backend/src/sector_pulse/ports/news_sources.py backend/src/sector_pulse/config backend/tests/unit/config backend/tests/unit/domain/test_news_retrieval.py backend/tests/unit/domain/test_provider.py
git commit -m "feat: define real news retrieval contracts"
```

---

### Task 2: SQLite `002` 迁移和审计 Repository

**Files:**
- Modify: `backend/src/sector_pulse/storage/sqlite.py`
- Modify: `backend/src/sector_pulse/storage/news_repository.py`
- Create: `backend/src/sector_pulse/storage/migrations/002_real_news.sql`
- Create: `backend/src/sector_pulse/storage/news_retrieval_repository.py`
- Test: `backend/tests/unit/storage/test_real_news_schema.py`
- Test: `backend/tests/integration/test_news_retrieval_repository.py`

**Interfaces:**
- Consumes: `NewsDocument`、`NewsQuery`、`SectorEventLink`、`SourceRunMetric`。
- Produces: 可幂等保存并查询来源运行、查询计划和板块事件关联的 `SQLiteNewsRetrievalRepository`。

- [ ] **Step 1: 写迁移与 Repository 失败测试**

```python
def test_initialize_applies_real_news_migration(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "sector-pulse.db")
    database.initialize()
    with database.connection() as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"news_source_runs", "news_queries", "sector_event_links"} <= names
```

集成测试构造一个 `SourceRunMetric`、一个 `NewsQuery` 和一个 `SectorEventLink`，调用 `save_audit()` 两次后断言三张表均只有一行。

- [ ] **Step 2: 运行测试并确认缺少 `002` 表而失败**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_real_news_schema.py backend/tests/integration/test_news_retrieval_repository.py -q`

Expected: FAIL，错误包含 `no such table: news_source_runs` 或缺少 Repository。

- [ ] **Step 3: 编写 `002_real_news.sql`**

迁移必须创建：

```sql
ALTER TABLE news_documents ADD COLUMN citation_url TEXT;
ALTER TABLE news_documents ADD COLUMN publisher TEXT;
ALTER TABLE news_documents ADD COLUMN summary TEXT;
ALTER TABLE news_documents ADD COLUMN source_observed_at TEXT;
ALTER TABLE news_documents ADD COLUMN use_grade TEXT NOT NULL DEFAULT 'BACKGROUND';
ALTER TABLE news_documents ADD COLUMN quality_flags_json TEXT NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS news_source_runs (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    call_count INTEGER NOT NULL,
    retry_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    error_code TEXT,
    PRIMARY KEY (run_id, source_id)
);

CREATE TABLE IF NOT EXISTS news_queries (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    query_id TEXT NOT NULL,
    query_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    sector_ids_json TEXT NOT NULL,
    priority INTEGER NOT NULL,
    start_at TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    status TEXT NOT NULL,
    result_count INTEGER NOT NULL,
    error_code TEXT,
    PRIMARY KEY (run_id, query_id)
);

CREATE TABLE IF NOT EXISTS sector_event_links (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES news_events(event_id) ON DELETE CASCADE,
    sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    matched_entities_json TEXT NOT NULL,
    mapping_confidence TEXT NOT NULL,
    mapping_reason TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    PRIMARY KEY (run_id, event_id, sector_id, sector_kind)
);
```

- [ ] **Step 4: 将迁移器改为按文件顺序执行所有迁移**

把 `initialize()` 改为遍历 `migrations/[0-9][0-9][0-9]_*.sql`，从文件名前三位取得版本；每个未应用文件执行后写入 `schema_migrations`。不要在遇到已应用版本时提前 `return`，否则后续迁移永远不会执行。

- [ ] **Step 5: 实现 Repository 显式映射**

`SQLiteNewsRetrievalRepository.save_audit()` 签名固定为：

```python
def save_audit(
    self,
    run_id: UUID,
    metrics: Sequence[SourceRunMetric],
    query_results: Sequence[tuple[NewsQuery, DataStatus, int, str | None]],
    links: Sequence[SectorEventLink],
) -> None:
```

使用一个事务和 `ON CONFLICT ... DO UPDATE`。查询值仅保存 `sha256(query.value)`，不保存原始搜索词；板块 ID 和命中实体可以保存。同步修改 `SQLiteNewsRepository`：把 `canonical_locator` 写入现有 `canonical_url` 列，把 `collected_at` 写入现有 `observed_at` 列，并新增写入 `citation_url`、`publisher`、`summary`、`source_observed_at`、`use_grade` 和质量标记。现有列名只作为 SQLite 兼容细节，不再向领域层暴露错误语义。

- [ ] **Step 6: 运行测试并提交**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_real_news_schema.py backend/tests/integration/test_news_retrieval_repository.py backend/tests/integration/test_news_ingestion_sqlite.py -q`

Expected: PASS。

```powershell
git add backend/src/sector_pulse/storage backend/tests/unit/storage/test_real_news_schema.py backend/tests/integration/test_news_retrieval_repository.py
git commit -m "feat: persist real news retrieval audit"
```

---

### Task 3: 财联社、东方财富和巨潮 AKShare Adapters

**Files:**
- Create: `backend/src/sector_pulse/infrastructure/news/akshare_client.py`
- Create: `backend/src/sector_pulse/infrastructure/news/akshare_adapters.py`
- Create: `backend/tests/fixtures/news/cls_rows.json`
- Create: `backend/tests/fixtures/news/eastmoney_rows.json`
- Create: `backend/tests/fixtures/news/cninfo_rows.json`
- Test: `backend/tests/unit/infrastructure/test_akshare_news_adapters.py`

**Interfaces:**
- Consumes: Task 1 的三个新闻 Port 和 `NewsDocument`。
- Produces: `AkShareClsAdapter`、`AkShareEastmoneyNewsAdapter`、`AkShareCninfoAdapter`。

- [ ] **Step 1: 写三个 Adapter 的字段映射失败测试**

测试必须覆盖：

```python
def test_cls_document_is_discovery_only_and_has_no_article_url() -> None:
    result = AkShareClsAdapter(FixtureNewsClient()).map_rows(
        load_rows("cls_rows.json"), cutoff=utc(2026, 8, 14, 3), collected_at=utc(2026, 8, 14, 4)
    )
    document = result.data[0]
    assert document.canonical_locator.startswith("urn:sector-pulse:akshare-cls:")
    assert document.citation_url is None
    assert document.source_grade is SourceGrade.DISCOVERY_ONLY


def test_eastmoney_maps_publisher_summary_time_and_url() -> None:
    document = map_eastmoney_rows(load_rows("eastmoney_rows.json"), CUTOFF, COLLECTED)[0]
    assert document.publisher == "证券时报"
    assert document.citation_url == "https://finance.eastmoney.com/a/example.html"
    assert document.published_at is not None


def test_cninfo_is_primary_and_filters_after_cutoff() -> None:
    documents = map_cninfo_rows(load_rows("cninfo_rows.json"), CUTOFF, COLLECTED)
    assert len(documents) == 1
    assert documents[0].source_grade is SourceGrade.PRIMARY
```

- [ ] **Step 2: 运行测试并确认 Adapter 不存在**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure/test_akshare_news_adapters.py -q`

Expected: FAIL with import error。

- [ ] **Step 3: 实现同步 DataFrame 客户端隔离**

`PandasAkShareNewsClient` 提供三个 async 方法，并在内部使用 `asyncio.to_thread`：

```python
async def fetch_cls(self) -> RawNewsBatch:
    return await self._call(ak.stock_info_global_cls, symbol="全部")

async def search_eastmoney(self, query: str) -> RawNewsBatch:
    return await self._call(ak.stock_news_em, symbol=query)

async def search_cninfo(
    self, stock_code: str, start_date: str, end_date: str
) -> RawNewsBatch:
    return await self._call(
        ak.stock_zh_a_disclosure_report_cninfo,
        symbol=stock_code,
        market="沪深京",
        category="",
        start_date=start_date,
        end_date=end_date,
    )
```

`RawNewsBatch` 保存 rows、collected_at、AKShare 版本和原始行 SHA256；不把本地采集时间伪装成来源侧观测时间。

- [ ] **Step 4: 实现三个 Adapter 和统一时间转换**

增加 `_shanghai_to_utc(date_text, time_text=None)`，使用 `ZoneInfo("Asia/Shanghai")` 解析后转换 UTC。逐行映射失败时跳过该行并使结果成为 `PARTIAL`；全部行失败时返回 `FAILED`，错误码分别为 `CLS_MAPPING_FAILED`、`EASTMONEY_NEWS_MAPPING_FAILED`、`CNINFO_MAPPING_FAILED`。

Adapter manifests 固定：

- `akshare-cls-news` / `news.global.discovery`；
- `akshare-eastmoney-news` / `news.keyword.search`；
- `akshare-cninfo-disclosure` / `news.disclosure.search`。

每个 Adapter 将批次完成时间写入 `collected_at`；只有来源明确给出更新时间时才写 `source_observed_at`。映射后调用 `NewsDocument.use_at(cutoff)`，排除来源发布时间或来源观测时间晚于 cutoff 的数据；采集时间晚于 cutoff 是正常审计事实。无剩余数据返回 `EMPTY`，不是 `FAILED`。

- [ ] **Step 5: 运行测试和提交**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure/test_akshare_news_adapters.py backend/tests/unit/domain/test_news.py -q`

Expected: PASS。

```powershell
git add backend/src/sector_pulse/infrastructure/news/akshare_client.py backend/src/sector_pulse/infrastructure/news/akshare_adapters.py backend/tests/fixtures/news backend/tests/unit/infrastructure/test_akshare_news_adapters.py
git commit -m "feat: add akshare real news providers"
```

---

### Task 4: 市场预候选、成分股 Adapter 和受控查询计划

**Files:**
- Modify: `backend/src/sector_pulse/application/candidate_selection.py`
- Create: `backend/src/sector_pulse/infrastructure/providers/akshare/constituents.py`
- Create: `backend/src/sector_pulse/application/news_retrieval.py`
- Test: `backend/tests/unit/application/test_news_retrieval_plan.py`
- Test: `backend/tests/unit/infrastructure/test_akshare_constituents.py`

**Interfaces:**
- Consumes: `SectorUniverseSnapshot`、`SectorCandidate`、`NewsQueryPlan`、`SectorConstituentPort`。
- Produces: `select_market_precandidates(..., limit=30)`、`build_news_query_plan(...)`、`AkShareSectorConstituentAdapter`。

- [ ] **Step 1: 写预算和确定性失败测试**

```python
def test_plan_obeys_keyword_and_disclosure_budgets() -> None:
    plan = build_news_query_plan(
        candidates=make_candidates(30),
        entity_config=make_entity_config(),
        constituents=make_constituents(),
        start_at=START,
        cutoff=CUTOFF,
        keyword_budget=24,
        disclosure_code_budget=12,
    )
    assert sum(query.query_type is QueryType.GLOBAL for query in plan.queries) == 1
    assert sum(query.query_type is QueryType.KEYWORD for query in plan.queries) <= 24
    disclosure_codes = {
        query.value for query in plan.queries if query.query_type is QueryType.DISCLOSURE
    }
    assert len(disclosure_codes) <= 12
    assert plan == build_news_query_plan(
        make_candidates(30), make_entity_config(), make_constituents(), START, CUTOFF, 24, 12
    )
```

另写测试证明 `select_market_precandidates()` 在新闻列表变化时结果不变。

- [ ] **Step 2: 运行测试并确认函数缺失**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_news_retrieval_plan.py backend/tests/unit/infrastructure/test_akshare_constituents.py -q`

Expected: FAIL with import errors。

- [ ] **Step 3: 拆分预候选和最终候选函数**

将现有市场 45%/成交 25%/扩散 20% 的计算抽成 `_market_score()`。新增：

```python
def select_market_precandidates(
    industry: SectorUniverseSnapshot,
    concept: SectorUniverseSnapshot,
    limit: int = 30,
) -> tuple[SectorCandidate, ...]:
    return _rank_candidates(industry, concept, event_sector_ids=frozenset(), limit=limit)
```

现有 `select_candidates()` 继续作为最终排序入口，新闻丰富度只从去重事件关联集合计算。

- [ ] **Step 4: 实现候选成分股 Adapter**

`AkShareSectorConstituentAdapter.fetch_constituents()` 根据 `SectorKind` 选择 `stock_board_industry_cons_em` 或 `stock_board_concept_cons_em`，只返回规范化的 `(股票代码, 股票名称)` tuple。失败返回 `AKSHARE_CONSTITUENTS_FAILED`，不得伪装为空。

- [ ] **Step 5: 实现查询计划排序规则**

查询顺序固定为：全局查询、候选规范名、候选审核别名、候选 leader、其余核心成分股。相同优先级按 `sector_id` 和查询值排序；使用 `(query_type, source_id, normalized_value)` 去重。`query_id` 是上述字段和 cutoff 的 SHA256 前 24 位。

- [ ] **Step 6: 实现限并发执行器并测试重试语义**

在 `news_retrieval.py` 增加：

```python
async def execute_news_query_plan(
    plan: NewsQueryPlan,
    global_provider: GlobalNewsDiscoveryPort,
    keyword_provider: KeywordNewsSearchPort,
    disclosure_provider: DisclosureSearchPort,
    max_retries: int = 2,
) -> tuple[QueryExecutionResult, ...]:
```

`QueryExecutionResult` 是不可变模型，包含 query、Provider 状态、documents、attempts、duration_ms 和 error_code。每个 Provider 使用独立 `asyncio.Semaphore(plan.concurrency_per_provider)`；每次重试前使用可注入的 backoff 函数，默认等待 `0.5 * attempt` 秒；只重试 `ProviderError.retriable=True` 的 `FAILED`。结果顺序必须与 `plan.queries` 一致，单个查询失败不得取消其他查询。

在 `test_news_retrieval_plan.py` 使用记录当前并发数的 fake Provider，断言峰值不超过 4；另用第一次返回可重试失败、第二次成功的 fake，断言 `attempts == 2` 和最终状态为 `SUCCESS`。

- [ ] **Step 7: 运行测试和提交**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_candidate_selection.py backend/tests/unit/application/test_news_retrieval_plan.py backend/tests/unit/infrastructure/test_akshare_constituents.py -q`

Expected: PASS。

```powershell
git add backend/src/sector_pulse/application/candidate_selection.py backend/src/sector_pulse/application/news_retrieval.py backend/src/sector_pulse/infrastructure/providers/akshare/constituents.py backend/tests/unit/application backend/tests/unit/infrastructure/test_akshare_constituents.py
git commit -m "feat: plan bounded real news retrieval"
```

---

### Task 5: 实体映射、质量门禁和证据等级修正

**Files:**
- Create: `backend/src/sector_pulse/application/entity_resolution.py`
- Create: `backend/src/sector_pulse/application/news_quality.py`
- Modify: `backend/src/sector_pulse/application/candidate_selection.py`
- Test: `backend/tests/unit/application/test_entity_resolution.py`
- Test: `backend/tests/unit/application/test_news_quality.py`
- Modify: `backend/tests/unit/application/test_candidate_selection.py`

**Interfaces:**
- Consumes: `NewsEvent`、`NewsDocument`、板块配置、成分股关系和 Provider 状态。
- Produces: `resolve_sector_links()`、`evaluate_news_quality()` 和不越级的 `EvidencePack`。

- [ ] **Step 1: 写映射拒绝和证据上限失败测试**

```python
def test_stock_code_maps_with_high_confidence() -> None:
    links = resolve_sector_links(
        run_id=RUN_ID,
        events=(event("某公司 600001 发布公告"),),
        sectors=SECTORS,
        memberships={"600001": ("industry-1", "concept-2")},
        entity_config=ENTITY_CONFIG,
    )
    assert {link.mapping_confidence for link in links} == {MappingConfidence.HIGH}


def test_ambiguous_term_alone_does_not_map() -> None:
    links = resolve_sector_links(
        RUN_ID, (event("AI 今日活跃"),), SECTORS, {}, ENTITY_CONFIG
    )
    assert links == ()


def test_related_news_never_sets_possible_catalyst_in_phase1a2() -> None:
    pack = build_evidence_pack(CANDIDATE, SNAPSHOTS, (RELATED_EVENT,), RUN_ID)
    assert pack.max_level is EvidenceLevel.MARKET_ASSOCIATION
```

- [ ] **Step 2: 运行测试并确认当前实现错误升级等级**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_entity_resolution.py backend/tests/unit/application/test_news_quality.py backend/tests/unit/application/test_candidate_selection.py -q`

Expected: FAIL；现有候选测试应显示实际值为 `POSSIBLE_CATALYST`。

- [ ] **Step 3: 实现确定性解析器**

`resolve_sector_links()` 先拼接事件标题和关联文档的短摘要，再依次检查股票代码/唯一公司名、规范板块名、审核别名、产业链组合词。歧义词配置中的词必须与至少一个非歧义上下文词共同命中。对相同 `(event, sector)` 只保留最高置信结果，并把所有命中实体合并排序。

- [ ] **Step 4: 实现新闻质量报告**

定义不可变的 `NewsQualityReport`，包含 `status`、`document_count`、`event_count`、`citation_eligible_count`、`background_only_count`、`excluded_after_cutoff_count`、`source_statuses` 和 `blocking_reasons`。规则固定：

- 任一 cutoff 穿越进入结果即 `BLOCKED`；
- 东方财富与巨潮同时 `FAILED/UNAVAILABLE` 即 `BLOCKED`；
- 单个非核心来源失败为 `DEGRADED`；
- 其余为 `NORMAL`。

- [ ] **Step 5: 修正 EvidencePack 上限**

将 `build_evidence_pack()` 的有关联事件分支从 `POSSIBLE_CATALYST` 改为 `MARKET_ASSOCIATION`，并在中文注释中说明因果等级由 Phase 1B 决定。

- [ ] **Step 6: 运行测试和提交**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_entity_resolution.py backend/tests/unit/application/test_news_quality.py backend/tests/unit/application/test_candidate_selection.py -q`

Expected: PASS。

```powershell
git add backend/src/sector_pulse/application/entity_resolution.py backend/src/sector_pulse/application/news_quality.py backend/src/sector_pulse/application/candidate_selection.py backend/tests/unit/application
git commit -m "feat: map news events without causal overreach"
```

---

### Task 6: Phase 1A.2 编排、报告和 CLI

**Files:**
- Create: `backend/src/sector_pulse/application/phase1a2_probe.py`
- Create: `backend/src/sector_pulse/reporting/phase1a2_report.py`
- Modify: `backend/src/sector_pulse/cli.py`
- Test: `backend/tests/integration/test_phase1a2_probe.py`
- Test: `backend/tests/unit/reporting/test_phase1a2_report.py`

**Interfaces:**
- Consumes: 前五个任务的 Providers、Planner、Resolver、QualityGate 和 Repositories。
- Produces: `run_phase1a2_probe()`、`Phase1A2Report`、`render_phase1a2_markdown()` 和 CLI `phase1a2-news-probe`。

- [ ] **Step 1: 写 fixture 端到端失败测试**

测试注入 fixture market/news/constituent Providers，断言：

```python
report = await run_phase1a2_probe(dependencies=deps, request=request)
assert report.market_precandidate_count == 20
assert report.final_candidate_count <= 12
assert report.cutoff_violation_count == 0
assert report.source_metrics["cls"].call_count == 1
assert report.source_metrics["eastmoney"].call_count <= 24
assert report.source_metrics["cninfo"].call_count <= 12
assert report.attribution_levels <= {EvidenceLevel.MARKET_ASSOCIATION, EvidenceLevel.NO_RELIABLE_EXPLANATION}
```

报告测试断言 Markdown 包含 cutoff、每个来源状态、调用数、延迟、文档数、去重率、映射率和降级原因，且不包含 fixture secret 和完整正文。

- [ ] **Step 2: 运行测试并确认编排模块缺失**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase1a2_probe.py backend/tests/unit/reporting/test_phase1a2_report.py -q`

Expected: FAIL with import error。

- [ ] **Step 3: 实现依赖容器和请求/报告模型**

`Phase1A2Dependencies` 显式持有 market、constituent、global、keyword、disclosure Providers 和三个 Repositories；`Phase1A2Request` 包含 `requested_at`、`run_kind`、配置路径和预算覆盖。禁止在编排函数内部构造具体 Provider。

`Phase1A2Report` 至少包含：run、run_kind、elapsed_ms、市场质量、预候选/最终候选数量、来源指标、文档/事件/关联数量、去重率、映射率、cutoff 违规数、降级原因、是否可进入 Phase 1B。

- [ ] **Step 4: 实现编排顺序和失败短路**

顺序固定为：行情采集与 cutoff 锁定 → 市场预候选 → 候选成分股 → 查询计划 → 三类新闻执行 → 去重 → 实体映射 → 新闻质量 → 最终候选 → EvidencePack → 审计持久化 → 报告。行情 `BLOCKED` 时不得调用新闻 Provider；新闻 `BLOCKED` 时仍保存审计和报告，但 `ready_for_phase1b=False`。

- [ ] **Step 5: 新增 CLI**

命令参数固定为：

```python
@app.command("phase1a2-news-probe")
def phase1a2_news_probe(
    run_kind: str = typer.Option(..., "--run-kind", help="intraday or post_close"),
    output_dir: Path = typer.Option(Path("data/phase1a2")),
    database_path: Path = typer.Option(Path("data/sector-pulse.db")),
    news_config: Path = typer.Option(Path("config/news_sources.yaml")),
    entity_config: Path = typer.Option(Path("config/sector_entities.yaml")),
    consent_file: Path = typer.Option(Path(".live-data-consent")),
) -> None:
```

`run_kind` 只接受 `intraday` 和 `post_close`。输出目录使用 `<date>/<run_kind>/<run_id>/report.json` 和 `report.md`，避免覆盖。缺少 consent 时在触网前失败。

- [ ] **Step 6: 运行测试和提交**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase1a2_probe.py backend/tests/unit/reporting/test_phase1a2_report.py -q`

Expected: PASS。

```powershell
git add backend/src/sector_pulse/application/phase1a2_probe.py backend/src/sector_pulse/reporting/phase1a2_report.py backend/src/sector_pulse/cli.py backend/tests/integration/test_phase1a2_probe.py backend/tests/unit/reporting/test_phase1a2_report.py
git commit -m "feat: add phase 1a2 real news probe"
```

---

### Task 7: Gated live 测试和盘中/盘后验收记录

**Files:**
- Create: `backend/tests/live/test_real_news_live.py`
- Modify: `backend/tests/conftest.py`
- Modify: `docs/provider-matrix/phase-0.md`
- Create: `docs/phase1a2/README.md`
- Runtime output: `data/phase1a2/<date>/<run_kind>/<run_id>/report.json`
- Runtime output: `data/phase1a2/<date>/<run_kind>/<run_id>/report.md`

**Interfaces:**
- Consumes: 三个真实 Provider 和 `phase1a2-news-probe`。
- Produces: 可重复执行的逐来源 live 健康检查及两份不覆盖的验收报告。

- [ ] **Step 1: 写显式 live 测试**

```python
pytestmark = pytest.mark.live


async def test_cls_live_returns_explicit_status() -> None:
    result = await AkShareClsAdapter().fetch_global(datetime.now(UTC))
    assert result.status in {DataStatus.SUCCESS, DataStatus.EMPTY, DataStatus.PARTIAL}
    assert result.status is not DataStatus.FAILED


async def test_eastmoney_live_has_auditable_metadata() -> None:
    now = datetime.now(UTC)
    result = await AkShareEastmoneyNewsAdapter().search("人工智能", now - timedelta(days=7), now)
    assert result.status in {DataStatus.SUCCESS, DataStatus.EMPTY, DataStatus.PARTIAL}
    for document in result.data or ():
        assert document.source_id
        assert document.published_at is None or document.published_at <= now
        assert document.source_observed_at is None or document.source_observed_at <= now


async def test_cninfo_live_has_primary_documents_or_empty() -> None:
    now = datetime.now(UTC)
    result = await AkShareCninfoAdapter().search_disclosures(
        ("000001",), now - timedelta(days=7), now
    )
    assert result.status in {DataStatus.SUCCESS, DataStatus.EMPTY, DataStatus.PARTIAL}
```

- [ ] **Step 2: 运行默认测试确认 live 测试跳过**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/live/test_real_news_live.py -q`

Expected: 3 skipped，原因包含 `requires --run-live and .live-data-consent`。

- [ ] **Step 3: 在用户已审查来源条款且 consent 存在时运行逐来源 live 测试**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests/live/test_real_news_live.py -q --run-live --basetemp=.test-tmp`

Expected: 三个测试 PASS；若上游失败，保留具体 `ProviderError.code`，修复 Adapter 后重跑，不修改断言接受 `FAILED`。

- [ ] **Step 4: 执行盘中验收**

Run: `.\.venv\Scripts\sector-pulse.exe phase1a2-news-probe --run-kind intraday --output-dir data/phase1a2 --database-path data/sector-pulse.db`

Expected: 退出码 0，报告 `cutoff_violation_count=0`、`elapsed_ms<=300000`，并产生唯一 run 目录。若执行时已经收盘，不伪造盘中报告，等待下一个交易时段执行本步骤。

- [ ] **Step 5: 执行盘后验收**

Run: `.\.venv\Scripts\sector-pulse.exe phase1a2-news-probe --run-kind post_close --output-dir data/phase1a2 --database-path data/sector-pulse.db`

Expected: 退出码 0，报告与盘中 `run_id`、目录不同，且 `ready_for_phase1b=true`。

- [ ] **Step 6: 更新 Provider 矩阵和验收说明并提交代码/文档**

`docs/phase1a2/README.md` 记录命令、时间、真实状态、报告相对路径、授权边界和仍存在的上游风险；不得提交 `data/` 运行数据或新闻正文。

```powershell
git add backend/tests/live/test_real_news_live.py backend/tests/conftest.py docs/provider-matrix/phase-0.md docs/phase1a2/README.md
git commit -m "test: validate real news providers"
```

---

### Task 8: 全量回归、构建和阶段验收

**Files:**
- Modify only if validation reveals a defect in files introduced by Tasks 1-7.
- Verify: `docs/superpowers/specs/2026-08-14-phase-1a2-real-news-ingestion-design.md`
- Verify: `docs/phase1a2/README.md`

**Interfaces:**
- Consumes: Tasks 1-7 的完整实现。
- Produces: 可审核的 Phase 1A.2 完成证据；不进入 Phase 1B 实现。

- [ ] **Step 1: 运行默认非 live 测试**

Run: `.\.venv\Scripts\python.exe -m pytest backend/tests -q --basetemp=.test-tmp`

Expected: 所有非 live 测试 PASS，live 测试明确 SKIPPED。

- [ ] **Step 2: 运行静态检查**

Run: `.\.venv\Scripts\ruff.exe check backend/src backend/tests`

Expected: `All checks passed!`

Run: `.\.venv\Scripts\python.exe -m mypy backend/src`

Expected: `Success: no issues found`。

- [ ] **Step 3: 构建 wheel 并检查配置资源策略**

Run: `.\.venv\Scripts\python.exe -m pip wheel . --no-deps -w dist`

Expected: 生成 `sector_pulse-0.1.0-py3-none-any.whl`。配置文件保持仓库部署资源，不假装已经打包进 wheel；CLI 对缺失配置给出明确路径错误。

- [ ] **Step 4: 检查 Git 和差异质量**

Run: `git diff --check`

Expected: 无输出。

Run: `git status --short --branch`

Expected: 只允许存在明确记录的验收文档修改；`data/`、`.live-data-consent`、数据库和密钥均不被跟踪。

- [ ] **Step 5: 对照规格做最终人工检查**

逐项确认：三个默认 Provider、双通道两阶段召回、调用预算、cutoff、状态语义、映射准确率 fixture、证据等级不越级、SQLite 审计、盘中/盘后报告、无 LLM/正文/Web。任何未满足项必须在 Phase 1A.2 保持未完成，不得写成后续优化。

- [ ] **Step 6: 提交最终验收文档**

```powershell
git add docs/phase1a2/README.md
git commit -m "docs: record phase 1a2 validation"
```

## Phase 1A.2 Exit Checklist

- [ ] 财联社、东方财富和巨潮 Provider 均通过 fixture 契约测试。
- [ ] 显式 live 测试未把 `FAILED` 放宽成可接受状态。
- [ ] 市场预候选不依赖新闻，最终候选才使用去重新闻丰富度。
- [ ] 全局突发可以补召回非市场预候选板块。
- [ ] 东方财富查询不超过 24 次，巨潮股票代码不超过 12 个。
- [ ] 所有进入本轮的数据不晚于锁定 cutoff。
- [ ] 缺发布时间或缺可核验 URL 的新闻不会成为引用证据。
- [ ] 高置信实体映射 fixture 准确率不低于 90%。
- [ ] `EvidencePack` 不会在本阶段升级到 `POSSIBLE_CATALYST` 或 `EXPLICIT_DRIVER`。
- [ ] 来源执行、查询摘要和板块事件关联可从 SQLite 审计。
- [ ] 盘中和盘后报告使用不同 run 目录，不互相覆盖。
- [ ] 默认非 live 测试、Ruff、mypy 和 wheel 构建通过。
- [ ] 用户审核 Phase 1A.2 真实验收记录后，才开始 Phase 1B 归因与成文设计。
