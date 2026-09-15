from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest


def setup_task_state(tmp_path):
    from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "task-state.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    root = TaskRecord(task_id=uuid4(), role="A0", scope="run")
    child = TaskRecord(
        task_id=uuid4(), parent_id=root.task_id, role="research", scope="industry:1"
    )
    snapshot = RunSnapshot(
        run_id=uuid4(),
        deadline=datetime.now(UTC) + timedelta(minutes=10),
        tasks=(root, child),
    )
    repository.save(snapshot, -1, "created")
    return database, repository, snapshot, root, child


def task_by_id(repository, run_id, task_id):
    snapshot = repository.load(run_id)
    return next(task for task in snapshot.tasks if task.task_id == task_id)


def test_only_legal_task_status_transitions_are_accepted(tmp_path):
    from sector_pulse.application.orchestration.tasks import (
        InvalidTaskTransition,
        TaskCoordinator,
    )
    from sector_pulse.domain.orchestration.models import TaskStatus

    _, repository, snapshot, root, _ = setup_task_state(tmp_path)
    service = TaskCoordinator(repository, snapshot.run_id)
    lease = datetime.now(UTC) + timedelta(minutes=1)

    service.start(root.task_id, attempt=1, worker_id="worker-a", lease_expires_at=lease)
    service.transition(
        root.task_id,
        attempt=1,
        worker_id="worker-a",
        target=TaskStatus.COMPLETED,
        now=lease - timedelta(seconds=1),
    )
    with pytest.raises(InvalidTaskTransition, match="completed.*running"):
        service.start(
            root.task_id,
            attempt=1,
            worker_id="worker-a",
            lease_expires_at=lease + timedelta(minutes=1),
        )


def test_worker_must_own_a_live_lease_to_update_task(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator, TaskOwnershipError
    from sector_pulse.domain.orchestration.models import TaskStatus

    _, repository, snapshot, root, _ = setup_task_state(tmp_path)
    service = TaskCoordinator(repository, snapshot.run_id)
    now = datetime.now(UTC)
    service.start(
        root.task_id,
        attempt=1,
        worker_id="worker-a",
        lease_expires_at=now + timedelta(seconds=10),
    )

    with pytest.raises(TaskOwnershipError, match="own task"):
        service.transition(
            root.task_id,
            attempt=1,
            worker_id="worker-b",
            target=TaskStatus.COMPLETED,
            now=now + timedelta(seconds=1),
        )
    with pytest.raises(TaskOwnershipError, match="expired"):
        service.transition(
            root.task_id,
            attempt=1,
            worker_id="worker-a",
            target=TaskStatus.COMPLETED,
            now=now + timedelta(seconds=11),
        )
    assert task_by_id(repository, snapshot.run_id, root.task_id).status is TaskStatus.RUNNING


def test_only_current_owner_can_renew_a_lease(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator, TaskOwnershipError

    _, repository, snapshot, root, _ = setup_task_state(tmp_path)
    service = TaskCoordinator(repository, snapshot.run_id)
    now = datetime.now(UTC)
    original_expiry = now + timedelta(seconds=10)
    service.start(
        root.task_id,
        attempt=1,
        worker_id="worker-a",
        lease_expires_at=original_expiry,
    )
    with pytest.raises(TaskOwnershipError, match="own task"):
        service.renew_lease(
            root.task_id,
            attempt=1,
            worker_id="worker-b",
            lease_expires_at=now + timedelta(minutes=1),
            now=now,
        )
    renewed = service.renew_lease(
        root.task_id,
        attempt=1,
        worker_id="worker-a",
        lease_expires_at=now + timedelta(minutes=1),
        now=now,
    )
    assert renewed.lease_expires_at > original_expiry


def test_parent_cancellation_propagates_only_to_unfinished_children(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.domain.orchestration.models import TaskStatus

    _, repository, snapshot, root, child = setup_task_state(tmp_path)
    completed_child = child.model_copy(update={"task_id": uuid4(), "status": TaskStatus.COMPLETED})
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "tasks": (*current.tasks, completed_child),
            }
        ),
        current.revision,
        "child.completed",
    )

    TaskCoordinator(repository, snapshot.run_id).cancel(root.task_id)

    state = repository.load(snapshot.run_id)
    statuses = {task.task_id: task.status for task in state.tasks}
    assert statuses[root.task_id] is TaskStatus.CANCELLED
    assert statuses[child.task_id] is TaskStatus.CANCELLED
    assert statuses[completed_child.task_id] is TaskStatus.COMPLETED


