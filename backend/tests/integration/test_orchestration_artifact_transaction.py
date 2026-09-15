from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest


class PayloadPersistence:
    def __init__(self, payload, *, fail_after_write=False, skip_write=False):
        self.payload = payload
        self.fail_after_write = fail_after_write
        self.skip_write = skip_write

    def write(self, session, artifact):
        if not self.skip_write:
            session.execute(
                "INSERT INTO test_business_artifacts (reference, payload) "
                "VALUES (:reference, :payload)",
                {"reference": artifact.reference, "payload": self.payload},
            )
        if self.fail_after_write:
            raise RuntimeError("simulated business write failure")

    def exists(self, session, artifact):
        return bool(
            session.rows(
                "SELECT 1 FROM test_business_artifacts WHERE reference=:reference",
                {"reference": artifact.reference},
            )
        )


def setup_transaction_state(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "artifact-transaction.db")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "CREATE TABLE test_business_artifacts "
            "(reference TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
    repository = SQLiteOrchestrationRepository(database)
    task = TaskRecord(task_id=uuid4(), role="A0", scope="run")
    snapshot = RunSnapshot(
        run_id=uuid4(),
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        tasks=(task,),
    )
    repository.save(snapshot, -1, "created")
    now = datetime.now(UTC)
    TaskCoordinator(repository, snapshot.run_id).start(
        task.task_id,
        attempt=1,
        worker_id="worker-a",
        lease_expires_at=now + timedelta(minutes=1),
    )
    return database, repository, snapshot, task, now


def business_payload(database, reference):
    with database.connection() as connection:
        row = connection.execute(
            "SELECT payload FROM test_business_artifacts WHERE reference=?", (reference,)
        ).fetchone()
    return row[0] if row else None


def artifact_for(task, reference="draft:1"):
    from sector_pulse.domain.orchestration.models import ArtifactRef

    return ArtifactRef(
        artifact_id=uuid4(),
        task_id=task.task_id,
        attempt=1,
        kind="draft",
        reference=reference,
    )


def test_business_payload_index_and_event_commit_in_one_transaction(tmp_path):
    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter

    database, repository, snapshot, task, now = setup_transaction_state(tmp_path)
    artifact = artifact_for(task)
    AtomicArtifactCommitter(repository, snapshot.run_id).commit(
        artifact,
        worker_id="worker-a",
        persistence=PayloadPersistence("complete draft"),
        now=now,
    )
    state = repository.load(snapshot.run_id)
    assert business_payload(database, artifact.reference) == "complete draft"
    assert state.artifacts == (artifact,)
    assert repository.events(snapshot.run_id)[-1][1] == f"artifact.committed:{artifact.artifact_id}"


def test_business_failure_rolls_back_payload_index_and_event(tmp_path):
    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter

    database, repository, snapshot, task, now = setup_transaction_state(tmp_path)
    artifact = artifact_for(task)
    before = repository.load(snapshot.run_id)
    with pytest.raises(RuntimeError, match="simulated business write failure"):
        AtomicArtifactCommitter(repository, snapshot.run_id).commit(
            artifact,
            worker_id="worker-a",
            persistence=PayloadPersistence("partial", fail_after_write=True),
            now=now,
        )
    after = repository.load(snapshot.run_id)
    assert business_payload(database, artifact.reference) is None
    assert after.artifacts == ()
    assert after.revision == before.revision
    assert [event for _, event in repository.events(snapshot.run_id)] == [
        "created",
        f"task.started:{task.task_id}:1",
    ]


def test_missing_business_payload_cannot_publish_artifact_index(tmp_path):
    from sector_pulse.application.orchestration.artifacts import (
        ArtifactPersistenceError,
        AtomicArtifactCommitter,
    )

    database, repository, snapshot, task, now = setup_transaction_state(tmp_path)
    artifact = artifact_for(task)
    before = repository.load(snapshot.run_id)
    with pytest.raises(ArtifactPersistenceError, match="not visible"):
        AtomicArtifactCommitter(repository, snapshot.run_id).commit(
            artifact,
            worker_id="worker-a",
            persistence=PayloadPersistence("ignored", skip_write=True),
            now=now,
        )
    assert business_payload(database, artifact.reference) is None
    assert repository.load(snapshot.run_id).revision == before.revision
    assert repository.load(snapshot.run_id).artifacts == ()


def test_snapshot_cas_conflict_rolls_back_business_payload(tmp_path):
    from sector_pulse.domain.orchestration.models import ArtifactRef
    from sector_pulse.ports.orchestration import RevisionConflict

    database, repository, snapshot, task, _ = setup_transaction_state(tmp_path)
    stale = repository.load(snapshot.run_id)
    current = stale.model_copy(update={"revision": stale.revision + 1})
    repository.save(current, stale.revision, "concurrent.update")
    artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=task.task_id,
        attempt=1,
        kind="draft",
        reference="draft:stale",
    )
    stale_with_artifact = stale.model_copy(
        update={"revision": stale.revision + 1, "artifacts": (artifact,)}
    )
    with pytest.raises(RevisionConflict):
        repository.save_atomic(
            stale_with_artifact,
            stale.revision,
            f"artifact.committed:{artifact.artifact_id}",
            lambda session: PayloadPersistence("must roll back").write(session, artifact),
        )
    assert business_payload(database, artifact.reference) is None
    assert repository.load(snapshot.run_id).artifacts == ()


@pytest.mark.postgres
def test_postgres_business_payload_and_artifact_index_share_transaction():
    import os

    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
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
    now = datetime.now(UTC)
    snapshot = RunSnapshot(
        run_id=uuid4(),
        deadline=now + timedelta(minutes=5),
        tasks=(task,),
    )
    reference = f"test-artifact:{uuid4()}"
    artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=task.task_id,
        attempt=1,
        kind="test",
        reference=reference,
    )
    with database.start().begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS test_business_artifacts "
                "(reference TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
        )
    repository.save(snapshot, -1, "created")
    TaskCoordinator(repository, snapshot.run_id).start(
        task.task_id,
        attempt=1,
        worker_id="worker-a",
        lease_expires_at=now + timedelta(minutes=1),
        now=now,
    )
    try:
        AtomicArtifactCommitter(repository, snapshot.run_id).commit(
            artifact,
            worker_id="worker-a",
            persistence=PayloadPersistence("postgres payload"),
            now=now,
        )
        with database.start().connect() as connection:
            payload = connection.execute(
                text(
                    "SELECT payload FROM test_business_artifacts "
                    "WHERE reference=:reference"
                ),
                {"reference": reference},
            ).scalar_one()
        assert payload == "postgres payload"
        assert repository.load(snapshot.run_id).artifacts == (artifact,)
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM test_business_artifacts "
                    "WHERE reference=:reference"
                ),
                {"reference": reference},
            )
            connection.execute(
                text("DELETE FROM orchestration_events WHERE run_id=:run"),
                {"run": str(snapshot.run_id)},
            )
            connection.execute(
                text("DELETE FROM orchestration_snapshots WHERE run_id=:run"),
                {"run": str(snapshot.run_id)},
            )
        database.close()
