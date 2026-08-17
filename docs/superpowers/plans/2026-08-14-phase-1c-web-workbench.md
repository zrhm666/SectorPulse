# Phase 1C 基础 Web 工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Phase 1B 归因/成文管线之上交付一个只读 Web 工作台，支持手动触发运行、SSE 实时进度、运行历史列表、重点板块雷达、草稿查看（含版本对比与复制导出）、证据视图（含调用审计）和审核报告。

**Architecture:** FastAPI 单进程异步服务 + React/Vite SPA。管线通过可选 `ProgressSink` 发阶段事件，通过可选 `InvocationSink` 记录模型调用；Web 层用 `ProgressBus` 广播给 SSE 订阅者；新增 `phase1b_runs` 表记录运行元数据；只读端点直接读取 SQLite 已持久化的结构化产物。

**Tech Stack:** Python 3.12、FastAPI、uvicorn、Pydantic 2、asyncio、SQLite、React、TypeScript、Vite、EventSource。

## Global Constraints

- 市场范围固定为 A 股行业板块 + 概念板块。
- 每轮只生成一篇通用社区稿，不做平台专属稿，不接入自动发布。
- 正文约 1000～1800 字，通常选择 3～6 个重点板块。
- 归因等级固定为 `NO_RELIABLE_EXPLANATION < MARKET_ASSOCIATION < POSSIBLE_CATALYST < EXPLICIT_DRIVER`。
- API Key 只从环境变量读取，绝不回传前端、不写入日志或数据库。
- 默认绑定 127.0.0.1，单用户，Phase 1C 不做登录认证。
- 真实模型调用必须经过显式 `.live-llm-consent` 门禁，缺少配置时返回 409，不静默回退。
- 进度埋点与调用审计均通过可选回调注入，默认空实现保证现有 CLI 与测试零改动。
- 不引入 Redis / 消息队列 / 子进程。
- 变更先更新规格或计划，再修改实现。

---

## File Structure

### 新增后端文件

```
backend/src/sector_pulse/
  application/
    progress.py                 # ProgressSink 协议 + NoopProgressSink
    invocations.py              # InvocationSink + build_invocation 助手
  storage/
    migrations/
      004_phase1b_runs.sql      # phase1b_runs 表
    phase1b_runs_repository.py  # 运行元数据 CRUD
    news_evidence_repository.py # 事件→文档证据查询
  web/
    __init__.py
    app.py                      # FastAPI app factory, 静态托管, SPA fallback
    schemas.py                  # REST 响应模型
    run_service.py              # RunService: 创建/取消/查询
    progress_bus.py             # ProgressBus + SSE 订阅
    live_provider.py            # live Provider 工厂与 consent 校验
```

### 修改后端文件

```
backend/src/sector_pulse/application/phase1b_pipeline.py
  # 增加 progress_sink / invocation_sink 可选参数并保存 invocations

backend/src/sector_pulse/application/attribution_agents.py
  # 增加 progress_sink / invocation_sink 参数

backend/src/sector_pulse/application/editorial_agents.py
  # 增加 invocation_sink 参数

backend/src/sector_pulse/storage/phase1b_repository.py
  # 增加 get_contexts/get_gates/get_cards/get_outline/get_drafts/get_review

backend/src/sector_pulse/storage/agent_invocation_repository.py
  # 增加 list_for_run

backend/src/sector_pulse/config/llm_config.py
  # 增加 optional pricing 字段

config/llm.yaml
  # 增加 pricing 配置节
```

### 新增前端文件

```
web/
  package.json  tsconfig.json  vite.config.ts  index.html
  src/
    main.tsx  App.tsx  api.ts  useRuns.ts  styles.css
    components/
      Badge.tsx  Card.tsx  Tab.tsx  Table.tsx  Spinner.tsx  NewRunDialog.tsx
    pages/
      RunListPage.tsx  RunDetailPage.tsx
      tabs/OverviewTab.tsx  RadarTab.tsx  DraftTab.tsx  EvidenceTab.tsx  ReviewTab.tsx
```

---

### Task 1: ProgressSink 协议与管线进度埋点

**Files:**
- Create: `backend/src/sector_pulse/application/progress.py`
- Modify: `backend/src/sector_pulse/application/phase1b_pipeline.py`
- Modify: `backend/src/sector_pulse/application/attribution_agents.py`
- Test: `backend/tests/unit/application/test_progress.py`
- Test: `backend/tests/integration/test_phase1b_pipeline_progress.py`

**Interfaces:**
- Produces: `ProgressSink`（`emit(stage: str, detail: dict) -> None`）
- Produces: `NoopProgressSink`
- Produces: `run_phase1b_pipeline(deps, request, progress_sink=NoopProgressSink())`
- Produces: `run_attribution_agents(contexts, gates, llm, prompt, concurrency, progress_sink=None)`

- [ ] **Step 1: Create progress.py**

```python
# backend/src/sector_pulse/application/progress.py
from typing import Protocol


class ProgressSink(Protocol):
    """管线进度事件接收器，只通报阶段事实，不感知 Web/SSE。"""

    def emit(self, stage: str, detail: dict) -> None: ...


class NoopProgressSink:
    """默认空实现，保证现有调用方零改动。"""

    def emit(self, stage: str, detail: dict) -> None:
        pass
```

- [ ] **Step 2: Write unit test**

```python
# backend/tests/unit/application/test_progress.py
from sector_pulse.application.progress import NoopProgressSink


def test_noop_sink_does_not_raise() -> None:
    NoopProgressSink().emit("phase1b.start", {"run_id": "1"})
```

- [ ] **Step 3: Run test**

Run: `pytest backend/tests/unit/application/test_progress.py -v`
Expected: PASS

- [ ] **Step 4: Modify run_attribution_agents to accept progress_sink**

在 `attribution_agents.py` 中：

```python
from sector_pulse.application.progress import NoopProgressSink, ProgressSink

async def run_attribution_agents(
    contexts: tuple[AttributionContext, ...],
    gates: dict[str, AttributionGateResult],
    llm: LLMPort,
    prompt: Any,
    concurrency: int = 4,
    progress_sink: ProgressSink | None = None,
) -> tuple[AttributionAgentResult, ...]:
    sink = progress_sink or NoopProgressSink()
    semaphore = asyncio.Semaphore(concurrency)
    total = len(contexts)
    completed = 0

    async def run_one(context: AttributionContext) -> AttributionAgentResult:
        nonlocal completed
        gate = gates[context.sector_id]
        async with semaphore:
            request = LLMRequest[SectorAnalysisCard](
                agent_name="attribution",
                model="fixture",
                prompt_id=getattr(prompt, "prompt_id", "attribution"),
                prompt_version=getattr(prompt, "version", "1"),
                system_prompt=getattr(prompt, "system", ""),
                user_payload=context.model_dump(mode="json"),
                response_model=SectorAnalysisCard,
                fixture_key=f"sector-analysis:{context.sector_id}",
            )
            result = await llm.generate_structured(request)
            if result.status is LLMStatus.SUCCESS and result.data is not None:
                try:
                    value: AttributionAgentResult = AttributionAgentResult(
                        validate_analysis_card(result.data, gate, context)
                    )
                except ValueError as exc:
                    value = _fallback(context, gate, type(exc).__name__)
            else:
                value = _fallback(
                    context, gate, result.error.code if result.error else "AGENT_FAILED"
                )
        completed += 1
        sink.emit(
            "attribution.progress",
            {"done": completed, "total": total, "sector_id": context.sector_id},
        )
        return value

    return tuple(await asyncio.gather(*(run_one(context) for context in contexts)))
```

- [ ] **Step 5: Modify run_phase1b_pipeline to emit stage events**

在 `phase1b_pipeline.py` 中：

```python
from sector_pulse.application.progress import NoopProgressSink, ProgressSink

async def run_phase1b_pipeline(
    dependencies: Phase1BDependencies,
    request: Phase1BRequest,
    progress_sink: ProgressSink = NoopProgressSink(),
) -> Phase1BRunResult:
    started = time.perf_counter()
    progress_sink.emit("phase1b.start", {"run_id": str(request.run_id)})
    if len(request.contexts) < 3:
        return Phase1BRunResult(
            status=PipelineStatus.ATTRIBUTION_BLOCKED,
            analysis_cards=(),
            outline=None,
            draft=None,
            review=None,
            total_cost_cny=MoneyCny(amount=Decimal("0")),
            elapsed_ms=0,
        )
    prompt_attribution = dependencies.prompts.get("attribution")
    progress_sink.emit("attribution.start", {"total": len(request.contexts)})
    agent_results = await run_attribution_agents(
        request.contexts,
        request.gates,
        dependencies.llm,
        prompt_attribution,
        dependencies.config.max_attribution_concurrency,
        progress_sink=progress_sink,
    )
    cards = tuple(result.card for result in agent_results)
    dependencies.repository.save_contexts(request.contexts)
    dependencies.repository.save_gate_results(tuple(request.gates.values()))
    dependencies.repository.save_cards(cards)
    progress_sink.emit("attribution.done", {"cards": len(cards)})
    outline = await run_editorial_agent(
        cards, dependencies.llm, dependencies.prompts.get("editorial")
    )
    dependencies.repository.save_outline(outline)
    progress_sink.emit("editorial.done", {"sector_ids": list(outline.sector_ids)})
    cards_by_id = {card.sector_id: card for card in cards}
    draft = await run_writing_agent(
        outline, cards_by_id, dependencies.llm, dependencies.prompts.get("writing")
    )
    progress_sink.emit("writing.done", {"version": draft.version if draft else None})
    # ... 其余代码保持不变；在每次 review 完成后（含返工循环内）追加：
    progress_sink.emit(
        "review.done",
        {"decision": review.decision.value if review else None},
    )
```

- [ ] **Step 6: Write integration test verifying event order**

```python
# backend/tests/integration/test_phase1b_pipeline_progress.py
import asyncio
from datetime import UTC, datetime

from sector_pulse.application.phase1b_pipeline import Phase1BRequest, run_phase1b_pipeline

from backend.tests.integration.test_phase1b_pipeline import (
    RUN_ID,
    contexts,
    dependencies,
    gate,
)


class ListSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, stage: str, detail: dict) -> None:
        self.events.append((stage, detail))


def test_pipeline_emits_progress_events_in_order(tmp_path) -> None:
    sink = ListSink()
    deps = dependencies(tmp_path)
    result = asyncio.run(
        run_phase1b_pipeline(
            deps,
            Phase1BRequest(
                run_id=RUN_ID,
                requested_at=datetime(2026, 8, 14, 3, tzinfo=UTC),
                contexts=contexts(),
                gates={c.sector_id: gate(c) for c in contexts()},
            ),
            progress_sink=sink,
        )
    )
    assert result.status == "READY_FOR_HUMAN_REVIEW"
    stages = [s for s, _ in sink.events]
    assert stages[0] == "phase1b.start"
    assert stages[1] == "attribution.start"
    assert "attribution.progress" in stages
    assert "attribution.done" in stages
    assert "editorial.done" in stages
    assert "writing.done" in stages
    assert "review.done" in stages
```

