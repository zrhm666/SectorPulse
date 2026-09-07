# Run Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 用户已选择 Inline Execution；在当前会话连续执行，不使用子代理。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重新采集或修改业务数据的前提下，对比两次同来源、同场景的已结束数据运行中的候选、行情、新闻成员和证据关联。

**Architecture:** 新增类型化只读查询服务和纯差异函数，复用 RuntimeStorageBundle；仅扩展运行仓储的历史分页查询。前端在既有 AppShell 内新增 `/runs/compare`，使用双运行选择区、对齐结果表和新闻/证据分页。SQLite 与 PostgreSQL 使用相同规则，不新增 schema 迁移。

**Tech Stack:** Python >=3.12、Pydantic、FastAPI、SQLite、同步 SQLAlchemy/psycopg、React 18、TypeScript、现有 Vite/Vitest/Playwright。

**Spec:** [2026-09-07-run-comparison-design.md](../specs/2026-09-07-run-comparison-design.md)。执行前完整阅读设计，尤其是新闻历史边界和不可比分类处理。

## Global Constraints

- 仅查询已持久化数据；不调用行情、新闻或 LLM 上游，不写入业务数据。
- 同时支持 SQLite 和原生 PostgreSQL；Docker 不是前置条件。
- 沿用 Python >=3.12、React 18、TypeScript、FastAPI 及当前锁定依赖；不增加运行时依赖。
- 沿用现有 AppShell、统一导航和 `web/src/styles/tokens.css`；不另建主题或侧边栏。
- 缺失或不可比的值使用 null 和原因；不得替换为零、正常或已完成。
- 新闻文字是当前保存的元数据，不是历史正文快照；不输出历史正文差异。
- 测试使用临时 SQLite 或经核实的独立 PostgreSQL 测试库，禁止使用业务库写入测试数据。
- 当前会话执行，不使用子代理；未获授权不推送远端，不恢复影子测试。

---

## 执行状态与准备

创建日期：2026-09-07；代码核对基线 `main / bf8d953`。**本文件是待执行计划，不是验收记录；当前无任务已完成。** 跨来源/场景限制是设计稿推荐默认值，用户若在实施前另行选择，先同步契约与测试。

实现开始时使用 using-git-worktrees 检查隔离工作区，以当时已核对的 main 创建 `codex/run-comparison`；不得在旧的 `.worktrees/stage0-reliability` 上直接开工，也不得清除用户未提交改动。本轮只写文档，不创建功能分支或执行以下实现命令。

每项任务遵循 test-driven-development：先运行新增测试确认红灯，再实现，再运行确认绿灯，随后本地小提交。阶段间不重复请求用户确认；遇到业务权限、测试库身份不明或设计边界必须扩展时才暂停。

PowerShell 验证命令从功能工作区根目录执行；共享已有 Python 环境可使用 `D:\work\SectorPulse\.venv\Scripts\python.exe`，运行前把 `PYTHONPATH` 明确指向**该功能工作区**的 `backend/src`，防止测试旧主目录包。前端命令从该工作区 `web` 执行；不更改 `.env`、consent 或业务数据库设置。

## 文件责任图

下列“新增”路径是计划产物，当前尚不存在。后端路径均相对仓库根。

| 动作 | 路径 | 责任 |
| --- | --- | --- |
| 新增 | `backend/src/sector_pulse/application/run_comparison_models.py` | 设计 §6 全部响应模型、Literal 类型和分页模型 |
| 新增 | `backend/src/sector_pulse/application/run_comparison_diff.py` | 候选身份、差值、字段可用性、新闻成员集合、证据关系集合纯函数 |
| 修改 | `backend/src/sector_pulse/storage/ports.py` | RealDataRunRepositoryPort 增加只读分页方法 |
| 修改 | `backend/src/sector_pulse/storage/real_data_run_repository.py` | SQLite 分页查询 |
| 修改 | `backend/src/sector_pulse/storage/postgres_real_data_run_repository.py` | PostgreSQL 对等分页查询 |
| 新增 | `backend/src/sector_pulse/application/run_comparison_queries.py` | 获取两侧持久化记录、兼容性验证、拼装 DTO、分页后批量加载元数据 |
| 新增 | `backend/src/sector_pulse/web/routers/run_comparisons.py` | 四个只读端点、参数校验与错误转换 |
| 修改 | `backend/src/sector_pulse/web/dependencies.py`、`backend/src/sector_pulse/web/app.py` | 查询依赖装配和路由注册 |
| 新增 | `web/src/runComparisonsApi.ts` | 与设计 §6 同名 TS 类型、GET 请求、错误解析和 AbortSignal |
| 新增 | `web/src/hooks/useRunComparison.ts` | 已提交 URL 组合、分页/请求状态和晚响应隔离 |
| 新增 | `web/src/pages/RunComparisonPage.tsx` | 页面编排、选择区与标签页 |
| 新增 | `web/src/pages/run-comparison/RunPickerDialog.tsx` | 20 条分页的原生 modal dialog 选择器 |
| 新增 | `web/src/pages/run-comparison/SectorComparisonPanel.tsx` | 候选/行情对齐表、过滤与行内详情 |
| 新增 | `web/src/pages/run-comparison/NewsComparisonPanel.tsx` | 成员差异、分页、当前元数据详情 |
| 新增 | `web/src/pages/run-comparison/EvidenceComparisonPanel.tsx` | 板块事件关联两侧说明 |
| 新增 | `web/src/styles/run-comparison.css` | 仅新增页面的 scoped 样式，不覆写全站 token |
| 修改 | `web/src/App.tsx`、`web/src/pages/RunListPage.tsx`、`web/src/pages/DataRunPage.tsx` | 静态路由、历史入口、已结束数据运行入口 |
| 新增测试支撑 | `backend/tests/comparison_support.py` | PostgreSQL 专用库身份守卫与共享 fixture；不得包含业务库连接兜底 |
| 新增/修改测试 | 见各 Task | 纯规则、SQLite、PostgreSQL、HTTP、交互和浏览器门槛 |
| 修改文档 | `README.md`、`docs/PROJECT_STATUS.md` | 仅在功能验收后宣告交付 |
| 新增验收 | `docs/superpowers/acceptance/2026-09-07-run-comparison.md` | 实际执行日期、提交、结果、限制与截图（执行跨日则文件日期随实际验收日调整） |

