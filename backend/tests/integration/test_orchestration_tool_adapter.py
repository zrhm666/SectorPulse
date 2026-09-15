import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

pytest.importorskip("aidynamic_agent")


def setup_budgeted_tool(tmp_path, inner, *, replay_resolver=None, actual_cost=None):
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
    from sector_pulse.domain.orchestration.models import BudgetLimits, RunSnapshot, TaskRecord
    from sector_pulse.infrastructure.agents.tool_adapter import BudgetedTool
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "adapter.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    root = TaskRecord(task_id=uuid4(), role="supervisor", scope="run")
    child = TaskRecord(task_id=uuid4(), parent_id=root.task_id, role="research", scope="industry:1")
    snapshot = RunSnapshot(
        run_id=uuid4(),
        limits=BudgetLimits(max_tool_calls=3, max_cny=Decimal("1")),
        deadline=datetime.now(UTC) + timedelta(minutes=1),
        tasks=(root, child),
    )
    repository.save(snapshot, -1)
    tool = BudgetedTool(
        inner,
        SharedToolBudget(repository, snapshot.run_id),
        task_id=child.task_id,
        attempt=1,
        reserved_cny=Decimal("0.20"),
        actual_cost=actual_cost,
        replay_resolver=replay_resolver,
    )
    return tool, repository, snapshot


@pytest.mark.asyncio
async def test_budgeted_tool_replay_uses_persisted_result_without_second_side_effect(tmp_path):
    from aidynamic_agent.tools.base import Tool, ToolResult

    class SavingTool(Tool):
        name = "search_news"
        description = "search"
        parameters = {"type": "object"}

        def __init__(self):
            super().__init__()
            self.executions = 0

        async def execute(self, **kwargs):
            self.executions += 1
            return ToolResult(
                content="fresh result",
                metadata={"result_reference": "news-batch:1"},
            )

    inner = SavingTool()
    tool, repository, snapshot = setup_budgeted_tool(
        tmp_path,
        inner,
        replay_resolver=lambda reference: ToolResult(content=f"replayed {reference}"),
        actual_cost=lambda result: Decimal("0.05"),
    )
    first = await tool.run(query="医药")
    replay = await tool.run(query="医药")
    assert first.content == "fresh result"
    assert replay.content == "replayed news-batch:1"
    assert inner.executions == 1
    ledger = repository.load(snapshot.run_id).ledger
    assert ledger.tool_calls == 1
    assert ledger.charged_cny == Decimal("0.05")


@pytest.mark.asyncio
async def test_budgeted_tool_uses_inner_persisted_replay_contract_by_default(tmp_path):
    from aidynamic_agent.tools.base import Tool, ToolResult

    class ReplayableTool(Tool):
        name = "collect_market"
        description = "collect"
        parameters = {"type": "object"}

        def __init__(self):
            super().__init__()
            self.executions = 0

        async def execute(self, **kwargs):
            self.executions += 1
            return ToolResult(
                content="fresh market",
                metadata={"result_reference": "market:run:INDUSTRY:v1"},
            )

        def replay(self, reference):
            return ToolResult(content=f"persisted {reference}")

    inner = ReplayableTool()
    tool, _repository, _snapshot = setup_budgeted_tool(tmp_path, inner)

    await tool.run(kind="INDUSTRY")
    replay = await tool.run(kind="INDUSTRY")

    assert replay.content == "persisted market:run:INDUSTRY:v1"
    assert inner.executions == 1


@pytest.mark.asyncio
async def test_budgeted_tool_records_known_failure_and_unknown_cost(tmp_path):
    from aidynamic_agent.tools.base import Tool, ToolResult
    from sector_pulse.domain.orchestration.models import ToolCallStatus

    class FailingTool(Tool):
        name = "read_news_detail"
        description = "read"
        parameters = {"type": "object"}

        async def execute(self, **kwargs):
            return ToolResult(content="", success=False, error="source unavailable")

    tool, repository, snapshot = setup_budgeted_tool(tmp_path, FailingTool())
    result = await tool.run(document_id="doc-1")
    assert not result.success
    invocation = repository.load(snapshot.run_id).ledger.tool_invocations[0]
    assert invocation.status is ToolCallStatus.FAILED
    assert invocation.actual_cny is None
    assert repository.load(snapshot.run_id).ledger.charged_cny == Decimal("0.20")


@pytest.mark.asyncio
async def test_budgeted_tool_cancellation_records_unknown_outcome(tmp_path):
    from aidynamic_agent.tools.base import Tool, ToolResult
    from sector_pulse.domain.orchestration.models import ToolCallStatus

    started = asyncio.Event()

    class SlowTool(Tool):
        name = "collect_market"
        description = "collect"
        parameters = {"type": "object"}

        async def execute(self, **kwargs):
            started.set()
            await asyncio.Event().wait()
            return ToolResult(content="unreachable")

    tool, repository, snapshot = setup_budgeted_tool(tmp_path, SlowTool())
    task = asyncio.create_task(tool.run(market="industry"))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    invocation = repository.load(snapshot.run_id).ledger.tool_invocations[0]
    assert invocation.status is ToolCallStatus.UNKNOWN
    assert repository.load(snapshot.run_id).ledger.charged_cny == Decimal("0.20")