- [ ] **Step 7: Run new integration test**

Run: `pytest backend/tests/integration/test_phase1b_pipeline_progress.py -v`
Expected: PASS

- [ ] **Step 8: Run full Phase 1B suite to confirm no regression**

Run: `pytest backend/tests -k "phase1b or attribution or editorial" -q`
Expected: All PASS

---

### Task 2: 调用审计记录（InvocationSink）

**Files:**
- Create: `backend/src/sector_pulse/application/invocations.py`
- Modify: `backend/src/sector_pulse/application/attribution_agents.py`
- Modify: `backend/src/sector_pulse/application/editorial_agents.py`
- Modify: `backend/src/sector_pulse/application/phase1b_pipeline.py`
- Modify: `backend/src/sector_pulse/storage/agent_invocation_repository.py`
- Test: `backend/tests/unit/application/test_invocations.py`
- Test: `backend/tests/integration/test_phase1b_pipeline_progress.py`（追加断言）

**Interfaces:**
- Produces: `InvocationSink = Callable[[AgentInvocation], None]`
- Produces: `noop_invocation_sink(invocation) -> None`
- Produces: `build_invocation(run_id, stage, request, result, provider_id) -> AgentInvocation`
- Produces: `SQLiteAgentInvocationRepository.list_for_run(run_id) -> list[AgentInvocation]`

- [ ] **Step 1: Create invocations.py**

```python
# backend/src/sector_pulse/application/invocations.py
import hashlib
import json
from collections.abc import Callable
from uuid import UUID, uuid4

from sector_pulse.domain.llm import AgentInvocation, LLMRequest, LLMResult

InvocationSink = Callable[[AgentInvocation], None]


def noop_invocation_sink(invocation: AgentInvocation) -> None:
    pass


def build_invocation(
    run_id: UUID,
    stage: str,
    request: LLMRequest,
    result: LLMResult,
    provider_id: str,
) -> AgentInvocation:
    input_hash = hashlib.sha256(
        json.dumps(request.user_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return AgentInvocation(
        invocation_id=uuid4(),
        run_id=run_id,
        stage=stage,
        provider_id=provider_id,
        model=request.model,
        prompt_id=request.prompt_id,
        prompt_version=request.prompt_version,
        input_hash=input_hash,
        status=result.status,
        usage=result.usage,
        estimated_cost_cny=result.estimated_cost_cny,
        error_code=result.error.code if result.error else None,
    )
```

- [ ] **Step 2: Write unit test**

```python
# backend/tests/unit/application/test_invocations.py
from decimal import Decimal
from uuid import UUID

from sector_pulse.application.invocations import build_invocation
from sector_pulse.domain.attribution import SectorAnalysisCard
from sector_pulse.domain.evidence import EvidenceLevel
from sector_pulse.domain.llm import LLMRequest, LLMResult, LLMStatus, MoneyCny, TokenUsage
from sector_pulse.domain.market import SectorKind

RUN_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_build_invocation_roundtrip() -> None:
    card = SectorAnalysisCard(
        run_id=RUN_ID,
        sector_id="industry-1",
        sector_kind=SectorKind.INDUSTRY,
        allowed_max_level=EvidenceLevel.NO_RELIABLE_EXPLANATION,
        attribution_level=EvidenceLevel.NO_RELIABLE_EXPLANATION,
        confidence=Decimal("0"),
        conclusion="暂无可靠解释",
        supporting_evidence_ids=(),
        counter_evidence=(),
        uncertainties=(),
        background_event_ids=(),
        claims=(),
        forbidden_inferences=(),
    )
    request = LLMRequest[SectorAnalysisCard](
        agent_name="attribution",
        model="fixture",
        prompt_id="attribution",
        prompt_version="1",
        system_prompt="sys",
        user_payload={"sector_id": "industry-1"},
        response_model=SectorAnalysisCard,
        fixture_key="x",
    )
    result = LLMResult[SectorAnalysisCard](
        status=LLMStatus.SUCCESS,
        data=card,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        estimated_cost_cny=MoneyCny(amount=Decimal("0.01")),
    )
    invocation = build_invocation(RUN_ID, "attribution", request, result, "fixture")
    assert invocation.run_id == RUN_ID
    assert invocation.stage == "attribution"
    assert invocation.usage.total_tokens == 15
    assert invocation.estimated_cost_cny.amount == Decimal("0.01")
```

- [ ] **Step 3: Run test**

Run: `pytest backend/tests/unit/application/test_invocations.py -v`
Expected: PASS

- [ ] **Step 4: Add invocation_sink to attribution_agents.py**

在 `run_attribution_agents` 中增加参数，并在每次 `generate_structured` 之后、`completed += 1` 之前记录：

```python
from sector_pulse.application.invocations import (
    InvocationSink,
    build_invocation,
    noop_invocation_sink,
)

async def run_attribution_agents(
    contexts: tuple[AttributionContext, ...],
    gates: dict[str, AttributionGateResult],
    llm: LLMPort,
    prompt: Any,
    concurrency: int = 4,
    progress_sink: ProgressSink | None = None,
    invocation_sink: InvocationSink = noop_invocation_sink,
) -> tuple[AttributionAgentResult, ...]:
    # 在 generate_structured 之后：
    provider_id = getattr(llm, "provider_id", "unknown")
    invocation_sink(
        build_invocation(context.run_id, "attribution", request, result, provider_id)
    )
```

- [ ] **Step 5: Add invocation_sink to editorial_agents.py**

三个函数各增加 `invocation_sink: InvocationSink = noop_invocation_sink` 参数，并在各自 `generate_structured` 后记录，stage 分别为 `"editorial"`、`"writing"`、`"review"`。示例（`run_review_agent`）：

```python
async def run_review_agent(
    draft: ArticleDraft,
    cards: Mapping[str, SectorAnalysisCard],
    llm: LLMPort,
    prompt: Any,
    invocation_sink: InvocationSink = noop_invocation_sink,
) -> ReviewReport | None:
    request = LLMRequest[ReviewReport](
        agent_name="review",
        model="fixture-review",
        prompt_id=getattr(prompt, "prompt_id", "review"),
        prompt_version=getattr(prompt, "version", "1"),
        system_prompt=getattr(prompt, "system", ""),
        user_payload={"draft": draft.model_dump(mode="json"), "cards": {
            key: value.model_dump(mode="json") for key, value in cards.items()
        }},
        response_model=ReviewReport,
        fixture_key=f"review:{draft.version}",
    )
    result = await llm.generate_structured(request)
    invocation_sink(
        build_invocation(
            draft.run_id,
            "review",
            request,
            result,
            getattr(llm, "provider_id", "unknown"),
        )
    )
    return result.data if result.status is LLMStatus.SUCCESS else None
```

- [ ] **Step 6: Wire invocation saving in the pipeline**

在 `run_phase1b_pipeline` 中：

```python
from sector_pulse.application.invocations import InvocationSink
from sector_pulse.domain.llm import AgentInvocation

async def run_phase1b_pipeline(
    dependencies: Phase1BDependencies,
    request: Phase1BRequest,
    progress_sink: ProgressSink = NoopProgressSink(),
    invocation_sink: InvocationSink | None = None,
) -> Phase1BRunResult:
    collected: list[AgentInvocation] = []

    def record(invocation: AgentInvocation) -> None:
        collected.append(invocation)

    active_invocation_sink = invocation_sink or record

    def save_invocations() -> None:
        if collected:
            dependencies.invocation_repository.save(tuple(collected))

    # 将 active_invocation_sink 传给所有 agent 调用
    # 在每个 return 分支之前调用 save_invocations()
```

注意：所有 return 分支（约 8 处）都需要在返回前调用 `save_invocations()`，保证即便中途失败也落库。

- [ ] **Step 7: Add list_for_run to agent_invocation_repository.py**

```python
from decimal import Decimal
from uuid import UUID

from sector_pulse.domain.llm import (
    AgentInvocation,
    LLMStatus,
    MoneyCny,
    TokenUsage,
)

    def list_for_run(self, run_id: UUID) -> list[AgentInvocation]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """SELECT invocation_id, run_id, stage, provider_id, model, prompt_id,
                   prompt_version, input_hash, output_hash, status,
                   prompt_tokens, completion_tokens, total_tokens,
                   estimated_cost_cny, error_code
                   FROM agent_invocations WHERE run_id = ? ORDER BY rowid""",
                (str(run_id),),
            ).fetchall()
        return [
            AgentInvocation(
                invocation_id=UUID(r[0]),
                run_id=UUID(r[1]),
                stage=r[2],
                provider_id=r[3],
                model=r[4],
                prompt_id=r[5],
                prompt_version=r[6],
                input_hash=r[7],
                output_hash=r[8],
                status=LLMStatus(r[9]),
                usage=TokenUsage(
                    prompt_tokens=r[10], completion_tokens=r[11], total_tokens=r[12]
                ),
                estimated_cost_cny=MoneyCny(amount=Decimal(r[13])),
                error_code=r[14],
            )
            for r in rows
        ]
```

- [ ] **Step 8: Extend integration test to assert invocations recorded**

在 `test_phase1b_pipeline_progress.py` 中追加：

```python
def test_pipeline_records_invocations(tmp_path) -> None:
    deps = dependencies(tmp_path)
    asyncio.run(
        run_phase1b_pipeline(
            deps,
            Phase1BRequest(
                run_id=RUN_ID,
                requested_at=datetime(2026, 8, 14, 3, tzinfo=UTC),
                contexts=contexts(),
                gates={c.sector_id: gate(c) for c in contexts()},
            ),
        )
    )
    invocations = deps.invocation_repository.list_for_run(RUN_ID)
    stages = {inv.stage for inv in invocations}
    assert {"attribution", "editorial", "writing", "review"} <= stages
```

- [ ] **Step 9: Run tests**

Run: `pytest backend/tests/unit/application/test_invocations.py backend/tests/integration/test_phase1b_pipeline_progress.py -v`
Expected: PASS

---

### Task 3: phase1b_runs 表与 Repository

**Files:**
- Create: `backend/src/sector_pulse/storage/migrations/004_phase1b_runs.sql`
- Create: `backend/src/sector_pulse/storage/phase1b_runs_repository.py`
- Test: `backend/tests/unit/storage/test_phase1b_runs_repository.py`

**Interfaces:**
- Produces: `Phase1BRunRow` dataclass 与 `SQLitePhase1BRunsRepository(database)`，方法 `insert`、`update_status`、`list_runs(limit=50)`、`get_run`

- [ ] **Step 1: Create migration 004**

```sql
-- backend/src/sector_pulse/storage/migrations/004_phase1b_runs.sql
CREATE TABLE IF NOT EXISTS phase1b_runs (
  run_id TEXT PRIMARY KEY,
  requested_at TEXT NOT NULL,
  provider TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN (
    'RUNNING', 'READY_FOR_HUMAN_REVIEW', 'REVISE_REQUIRED',
    'UNREVIEWED', 'BUDGET_EXCEEDED', 'ATTRIBUTION_BLOCKED',
    'DRAFT_GENERATION_FAILED', 'FAILED', 'CANCELLED'
  )),
  elapsed_ms INTEGER,
  total_cost_cny TEXT,
  input_json_hash TEXT,
  draft_id TEXT,
  error_message TEXT,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_phase1b_runs_requested_at
  ON phase1b_runs(requested_at DESC);
```