三阶段依赖：Task 1–3（后端）→ Task 4–5（前端）→ Task 6（整体交付）。各阶段只重用公共约定，不新增并行的导航/状态系统。

## Phase 1：可信只读后端

### Task 1：类型契约与纯差异规则

**Files:** 新增 `run_comparison_models.py`、`run_comparison_diff.py`；新增 `backend/tests/unit/application/test_run_comparison_diff.py`。

**Interfaces:**

- models：逐一实现设计 §6 类型字典中的 17 个 Pydantic 模型；frozen、extra=forbid，Decimal 使用 Pydantic JSON 字符串序列化。SectorKind、RealDataRunStatus 引用现有枚举，不复制。
- `metric_difference(base: Decimal | None, compare: Decimal | None, *, unit: Literal["percentage_points", "count"], base_reason: MissingReason | None = None, compare_reason: MissingReason | None = None) -> MetricDifference`。
- `rank_delta(base: int | None, compare: int | None) -> int | None`。
- `candidate_keys(candidates: Sequence[RealDataCandidate]) -> set[tuple[SectorKind, str]]`。
- `document_membership(base_ids: set[str], compare_ids: set[str]) -> dict[str, Membership]`；仅负责集合，coverage guard 在查询服务。
- MissingReason 为 VALUE_MISSING/FIELD_UNDECLARED/SECTOR_MISSING；Membership 为 BOTH/ONLY_BASE/ONLY_COMPARE。这两个 Literal 在 models 定义。

- [ ] **1. 写红灯测试**，包含以下精确断言，再补种类同码、单侧 null、负值和 Decimal 序列化用例：

```python
from decimal import Decimal

from sector_pulse.application.run_comparison_diff import (
    document_membership, metric_difference, rank_delta,
)


def test_zero_is_known_and_percentage_change_uses_points() -> None:
    result = metric_difference(
        Decimal("0"), Decimal("0.10"), unit="percentage_points"
    )
    assert result.base == Decimal("0")
    assert result.delta == Decimal("0.10")
    assert result.model_dump(mode="json")["delta"] == "0.10"
    assert rank_delta(5, 2) == 3
    assert rank_delta(None, 2) is None


def test_unknown_is_not_zero() -> None:
    result = metric_difference(
        None, Decimal("0"), unit="count", base_reason="FIELD_UNDECLARED"
    )
    assert result.delta is None
    assert result.base_reason == "FIELD_UNDECLARED"


def test_membership_uses_ids_not_titles() -> None:
    assert document_membership({"a", "shared"}, {"b", "shared"}) == {
        "a": "ONLY_BASE", "b": "ONLY_COMPARE", "shared": "BOTH",
    }
```

- [ ] **2. 运行测试确认失败**：`python -m pytest backend/tests/unit/application/test_run_comparison_diff.py -q`。预期新模块未定义导致失败；若意外通过，先检查 PYTHONPATH 和是否存在他人实现。
- [ ] **3. 实现 DTO 和纯规则**。核心算术不读取数据库、不转换 float；空值原因自动补 VALUE_MISSING，明确原因意味着对应值未知：

