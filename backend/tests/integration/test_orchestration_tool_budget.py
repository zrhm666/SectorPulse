from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64


def setup_state(tmp_path, *, max_tools=2, max_cny=Decimal("1.00")):
    from sector_pulse.domain.orchestration.models import BudgetLimits, RunSnapshot, TaskRecord
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "tools.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    root = TaskRecord(task_id=uuid4(), role="supervisor", scope="run")
    child = TaskRecord(task_id=uuid4(), parent_id=root.task_id, role="research", scope="industry:1")
    snapshot = RunSnapshot(
        run_id=uuid4(),
        limits=BudgetLimits(max_tool_calls=max_tools, max_cny=max_cny),
        deadline=datetime.now(UTC) + timedelta(minutes=1),
        tasks=(root, child),
    )
    repository.save(snapshot, -1, "created")
    return database, repository, snapshot, child


def test_concurrent_children_cannot_exceed_shared_tool_limit(tmp_path):
    from sector_pulse.application.orchestration.tool_budget import (
        SharedToolBudget,
        ToolBudgetExceeded,
    )
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database, repository, snapshot, child = setup_state(tmp_path, max_tools=1)

    def admit(index):
        service = SharedToolBudget(SQLiteOrchestrationRepository(database), snapshot.run_id)
        try:
            return service.admit(
                task_id=child.task_id,
                attempt=1,
                call_id=f"call-{index}",
                tool_name="search_news",
                input_fingerprint=("a" if index == 0 else "b") * 64,
                reserved_cny=Decimal("0.10"),
            ).execute
        except ToolBudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(admit, range(2))) == [False, True]
    assert repository.load(snapshot.run_id).ledger.tool_calls == 1


def test_same_tool_call_replays_without_execution_and_changed_input_conflicts(tmp_path):
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget

    _, repository, snapshot, child = setup_state(tmp_path)
    service = SharedToolBudget(repository, snapshot.run_id)
    first = service.admit(
        task_id=child.task_id,
        attempt=1,
        call_id="stable-call",
        tool_name="read_news_detail",
        input_fingerprint=FINGERPRINT_A,
        reserved_cny=Decimal("0"),
    )
    replay = service.admit(
        task_id=child.task_id,
        attempt=1,
        call_id="stable-call",
        tool_name="read_news_detail",
        input_fingerprint=FINGERPRINT_A,
        reserved_cny=Decimal("0"),
    )
    assert first.execute is True
    assert replay.execute is False
    assert replay.invocation == first.invocation
    assert repository.load(snapshot.run_id).ledger.tool_calls == 1
    with pytest.raises(ValueError, match="conflicting tool replay"):
        service.admit(
            task_id=child.task_id,
            attempt=1,
            call_id="stable-call",
            tool_name="read_news_detail",
            input_fingerprint=FINGERPRINT_B,
            reserved_cny=Decimal("0"),
        )


def test_stale_attempt_cannot_start_or_settle_tool_call(tmp_path):
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget

    _, repository, snapshot, child = setup_state(tmp_path)
    service = SharedToolBudget(repository, snapshot.run_id)
    with pytest.raises(ValueError, match="stale task attempt"):
        service.admit(
            task_id=child.task_id,
            attempt=2,
            call_id="late",
            tool_name="search_news",
            input_fingerprint=FINGERPRINT_A,
            reserved_cny=Decimal("0"),
        )
    admission = service.admit(
        task_id=child.task_id,
        attempt=1,
        call_id="active",
        tool_name="search_news",
        input_fingerprint=FINGERPRINT_A,
        reserved_cny=Decimal("0"),
    )
    current = repository.load(snapshot.run_id)
    tasks = tuple(
        task.model_copy(update={"attempt": 2}) if task.task_id == child.task_id else task
        for task in current.tasks
    )
    repository.save(
        current.model_copy(update={"revision": current.revision + 1, "tasks": tasks}),
        current.revision,
        "attempt.advanced",
    )
    with pytest.raises(ValueError, match="stale task attempt"):
        service.settle(admission.invocation.call_id, succeeded=True, actual_cny=Decimal("0"))


def test_model_and_tool_calls_share_total_money_limit(tmp_path):
    from sector_pulse.application.orchestration.budget import SharedBudget
    from sector_pulse.application.orchestration.tool_budget import (
        SharedToolBudget,
        ToolBudgetExceeded,
    )

    _, repository, snapshot, child = setup_state(tmp_path)
    SharedBudget(repository, snapshot.run_id).reserve("model", 1, 1, reserved_cny=Decimal("0.60"))
    with pytest.raises(ToolBudgetExceeded):
        SharedToolBudget(repository, snapshot.run_id).admit(
            task_id=child.task_id,
            attempt=1,
            call_id="tool",
            tool_name="collect_market",
            input_fingerprint=FINGERPRINT_A,
            reserved_cny=Decimal("0.50"),
        )