def test_only_expired_lease_can_be_recovered_and_recovery_advances_attempt(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator, TaskOwnershipError

    _, repository, snapshot, root, _ = setup_task_state(tmp_path)
    service = TaskCoordinator(repository, snapshot.run_id)
    now = datetime.now(UTC)
    service.start(
        root.task_id,
        attempt=1,
        worker_id="worker-a",
        lease_expires_at=now + timedelta(seconds=10),
    )
    with pytest.raises(TaskOwnershipError, match="active lease"):
        service.recover(
            root.task_id,
            expected_attempt=1,
            worker_id="worker-b",
            lease_expires_at=now + timedelta(minutes=1),
            now=now,
        )

    recovered = service.recover(
        root.task_id,
        expected_attempt=1,
        worker_id="worker-b",
        lease_expires_at=now + timedelta(minutes=2),
        now=now + timedelta(seconds=11),
    )
    assert recovered.attempt == 2
    assert recovered.worker_id == "worker-b"


def test_interrupted_task_still_requires_its_lease_to_expire_before_recovery(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator, TaskOwnershipError
    from sector_pulse.domain.orchestration.models import TaskStatus

    _, repository, snapshot, root, _ = setup_task_state(tmp_path)
    service = TaskCoordinator(repository, snapshot.run_id)
    now = datetime.now(UTC)
    lease = now + timedelta(seconds=10)
    service.start(
        root.task_id,
        attempt=1,
        worker_id="worker-a",
        lease_expires_at=lease,
    )
    interrupted = service.transition(
        root.task_id,
        attempt=1,
        worker_id="worker-a",
        target=TaskStatus.INTERRUPTED,
        now=now,
    )
    assert interrupted.lease_expires_at == lease
    with pytest.raises(TaskOwnershipError, match="active lease"):
        service.recover(
            root.task_id,
            expected_attempt=1,
            worker_id="worker-b",
            lease_expires_at=now + timedelta(minutes=1),
            now=now + timedelta(seconds=1),
        )
    recovered = service.recover(
        root.task_id,
        expected_attempt=1,
        worker_id="worker-b",
        lease_expires_at=now + timedelta(minutes=2),
        now=now + timedelta(seconds=11),
    )
    assert recovered.status is TaskStatus.RUNNING
    assert recovered.attempt == 2


def test_concurrent_recovery_has_one_owner_and_one_new_attempt(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator, TaskOwnershipError
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database, repository, snapshot, root, _ = setup_task_state(tmp_path)
    now = datetime.now(UTC)
    TaskCoordinator(repository, snapshot.run_id).start(
        root.task_id,
        attempt=1,
        worker_id="dead-worker",
        lease_expires_at=now - timedelta(seconds=1),
        now=now - timedelta(seconds=2),
    )

    def recover(worker_id):
        service = TaskCoordinator(SQLiteOrchestrationRepository(database), snapshot.run_id)
        try:
            service.recover(
                root.task_id,
                expected_attempt=1,
                worker_id=worker_id,
                lease_expires_at=now + timedelta(minutes=1),
                now=now,
            )
            return True
        except TaskOwnershipError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(recover, ("worker-b", "worker-c"))) == [False, True]
    task = task_by_id(repository, snapshot.run_id, root.task_id)
    assert task.attempt == 2
    assert task.worker_id in {"worker-b", "worker-c"}


def test_only_live_a0_owner_can_delegate_registered_child_role(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator, TaskOwnershipError
    from sector_pulse.domain.orchestration.models import TaskStatus

    _, repository, snapshot, root, _ = setup_task_state(tmp_path)
    service = TaskCoordinator(repository, snapshot.run_id)
    now = datetime.now(UTC)
    service.start(
        root.task_id,
        attempt=1,
        worker_id="parent-worker",
        lease_expires_at=now + timedelta(minutes=1),
    )
    with pytest.raises(TaskOwnershipError, match="own task"):
        service.delegate_child(
            root.task_id,
            parent_attempt=1,
            parent_worker_id="other-worker",
            child_id=uuid4(),
            child_worker_id="child-worker",
            child_lease_expires_at=now + timedelta(minutes=1),
            role="A2",
            scope="industry:2",
            now=now,
        )
    child = service.delegate_child(
        root.task_id,
        parent_attempt=1,
        parent_worker_id="parent-worker",
        child_id=uuid4(),
        child_worker_id="child-worker",
        child_lease_expires_at=now + timedelta(minutes=1),
        role="A2",
        scope="industry:2",
        now=now,
    )
    assert child.parent_id == root.task_id
    assert child.status is TaskStatus.RUNNING
    assert child.attempt == 1


def test_delegated_inputs_and_selection_survive_attempt_recovery(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.domain.orchestration.models import ArtifactRef

    _, repository, snapshot, root, _ = setup_task_state(tmp_path)
    current = repository.load(snapshot.run_id)
    input_artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root.task_id,
        kind="candidate_selection",
        reference="selection:4",
    )
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "tasks": (root,),
                "artifacts": (input_artifact,),
            }
        ),
        current.revision,
        "research.input.seeded",
    )
    now = datetime.now(UTC)
    service = TaskCoordinator(repository, snapshot.run_id)
    service.start(
        root.task_id,
        attempt=1,
        worker_id="parent-worker",
        lease_expires_at=now + timedelta(minutes=1),
    )
    child = service.delegate_child(
        root.task_id,
        parent_attempt=1,
        parent_worker_id="parent-worker",
        child_id=uuid4(),
        child_worker_id="research-worker",
        child_lease_expires_at=now + timedelta(seconds=10),
        role="A2",
        scope="sector:INDUSTRY:1",
        input_artifact_ids=(input_artifact.artifact_id,),
        selection_version=4,
        now=now,
    )
    assert child.input_artifact_ids == (input_artifact.artifact_id,)
    assert child.selection_version == 4

    recovered = service.recover(
        child.task_id,
        expected_attempt=1,
        worker_id="replacement-worker",
        lease_expires_at=now + timedelta(minutes=2),
        now=now + timedelta(seconds=11),
    )
    assert recovered.attempt == 2
    assert recovered.input_artifact_ids == (input_artifact.artifact_id,)
    assert recovered.selection_version == 4