```python
def metric_difference(base, compare, *, unit, base_reason=None, compare_reason=None):
    if base_reason is not None:
        base = None
    if compare_reason is not None:
        compare = None
    return MetricDifference(
        base=base,
        compare=compare,
        delta=None if base is None or compare is None else compare - base,
        unit=unit,
        base_reason=base_reason or ("VALUE_MISSING" if base is None else None),
        compare_reason=compare_reason or ("VALUE_MISSING" if compare is None else None),
    )


def rank_delta(base, compare):
    return None if base is None or compare is None else base - compare


def document_membership(base_ids, compare_ids):
    return {
        key: "BOTH" if key in base_ids and key in compare_ids
        else "ONLY_BASE" if key in base_ids else "ONLY_COMPARE"
        for key in sorted(base_ids | compare_ids)
    }
```

上段函数体实施时使用 Interfaces 的完整类型签名。字段读取逻辑按 available_fields、sector 是否存在逐项判断；没有 declared 字段不能利用默认 0。候选使用 `(item.sector_kind, item.sector_id)`；不调用现有评分器或 breadth_ratio。

- [ ] **4. 验证绿灯及风格**：重跑该测试，再运行 `python -m ruff check backend/src/sector_pulse/application/run_comparison_models.py backend/src/sector_pulse/application/run_comparison_diff.py backend/tests/unit/application/test_run_comparison_diff.py`。
- [ ] **5. 本地小提交**：只暂存本任务三个文件，提交 `feat: define truthful run comparison rules`。

### Task 2：双数据库历史选择分页

**Files:** 修改 ports、SQLite/PostgreSQL real_data_run_repository；新增 `backend/tests/integration/test_comparison_run_listing.py`、`backend/tests/integration/test_postgres_comparison_run_listing.py`、`backend/tests/comparison_support.py`；复查现有两种 runtime bundle contract。

**Interfaces:** 在 RealDataRunRepositoryPort 和两种仓储定义：

```python
def list_comparison_runs(
    self,
    *,
    provider: Literal["fixture", "live"] | None = None,
    mode: Literal["intraday", "post_close"] | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[RealDataRun], int]:
    """Return terminal data runs and the matching total; never modify run state."""
```

这是协议签名说明；实际实现必须返回查询结果，不保留空方法体。既有 list_runs 不改语义，RuntimeStorageBundle 无新增仓储字段。

- [ ] **1. 写分页红灯测试**。在临时 SQLite 插入 55 个同时间终态 fixture 运行和一个 FETCHING_MARKET，按 UUID 从大到小核对所有页；原始实体由既有类型直接构建：

```python
from datetime import UTC, datetime
from uuid import UUID

from sector_pulse.domain.real_data_run import (
    RealDataRun, RealDataRunRequest, RealDataRunStatus,
)
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite import SQLiteDatabase


def test_listing_reaches_history_beyond_fifty(tmp_path) -> None:
    repo = SQLiteRealDataRunRepository(SQLiteDatabase(tmp_path / "comparison.sqlite"))
    now = datetime(2026, 9, 7, tzinfo=UTC)
    for number in range(1, 56):
        repo.insert(RealDataRun(
            run_id=UUID(int=number), provider="fixture",
            request=RealDataRunRequest(mode="post_close", requested_at=now),
            status=RealDataRunStatus.READY_FOR_ATTRIBUTION,
        ))
    repo.insert(RealDataRun(
        provider="fixture", request=RealDataRunRequest(mode="post_close"),
        status=RealDataRunStatus.FETCHING_MARKET,
    ))
    items, total = repo.list_comparison_runs(
        provider="fixture", mode="post_close", offset=50, limit=20,
    )
    assert total == 55
    assert [item.run_id for item in items] == [UUID(int=n) for n in range(5, 0, -1)]
```

- [ ] **2. 运行确认失败**：`python -m pytest backend/tests/integration/test_comparison_run_listing.py -q`。预期未实现 list_comparison_runs。
- [ ] **3. 两种仓储实现同一 SQL 语义**。终态枚举使用 `tuple(status.value for status in RealDataRunStatus if status.is_terminal)`；终态列表、provider、mode、offset、limit 全部绑定参数，禁止拼接用户值。固定 SQL 结构如下，SQLite 使用对应问号/命名占位符，PostgreSQL 使用 SQLAlchemy text + expanding bindparam：

```sql
SELECT * FROM real_data_runs
WHERE status IN :terminal
  AND (:provider IS NULL OR provider = :provider)
  AND (:mode IS NULL OR mode = :mode)
ORDER BY requested_at DESC, run_id DESC
LIMIT :limit OFFSET :offset
```

COUNT(*) 使用完全相同 WHERE，在同一连接中查询；结果映射复用仓储已有 `_row_to_run`。仓储拒绝 offset <0 或 limit 不在 1–100；边界空页仍返回正确 total。SQL 语法按数据库驱动绑定，不直接把示意 SQL 原样发送 SQLite。