def test_unknown_tool_cost_keeps_hold_and_terminal_settlement_is_idempotent(tmp_path):
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
    from sector_pulse.domain.orchestration.models import ToolCallStatus

    _, repository, snapshot, child = setup_state(tmp_path)
    service = SharedToolBudget(repository, snapshot.run_id)
    admission = service.admit(
        task_id=child.task_id,
        attempt=1,
        call_id="unknown-cost",
        tool_name="collect_market",
        input_fingerprint=FINGERPRINT_A,
        reserved_cny=Decimal("0.40"),
    )
    settled = service.settle(admission.invocation.call_id, succeeded=None, actual_cny=None)
    repeated = service.settle(admission.invocation.call_id, succeeded=None, actual_cny=None)
    assert settled == repeated
    assert settled.status is ToolCallStatus.UNKNOWN
    ledger = repository.load(snapshot.run_id).ledger
    assert ledger.charged_cny == Decimal("0.40")
    assert ledger.has_unknown_cost
    with pytest.raises(ValueError, match="conflicting tool settlement"):
        service.settle(admission.invocation.call_id, succeeded=True, actual_cny=Decimal("0.10"))


def test_tool_admission_rejects_unknown_price_when_money_is_limited(tmp_path):
    from sector_pulse.application.orchestration.tool_budget import (
        SharedToolBudget,
        ToolBudgetExceeded,
    )

    _, repository, snapshot, child = setup_state(tmp_path)
    with pytest.raises(ToolBudgetExceeded, match="price"):
        SharedToolBudget(repository, snapshot.run_id).admit(
            task_id=child.task_id,
            attempt=1,
            call_id="unpriced",
            tool_name="search_news",
            input_fingerprint=FINGERPRINT_A,
        )
    assert repository.load(snapshot.run_id).ledger.tool_calls == 0


def test_enabling_money_limit_rejects_calls_after_unpriced_model_history(tmp_path):
    from sector_pulse.application.orchestration.budget import SharedBudget
    from sector_pulse.application.orchestration.tool_budget import (
        SharedToolBudget,
        ToolBudgetExceeded,
    )
    from sector_pulse.domain.orchestration.models import BudgetLimits

    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    SharedBudget(repository, snapshot.run_id).reserve("legacy-model", 1, 1)
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "limits": BudgetLimits(max_cny=Decimal("1")),
            }
        ),
        current.revision,
    )
    with pytest.raises(ToolBudgetExceeded, match="unpriced history"):
        SharedToolBudget(repository, snapshot.run_id).admit(
            task_id=child.task_id,
            attempt=1,
            call_id="free-tool",
            tool_name="inspect_artifacts",
            input_fingerprint=FINGERPRINT_A,
            reserved_cny=Decimal("0"),
        )


def test_enabling_money_limit_rejects_model_after_unpriced_tool_history(tmp_path):
    from sector_pulse.application.orchestration.budget import BudgetExceeded, SharedBudget
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
    from sector_pulse.domain.orchestration.models import BudgetLimits

    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    SharedToolBudget(repository, snapshot.run_id).admit(
        task_id=child.task_id,
        attempt=1,
        call_id="legacy-tool",
        tool_name="search_news",
        input_fingerprint=FINGERPRINT_A,
    )
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "limits": BudgetLimits(max_cny=Decimal("1")),
            }
        ),
        current.revision,
    )
    with pytest.raises(BudgetExceeded, match="unpriced history"):
        SharedBudget(repository, snapshot.run_id).reserve(
            "priced-model", 1, 1, reserved_cny=Decimal("0")
        )


def test_model_reservation_and_settlement_preserve_tool_audit_history(tmp_path):
    from sector_pulse.application.orchestration.budget import SharedBudget
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget

    _, repository, snapshot, child = setup_state(tmp_path)
    tools = SharedToolBudget(repository, snapshot.run_id)
    tools.admit(
        task_id=child.task_id,
        attempt=1,
        call_id="tool-before-model",
        tool_name="inspect_artifacts",
        input_fingerprint=FINGERPRINT_A,
        reserved_cny=Decimal("0"),
    )
    models = SharedBudget(repository, snapshot.run_id)
    models.reserve("model-after-tool", 1, 1, reserved_cny=Decimal("0"))
    models.settle("model-after-tool", 2, actual_cny=Decimal("0"))
    ledger = repository.load(snapshot.run_id).ledger
    assert [item.call_id for item in ledger.tool_invocations] == ["tool-before-model"]
    assert [item.call_id for item in ledger.reservations] == ["model-after-tool"]