- [ ] **Step 2: Create phase1b_runs_repository.py**

```python
# backend/src/sector_pulse/storage/phase1b_runs_repository.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sector_pulse.storage.sqlite import SQLiteDatabase


@dataclass
class Phase1BRunRow:
    run_id: UUID
    requested_at: datetime
    provider: str
    status: str
    elapsed_ms: int | None = None
    total_cost_cny: str | None = None
    input_json_hash: str | None = None
    draft_id: UUID | None = None
    error_message: str | None = None
    finished_at: datetime | None = None


class SQLitePhase1BRunsRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def insert(self, run: Phase1BRunRow) -> None:
        with self._database.transaction() as conn:
            conn.execute(
                """INSERT INTO phase1b_runs
                (run_id, requested_at, provider, status, elapsed_ms, total_cost_cny,
                 input_json_hash, draft_id, error_message, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(run.run_id),
                    run.requested_at.isoformat(),
                    run.provider,
                    run.status,
                    run.elapsed_ms,
                    run.total_cost_cny,
                    run.input_json_hash,
                    str(run.draft_id) if run.draft_id else None,
                    run.error_message,
                    run.finished_at.isoformat() if run.finished_at else None,
                ),
            )

    def update_status(
        self,
        run_id: UUID,
        status: str,
        elapsed_ms: int | None = None,
        total_cost_cny: str | None = None,
        draft_id: UUID | None = None,
        error_message: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        with self._database.transaction() as conn:
            conn.execute(
                """UPDATE phase1b_runs
                SET status = ?, elapsed_ms = ?, total_cost_cny = ?, draft_id = ?,
                    error_message = ?, finished_at = ?
                WHERE run_id = ?""",
                (
                    status,
                    elapsed_ms,
                    total_cost_cny,
                    str(draft_id) if draft_id else None,
                    error_message,
                    finished_at.isoformat() if finished_at else None,
                    str(run_id),
                ),
            )

    def list_runs(self, limit: int = 50) -> list[Phase1BRunRow]:
        with self._database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM phase1b_runs ORDER BY requested_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_run(self, run_id: UUID) -> Phase1BRunRow | None:
        with self._database.connection() as conn:
            row = conn.execute(
                "SELECT * FROM phase1b_runs WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
        return self._row_to_model(row) if row else None

    @staticmethod
    def _row_to_model(row: object) -> Phase1BRunRow:
        r = tuple(row)  # type: ignore[arg-type]
        return Phase1BRunRow(
            run_id=UUID(r[0]),
            requested_at=datetime.fromisoformat(r[1]),
            provider=r[2],
            status=r[3],
            elapsed_ms=r[4],
            total_cost_cny=r[5],
            input_json_hash=r[6],
            draft_id=UUID(r[7]) if r[7] else None,
            error_message=r[8],
            finished_at=datetime.fromisoformat(r[9]) if r[9] else None,
        )
```

- [ ] **Step 3: Write unit tests**

```python
# backend/tests/unit/storage/test_phase1b_runs_repository.py
from datetime import UTC, datetime
from uuid import uuid4

from sector_pulse.storage.phase1b_runs_repository import (
    Phase1BRunRow,
    SQLitePhase1BRunsRepository,
)
from sector_pulse.storage.sqlite import SQLiteDatabase


def test_insert_list_and_update(tmp_path) -> None:
    db = SQLiteDatabase(tmp_path / "test.db")
    repo = SQLitePhase1BRunsRepository(db)
    run_id = uuid4()
    repo.insert(
        Phase1BRunRow(
            run_id=run_id,
            requested_at=datetime(2026, 8, 14, 12, tzinfo=UTC),
            provider="fixture",
            status="RUNNING",
        )
    )
    draft_id = uuid4()
    repo.update_status(
        run_id,
        status="READY_FOR_HUMAN_REVIEW",
        elapsed_ms=500,
        total_cost_cny="0",
        draft_id=draft_id,
        finished_at=datetime(2026, 8, 14, 12, 1, tzinfo=UTC),
    )
    run = repo.get_run(run_id)
    assert run is not None
    assert run.status == "READY_FOR_HUMAN_REVIEW"
    assert run.elapsed_ms == 500
    assert run.draft_id == draft_id
    listed = repo.list_runs()
    assert len(listed) == 1
    assert listed[0].run_id == run_id
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/unit/storage/test_phase1b_runs_repository.py -v`
Expected: PASS

---

### Task 4: 只读查询方法（雷达/草稿/证据/审核数据源）

**Files:**
- Modify: `backend/src/sector_pulse/storage/phase1b_repository.py`
- Create: `backend/src/sector_pulse/storage/news_evidence_repository.py`
- Test: `backend/tests/unit/storage/test_phase1b_query.py`
- Test: `backend/tests/unit/storage/test_news_evidence_repository.py`

**Interfaces:**
- Produces: `SQLitePhase1BRepository.get_contexts/get_gates/get_cards/get_outline/get_drafts/get_review`
- Produces: `SQLiteNewsEvidenceRepository.get_events(event_ids) -> tuple[NewsEvidenceItem, ...]`

- [ ] **Step 1: Add query methods to phase1b_repository.py**

```python
# 追加到 SQLitePhase1BRepository
    def _payloads_for(self, table: str, order_column: str, run_id: UUID) -> tuple[str, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {table} WHERE run_id = ? ORDER BY {order_column}",
                (str(run_id),),
            ).fetchall()
        return tuple(row[0] for row in rows)

    def get_contexts(self, run_id: UUID) -> tuple[AttributionContext, ...]:
        return tuple(
            AttributionContext.model_validate_json(p)
            for p in self._payloads_for("attribution_contexts", "sector_id", run_id)
        )

    def get_gates(self, run_id: UUID) -> tuple[AttributionGateResult, ...]:
        return tuple(
            AttributionGateResult.model_validate_json(p)
            for p in self._payloads_for("attribution_gate_results", "sector_id", run_id)
        )

    def get_cards(self, run_id: UUID) -> tuple[SectorAnalysisCard, ...]:
        return tuple(
            SectorAnalysisCard.model_validate_json(p)
            for p in self._payloads_for("sector_analysis_cards", "sector_id", run_id)
        )

    def get_outline(self, run_id: UUID) -> ArticleOutline | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM article_outlines WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
        return ArticleOutline.model_validate_json(row[0]) if row else None

    def get_drafts(self, run_id: UUID) -> tuple[ArticleDraft, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM article_drafts WHERE run_id = ? ORDER BY version",
                (str(run_id),),
            ).fetchall()
        return tuple(ArticleDraft.model_validate_json(row[0]) for row in rows)

    def get_review(self, run_id: UUID) -> ReviewReport | None:
        with self._database.connection() as connection:
            row = connection.execute(
                """SELECT rr.payload_json FROM review_reports rr
                   JOIN article_drafts ad ON ad.draft_id = rr.draft_id
                   AND ad.version = rr.draft_version
                   WHERE ad.run_id = ? ORDER BY rr.draft_version DESC LIMIT 1""",
                (str(run_id),),
            ).fetchone()
        return ReviewReport.model_validate_json(row[0]) if row else None
```

`_payloads_for` 中的 `{table}`、`{order_column}` 只允许来自本类内固定字符串（`attribution_contexts`、`attribution_gate_results`、`sector_analysis_cards` 与 `sector_id`），不得接收外部输入（防注入）。

- [ ] **Step 2: Create news_evidence_repository.py**

```python
# backend/src/sector_pulse/storage/news_evidence_repository.py
from dataclasses import dataclass
from typing import Any

from sector_pulse.storage.sqlite import SQLiteDatabase


@dataclass(frozen=True)
class NewsEvidenceItem:
    event_id: str
    canonical_title: str
    first_published_at: str | None
    documents: tuple[dict[str, Any], ...]


class SQLiteNewsEvidenceRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def get_events(self, event_ids: tuple[str, ...]) -> tuple[NewsEvidenceItem, ...]:
        if not event_ids:
            return ()
        placeholders = ",".join("?" for _ in event_ids)
        with self._database.connection() as conn:
            event_rows = conn.execute(
                f"""SELECT event_id, canonical_title, first_published_at
                    FROM news_events WHERE event_id IN ({placeholders})""",
                tuple(event_ids),
            ).fetchall()
            items: list[NewsEvidenceItem] = []
            for eid, title, published_at in event_rows:
                doc_rows = conn.execute(
                    """SELECT nd.title, nd.citation_url, nd.publisher,
                              nd.published_at, nd.source_grade
                       FROM news_documents nd
                       JOIN news_event_documents ned ON ned.document_id = nd.document_id
                       WHERE ned.event_id = ?""",
                    (eid,),
                ).fetchall()
                items.append(
                    NewsEvidenceItem(
                        event_id=eid,
                        canonical_title=title,
                        first_published_at=published_at,
                        documents=tuple(
                            {
                                "title": d[0],
                                "citation_url": d[1],
                                "publisher": d[2],
                                "published_at": d[3],
                                "source_grade": d[4],
                            }
                            for d in doc_rows
                        ),
                    )
                )
        return tuple(items)
```

- [ ] **Step 3: Write tests**

```python
# backend/tests/unit/storage/test_phase1b_query.py
import asyncio
from datetime import UTC, datetime

from sector_pulse.application.phase1b_pipeline import Phase1BRequest, run_phase1b_pipeline

from backend.tests.integration.test_phase1b_pipeline import (
    RUN_ID,
    contexts,
    dependencies,
    gate,
)


def test_query_methods_after_run(tmp_path) -> None:
    deps = dependencies(tmp_path)
    asyncio.run(
        run_phase1b_pipeline(
            deps,
            Phase1BRequest(
                run_id=RUN_ID,
                requested_at=datetime(2026, 8, 14, 3, tzinfo=UTC),
                contexts=contexts(),
                gates={c.sector_id: gate(c) for c in contexts()},
            ),
        )
    )
    repo = deps.repository
    assert len(repo.get_contexts(RUN_ID)) == 8
    assert len(repo.get_gates(RUN_ID)) == 8
    assert len(repo.get_cards(RUN_ID)) == 8
    assert repo.get_outline(RUN_ID) is not None
    assert len(repo.get_drafts(RUN_ID)) >= 2
    assert repo.get_review(RUN_ID) is not None
```

```python
# backend/tests/unit/storage/test_news_evidence_repository.py
from sector_pulse.storage.news_evidence_repository import SQLiteNewsEvidenceRepository
from sector_pulse.storage.sqlite import SQLiteDatabase


def test_get_events_empty(tmp_path) -> None:
    repo = SQLiteNewsEvidenceRepository(SQLiteDatabase(tmp_path / "t.db"))
    assert repo.get_events(()) == ()
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/unit/storage/test_phase1b_query.py backend/tests/unit/storage/test_news_evidence_repository.py -v`
Expected: PASS