- [ ] **4. 验证 SQLite 并准备 PostgreSQL 等价测试**。核对专用库真实名称与连接目标后才设置测试进程变量；缺少专用库时记录“PostgreSQL 未验证”，不得把 skip 当通过。在本任务就将 Task 6 展示的完整 comparison_postgres fixture 写入 `backend/tests/comparison_support.py`，两个 PostgreSQL 比较测试模块显式导入该 fixture；标记整个测试模块 `pytestmark = pytest.mark.postgres`。等价用例同时验证 provider/mode 过滤、所有终态包含、运行中排除、相同时间稳定排序和越界页。
PostgreSQL 专用库允许保留之前测试记录：先记录基线总量，使用本次新 UUID 插入，核对总量增量及遍历各页得到的本次 ID 集合；不要直接照搬临时 SQLite 的固定 UUID 和 total=55 断言到可重复使用的实库，也不要为了总数方便清空数据库。

- [ ] **5. 本地小提交**：上述仓储、协议、测试支撑和两项测试，提交 `feat: page comparable runs on sqlite and postgres`。

### Task 3：只读对比查询与 HTTP

**Files:** 新增 run_comparison_queries、routers/run_comparisons；修改 dependencies/app；新增 `backend/tests/unit/application/test_run_comparison_queries.py`、`backend/tests/integration/test_run_comparison_api.py`；修改 `backend/tests/unit/web/test_dependencies.py`。

**Interfaces:** `RunComparisonQueries(storage: RuntimeStorageBundle)` 提供以下方法，返回 Task 1 定义的 DTO：

```text
list_runs(*, provider=None, mode=None, offset=0, limit=20) -> RunOptionPage
compare(base_run_id: UUID, compare_run_id: UUID) -> RunComparisonView
news(base_run_id: UUID, compare_run_id: UUID, *, membership: MembershipFilter="ALL", offset=0, limit=20) -> NewsComparisonPage
evidence(base_run_id: UUID, compare_run_id: UUID, *, kind: SectorKind|None=None, sector_id: str|None=None, offset=0, limit=20) -> EvidenceComparisonPage
```

provider、mode 使用 Task 2 Literal；MembershipFilter 在 models 定义为 ALL/BOTH/ONLY_BASE/ONLY_COMPARE。错误类型在 queries 定义 `ComparisonNotFoundError`、`ComparisonConflictError`、`ComparisonInputError`，均继承 ValueError。路由 `build_run_comparisons_router(queries: RunComparisonQueries) -> APIRouter` 捕获并分别转 HTTPException 404/409/422，其他异常交给全站脱敏 handler。

- [ ] **1. 先写最小只读 API 红灯用例**，用临时 SQLite + 单独 FastAPI router，避免启动业务调度器：

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sector_pulse.application.run_comparison_queries import RunComparisonQueries
from sector_pulse.storage.runtime_bundle import build_sqlite_storage
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.web.errors import register_error_handlers
from sector_pulse.web.routers.run_comparisons import build_run_comparisons_router
from sector_pulse.domain.real_data_run import (
    RealDataRun, RealDataRunRequest, RealDataRunStatus,
)


def test_same_run_is_rejected_without_creating_runs(tmp_path) -> None:
    storage = build_sqlite_storage(SQLiteDatabase(tmp_path / "compare-api.sqlite"))
    run = RealDataRun(
        provider="fixture", request=RealDataRunRequest(mode="post_close"),
        status=RealDataRunStatus.READY_FOR_ATTRIBUTION,
    )
    storage.real_data_runs.insert(run)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(build_run_comparisons_router(RunComparisonQueries(storage)))
    response = TestClient(app).get("/api/run-comparisons", params={
        "base_run_id": str(run.run_id), "compare_run_id": str(run.run_id),
    })
    assert response.status_code == 422
    assert len(storage.real_data_runs.list_runs()) == 1
```

- [ ] **2. 运行确认失败**：`python -m pytest backend/tests/integration/test_run_comparison_api.py -q`。
- [ ] **3. 实现完整两侧验证与组装**。读取顺序固定为运行验证 → 各类快照兼容性 → 独立 get_candidates → 候选并集行 → 新闻 ID coverage/集合 → warning。新闻及证据端点调用相同验证入口，但不为了分页重复加载全部元数据。仅分组兼容时做键匹配，全部分类缺失时返回真实空组和警告。

```python
base_ids = {link.document_id for link in storage.news_retrieval.list_query_documents(base_id)}
compare_ids = {link.document_id for link in storage.news_retrieval.list_query_documents(compare_id)}
if not base_ids or not compare_ids:
    available = False
    counts = None
    page_ids = []
else:
    available = True
    membership_by_id = document_membership(base_ids, compare_ids)
    both = len(base_ids & compare_ids)
    counts = NewsCounts(
        both=both, only_base=len(base_ids - compare_ids),
        only_compare=len(compare_ids - base_ids),
    )
    filtered_ids = [
        key for key, value in membership_by_id.items()
        if membership == "ALL" or value == membership
    ]
    page_ids = filtered_ids[offset:offset + limit]
