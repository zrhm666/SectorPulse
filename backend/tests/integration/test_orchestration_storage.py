from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest


def setup_repo(tmp_path):
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    db = SQLiteDatabase(tmp_path / "orchestration.db")
    db.initialize()
    db.initialize()
    return SQLiteOrchestrationRepository(db)


def initial(repo, tokens=100, calls=10):
    from sector_pulse.domain.orchestration.models import BudgetLimits, RunSnapshot

    state = RunSnapshot(
        run_id=uuid4(),
        limits=BudgetLimits(max_tokens=tokens, max_calls=calls),
        deadline=datetime.now(UTC) + timedelta(minutes=1),
    )
    repo.save(state, expected_revision=-1, event="created")
    return state


def test_snapshot_cas_and_event_survive_reopen(tmp_path):
    from sector_pulse.ports.orchestration import RevisionConflict

    repo = setup_repo(tmp_path)
    state = initial(repo)
    updated = state.model_copy(update={"revision": 1})
    repo.save(updated, 0, event="started")
    with pytest.raises(RevisionConflict):
        repo.save(updated, 0, event="must-not-append")
    reopened = setup_repo(tmp_path)
    assert reopened.load(state.run_id).revision == 1
    assert reopened.events(state.run_id) == [(0, "created"), (1, "started")]
    assert reopened.load(uuid4()) is None


def test_competing_agents_cannot_double_spend(tmp_path):
    from sector_pulse.application.orchestration.budget import BudgetExceeded, SharedBudget

    repo = setup_repo(tmp_path)
    state = initial(repo)

    def reserve(index):
        budget = SharedBudget(setup_repo(tmp_path), state.run_id)
        try:
            budget.reserve(f"call-{index}", 20, 50)
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, range(2))) == [False, True]
    current = repo.load(state.run_id)
    assert current.ledger.charged_tokens == 70
    assert current.ledger.calls == 1


def test_settlement_and_idempotency(tmp_path):
    from sector_pulse.application.orchestration.budget import SharedBudget

    repo = setup_repo(tmp_path)
    state = initial(repo)
    budget = SharedBudget(repo, state.run_id)
    budget.reserve("a", 20, 50)
    budget.settle("a", 20)
    budget.settle("a", 20)
    budget.reserve("b", 20, 50)
    assert repo.load(state.run_id).ledger.charged_tokens == 90
    with pytest.raises(ValueError):
        budget.settle("a", 1)
    with pytest.raises(ValueError):
        budget.reserve("a", 20, 50)  # a replay cannot authorize another HTTP call


@pytest.mark.parametrize("usage", [None, 120])
def test_unknown_or_excess_usage_blocks_further_calls(tmp_path, usage):
    from sector_pulse.application.orchestration.budget import BudgetExceeded, SharedBudget

    repo = setup_repo(tmp_path)
    state = initial(repo)
    budget = SharedBudget(repo, state.run_id)
    budget.reserve("a", 50, 50)
    budget.settle("a", usage)
    with pytest.raises(BudgetExceeded):
        budget.reserve("b", 0, 1)
    assert repo.load(state.run_id).ledger.charged_tokens == (100 if usage is None else 120)


def test_call_limit_and_expired_deadline(tmp_path):
    from sector_pulse.application.orchestration.budget import BudgetExceeded, SharedBudget

    repo = setup_repo(tmp_path)
    state = initial(repo, calls=1)
    budget = SharedBudget(repo, state.run_id)
    budget.reserve("a", 0, 1)
    budget.settle("a", 0)
    with pytest.raises(BudgetExceeded):
        budget.reserve("b", 0, 1)
    other = initial(repo)
    repo.save(
        other.model_copy(
            update={"revision": 1, "deadline": datetime.now(UTC) - timedelta(seconds=1)}
        ),
        0,
    )
    with pytest.raises(BudgetExceeded):
        SharedBudget(repo, other.run_id).reserve("c", 0, 1)


def test_invalid_amount_does_not_modify_state(tmp_path):
    from sector_pulse.application.orchestration.budget import SharedBudget

    repo = setup_repo(tmp_path)
    state = initial(repo)
    budget = SharedBudget(repo, state.run_id)
    with pytest.raises(ValueError):
        budget.reserve("a", -1, 10)
    assert repo.load(state.run_id).revision == 0


def money_state(repo):
    from sector_pulse.domain.orchestration.models import BudgetLimits

    state = initial(repo, tokens=10000)
    state = state.model_copy(
        update={
            "revision": 1,
            "limits": BudgetLimits(max_tokens=10000, max_cny=Decimal("1.00")),
        }
    )
    repo.save(state, 0)
    return state


def test_competing_agents_share_money_limit(tmp_path):
    from sector_pulse.application.orchestration.budget import BudgetExceeded, SharedBudget

    repo = setup_repo(tmp_path)
    state = money_state(repo)

    def reserve(index):
        budget = SharedBudget(setup_repo(tmp_path), state.run_id)
        try:
            budget.reserve(str(index), 1, 1, reserved_cny=Decimal("0.70"))
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, range(2))) == [False, True]
    current = setup_repo(tmp_path).load(state.run_id)
    assert current.ledger.charged_cny == Decimal("0.70")
    assert current.ledger.calls == 1