---

### Task 5: ProgressBus 与 SSE 订阅

**Files:**
- Create: `backend/src/sector_pulse/web/__init__.py`
- Create: `backend/src/sector_pulse/web/progress_bus.py`
- Test: `backend/tests/unit/web/test_progress_bus.py`

**Interfaces:**
- Produces: `ProgressBus.subscribe(run_id) -> AsyncIterator[dict]`
- Produces: `ProgressBus.emit(run_id, event)`、`ProgressBus.close(run_id)`

- [ ] **Step 1: Create progress_bus.py**

```python
# backend/src/sector_pulse/web/progress_bus.py
import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from uuid import UUID


class ProgressBus:
    """进程内进度事件总线，支持 SSE 订阅与完成后回放。"""

    def __init__(self) -> None:
        self._queues: dict[UUID, list[asyncio.Queue[dict | None]]] = defaultdict(list)
        self._buffers: dict[UUID, list[dict]] = defaultdict(list)

    async def subscribe(self, run_id: UUID) -> AsyncIterator[dict]:
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._queues[run_id].append(queue)
        for event in self._buffers.get(run_id, []):
            await queue.put(event)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._queues[run_id].remove(queue)

    def emit(self, run_id: UUID, event: dict) -> None:
        self._buffers[run_id].append(event)
        for queue in self._queues.get(run_id, []):
            queue.put_nowait(event)

    def close(self, run_id: UUID) -> None:
        for queue in self._queues.get(run_id, []):
            queue.put_nowait(None)
```

- [ ] **Step 2: Write unit test**

```python
# backend/tests/unit/web/test_progress_bus.py
import asyncio
from uuid import uuid4

from sector_pulse.web.progress_bus import ProgressBus


def test_emit_and_subscribe() -> None:
    bus = ProgressBus()
    run_id = uuid4()
    received: list[dict] = []

    async def main() -> None:
        async def subscriber() -> None:
            async for event in bus.subscribe(run_id):
                received.append(event)

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0)
        bus.emit(run_id, {"type": "progress", "stage": "start"})
        bus.emit(run_id, {"type": "done"})
        bus.close(run_id)
        await task

    asyncio.run(main())
    assert received == [
        {"type": "progress", "stage": "start"},
        {"type": "done"},
    ]
```

- [ ] **Step 3: Run test**

Run: `pytest backend/tests/unit/web/test_progress_bus.py -v`
Expected: PASS

---

### Task 6: FastAPI 骨架与 Schemas

**Files:**
- Create: `backend/src/sector_pulse/web/schemas.py`
- Create: `backend/src/sector_pulse/web/app.py`
- Test: `backend/tests/unit/web/test_app.py`

**Interfaces:**
- Produces: `create_app(database_path, static_dir=None, overrides=None) -> FastAPI`
- Produces: `NewRunRequest`, `NewRunResponse`, `RunSummary`, `RunDetail`, `RadarResponse`, `DraftResponse`, `EvidenceResponse`, `ReviewResponse`

- [ ] **Step 1: Create schemas.py**

```python
# backend/src/sector_pulse/web/schemas.py
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class NewRunRequest(BaseModel):
    input_json: dict[str, Any]
    provider: str = "fixture"


class NewRunResponse(BaseModel):
    run_id: UUID


class RunSummary(BaseModel):
    run_id: UUID
    requested_at: datetime
    provider: str
    status: str
    elapsed_ms: int | None
    total_cost_cny: str | None
    draft_id: UUID | None


class RunDetail(RunSummary):
    input_json_hash: str | None
    error_message: str | None
    sector_count: int
    review_decision: str | None


class RadarCard(BaseModel):
    sector_id: str
    sector_kind: str
    attribution_level: str
    allowed_max_level: str
    confidence: str
    conclusion: str
    supporting_evidence_ids: list[str]
    counter_evidence: list[str]
    uncertainties: list[str]
    forbidden_inferences: list[str]
    claims: list[dict[str, Any]]


class RadarResponse(BaseModel):
    cards: list[RadarCard]


class DraftVersion(BaseModel):
    version: int
    status: str
    titles: list[str]
    introduction: str
    sections: list[dict[str, Any]]
    conclusion: str
    risk_notice: str
    sources: list[dict[str, Any]]
    character_count: int


class DraftResponse(BaseModel):
    versions: list[DraftVersion]


class EvidenceResponse(BaseModel):
    sectors: list[dict[str, Any]]
    events: list[dict[str, Any]]
    invocations: list[dict[str, Any]]


class ReviewResponse(BaseModel):
    decision: str | None
    revision_round: int | None
    issues: list[dict[str, Any]]
```

- [ ] **Step 2: Create app.py（骨架 + 健康检查 + 静态托管）**

```python
# backend/src/sector_pulse/web/app.py
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sector_pulse.storage.sqlite import SQLiteDatabase


def create_app(
    database_path: Path = Path("data/sector-pulse.db"),
    static_dir: Path | None = None,
) -> FastAPI:
    database = SQLiteDatabase(database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()
        yield

    app = FastAPI(title="SectorPulse Web", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    if static_dir is not None and static_dir.exists():
        assets = static_dir / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        async def spa_index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

        @app.get("/{path:path}")
        async def spa_fallback(path: str) -> FileResponse | dict:
            if path.startswith("api/"):
                return {"detail": "not found"}
            return FileResponse(static_dir / "index.html")

    return app
```

- [ ] **Step 3: Write test**

```python
# backend/tests/unit/web/test_app.py
from fastapi.testclient import TestClient

from sector_pulse.web.app import create_app


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 4: Run test**

Run: `pytest backend/tests/unit/web/test_app.py -v`
Expected: PASS

---

### Task 7: RunService（创建/取消/查询）

**Files:**
- Create: `backend/src/sector_pulse/web/run_service.py`
- Test: `backend/tests/unit/web/test_run_service.py`

**Interfaces:**
- Produces: `ProviderUnavailable(ValueError)`
- Produces: `RunService(runs_repo, phase1b_repo, invocation_repo, news_evidence, prompts, config, bus, fixture_responses, llm_factory)`
- Produces: `RunService.create_run(input_json, provider) -> UUID`
- Produces: `RunService.cancel_run(run_id) -> bool`
- Produces: `RunService.list_runs(limit=50) -> list[RunSummary]`
- Produces: `RunService.get_run(run_id) -> RunDetail | None`

- [ ] **Step 1: Create run_service.py**

```python
# backend/src/sector_pulse/web/run_service.py
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sector_pulse.application.phase1b_pipeline import Phase1BRequest, run_phase1b_pipeline
from sector_pulse.application.progress import ProgressSink
from sector_pulse.config.llm_config import LLMRuntimeConfig
from sector_pulse.domain.llm import AgentInvocation
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.storage.agent_invocation_repository import SQLiteAgentInvocationRepository
from sector_pulse.storage.news_evidence_repository import SQLiteNewsEvidenceRepository
from sector_pulse.storage.phase1b_repository import SQLitePhase1BRepository
from sector_pulse.storage.phase1b_runs_repository import (
    Phase1BRunRow,
    SQLitePhase1BRunsRepository,
)
from sector_pulse.web.progress_bus import ProgressBus
from sector_pulse.web.schemas import RunDetail, RunSummary


class ProviderUnavailable(ValueError):
    pass