metadata_by_id = storage.news.get_documents(page_ids) if page_ids else {}
```

上段是 `news()` 核心组装过程；base_id/compare_id 是已验证的运行 UUID，membership/offset/limit 为方法参数。逐个 page_id 生成 NewsComparisonRow，即使 metadata_by_id 中缺失也保留 metadata=null。counts 在筛选分页前计算，total 是筛选后 ID 数；不可核验时 total=null、reason=LINEAGE_UNVERIFIABLE。外链通过 urllib.parse 检查 scheme+netloc；输出元数据统一 CURRENT_STORED。

证据键为 `(link.sector_kind, link.sector_id, link.event_id)`；先限制兼容分类和候选并集，再集合差异、稳定排序和分页，最后 get_events 批量查询标题；保留两侧 mapping 原值，不拼接 current event.document_ids。警告代码、字段空值及排名方向逐项照设计 §4、§6。

- [ ] **4. 加入四个同步 GET 端点和依赖装配**。WebRouterDependencies 增加 comparison_queries，在 build_web_router_dependencies 用 runtime.storage 构建并允许同名 overrides 注入；app.include_router 注册新前缀。为端点声明 response_model、UUID/Literal、分页 Query 范围。不得构造新的数据库连接配置或启动业务运行。
- [ ] **5. 增加以下固定数据测试并运行至全绿**：

| 固定输入 | 必须断言 |
| --- | --- |
| A 行业001排5涨0%，B行业001排2涨0.10%，同类别来源/分类 | rank_delta=3，pct_change.delta="0.10"，分数无 delta 字段 |
| 另有概念001，两侧排名、新闻关联与行业不同 | 不串候选、不串事件、两行独立 |
| A 未入选某板块但行情有值，B 入选 | rank_delta=null，仍可比较双方已声明的行情 |
| B source_version 不同 | 可查看并显示 SOURCE_VERSION_DIFF |
| B classification_version 不同/一侧缺快照 | 对应组 INCOMPATIBLE/UNAVAILABLE，rows=[]，不计单侧候选 |
| A 文档{a,s}，B文档{s,b}，a 缺元数据，s 标题被更新 | 总数和成员不变，a 保留空元数据，s 明确 CURRENT_STORED |
| A 没 query_documents 但全局 event 有 documents | 不从 event 补成员，news_counts=null |
| 新闻200个，limit20，重复query命中 | 按去重成员计算全部数量，仅批量加载该页20个元数据 |
| 非终态、provider/mode 不同、未知UUID、非法分页 | 409/409/404/422，所有端点一致；无业务表改写 |

命令：`python -m pytest backend/tests/unit/application/test_run_comparison_diff.py backend/tests/unit/application/test_run_comparison_queries.py backend/tests/integration/test_run_comparison_api.py backend/tests/unit/web/test_dependencies.py -q`。补全应用装配 smoke 测试时使用显式临时 settings，禁用 scheduler，不加载业务 `.env`。

- [ ] **6. 本地小提交**：只读查询、路由、装配与测试，提交 `feat: expose persisted run comparison queries`。Phase 1 完成后在本计划记入实际命令结果，不先标记前端完成。

## Phase 2：对照工作台

### Task 4：运行选择、URL 状态与入口

**Files:** 新增 runComparisonsApi、useRunComparison、RunComparisonPage、RunPickerDialog、run-comparison.css；修改 App/RunListPage/DataRunPage；新增对应 API、hook、page、dialog 的 `.test.ts(x)`，更新 RunListPage.test.tsx 和 DataRunPage.test.tsx。

**Interfaces:** TS DTO 字段与设计 §6 完全一致，Decimal 映射 string，datetime/UUID 映射 string；不要复用已有把缺失行情声明为非 null 的 MarketSectorView。

```typescript
type ComparisonPair = { base: string; compare: string }
type ComparisonTab = 'sectors' | 'news' | 'evidence'
type MembershipFilter = 'ALL' | 'BOTH' | 'ONLY_BASE' | 'ONLY_COMPARE'