def test_money_settlement_is_exact_and_idempotent(tmp_path):
    from sector_pulse.application.orchestration.budget import SharedBudget

    repo = setup_repo(tmp_path)
    state = money_state(repo)
    budget = SharedBudget(repo, state.run_id)
    budget.reserve("a", 1, 1, reserved_cny=Decimal("0.70"))
    budget.settle("a", 1, actual_cny=Decimal("0.20"))
    budget.settle("a", 1, actual_cny=Decimal("0.20"))
    with pytest.raises(ValueError):
        budget.settle("a", 1, actual_cny=Decimal("0.10"))
    budget.reserve("b", 1, 1, reserved_cny=Decimal("0.70"))
    current = setup_repo(tmp_path).load(state.run_id)
    assert current.ledger.charged_cny == Decimal("0.90")


@pytest.mark.parametrize("cost", [None, Decimal("1.20")])
def test_unknown_or_excess_money_is_not_refunded(tmp_path, cost):
    from sector_pulse.application.orchestration.budget import BudgetExceeded, SharedBudget

    repo = setup_repo(tmp_path)
    state = money_state(repo)
    budget = SharedBudget(repo, state.run_id)
    budget.reserve("a", 1, 1, reserved_cny=Decimal("1.00"))
    budget.settle("a", 1, actual_cny=cost)
    with pytest.raises(BudgetExceeded):
        budget.reserve("b", 1, 1, reserved_cny=Decimal("0.01"))
    current = repo.load(state.run_id)
    assert current.ledger.charged_cny == (Decimal("1.00") if cost is None else cost)
    assert current.ledger.has_unknown_cost is (cost is None)


def test_unknown_price_cannot_bypass_money_limit(tmp_path):
    from sector_pulse.application.orchestration.budget import BudgetExceeded, SharedBudget

    repo = setup_repo(tmp_path)
    state = money_state(repo)
    with pytest.raises(BudgetExceeded, match="price"):
        SharedBudget(repo, state.run_id).reserve("unknown", 1, 1)
    assert repo.load(state.run_id).ledger.calls == 0


def test_ambiguous_snapshot_is_rejected(tmp_path):
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        BudgetLedger,
        BudgetReservation,
        TaskRecord,
    )

    repo = setup_repo(tmp_path)
    state = initial(repo)
    reservation = BudgetReservation(call_id="duplicate", reserved_tokens=10)
    with pytest.raises(ValueError):
        repo.save(
            state.model_copy(
                update={
                    "revision": 1,
                    "ledger": BudgetLedger(reservations=(reservation, reservation)),
                }
            ),
            0,
        )
    orphan = TaskRecord(task_id=uuid4(), parent_id=uuid4(), role="research", scope="industry:1")
    with pytest.raises(ValueError):
        repo.save(state.model_copy(update={"revision": 1, "tasks": (orphan,)}), 0)
    artifact = ArtifactRef(artifact_id=uuid4(), task_id=uuid4(), kind="draft", reference="draft:1")
    with pytest.raises(ValueError):
        repo.save(state.model_copy(update={"revision": 1, "artifacts": (artifact,)}), 0)
    assert repo.load(state.run_id).revision == 0


def test_task_artifact_and_reservation_survive_reopen(tmp_path):
    from sector_pulse.application.orchestration.budget import SharedBudget
    from sector_pulse.domain.orchestration.models import ArtifactRef, TaskRecord

    repo = setup_repo(tmp_path)
    state = initial(repo)
    root = TaskRecord(task_id=uuid4(), role="supervisor", scope="run")
    child = TaskRecord(task_id=uuid4(), parent_id=root.task_id, role="research", scope="industry:1")
    artifact = ArtifactRef(
        artifact_id=uuid4(), task_id=child.task_id, kind="analysis", reference="card:1"
    )
    repo.save(
        state.model_copy(update={"revision": 1, "tasks": (root, child), "artifacts": (artifact,)}),
        0,
    )
    SharedBudget(repo, state.run_id).reserve("inflight", 10, 30)
    reopened = setup_repo(tmp_path).load(state.run_id)
    assert reopened.tasks[1].parent_id == root.task_id
    assert reopened.artifacts == (artifact,)
    assert reopened.ledger.charged_tokens == 40
    assert not reopened.ledger.reservations[0].settled


@pytest.mark.postgres
def test_postgres_snapshot_contract():
    import os

    from sector_pulse.application.orchestration.budget import SharedBudget
    from sector_pulse.ports.orchestration import RevisionConflict
    from sector_pulse.storage.postgres.database import PostgresDatabase
    from sector_pulse.storage.postgres.orchestration.repository import (
        PostgresOrchestrationRepository,
    )
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    url = os.getenv("SECTOR_PULSE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires dedicated SECTOR_PULSE_TEST_DATABASE_URL")
    assert (make_url(url).database or "").endswith("_test"), "business database refused"
    db = PostgresDatabase(url)
    db.initialize()
    repo = PostgresOrchestrationRepository(db)
    state = initial(repo)
    try:
        SharedBudget(repo, state.run_id).reserve("a", 20, 50)
        SharedBudget(repo, state.run_id).settle("a", 25)
        with pytest.raises(RevisionConflict):
            repo.save(state.model_copy(update={"revision": 1}), 0)
        assert PostgresOrchestrationRepository(db).load(state.run_id).ledger.charged_tokens == 25
        assert [revision for revision, _ in repo.events(state.run_id)] == [0, 1, 2]
    finally:
        with db.start().begin() as connection:
            connection.execute(
                text("DELETE FROM orchestration_events WHERE run_id=:run"),
                {"run": str(state.run_id)},
            )
            connection.execute(
                text("DELETE FROM orchestration_snapshots WHERE run_id=:run"),
                {"run": str(state.run_id)},
            )
        db.close()
