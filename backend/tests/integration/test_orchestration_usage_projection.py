from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4


def test_legacy_and_multi_agent_usage_share_one_safe_projection(tmp_path):
    from sector_pulse.application.orchestration.budget import SharedBudget
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
    from sector_pulse.application.orchestration.usage import InvocationUsageProjection
    from sector_pulse.domain.llm import (
        AgentInvocation,
        LLMStatus,
        MoneyCny,
        TokenUsage,
    )
    from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository
    from sector_pulse.storage.sqlite.writing.agent_invocation_repository import (
        SQLiteAgentInvocationRepository,
    )

    database = SQLiteDatabase(tmp_path / "usage-projection.db")
    database.initialize()
    orchestration = SQLiteOrchestrationRepository(database)
    legacy = SQLiteAgentInvocationRepository(database)
    task = TaskRecord(task_id=uuid4(), role="A0", scope="run")
    run_id = uuid4()
    orchestration.save(
        RunSnapshot(
            run_id=run_id,
            deadline=datetime.now(UTC) + timedelta(minutes=5),
            tasks=(task,),
        ),
        -1,
        "created",
    )
    duplicated_id = uuid4()
    legacy.save(
        (
            AgentInvocation(
                invocation_id=duplicated_id,
                run_id=run_id,
                stage="legacy-writing",
                provider_id="legacy-provider",
                model="legacy-model",
                prompt_id="writing",
                prompt_version="1",
                input_hash="safe-input-hash",
                status=LLMStatus.SUCCESS,
                usage=TokenUsage(prompt_tokens=7, completion_tokens=3, total_tokens=10),
                estimated_cost_cny=MoneyCny(amount=Decimal("0.05")),
            ),
        )
    )

    model_budget = SharedBudget(
        orchestration,
        run_id,
        task_id=task.task_id,
        attempt=1,
        role="A0",
        provider="fixture",
        model="fixture-model",
        action_summary="coordinate research",
    )
    model_budget.reserve(str(duplicated_id), 20, 10, reserved_cny=Decimal("0.20"))
    model_budget.settle(
        str(duplicated_id),
        15,
        actual_cny=Decimal("0.10"),
        succeeded=True,
    )
    model_budget.reserve("unknown-model", 5, 5, reserved_cny=Decimal("0.08"))
    model_budget.settle("unknown-model", None, actual_cny=None, succeeded=None)

    tool_budget = SharedToolBudget(orchestration, run_id)
    tool_budget.admit(
        task_id=task.task_id,
        attempt=1,
        call_id="tool-1",
        tool_name="inspect_tasks",
        input_fingerprint="a" * 64,
        reserved_cny=Decimal("0.02"),
    )
    tool_budget.settle(
        "tool-1",
        succeeded=True,
        actual_cny=Decimal("0.01"),
        result_reference="inspection:tasks",
    )

    projection = InvocationUsageProjection(legacy, orchestration)
    rows = projection.list_for_run(run_id)
    assert [row.call_id for row in rows] == [str(duplicated_id), "unknown-model", "tool-1"]
    model = rows[0]
    assert model.source == "multi_agent_model"
    assert model.task_id == task.task_id
    assert model.attempt == 1
    assert model.role == "A0"
    assert model.total_tokens == 15
    assert model.cost_cny == Decimal("0.10")
    assert model.usage_known and model.cost_known
    unknown = rows[1]
    assert unknown.total_tokens is None
    assert unknown.cost_cny is None
    assert not unknown.usage_known and not unknown.cost_known
    tool = rows[2]
    assert tool.source == "multi_agent_tool"
    assert tool.tool_name == "inspect_tasks"
    assert tool.result_reference == "inspection:tasks"
    assert not hasattr(tool, "input_hash")

    summary = projection.summary_for_run(run_id)
    assert summary.call_count == 3
    assert summary.model_call_count == 2
    assert summary.tool_call_count == 1
    assert summary.known_tokens == 15
    assert summary.known_cost_cny == Decimal("0.11")
    assert summary.has_unknown_usage
    assert summary.has_unknown_cost