// runComparisonsApi.ts 的导出接口
function fetchComparisonRuns(options: { provider?: 'fixture' | 'live'; mode?: 'intraday' | 'post_close'; offset?: number; limit?: number }, signal: AbortSignal): Promise<RunOptionPage>
function fetchRunComparison(pair: ComparisonPair, signal: AbortSignal): Promise<RunComparisonView>
function fetchComparisonNews(pair: ComparisonPair, options: { membership: MembershipFilter; offset: number; limit: number }, signal: AbortSignal): Promise<NewsComparisonPage>
function fetchComparisonEvidence(pair: ComparisonPair, options: { kind?: SectorKind; sector_id?: string; offset: number; limit: number }, signal: AbortSignal): Promise<EvidenceComparisonPage>
```

这些是契约声明，实际导出函数必须有请求实现；API DTO 和上述类型统一从 runComparisonsApi 导出。hook 接口为 `useRunComparison(pair: ComparisonPair | null): { data: RunComparisonView | null; loading: boolean; error: string | null; reload: () => void }`；分页请求由对应面板持有局部状态并使用相同取消规则。RunPickerDialog props 为 `{ title: string; constraint: Pick<RunOption, 'provider' | 'mode'> | null; excludedRunId: string | null; onSelect: (run: RunOption) => void; onClose: () => void }`。

- [ ] **1. 写红灯交互测试**。用 MemoryRouter 初始化 `/runs/compare?base=00000000-0000-0000-0000-000000000001&compare=00000000-0000-0000-0000-000000000002`；mock 只读 API，验证静态路径不会落入 `/runs/:runId`。dialog 测试示例：

```tsx
const onSelect = vi.fn()
render(<RunPickerDialog title="选择对照运行" constraint={null}
  excludedRunId={null} onSelect={onSelect} onClose={vi.fn()} />)
expect(await screen.findByRole('dialog', { name: '选择对照运行' })).toBeVisible()
await userEvent.click(screen.getByRole('button', { name: '下一页' }))
expect(fetchComparisonRuns).toHaveBeenLastCalledWith(
  expect.objectContaining({ offset: 20, limit: 20 }), expect.any(AbortSignal),
)
```

测试准备在本文件 mock fetchComparisonRuns 返回 items 为合法 RunOption、total=55、offset 与请求一致；原生 showModal 在 jsdom 中使用当前项目支持方式设置测试替身，真实焦点由 Task 6 浏览器验证。再用 deferred promise 控制旧请求晚到，断言页面仍显示新 A/B 组合。

- [ ] **2. 运行确认失败**：在 web 执行 `npm test -- src/pages/RunComparisonPage.test.tsx src/pages/run-comparison/RunPickerDialog.test.tsx src/hooks/useRunComparison.test.tsx`。
- [ ] **3. 编写 GET 包装**，保留本地相对 URL，不写死8000/9000端口，使用 URLSearchParams，沿用 error.message 解析。请求不得发 POST。核心示例：

```typescript
export async function fetchRunComparison(pair: ComparisonPair, signal: AbortSignal): Promise<RunComparisonView> {
  const params = new URLSearchParams({ base_run_id: pair.base, compare_run_id: pair.compare })
  const response = await fetch(`/api/run-comparisons?${params}`, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.error?.message ?? '无法加载运行对比，请重试。')
  }
  return response.json() as Promise<RunComparisonView>
}
```

其余三个 GET 用同一文件私有请求函数复用此错误逻辑；400/500不回退为成功空数组。hook effect 内每次创建 AbortController 和 cancelled 标记，cleanup 同时 abort 与置 cancelled；成功、失败、finally 都检查当前请求归属，AbortError 不显示用户错误。

- [ ] **4. 实现选择区和 URL 提交**。page 用 useSearchParams 获取已提交 pair；临时选择保存完整 RunOption，改变其中一侧时验证另一侧 provider/mode，失配清空并提示。只提交两个不同完整 UUID；base 单独存在时调用既有 `fetchDataRun` 读入元信息，不假定在第一页。交换已提交组合时更新 URL 并清空结果。非法 tab 归一为 sectors，非法 UUID 显示可编辑选择错误，不崩溃。
- [ ] **5. 加入既有入口及布局**。AppRoutes 增加 `/runs/compare` 并放在参数路由前；RunListPage 新增 Link，DataRunPage 仅对设计终态集合显示预填 base 的 Link。复用 AppShell 和现有按钮/面板，只从 page 引入 scoped CSS；原有 sidebar navigation 数据不变。
- [ ] **6. 验证绿灯**：运行上述新增测试、runComparisonsApi.test.ts 及两处入口原有测试；在不完整组合、只有一条历史、404和409情况下检查按钮、提示、返回入口均真实有效。
- [ ] **7. 本地小提交**：仅本任务文件，提交 `feat: select and restore run comparison pairs`。

### Task 5：行情表、新闻成员与证据关系

**Files:** 新增 SectorComparisonPanel、NewsComparisonPanel、EvidenceComparisonPanel 及对应 `.test.tsx`；补充 RunComparisonPage 和 run-comparison.css。

**Interfaces:**

- `SectorComparisonPanel({ data }: { data: RunComparisonView })`：仅渲染已计算差值，前端不重新做小数减法。
- `NewsComparisonPanel({ pair }: { pair: ComparisonPair })`：消费 fetchComparisonNews，局部 membership/offset 状态；pair 改变归零。
- `EvidenceComparisonPanel({ pair }: { pair: ComparisonPair })`：消费 fetchComparisonEvidence；首版传整组关系，必要时由行内控件同时传 kind 和 sector_id，取消筛选时二者同时省略。

- [ ] **1. 写红灯展示测试**。测试必须同时放入值为 "0" 和 null 的单元格、同码行业/概念，以及 metadata=null 的新闻，不使用标题当 key：

```tsx
expect(screen.getByText('上升 3 位')).toBeVisible()
expect(screen.getByText('仅对照入选')).toBeVisible()
expect(screen.getByText('字段口径未知')).toBeVisible()
expect(screen.getByText('新闻元数据不可用')).toBeVisible()
expect(screen.getByText('当前保存的新闻元数据，非历史正文快照')).toBeVisible()
expect(screen.queryByRole('link', { name: '查看原文' })).not.toBeInTheDocument()
```

把上面断言放在分别渲染行情和新闻面板的用例中，fixture 使用设计 §6 完整 DTO：排名5→2；单侧候选；FIELD_UNDECLARED；非法 citation_url 不产生 link。另写同一页新闻统计200、当前页20行的用例，确认不把分页长度显示为总量。

- [ ] **2. 运行确认失败**：`npm test -- src/pages/run-comparison/SectorComparisonPanel.test.tsx src/pages/run-comparison/NewsComparisonPanel.test.tsx src/pages/run-comparison/EvidenceComparisonPanel.test.tsx`。
- [ ] **3. 实现结果面板**。使用语义 table、caption、th scope；移动断点下保留每项 A/B 标签。unknown 的说明由 reason 映射，不靠颜色区别；数字仅做显示格式化，不参与计算。详情采用行内折叠：

```tsx
<button type="button" aria-expanded={expanded} aria-controls={detailsId}
  onClick={() => setExpanded(value => !value)}>
  {expanded ? '收起详情' : '查看详情'}