def test_delegation_rejects_unknown_or_duplicate_input_artifacts(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator

    _, repository, snapshot, root, _ = setup_task_state(tmp_path)
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(update={"revision": current.revision + 1, "tasks": (root,)}),
        current.revision,
        "unused.child.removed",
    )
    now = datetime.now(UTC)
    service = TaskCoordinator(repository, snapshot.run_id)
    service.start(
        root.task_id,
        attempt=1,
        worker_id="parent-worker",
        lease_expires_at=now + timedelta(minutes=1),
    )
    unknown = uuid4()
    with pytest.raises(ValueError, match="unknown artifact"):
        service.delegate_child(
            root.task_id,
            parent_attempt=1,
            parent_worker_id="parent-worker",
            child_id=uuid4(),
            child_worker_id="research-worker",
            child_lease_expires_at=now + timedelta(minutes=1),
            role="A2",
            scope="sector:INDUSTRY:1",
            input_artifact_ids=(unknown,),
            selection_version=1,
            now=now,
        )
    with pytest.raises(ValueError, match="unique"):
        service.delegate_child(
            root.task_id,
            parent_attempt=1,
            parent_worker_id="parent-worker",
            child_id=uuid4(),
            child_worker_id="research-worker",
            child_lease_expires_at=now + timedelta(minutes=1),
            role="A2",
            scope="sector:INDUSTRY:1",
            input_artifact_ids=(unknown, unknown),
            selection_version=1,
            now=now,
        )


def test_concurrent_a2_delegation_cannot_exceed_two_active_scopes(tmp_path):
    from sector_pulse.application.orchestration.tasks import (
        DelegationLimitExceeded,
        TaskCoordinator,
    )
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database, repository, snapshot, root, _ = setup_task_state(tmp_path)
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "tasks": (root,),
            }
        ),
        current.revision,
        "unused.child.removed",
    )
    now = datetime.now(UTC)
    TaskCoordinator(repository, snapshot.run_id).start(
        root.task_id,
        attempt=1,
        worker_id="parent-worker",
        lease_expires_at=now + timedelta(minutes=1),
    )

    def delegate(index):
        service = TaskCoordinator(SQLiteOrchestrationRepository(database), snapshot.run_id)
        try:
            service.delegate_child(
                root.task_id,
                parent_attempt=1,
                parent_worker_id="parent-worker",
                child_id=uuid4(),
                child_worker_id=f"child-{index}",
                child_lease_expires_at=now + timedelta(minutes=1),
                role="A2",
                scope=f"industry:{index}",
                now=now,
            )
            return True
        except DelegationLimitExceeded:
            return False

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sorted(pool.map(delegate, range(3))) == [False, True, True]
    state = repository.load(snapshot.run_id)
    assert sum(task.role == "A2" for task in state.tasks) == 2