class RunService:
    def __init__(
        self,
        runs_repo: SQLitePhase1BRunsRepository,
        phase1b_repo: SQLitePhase1BRepository,
        invocation_repo: SQLiteAgentInvocationRepository,
        news_evidence: SQLiteNewsEvidenceRepository,
        prompts: PromptRegistry,
        config: LLMRuntimeConfig,
        bus: ProgressBus,
        fixture_responses: dict[str, object],
        llm_factory: dict[str, Any],
    ) -> None:
        self._runs_repo = runs_repo
        self._phase1b_repo = phase1b_repo
        self._invocation_repo = invocation_repo
        self._news_evidence = news_evidence
        self._prompts = prompts
        self._config = config
        self._bus = bus
        self._fixture_responses = fixture_responses
        self._llm_factory = llm_factory
        self._tasks: dict[UUID, asyncio.Task] = {}

    def create_run(self, input_json: dict[str, Any], provider: str) -> UUID:
        run_id = uuid4()
        request = Phase1BRequest.model_validate({"run_id": str(run_id), **input_json})
        input_hash = hashlib.sha256(
            json.dumps(input_json, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self._runs_repo.insert(
            Phase1BRunRow(
                run_id=run_id,
                requested_at=request.requested_at,
                provider=provider,
                status="RUNNING",
                input_json_hash=input_hash,
            )
        )

        class BridgeSink:
            def __init__(self, bus: ProgressBus, rid: UUID) -> None:
                self.bus = bus
                self.rid = rid

            def emit(self, stage: str, detail: dict) -> None:
                self.bus.emit(self.rid, {"type": "progress", "stage": stage, "detail": detail})

        bridge = BridgeSink(self._bus, run_id)
        self._tasks[run_id] = asyncio.create_task(
            self._execute(run_id, request, provider, bridge)
        )
        return run_id

    async def _execute(
        self,
        run_id: UUID,
        request: Phase1BRequest,
        provider: str,
        progress_sink: ProgressSink,
    ) -> None:
        invocations: list[AgentInvocation] = []

        def record(invocation: AgentInvocation) -> None:
            invocations.append(invocation)

        try:
            llm = self._build_llm(provider)
            deps = type(
                "WebDependencies",
                (),
                {
                    "llm": llm,
                    "prompts": self._prompts,
                    "repository": self._phase1b_repo,
                    "invocation_repository": self._invocation_repo,
                    "config": self._config,
                },
            )()
            result = await run_phase1b_pipeline(
                deps,
                request,
                progress_sink=progress_sink,
                invocation_sink=record,
            )
            self._runs_repo.update_status(
                run_id,
                status=result.status,
                elapsed_ms=result.elapsed_ms,
                total_cost_cny=str(result.total_cost_cny.amount),
                draft_id=result.draft.draft_id if result.draft else None,
                finished_at=datetime.now(UTC),
            )
            self._bus.emit(run_id, {"type": "done", "status": result.status})
        except asyncio.CancelledError:
            self._runs_repo.update_status(
                run_id, status="CANCELLED", finished_at=datetime.now(UTC)
            )
            self._bus.emit(run_id, {"type": "cancelled"})
        except ProviderUnavailable as exc:
            self._runs_repo.update_status(
                run_id, status="FAILED", error_message=str(exc), finished_at=datetime.now(UTC)
            )
            self._bus.emit(run_id, {"type": "error", "message": str(exc)})
        except Exception as exc:
            self._runs_repo.update_status(
                run_id, status="FAILED", error_message=str(exc), finished_at=datetime.now(UTC)
            )
            self._bus.emit(run_id, {"type": "error", "message": str(exc)})
        finally:
            if invocations:
                self._invocation_repo.save(invocations)
            self._bus.close(run_id)

    def _build_llm(self, provider: str) -> Any:
        if provider == "fixture":
            from sector_pulse.infrastructure.llm.fixture_provider import FixtureLLMProvider

            return FixtureLLMProvider(self._fixture_responses)
        factory = self._llm_factory.get(provider)
        if factory is None:
            raise ProviderUnavailable(f"unknown provider: {provider}")
        return factory()

    def cancel_run(self, run_id: UUID) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        return [
            RunSummary(
                run_id=r.run_id,
                requested_at=r.requested_at,
                provider=r.provider,
                status=r.status,
                elapsed_ms=r.elapsed_ms,
                total_cost_cny=r.total_cost_cny,
                draft_id=r.draft_id,
            )
            for r in self._runs_repo.list_runs(limit)
        ]

    def get_run(self, run_id: UUID) -> RunDetail | None:
        row = self._runs_repo.get_run(run_id)
        if row is None:
            return None
        cards = self._phase1b_repo.get_cards(run_id)
        review = self._phase1b_repo.get_review(run_id)
        return RunDetail(
            run_id=row.run_id,
            requested_at=row.requested_at,
            provider=row.provider,
            status=row.status,
            elapsed_ms=row.elapsed_ms,
            total_cost_cny=row.total_cost_cny,
            draft_id=row.draft_id,
            input_json_hash=row.input_json_hash,
            error_message=row.error_message,
            sector_count=len(cards),
            review_decision=review.decision.value if review else None,
        )
```

- [ ] **Step 2: Write unit test**

```python
# backend/tests/unit/web/test_run_service.py
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sector_pulse.config.llm_config import LLMRuntimeConfig
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.storage.agent_invocation_repository import SQLiteAgentInvocationRepository
from sector_pulse.storage.news_evidence_repository import SQLiteNewsEvidenceRepository
from sector_pulse.storage.phase1b_repository import SQLitePhase1BRepository
from sector_pulse.storage.phase1b_runs_repository import SQLitePhase1BRunsRepository
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.web.progress_bus import ProgressBus
from sector_pulse.web.run_service import RunService

from backend.tests.integration.test_phase1b_pipeline import contexts, gate, fixture_responses


def _service(tmp_path) -> RunService:
    db = SQLiteDatabase(tmp_path / "test.db")
    config = LLMRuntimeConfig(
        version="test",
        budget_cny_per_run=2,
        max_attribution_concurrency=4,
        max_revision_rounds=2,
        routes={},
    )
    return RunService(
        runs_repo=SQLitePhase1BRunsRepository(db),
        phase1b_repo=SQLitePhase1BRepository(db),
        invocation_repo=SQLiteAgentInvocationRepository(db),
        news_evidence=SQLiteNewsEvidenceRepository(db),
        prompts=PromptRegistry(Path("config/prompts")),
        config=config,
        bus=ProgressBus(),
        fixture_responses=fixture_responses(),
        llm_factory={},
    )


def _input_json() -> dict:
    return {
        "requested_at": datetime(2026, 8, 14, 12, tzinfo=UTC).isoformat(),
        "contexts": [c.model_dump(mode="json") for c in contexts()],
        "gates": {c.sector_id: gate(c).model_dump(mode="json") for c in contexts()},
    }


def test_create_run_lifecycle(tmp_path) -> None:
    svc = _service(tmp_path)
    run_id = svc.create_run(_input_json(), "fixture")
    detail = svc.get_run(run_id)
    assert detail is not None
    assert detail.status == "RUNNING"
    asyncio.run(asyncio.sleep(1.0))
    detail = svc.get_run(run_id)
    assert detail is not None
    assert detail.status == "READY_FOR_HUMAN_REVIEW"
    assert detail.sector_count == 8
```

- [ ] **Step 3: Run test**

Run: `pytest backend/tests/unit/web/test_run_service.py -v`
Expected: PASS

---

### Task 8: REST 端点 + SSE

**Files:**
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `backend/src/sector_pulse/web/run_service.py`（补充只读详情查询方法）
- Test: `backend/tests/integration/test_web_api.py`

**Interfaces:**
- Produces: `GET /api/runs`、`POST /api/runs`、`GET /api/runs/{run_id}`、`GET /api/runs/{run_id}/events`、`POST /api/runs/{run_id}/cancel`

- [ ] **Step 1: Add run_service read helpers**

在 `RunService` 中追加：

```python
    def get_radar(self, run_id: UUID) -> dict:
        cards = self._phase1b_repo.get_cards(run_id)
        gates = self._phase1b_repo.get_gates(run_id)
        gate_by_sector = {g.sector_id: g for g in gates}
        return {
            "cards": [
                {
                    "sector_id": c.sector_id,
                    "sector_kind": c.sector_kind.value,
                    "attribution_level": c.attribution_level.value,
                    "allowed_max_level": c.allowed_max_level.value,
                    "confidence": str(c.confidence),
                    "conclusion": c.conclusion,
                    "supporting_evidence_ids": list(c.supporting_evidence_ids),
                    "counter_evidence": list(c.counter_evidence),
                    "uncertainties": list(c.uncertainties),
                    "forbidden_inferences": list(c.forbidden_inferences),
                    "claims": [claim.model_dump(mode="json") for claim in c.claims],
                    "gate_reasons": list(
                        gate_by_sector[c.sector_id].reasons if c.sector_id in gate_by_sector else ()
                    ),
                }
                for c in cards
            ]
        }

    def get_draft(self, run_id: UUID) -> dict:
        drafts = self._phase1b_repo.get_drafts(run_id)
        return {
            "versions": [
                {
                    "version": d.version,
                    "status": d.status.value,
                    "titles": list(d.titles),
                    "introduction": d.introduction,
                    "sections": [s.model_dump(mode="json") for s in d.sections],
                    "conclusion": d.conclusion,
                    "risk_notice": d.risk_notice,
                    "sources": [s.model_dump(mode="json") for s in d.sources],
                    "character_count": d.character_count,
                }
                for d in drafts
            ]
        }

    def get_evidence(self, run_id: UUID) -> dict:
        contexts = self._phase1b_repo.get_contexts(run_id)
        cards = self._phase1b_repo.get_cards(run_id)
        invocations = self._invocation_repo.list_for_run(run_id)
        event_ids: set[str] = set()
        for ctx in contexts:
            event_ids.update(ctx.event_ids)
            event_ids.update(ctx.eligible_event_ids)
            event_ids.update(ctx.background_event_ids)
        events = self._news_evidence.get_events(tuple(sorted(event_ids)))
        return {
            "sectors": [
                {
                    "sector_id": c.sector_id,
                    "attribution_level": c.attribution_level.value,
                    "claims": [claim.model_dump(mode="json") for claim in c.claims],
                }
                for c in cards
            ],
            "events": [ev.model_dump(mode="json") for ev in events],
            "invocations": [
                {
                    "stage": inv.stage,
                    "provider_id": inv.provider_id,
                    "model": inv.model,
                    "prompt_id": inv.prompt_id,
                    "prompt_version": inv.prompt_version,
                    "status": inv.status.value,
                    "total_tokens": inv.usage.total_tokens,
                    "estimated_cost_cny": str(inv.estimated_cost_cny.amount),
                    "error_code": inv.error_code,
                }
                for inv in invocations
            ],
        }

    def get_review(self, run_id: UUID) -> dict:
        review = self._phase1b_repo.get_review(run_id)
        if review is None:
            return {"decision": None, "revision_round": None, "issues": []}
        return {
            "decision": review.decision.value,
            "revision_round": review.revision_round,
            "issues": [issue.model_dump(mode="json") for issue in review.issues],
        }
```

- [ ] **Step 2: Wire routes into create_app**

```python
# app.py 顶部新增导入
import json
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from sector_pulse.config.llm_config import load_llm_config
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.storage.agent_invocation_repository import SQLiteAgentInvocationRepository
from sector_pulse.storage.news_evidence_repository import SQLiteNewsEvidenceRepository
from sector_pulse.storage.phase1b_repository import SQLitePhase1BRepository
from sector_pulse.storage.phase1b_runs_repository import SQLitePhase1BRunsRepository
from sector_pulse.web.progress_bus import ProgressBus
from sector_pulse.web.run_service import ProviderUnavailable, RunService
from sector_pulse.web.schemas import NewRunRequest, NewRunResponse


def create_app(
    database_path: Path = Path("data/sector-pulse.db"),
    static_dir: Path | None = None,
    overrides: dict | None = None,
) -> FastAPI:
    database = SQLiteDatabase(database_path)
    bus = ProgressBus()
    service = overrides.get("service") if overrides else None
    if service is None:
        service = RunService(
            runs_repo=SQLitePhase1BRunsRepository(database),
            phase1b_repo=SQLitePhase1BRepository(database),
            invocation_repo=SQLiteAgentInvocationRepository(database),
            news_evidence=SQLiteNewsEvidenceRepository(database),
            prompts=PromptRegistry(Path("config/prompts")),
            config=load_llm_config(Path("config/llm.yaml")),
            bus=bus,
            fixture_responses=json.loads(
                Path("backend/tests/fixtures/phase1b/fixture_responses.json").read_text(
                    encoding="utf-8"
                )
            ),
            llm_factory={},
        )
    # ... lifespan 与 health 保持 ...

    @app.get("/api/runs")
    async def list_runs() -> list:
        return service.list_runs()

    @app.post("/api/runs", response_model=NewRunResponse, status_code=200)
    async def create_run(req: NewRunRequest) -> NewRunResponse:
        try:
            run_id = service.create_run(req.input_json, req.provider)
        except ProviderUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        return NewRunResponse(run_id=run_id)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: UUID) -> dict:
        detail = service.get_run(run_id)
        if detail is None:
            raise HTTPException(404, "run not found")
        return detail.model_dump(mode="json")

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: UUID) -> StreamingResponse:
        async def event_stream():
            async for event in bus.subscribe(run_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: UUID) -> dict:
        if not service.cancel_run(run_id):
            raise HTTPException(404, "run not found or not running")
        return {"cancelled": True}
```

- [ ] **Step 3: Write integration tests**

```python
# backend/tests/integration/test_web_api.py
import time

from fastapi.testclient import TestClient

from sector_pulse.web.app import create_app

from backend.tests.unit.web.test_run_service import _input_json, _service


def _client(tmp_path):
    return TestClient(create_app(overrides={"service": _service(tmp_path)}))