</button>
<div id={detailsId} hidden={!expanded}>
  <p>各次运行内部相对分，不代表跨运行绝对强弱。</p>
  <dl><dt>基准 A</dt><dd>{row.base_score ?? '未入选'}</dd>
    <dt>对照 B</dt><dd>{row.compare_score ?? '未入选'}</dd></dl>
</div>
```

expanded、detailsId 为行组件内部状态和 useId，row 为 SectorComparisonRow。新闻也原位展开摘要；只渲染纯文本，不使用 dangerouslySetInnerHTML。分页前按钮有边界 disabled，加载时 aria-busy；局部错误保留原 pair 和重试操作，不显示上一组合的数据。

- [ ] **4. 实现标签页与响应式**。三个 tab 具备 tablist/tab/tabpanel、方向键、Home/End 和 roving tabindex；切换 tab 更新 URL，卸载旧分页组件以清理请求。960px 选择区纵排，720px 以下逐板块显示；复用 var(--sp-*) 与 compact 间距，数字 font-variant-numeric: tabular-nums；不得整体修改 globals 或 token 来适配单页。
- [ ] **5. 验证绿灯和构建**：运行该目录全部测试，执行 `npm run build`，检查真实数据缺失、全类别不可比、旧新闻无 lineage、证据元数据丢失均有可解释状态。
- [ ] **6. 本地小提交**：提交 `feat: present sector news and evidence comparisons`。

## Phase 3：完整验收与交付

### Task 6：双数据库只读证明、真实浏览器与文档

**Files:** 新增 `backend/tests/integration/test_postgres_run_comparison_api.py`、`web/e2e/run-comparison.spec.ts`；扩充前述 SQLite HTTP 测试；更新 README、PROJECT_STATUS、新增实际日期的验收 MD；保存实际构建截图 `docs/screenshots/sectorpulse-run-comparison.png`。

**Interfaces:** HTTP 仍为设计四个 GET，不增加为验收专用的生产写接口。浏览器用已有 `web/e2e/fixtures.ts` 的请求泄漏防护；API 实库测试直接用 test storage 种子，不通过真实 Provider 获取数据。

- [ ] **1. 先加系统级红灯用例**。SQLite 和专用 PostgreSQL 分别创建固定fixture对：共同候选、单侧候选、缺失字段、元数据更新、旧运行无lineage、超过50历史。种子完成后，对涉及的业务表做稳定内容摘要，调用四个 GET 后再比较摘要，断言无变化。排除连接会话/测试日志等非业务状态，不允许用仅运行行数一致代替全部写入检查。

PostgreSQL 测试变量使用专用 `SECTOR_PULSE_TEST_DATABASE_URL`，若未配置则 skip 并显式登记未验收；建立连接后检查 `current_database()`，必须为 `sector_pulse_run_comparison_test`。此检查在 initialize/seed 前完成，不读取 `.env` 的业务 URL。已有专用测试库若名字不同，先核对并明确更新测试白名单，不靠名称含 test 的模糊判断。

```python
import os
import pytest
from sqlalchemy import text
from sector_pulse.storage.postgres import PostgresDatabase