def test_duplicate_active_a2_scope_is_rejected(tmp_path):
    from sector_pulse.application.orchestration.tasks import (
        DelegationLimitExceeded,
        TaskCoordinator,
    )

    _, repository, snapshot, root, _ = setup_task_state(tmp_path)
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(update={"revision": current.revision + 1, "tasks": (root,)}),
        current.revision,
        "unused.child.removed",
    )
    service = TaskCoordinator(repository, snapshot.run_id)
    now = datetime.now(UTC)
    service.start(
        root.task_id,
        attempt=1,
        worker_id="parent-worker",
        lease_expires_at=now + timedelta(minutes=1),
    )
    kwargs = {
        "parent_attempt": 1,
        "parent_worker_id": "parent-worker",
        "child_worker_id": "child-worker",
        "child_lease_expires_at": now + timedelta(minutes=1),
        "role": "A2",
        "scope": "industry:1",
        "now": now,
    }
    service.delegate_child(root.task_id, child_id=uuid4(), **kwargs)
    with pytest.raises(DelegationLimitExceeded, match="scope"):
        service.delegate_child(root.task_id, child_id=uuid4(), **kwargs)


def test_stale_attempt_cannot_submit_artifact(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator, TaskOwnershipError
    from sector_pulse.domain.orchestration.models import ArtifactRef

    _, repository, snapshot, root, _ = setup_task_state(tmp_path)
    service = TaskCoordinator(repository, snapshot.run_id)
    now = datetime.now(UTC)
    service.start(
        root.task_id,
        attempt=1,
        worker_id="worker-a",
        lease_expires_at=now - timedelta(seconds=1),
        now=now - timedelta(seconds=2),
    )
    service.recover(
        root.task_id,
        expected_attempt=1,
        worker_id="worker-b",
        lease_expires_at=now + timedelta(minutes=1),
        now=now,
    )

    late = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root.task_id,
        attempt=1,
        kind="analysis",
        reference="card:late",
    )
    with pytest.raises(TaskOwnershipError, match="stale task attempt"):
        service.submit_artifact(late, worker_id="worker-a", now=now)
    assert repository.load(snapshot.run_id).artifacts == ()


def test_stale_attempt_cannot_settle_or_start_model_call(tmp_path):
    from sector_pulse.application.orchestration.budget import SharedBudget
    from sector_pulse.application.orchestration.tasks import TaskCoordinator, TaskOwnershipError

    _, repository, snapshot, root, _ = setup_task_state(tmp_path)
    service = TaskCoordinator(repository, snapshot.run_id)
    now = datetime.now(UTC)
    service.start(
        root.task_id,
        attempt=1,
        worker_id="worker-a",
        lease_expires_at=now - timedelta(seconds=1),
        now=now - timedelta(seconds=2),
    )
    old_budget = SharedBudget(
        repository,
        snapshot.run_id,
        task_id=root.task_id,
        attempt=1,
        role="A0",
    )
    old_budget.reserve("model-old", 1, 1)
    service.recover(
        root.task_id,
        expected_attempt=1,
        worker_id="worker-b",
        lease_expires_at=now + timedelta(minutes=1),
        now=now,
    )

    with pytest.raises(TaskOwnershipError, match="stale task attempt"):
        old_budget.settle("model-old", 1)
    with pytest.raises(TaskOwnershipError, match="stale task attempt"):
        old_budget.reserve("model-late", 1, 1)
    state = repository.load(snapshot.run_id)
    reservation = state.ledger.reservations[0]
    assert reservation.task_id == root.task_id
    assert reservation.attempt == 1
    assert reservation.role == "A0"
    assert not reservation.settled