def test_list_runs_empty(tmp_path) -> None:
    resp = _client(tmp_path).get("/api/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_invalid_input_json_returns_422(tmp_path) -> None:
    resp = _client(tmp_path).post("/api/runs", json={"input_json": {}, "provider": "fixture"})
    assert resp.status_code == 422


def test_create_and_get_run(tmp_path) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/runs", json={"input_json": _input_json(), "provider": "fixture"})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    for _ in range(40):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail["status"] != "RUNNING":
            break
        time.sleep(0.25)
    assert detail["status"] == "READY_FOR_HUMAN_REVIEW"
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/integration/test_web_api.py -v`
Expected: PASS

---

### Task 9: 只读详情端点（Radar / Draft / Evidence / Review / 导出）

**Files:**
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `backend/src/sector_pulse/web/run_service.py`（渲染助手）
- Test: `backend/tests/integration/test_web_api.py`（扩展）

**Interfaces:**
- Produces: `GET /api/runs/{run_id}/radar`、`/draft`、`/draft.md`、`/draft.txt`、`/evidence`、`/review`

- [ ] **Step 1: Add render helpers to RunService**

```python
# run_service.py 追加
    def _ready_draft(self, run_id: UUID):
        drafts = self._phase1b_repo.get_drafts(run_id)
        if not drafts:
            return None
        from sector_pulse.domain.article import DraftStatus

        for draft in reversed(drafts):
            if draft.status is DraftStatus.READY_FOR_HUMAN_REVIEW:
                return draft
        return drafts[-1]

    def render_draft_markdown(self, run_id: UUID) -> str | None:
        draft = self._ready_draft(run_id)
        if draft is None:
            return None
        from decimal import Decimal

        from sector_pulse.application.phase1b_pipeline import Phase1BRunResult
        from sector_pulse.domain.llm import MoneyCny
        from sector_pulse.reporting.phase1b_report import render_phase1b_markdown

        result = Phase1BRunResult(
            status="READY_FOR_HUMAN_REVIEW",
            analysis_cards=(),
            outline=None,
            draft=draft,
            review=None,
            total_cost_cny=MoneyCny(amount=Decimal("0")),
            elapsed_ms=0,
        )
        return render_phase1b_markdown(result)

    def render_draft_text(self, run_id: UUID) -> str | None:
        draft = self._ready_draft(run_id)
        if draft is None:
            return None
        from decimal import Decimal

        from sector_pulse.application.phase1b_pipeline import Phase1BRunResult
        from sector_pulse.domain.llm import MoneyCny
        from sector_pulse.reporting.phase1b_report import render_phase1b_text

        result = Phase1BRunResult(
            status="READY_FOR_HUMAN_REVIEW",
            analysis_cards=(),
            outline=None,
            draft=draft,
            review=None,
            total_cost_cny=MoneyCny(amount=Decimal("0")),
            elapsed_ms=0,
        )
        return render_phase1b_text(result)
```

- [ ] **Step 2: Add detail routes**

在 `create_app` 中追加：

```python
    from fastapi.responses import PlainTextResponse

    @app.get("/api/runs/{run_id}/radar")
    async def get_radar(run_id: UUID) -> dict:
        if service.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return service.get_radar(run_id)

    @app.get("/api/runs/{run_id}/draft")
    async def get_draft(run_id: UUID) -> dict:
        if service.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return service.get_draft(run_id)

    @app.get("/api/runs/{run_id}/draft.md")
    async def get_draft_md(run_id: UUID) -> PlainTextResponse:
        body = service.render_draft_markdown(run_id)
        if body is None:
            raise HTTPException(404, "draft not ready")
        return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")

    @app.get("/api/runs/{run_id}/draft.txt")
    async def get_draft_txt(run_id: UUID) -> PlainTextResponse:
        body = service.render_draft_text(run_id)
        if body is None:
            raise HTTPException(404, "draft not ready")
        return PlainTextResponse(body, media_type="text/plain; charset=utf-8")

    @app.get("/api/runs/{run_id}/evidence")
    async def get_evidence(run_id: UUID) -> dict:
        if service.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return service.get_evidence(run_id)

    @app.get("/api/runs/{run_id}/review")
    async def get_review(run_id: UUID) -> dict:
        if service.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return service.get_review(run_id)
```

- [ ] **Step 3: Extend integration tests**

在 `test_web_api.py` 中 `test_create_and_get_run` 之后追加：

```python
def test_detail_endpoints_after_run(tmp_path) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/runs", json={"input_json": _input_json(), "provider": "fixture"})
    run_id = resp.json()["run_id"]
    for _ in range(40):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail["status"] != "RUNNING":
            break
        time.sleep(0.25)
    assert client.get(f"/api/runs/{run_id}/radar").status_code == 200
    draft_resp = client.get(f"/api/runs/{run_id}/draft")
    assert draft_resp.status_code == 200
    assert draft_resp.json()["versions"]
    assert client.get(f"/api/runs/{run_id}/evidence").status_code == 200
    review_resp = client.get(f"/api/runs/{run_id}/review")
    assert review_resp.status_code == 200
    assert review_resp.json()["decision"] == "PASS"
    md = client.get(f"/api/runs/{run_id}/draft.md")
    assert md.status_code == 200
    assert md.text.strip() != ""
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/integration/test_web_api.py -v`
Expected: PASS

---

### Task 10: Live Provider 工厂与 Consent 校验

**Files:**
- Create: `backend/src/sector_pulse/web/live_provider.py`
- Modify: `backend/src/sector_pulse/config/llm_config.py`
- Modify: `config/llm.yaml`
- Modify: `backend/src/sector_pulse/web/run_service.py`（_build_llm 支持 live）
- Test: `backend/tests/unit/web/test_live_provider.py`

**Interfaces:**
- Produces: `check_live_consent() -> bool`
- Produces: `get_live_config() -> tuple[str, str, str] | None`
- Produces: `build_live_provider(base_url, api_key, pricing) -> OpenAICompatibleProvider`

- [ ] **Step 1: Add pricing to config**

```yaml
# config/llm.yaml 在 routes 之后追加
pricing:
  gpt-4o-mini:
    input_cny_per_million: "2.5"
    output_cny_per_million: "10.0"
```

```python
# backend/src/sector_pulse/config/llm_config.py
class LLMRuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str
    budget_cny_per_run: Decimal = Field(gt=0)
    max_attribution_concurrency: int = Field(ge=1, le=32)
    max_revision_rounds: int = Field(ge=0, le=2)
    routes: dict[str, LLMRoute]
    pricing: dict[str, dict[str, str]] = Field(default_factory=dict)
```

- [ ] **Step 2: Create live_provider.py**

```python
# backend/src/sector_pulse/web/live_provider.py
import os
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from sector_pulse.infrastructure.llm.openai_compatible import ModelPrice, OpenAICompatibleProvider


def check_live_consent() -> bool:
    return Path(".live-llm-consent").is_file()


def get_live_config() -> tuple[str, str, str] | None:
    base_url = os.environ.get("SECTOR_PULSE_LLM_BASE_URL")
    api_key = os.environ.get("SECTOR_PULSE_LLM_API_KEY")
    model = os.environ.get("SECTOR_PULSE_LLM_MODEL")
    if not base_url or not api_key or not model:
        return None
    return (base_url, api_key, model)


def build_live_provider(
    base_url: str, api_key: str, pricing: dict[str, Any]
) -> OpenAICompatibleProvider:
    prices = {
        key: ModelPrice(
            input_cny_per_million=str(item["input_cny_per_million"]),
            output_cny_per_million=str(item["output_cny_per_million"]),
        )
        for key, item in pricing.items()
    }
    return OpenAICompatibleProvider(
        base_url=base_url,
        api_key=SecretStr(api_key),
        timeout_seconds=60.0,
        pricing=prices,
    )
```

- [ ] **Step 3: Write tests**

```python
# backend/tests/unit/web/test_live_provider.py
from sector_pulse.web.live_provider import (
    build_live_provider,
    check_live_consent,
    get_live_config,
)


def test_check_live_consent_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert check_live_consent() is False


def test_check_live_consent_present(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".live-llm-consent").write_text("", encoding="utf-8")
    assert check_live_consent() is True


def test_get_live_config_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("SECTOR_PULSE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("SECTOR_PULSE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("SECTOR_PULSE_LLM_MODEL", raising=False)
    assert get_live_config() is None


def test_build_live_provider_pricing() -> None:
    provider = build_live_provider(
        "https://example.test/v1",
        "sk-test",
        {"gpt-4o-mini": {"input_cny_per_million": "2.5", "output_cny_per_million": "10.0"}},
    )
    assert provider.provider_id == "openai-compatible"
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/unit/web/test_live_provider.py -v`
Expected: PASS

- [ ] **Step 5: Wire live into RunService._build_llm**

```python
    def _build_llm(self, provider: str) -> Any:
        if provider == "fixture":
            from sector_pulse.infrastructure.llm.fixture_provider import FixtureLLMProvider

            return FixtureLLMProvider(self._fixture_responses)
        if provider == "live":
            from sector_pulse.web.live_provider import (
                build_live_provider,
                check_live_consent,
                get_live_config,
            )

            if not check_live_consent():
                raise ProviderUnavailable("缺少 .live-llm-consent，真实模型被禁用")
            config_value = get_live_config()
            if config_value is None:
                raise ProviderUnavailable(
                    "缺少 SECTOR_PULSE_LLM_API_KEY / BASE_URL / MODEL 环境变量"
                )
            base_url, api_key, _model = config_value
            return build_live_provider(base_url, api_key, self._config.pricing)
        factory = self._llm_factory.get(provider)
        if factory is None:
            raise ProviderUnavailable(f"unknown provider: {provider}")
        return factory()
```

---

### Task 11: 前端脚手架（Vite + React + TS）

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/styles.css`

**Interfaces:**
- Produces: 可启动的 Vite dev server，代理 `/api` 到 `http://127.0.0.1:8000`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "sector-pulse-web",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.2"
  },
  "devDependencies": {
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.6.2",
    "vite": "^5.4.8"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create vite.config.ts**

```typescript
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
```

- [ ] **Step 4: Create index.html + main.tsx**

```html
<!-- web/index.html -->
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>SectorPulse</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

```tsx
// web/src/main.tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

- [ ] **Step 5: Create App.tsx with routing**

```tsx
// web/src/App.tsx
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import RunDetailPage from './pages/RunDetailPage'
import RunListPage from './pages/RunListPage'

export default function App() {
  return (
    <BrowserRouter>
      <main className="app-layout">
        <Routes>
          <Route path="/" element={<RunListPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
```

- [ ] **Step 6: Create styles.css**

```css
/* web/src/styles.css */
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f6f8; }
.app-layout { max-width: 1100px; margin: 0 auto; padding: 16px; }
.card { background: #fff; border: 1px solid #e3e6ea; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
.tabbar { display: flex; gap: 8px; margin-bottom: 12px; }
.tabbar button { padding: 6px 14px; border: 1px solid #d4d8de; background: #fff; border-radius: 6px; cursor: pointer; }
.tabbar button.active { background: #1a73e8; color: #fff; border-color: #1a73e8; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; }
.modal { position: fixed; inset: 0; background: rgba(0,0,0,.4); display: flex; align-items: center; justify-content: center; }
.modal-inner { background: #fff; border-radius: 8px; padding: 20px; width: 560px; }
.modal textarea { width: 100%; height: 200px; font-family: ui-monospace, monospace; font-size: 12px; }
```

- [ ] **Step 7: Verify dev server starts**

Run: `cd web && pnpm install && pnpm dev`
Expected: Vite 启动，`http://localhost:5173` 可访问（页面尚未实现时显示路由占位错误属预期）

---

### Task 12: 前端 API 客户端 + useRunSSE

**Files:**
- Create: `web/src/api.ts`
- Create: `web/src/useRuns.ts`

**Interfaces:**
- Produces: `RunSummary`, `fetchRuns()`, `createRun(inputJson, provider)`, `fetchRun(id)`, `fetchRadar(id)`, `fetchDraft(id)`, `fetchEvidence(id)`, `fetchReview(id)`, `draftUrl(id, ext)`
- Produces: `useRunSSE(runId, onDone)` hook

- [ ] **Step 1: Create api.ts**

```typescript
// web/src/api.ts
const BASE = '/api'

export interface RunSummary {
  run_id: string
  requested_at: string
  provider: string
  status: string
  elapsed_ms: number | null
  total_cost_cny: string | null
  draft_id: string | null
  input_json_hash?: string | null
  error_message?: string | null
  sector_count?: number
  review_decision?: string | null
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`)
  return res.json() as Promise<T>
}