@pytest.fixture
def comparison_postgres():
    url = os.environ.get("SECTOR_PULSE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires verified isolated comparison PostgreSQL database")
    database = PostgresDatabase(url)
    with database.start().connect() as connection:
        name = connection.execute(text("SELECT current_database()" )).scalar_one()
    if name != "sector_pulse_run_comparison_test":
        database.close()
        pytest.fail("refusing to seed a non-comparison database")
    database.initialize()
    try:
        yield database
    finally:
        database.close()
```

上述 fixture 已在 Task 2 放入 `backend/tests/comparison_support.py`，本任务导入复用，不创建第二套守卫。不要在 fixture 中添加 TRUNCATE 或 DROP；种子使用本轮可追踪 UUID。需要清理专用测试库时另核对确切对象与恢复方式。所有新增 PostgreSQL 测试模块标记 `pytestmark = pytest.mark.postgres`。

- [ ] **2. 写真实浏览器断言并先运行确认存在失败/覆盖缺口**。使用有两个运行及55条历史的拦截fixture，覆盖刷新、前进/返回、交换、第二页选择、news分页、错误恢复、dialog Esc/焦点返回以及旧响应延迟。新增页面 fixture 只允许 GET，未处理的请求必须失败；不得落到用户本地后端。

```typescript
import { test, expect } from './fixtures'

test('comparison keeps the shared navigation active', async ({ page }) => {
  await page.goto('/runs/compare')
  await expect(page.getByRole('heading', { name: '运行对比', exact: true })).toBeVisible()
  await expect(page.locator('a[aria-current="page"]').filter({ hasText: '分析运行' })).toBeVisible()
  await expect(page.getByRole('button', { name: '开始对比', exact: true })).toBeDisabled()
})
```

该用例不打开选择器、不请求新比较接口；其他用例在 page.route 中完整覆盖新 GET 返回。浏览器请求断言另记录所有方法，确认没有触发采集、写作、重试或其它 POST/PUT/DELETE。

- [ ] **3. 修复门槛发现的问题，再运行全套验证**。以下逐条命令记录真实 exit code、通过/跳过/排除数量；不把历史343/185等数量复制为本轮结果：

```powershell
python -m pytest backend/tests -m "not live and not live_llm and not postgres" -q
python -m ruff check backend/src backend/tests
python -m mypy backend/src/sector_pulse
python -m pytest backend/tests/integration/test_postgres_comparison_run_listing.py backend/tests/integration/test_postgres_run_comparison_api.py -q
```

如果全量 lint 或 mypy 存在未触碰的基线问题，分别记录基线与新增结果，不用忽略规则掩盖差异；与新增功能直接相关的问题必须修复。专用 PostgreSQL 未通过时不宣称“双数据库完成验收”。

在 web 执行：

```powershell
npm test
npm run test:tooling
npm run build
npm run test:e2e
npm run test:e2e:dev
```

本轮不加 Live 标记、不开付费测试。E2E 启动的本地服务由现有 runner 收尾；不结束用户占用8000/9000端口的进程。4173被其他程序占用时先识别，不盲目杀进程。

- [ ] **4. 可视化与可用性验收**。使用 impeccable 的实现后检查流程和浏览器查看1440×900、1024×768、390×844；确认侧栏固定、内容独立滚动、文字不挤压、没有整页横溢、局部表格滚动清楚、焦点可见。键盘逐一检查选择器、tab、分页、展开及返回焦点；运行生产和开发模式，不能只看静态HTML。
- [ ] **5. 维护实际交付文档与截图**。README 新增“运行对比”使用路径与新闻元数据限制，截取生产构建中的fixture页面并标注示例数据，不伪装成真实行情；PROJECT_STATUS 把此小阶段更新为有证据的完成，不把整个Stage1标为完成。验收记录包括提交、环境、数据库身份（不含密码）、命令结果、只读摘要、浏览器截图、未做Live/影子/远端CI等边界。
- [ ] **6. 本地审查与提交**。检查 git diff、接口定义与 TS 一致性、没有 `.env`/缓存/测试库入库；使用 verification-before-completion 核对本轮证据。提交 `test: verify and document run comparison workflow`。功能分支交付后按用户后续明确请求处理合并或推送，不擅自改远端。

## 执行前自审记录

| 设计要求 | 对应任务 |
| --- | --- |
| 候选并集、kind身份、Decimal、空值与排名方向 | Task 1、3、5 |
| 历史超过50条、双数据库一致、终态列表 | Task 2、6 |
| 同来源/同场景、分类兼容、部分失败 | Task 3、4、6 |
| 新闻成员与可变元数据分离、缺失文档不丢行 | Task 1、3、5、6 |
| 四个只读接口、依赖装配、同步仓储 | Task 3、6 |
| 统一外壳、URL恢复、竞态、窄屏、键盘 | Task 4、5、6 |
| 不污染业务库、真实验收与文档 | Task 6 |

文档编制只进行了源码核对、契约对照与计划检查；上方任务及代码样例尚未执行。实现时若与最新仓库代码冲突，先核实差异并更新设计/计划，不以旧接口名称硬套。