@pytest.mark.postgres
def test_postgres_task_recovery_uses_the_same_lease_and_cas_contract():
    import os

    from sector_pulse.application.orchestration.tasks import (
        DelegationLimitExceeded,
        TaskCoordinator,
        TaskOwnershipError,
    )
    from sector_pulse.domain.orchestration.models import ArtifactRef, RunSnapshot, TaskRecord
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
    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresOrchestrationRepository(database)
    task = TaskRecord(task_id=uuid4(), role="A0", scope="run")
    input_artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=task.task_id,
        kind="candidate_selection",
        reference="selection:7",
    )
    now = datetime.now(UTC)
    snapshot = RunSnapshot(
        run_id=uuid4(),
        deadline=now + timedelta(minutes=10),
        tasks=(task,),
        artifacts=(input_artifact,),
    )
    repository.save(snapshot, -1, "created")
    try:
        TaskCoordinator(repository, snapshot.run_id).start(
            task.task_id,
            attempt=1,
            worker_id="dead-worker",
            lease_expires_at=now - timedelta(seconds=1),
            now=now - timedelta(seconds=2),
        )

        def recover(worker_id):
            service = TaskCoordinator(PostgresOrchestrationRepository(database), snapshot.run_id)
            try:
                service.recover(
                    task.task_id,
                    expected_attempt=1,
                    worker_id=worker_id,
                    lease_expires_at=now + timedelta(minutes=1),
                    now=now,
                )
                return True
            except TaskOwnershipError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(recover, ("worker-b", "worker-c"))) == [False, True]
        recovered = task_by_id(repository, snapshot.run_id, task.task_id)
        assert recovered.attempt == 2
        assert recovered.worker_id in {"worker-b", "worker-c"}
        coordinator = TaskCoordinator(repository, snapshot.run_id)
        for index in range(2):
            coordinator.delegate_child(
                task.task_id,
                parent_attempt=2,
                parent_worker_id=recovered.worker_id,
                child_id=uuid4(),
                child_worker_id=f"research-{index}",
                child_lease_expires_at=now + timedelta(minutes=1),
                role="A2",
                scope=f"industry:{index}",
                input_artifact_ids=(input_artifact.artifact_id,),
                selection_version=7,
                now=now,
            )
        persisted = repository.load(snapshot.run_id)
        children = tuple(item for item in persisted.tasks if item.parent_id == task.task_id)
        assert all(item.input_artifact_ids == (input_artifact.artifact_id,) for item in children)
        assert all(item.selection_version == 7 for item in children)
        with pytest.raises(DelegationLimitExceeded):
            coordinator.delegate_child(
                task.task_id,
                parent_attempt=2,
                parent_worker_id=recovered.worker_id,
                child_id=uuid4(),
                child_worker_id="research-3",
                child_lease_expires_at=now + timedelta(minutes=1),
                role="A2",
                scope="industry:3",
                now=now,
            )
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM orchestration_events WHERE run_id=:run"),
                {"run": str(snapshot.run_id)},
            )
            connection.execute(
                text("DELETE FROM orchestration_snapshots WHERE run_id=:run"),
                {"run": str(snapshot.run_id)},
            )
        database.close()


def test_only_the_root_task_records_when_the_run_stopped_working(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord, TaskStatus
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "run-finish.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    observed_at = datetime(2026, 9, 15, 2, 0, tzinfo=UTC)
    deadline = observed_at + timedelta(minutes=30)
    root_lease = observed_at + timedelta(minutes=2)
    root = TaskRecord(task_id=uuid4(), role="A0", scope="run")
    child = TaskRecord(task_id=uuid4(), parent_id=root.task_id, role="A2", scope="industry:1")
    snapshot = RunSnapshot(
        run_id=uuid4(),
        requested_at=observed_at,
        deadline=deadline,
        tasks=(root, child),
    )
    repository.save(snapshot, -1, "created")
    service = TaskCoordinator(repository, snapshot.run_id)
    service.start(
        root.task_id,
        attempt=1,
        worker_id="root-agent",
        lease_expires_at=root_lease,
        now=observed_at,
    )
    service.start(
        child.task_id,
        attempt=1,
        worker_id="child-agent",
        lease_expires_at=deadline,
        now=observed_at,
    )

    assert repository.load(snapshot.run_id).finished_at is None

    service.transition(
        child.task_id,
        attempt=1,
        worker_id="child-agent",
        target=TaskStatus.COMPLETED,
        now=observed_at + timedelta(seconds=30),
    )

    assert repository.load(snapshot.run_id).finished_at is None

    service.transition(
        root.task_id,
        attempt=1,
        worker_id="root-agent",
        target=TaskStatus.INTERRUPTED,
        now=observed_at + timedelta(minutes=1),
    )

    assert repository.load(snapshot.run_id).finished_at == observed_at + timedelta(minutes=1)

    recovered = service.recover(
        root.task_id,
        expected_attempt=1,
        worker_id="root-agent-2",
        lease_expires_at=deadline,
        now=observed_at + timedelta(minutes=9),
    )

    assert recovered.status is TaskStatus.RUNNING
    assert repository.load(snapshot.run_id).finished_at is None

    service.transition(
        root.task_id,
        attempt=2,
        worker_id="root-agent-2",
        target=TaskStatus.WAITING_USER_REVIEW,
        now=observed_at + timedelta(minutes=9, seconds=30),
    )

    assert repository.load(snapshot.run_id).finished_at == observed_at + timedelta(
        minutes=9, seconds=30
    )

    service.start(
        root.task_id,
        attempt=2,
        worker_id="root-agent-3",
        lease_expires_at=deadline,
        now=observed_at + timedelta(minutes=10),
    )

    assert repository.load(snapshot.run_id).finished_at is None