export function fetchRuns(): Promise<RunSummary[]> {
  return get<RunSummary[]>('/runs')
}

export function fetchRun(runId: string): Promise<RunSummary> {
  return get<RunSummary>(`/runs/${runId}`)
}

export function fetchRadar(runId: string) {
  return get<{ cards: unknown[] }>(`/runs/${runId}/radar`)
}

export function fetchDraft(runId: string) {
  return get<{ versions: unknown[] }>(`/runs/${runId}/draft`)
}

export function fetchEvidence(runId: string) {
  return get<{ sectors: unknown[]; events: unknown[]; invocations: unknown[] }>(
    `/runs/${runId}/evidence`,
  )
}

export function fetchReview(runId: string) {
  return get<{ decision: string | null; revision_round: number | null; issues: unknown[] }>(
    `/runs/${runId}/review`,
  )
}

export async function createRun(inputJson: object, provider: string): Promise<{ run_id: string }> {
  const res = await fetch(`${BASE}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input_json: inputJson, provider }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`create run failed: ${res.status} ${text}`)
  }
  return res.json() as Promise<{ run_id: string }>
}

export function draftUrl(runId: string, ext: 'md' | 'txt'): string {
  return `${BASE}/runs/${runId}/draft.${ext}`
}
```

- [ ] **Step 2: Create useRuns.ts**

```typescript
// web/src/useRuns.ts
import { useEffect, useState } from 'react'

export interface ProgressEvent {
  type: 'progress' | 'done' | 'error' | 'cancelled'
  stage?: string
  detail?: Record<string, unknown>
  status?: string
  message?: string
}

export function useRunSSE(runId: string | null, onDone?: () => void) {
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!runId) return
    let es: EventSource | null = new EventSource(`/api/runs/${runId}/events`)
    es.onmessage = (e) => {
      let event: ProgressEvent
      try {
        event = JSON.parse(e.data) as ProgressEvent
      } catch {
        return
      }
      setEvents((prev) => [...prev, event])
      if (event.type === 'done') {
        setDone(true)
        onDone?.()
        es?.close()
      } else if (event.type === 'error') {
        setError(event.message ?? '运行失败')
        setDone(true)
        es?.close()
      } else if (event.type === 'cancelled') {
        setDone(true)
        es?.close()
      }
    }
    es.onerror = () => {
      setDone(true)
      es?.close()
    }
    return () => {
      es?.close()
      es = null
    }
  }, [runId, onDone])

  return { events, done, error }
}
```

---

### Task 13: 运行列表页 + 新建运行弹窗

**Files:**
- Create: `web/src/components/Badge.tsx`
- Create: `web/src/components/NewRunDialog.tsx`
- Create: `web/src/pages/RunListPage.tsx`

**Interfaces:**
- Produces: `NewRunDialog({ onClose })`：粘贴/上传 JSON、选 Provider、启动后跳转 `/runs/{run_id}`

- [ ] **Step 1: Create Badge**

```tsx
// web/src/components/Badge.tsx
export default function Badge({
  text,
  tone = 'gray',
}: {
  text: string
  tone?: 'gray' | 'blue' | 'green' | 'red' | 'orange'
}) {
  const colors: Record<string, string> = {
    gray: '#6b7280',
    blue: '#1a73e8',
    green: '#0f9d58',
    red: '#d93025',
    orange: '#f9a825',
  }
  return (
    <span
      className="badge"
      style={{
        background: colors[tone] + '22',
        color: colors[tone],
        border: `1px solid ${colors[tone]}55`,
      }}
    >
      {text}
    </span>
  )
}
```

- [ ] **Step 2: Create NewRunDialog**

```tsx
// web/src/components/NewRunDialog.tsx
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createRun } from '../api'

export default function NewRunDialog({ onClose }: { onClose: () => void }) {
  const [jsonText, setJsonText] = useState('')
  const [provider, setProvider] = useState('fixture')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => setJsonText(String(reader.result ?? ''))
    reader.readAsText(file)
  }

  async function handleStart() {
    setBusy(true)
    setError(null)
    try {
      const input = JSON.parse(jsonText)
      const { run_id } = await createRun(input, provider)
      onClose()
      nav(`/runs/${run_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'JSON 无效或请求失败')
      setBusy(false)
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-inner" onClick={(e) => e.stopPropagation()}>
        <h2>新建运行</h2>
        <div style={{ marginBottom: 8 }}>
          <button onClick={() => fileRef.current?.click()}>上传 JSON 文件</button>
          <input ref={fileRef} type="file" accept=".json" hidden onChange={handleFile} />
        </div>
        <textarea
          placeholder='粘贴 Phase 1B 输入 JSON，例如 {"requested_at":"...","contexts":[...],"gates":{...}}'
          value={jsonText}
          onChange={(e) => setJsonText(e.target.value)}
        />
        <div style={{ margin: '8px 0' }}>
          <label>Provider：</label>
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="fixture">fixture（默认，无需密钥）</option>
            <option value="live">live（需 consent + 环境变量）</option>
          </select>
        </div>
        {error && <p style={{ color: '#d93025' }}>{error}</p>}
        <div>
          <button disabled={busy} onClick={handleStart}>启动</button>
          <button disabled={busy} onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Create RunListPage**

```tsx
// web/src/pages/RunListPage.tsx
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchRuns, RunSummary } from '../api'
import Badge from '../components/Badge'
import NewRunDialog from '../components/NewRunDialog'

const STATUS_TONE: Record<string, string> = {
  RUNNING: 'blue',
  READY_FOR_HUMAN_REVIEW: 'green',
  FAILED: 'red',
  CANCELLED: 'gray',
  REVISE_REQUIRED: 'orange',
  UNREVIEWED: 'orange',
  BUDGET_EXCEEDED: 'orange',
  ATTRIBUTION_BLOCKED: 'orange',
  DRAFT_GENERATION_FAILED: 'red',
}

export default function RunListPage() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [showNew, setShowNew] = useState(false)

  useEffect(() => {
    fetchRuns().then(setRuns).catch(console.error)
  }, [])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>运行历史</h1>
        <button onClick={() => setShowNew(true)}>新建运行</button>
      </div>
      {showNew && <NewRunDialog onClose={() => setShowNew(false)} />}
      {runs.length === 0 && <p>还没有运行记录，点击「新建运行」开始。</p>}
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {runs.map((r) => (
          <li key={r.run_id} className="card">
            <Link to={`/runs/${r.run_id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <Badge text={r.status} tone={STATUS_TONE[r.status] ?? 'gray'} />
                <span style={{ fontFamily: 'ui-monospace, monospace' }}>{r.run_id.slice(0, 8)}</span>
                <span>{r.provider}</span>
                <span>{r.elapsed_ms != null ? `${r.elapsed_ms}ms` : '—'}</span>
                <span>{r.total_cost_cny != null ? `¥${r.total_cost_cny}` : ''}</span>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
```

---

### Task 14: 运行详情页 + 五个标签

**Files:**
- Create: `web/src/pages/RunDetailPage.tsx`
- Create: `web/src/pages/tabs/OverviewTab.tsx`
- Create: `web/src/pages/tabs/RadarTab.tsx`
- Create: `web/src/pages/tabs/DraftTab.tsx`
- Create: `web/src/pages/tabs/EvidenceTab.tsx`
- Create: `web/src/pages/tabs/ReviewTab.tsx`

**Interfaces:**
- Produces: 概览（状态/进度/成本）、雷达（卡片）、草稿（版本对比 + 复制）、证据（事件/审计）、审核（决策/问题）

- [ ] **Step 1: Create RunDetailPage**

```tsx
// web/src/pages/RunDetailPage.tsx
import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchRun, RunSummary } from '../api'
import { useRunSSE } from '../useRuns'
import DraftTab from './tabs/DraftTab'
import EvidenceTab from './tabs/EvidenceTab'
import OverviewTab from './tabs/OverviewTab'
import RadarTab from './tabs/RadarTab'
import ReviewTab from './tabs/ReviewTab'

const TABS = ['overview', 'radar', 'draft', 'evidence', 'review'] as const
type Tab = (typeof TABS)[number]

export default function RunDetailPage() {
  const { runId } = useParams()
  const [tab, setTab] = useState<Tab>('overview')
  const [run, setRun] = useState<RunSummary | null>(null)

  const refresh = useCallback(() => {
    if (!runId) return
    fetchRun(runId).then(setRun).catch(console.error)
  }, [runId])

  const { events, done } = useRunSSE(runId ?? null, refresh)

  return (
    <div>
      <Link to="/">← 返回列表</Link>
      <h1>运行 {runId?.slice(0, 8)}</h1>
      {run && (
        <div className="card" style={{ display: 'flex', gap: 16 }}>
          <span>状态：{run.status}</span>
          <span>Provider：{run.provider}</span>
          <span>耗时：{run.elapsed_ms != null ? `${run.elapsed_ms}ms` : '—'}</span>
          <span>成本：{run.total_cost_cny != null ? `¥${run.total_cost_cny}` : '—'}</span>
        </div>
      )}
      <nav className="tabbar">
        {TABS.map((t) => (
          <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>
      {tab === 'overview' && <OverviewTab events={events} done={done} run={run} />}
      {tab === 'radar' && <RadarTab runId={runId ?? ''} />}
      {tab === 'draft' && <DraftTab runId={runId ?? ''} />}
      {tab === 'evidence' && <EvidenceTab runId={runId ?? ''} />}
      {tab === 'review' && <ReviewTab runId={runId ?? ''} />}
    </div>
  )
}
```

- [ ] **Step 2: Create OverviewTab**

```tsx
// web/src/pages/tabs/OverviewTab.tsx
import { RunSummary } from '../../api'
import { ProgressEvent } from '../../useRuns'

export default function OverviewTab({
  events,
  done,
  run,
}: {
  events: ProgressEvent[]
  done: boolean
  run: RunSummary | null
}) {
  const stages = [
    'phase1b.start',
    'attribution.start',
    'attribution.done',
    'editorial.done',
    'writing.done',
    'review.done',
  ]
  const seen = new Set(events.map((e) => e.stage))
  const attribution = events.filter(
    (e) => e.type === 'progress' && e.stage === 'attribution.progress',
  )
  const last = attribution[attribution.length - 1]
  return (
    <div>
      {!done && <p>运行中… SSE 阶段进度如下：</p>}
      {done && <p>运行已结束。</p>}
      <ul>
        {stages.map((s) => (
          <li key={s} style={{ color: seen.has(s) ? '#0f9d58' : '#9aa0a6' }}>
            {seen.has(s) ? '✓' : '○'} {s}
          </li>
        ))}
      </ul>
      {last && (
        <p>
          归因进度：{String(last.detail?.done)} / {String(last.detail?.total)}
        </p>
      )}
      {run?.status === 'READY_FOR_HUMAN_REVIEW' && <p>草稿已就绪，切到「草稿」标签查看。</p>}
    </div>
  )
}
```

- [ ] **Step 3: Create RadarTab**

```tsx
// web/src/pages/tabs/RadarTab.tsx
import { useEffect, useState } from 'react'
import { fetchRadar } from '../../api'
import Badge from '../../components/Badge'

export default function RadarTab({ runId }: { runId: string }) {
  const [cards, setCards] = useState<any[]>([])
  useEffect(() => {
    fetchRadar(runId).then((d) => setCards(d.cards)).catch(console.error)
  }, [runId])

  if (cards.length === 0) return <p>暂无板块分析卡。</p>
  return (
    <div>
      {cards.map((c) => (
        <div key={c.sector_id} className="card">
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <h3 style={{ margin: 0 }}>{c.sector_id}</h3>
            <Badge text={c.attribution_level} tone="blue" />
            <span>置信度 {c.confidence}</span>
            <span>上限 {c.allowed_max_level}</span>
          </div>
          <p>{c.conclusion}</p>
          <p>反证：{c.counter_evidence.join('；') || '无'}</p>
          <p>不确定性：{c.uncertainties.join('；') || '无'}</p>
          {c.claims.length > 0 && (
            <ul>
              {c.claims.map((claim: any) => (
                <li key={claim.claim_id}>{claim.text}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Create DraftTab**

```tsx
// web/src/pages/tabs/DraftTab.tsx
import { useEffect, useMemo, useState } from 'react'
import { draftUrl, fetchDraft } from '../../api'

export default function DraftTab({ runId }: { runId: string }) {
  const [versions, setVersions] = useState<any[]>([])
  const [left, setLeft] = useState<number>(0)
  const [right, setRight] = useState<number>(0)
  useEffect(() => {
    fetchDraft(runId)
      .then((d) => {
        setVersions(d.versions)
        if (d.versions.length > 0) {
          setRight(d.versions.length)
          if (d.versions.length > 1) setLeft(d.versions.length - 1)
        }
      })
      .catch(console.error)
  }, [runId])

  const latest = versions[versions.length - 1]
  const leftV = versions.find((v) => v.version === left)
  const rightV = versions.find((v) => v.version === right)

  const sections = useMemo(() => {
    if (!leftV || !rightV) return []
    return rightV.sections.map((sec: any, i: number) => {
      const lsec = leftV.sections.find((s: any) => s.section_id === sec.section_id)
      return {
        heading: sec.heading,
        left: lsec?.body ?? '',
        right: sec.body,
        diff: lsec?.body !== sec.body,
      }
    })
  }, [leftV, rightV])

  async function copy(url: string) {
    const res = await fetch(url)
    const text = await res.text()
    await navigator.clipboard.writeText(text)
    alert('已复制到剪贴板')
  }

  if (versions.length === 0) return <p>暂无草稿。</p>
  return (
    <div>
      <div className="card">
        <h3>{latest.titles[0]}</h3>
        <p>
          版本 {latest.version}｜{latest.status}｜{latest.character_count} 字
        </p>
        <button onClick={() => copy(draftUrl(runId, 'md'))}>复制 Markdown</button>
        <button onClick={() => copy(draftUrl(runId, 'txt'))}>复制纯文本</button>
      </div>
      <div className="card">
        <label>左版本：</label>
        <select value={left} onChange={(e) => setLeft(Number(e.target.value))}>
          {versions.map((v) => (
            <option key={v.version} value={v.version}>
              v{v.version}
            </option>
          ))}
        </select>
        <label>右版本：</label>
        <select value={right} onChange={(e) => setRight(Number(e.target.value))}>
          {versions.map((v) => (
            <option key={v.version} value={v.version}>
              v{v.version}
            </option>
          ))}
        </select>
        {sections.map((s, i) => (
          <div
            key={i}
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8 }}
          >
            <div
              style={{
                background: s.diff ? '#fef3e2' : '#fafafa',
                border: '1px solid #eee',
                padding: 8,
              }}
            >
              {s.left}
            </div>
            <div
              style={{
                background: s.diff ? '#eaf6ee' : '#fafafa',
                border: '1px solid #eee',
                padding: 8,
              }}
            >
              {s.right}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Create EvidenceTab**

```tsx
// web/src/pages/tabs/EvidenceTab.tsx
import { useEffect, useState } from 'react'
import { fetchEvidence } from '../../api'

export default function EvidenceTab({ runId }: { runId: string }) {
  const [data, setData] = useState<any>({ sectors: [], events: [], invocations: [] })
  useEffect(() => {
    fetchEvidence(runId).then(setData).catch(console.error)
  }, [runId])

  return (
    <div>
      <h3>新闻事件</h3>
      {data.events.length === 0 && <p>暂无关联新闻事件。</p>}
      {data.events.map((ev: any) => (
        <div key={ev.event_id} className="card">
          <p>
            <strong>{ev.canonical_title}</strong>
          </p>
          {ev.documents.map((d: any, i: number) => (
            <p key={i}>
              <a href={d.citation_url ?? '#'} target="_blank" rel="noreferrer">
                {d.title}
              </a>
              {d.publisher ? `（${d.publisher}）` : ''}
            </p>
          ))}
        </div>
      ))}
      <h3>调用审计</h3>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            <th>阶段</th>
            <th>模型</th>
            <th>Prompt</th>
            <th>状态</th>
            <th>Token</th>
            <th>成本</th>
          </tr>
        </thead>
        <tbody>
          {data.invocations.map((inv: any, i: number) => (
            <tr key={i}>
              <td>{inv.stage}</td>
              <td>{inv.model}</td>
              <td>
                {inv.prompt_id}@{inv.prompt_version}
              </td>
              <td>{inv.status}</td>
              <td>{inv.total_tokens}</td>
              <td>¥{inv.estimated_cost_cny}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 6: Create ReviewTab**

```tsx
// web/src/pages/tabs/ReviewTab.tsx
import { useEffect, useState } from 'react'
import { fetchReview } from '../../api'

export default function ReviewTab({ runId }: { runId: string }) {
  const [review, setReview] = useState<any>({ decision: null, revision_round: null, issues: [] })
  useEffect(() => {
    fetchReview(runId).then(setReview).catch(console.error)
  }, [runId])

  return (
    <div>
      <p>
        决策：<strong>{review.decision ?? '—'}</strong>｜返工轮次：{review.revision_round ?? '—'}
      </p>
      {review.issues.length === 0 && <p>无审核问题。</p>}
      {review.issues.map((issue: any) => (
        <div key={issue.issue_id} className="card">
          <p>
            [{issue.severity}] {issue.code}：{issue.message}
          </p>
          {issue.suggested_fix && <p>建议：{issue.suggested_fix}</p>}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 7: Verify TypeScript passes**

Run: `cd web && pnpm exec tsc -b --noEmit`
Expected: 无类型错误

---

### Task 15: 前端构建与 FastAPI 静态托管

**Files:**
- Modify: `backend/src/sector_pulse/web/app.py`

- [ ] **Step 1: Build frontend**

Run: `cd web && pnpm build`
Expected: 生成 `web/dist/index.html` + `web/dist/assets/*`

- [ ] **Step 2: 用 static_dir 启动后端**

```python
# 启动入口示例（可放在 cli.py 或独立 web 入口）
# PYTHONPATH=backend/src python -c "
# from pathlib import Path
# import uvicorn
# from sector_pulse.web.app import create_app
# app = create_app(static_dir=Path('web/dist'))
# uvicorn.run(app, host='127.0.0.1', port=8000)
# "
```

- [ ] **Step 3: Manual smoke test**

Open: `http://127.0.0.1:8000`
Expected: SPA 加载，`/api/health` 正常，列表页显示空态

---

### Task 16: 端到端集成测试

**Files:**
- Test: `backend/tests/e2e/test_web_run.py`

- [ ] **Step 1: Write E2E test**

```python
# backend/tests/e2e/test_web_run.py
import time

from fastapi.testclient import TestClient

from sector_pulse.web.app import create_app


def test_fixture_run_end_to_end(tmp_path) -> None:
    from backend.tests.unit.web.test_run_service import _input_json, _service

    client = TestClient(create_app(overrides={"service": _service(tmp_path)}))
    resp = client.post("/api/runs", json={"input_json": _input_json(), "provider": "fixture"})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    for _ in range(60):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail["status"] != "RUNNING":
            break
        time.sleep(0.25)

    assert detail["status"] == "READY_FOR_HUMAN_REVIEW"
    assert detail["sector_count"] == 8
    assert detail["review_decision"] == "PASS"

    radar = client.get(f"/api/runs/{run_id}/radar").json()
    assert len(radar["cards"]) == 8

    draft = client.get(f"/api/runs/{run_id}/draft").json()
    assert len(draft["versions"]) >= 2

    review = client.get(f"/api/runs/{run_id}/review").json()
    assert review["decision"] == "PASS"

    evidence = client.get(f"/api/runs/{run_id}/evidence").json()
    assert set(i["stage"] for i in evidence["invocations"]) >= {
        "attribution",
        "editorial",
        "writing",
        "review",
    }

    md = client.get(f"/api/runs/{run_id}/draft.md")
    assert md.status_code == 200
    assert md.text.strip() != ""
```

- [ ] **Step 2: Run E2E test**

Run: `pytest backend/tests/e2e/test_web_run.py -v`
Expected: PASS

---

## Final Acceptance Checklist

- [ ] Web 手动运行 fixture 任务可端到端完成，SSE 按顺序展示 `phase1b.start → attribution.start/progress/done → editorial.done → writing.done → review.done`
- [ ] 运行历史、概览、雷达、草稿、证据、审核各视图数据与 SQLite 持久化一致
- [ ] 草稿支持 Markdown/纯文本复制与 `/draft.md`、`/draft.txt` 下载
- [ ] live Provider 未配置时返回 409 且不触网，配置后显式 consent 才可运行
- [ ] 进度埋点与调用审计不影响 CLI 与现有 Phase 1B 测试（默认空实现）
- [ ] 全量后端验证通过：`ruff`、`mypy`、`pytest`、`uv build`
- [ ] 全量前端验证通过：`tsc -b --noEmit`、`vite build`
- [ ] 手动：`127.0.0.1:8000` 打开 SPA，fixture 新建运行 → 看到进度 → 草稿可复制