"""Orchestration CAS semantics with native database transaction adapters."""

import json
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from uuid import UUID

from sector_pulse.domain.orchestration.models import RunSnapshot
from sector_pulse.ports.orchestration import AtomicWrite, RevisionConflict, TransactionSession

Session = TransactionSession


class OrchestrationRepository(ABC):
    @abstractmethod
    def transaction(self) -> AbstractContextManager[Session]: ...

    def load(self, run_id: UUID) -> RunSnapshot | None:
        with self.transaction() as session:
            rows = session.rows(
                "SELECT payload_json FROM orchestration_snapshots WHERE run_id=:run",
                {"run": str(run_id)},
            )
        return RunSnapshot.model_validate_json(rows[0][0]) if rows else None

    def list_snapshots(self, limit: int | None = 50) -> list[RunSnapshot]:
        if limit is not None and limit <= 0:
            return []
        statement = "SELECT payload_json FROM orchestration_snapshots ORDER BY run_id"
        params: dict[str, object] = {}
        if limit is not None:
            statement += " LIMIT :limit"
            params["limit"] = limit
        with self.transaction() as session:
            rows = session.rows(statement, params)
        return [RunSnapshot.model_validate_json(row[0]) for row in rows]

    def save(self, snapshot: RunSnapshot, expected_revision: int, event: str = "updated") -> None:
        snapshot = RunSnapshot.model_validate_json(snapshot.model_dump_json())
        if snapshot.revision != expected_revision + 1 or not event:
            raise ValueError("invalid revision or event")
        with self.transaction() as session:
            self._save_in_transaction(session, snapshot, expected_revision, event)

    def save_atomic(
        self,
        snapshot: RunSnapshot,
        expected_revision: int,
        event: str,
        operation: AtomicWrite,
    ) -> None:
        snapshot = RunSnapshot.model_validate_json(snapshot.model_dump_json())
        if snapshot.revision != expected_revision + 1 or not event:
            raise ValueError("invalid revision or event")
        with self.transaction() as session:
            operation(session)
            self._save_in_transaction(session, snapshot, expected_revision, event)

    @staticmethod
    def _save_in_transaction(
        session: Session,
        snapshot: RunSnapshot,
        expected_revision: int,
        event: str,
    ) -> None:
        params = {
            "run": str(snapshot.run_id),
            "revision": snapshot.revision,
            "payload": snapshot.model_dump_json(),
            "expected": expected_revision,
        }
        if expected_revision == -1:
            count = session.execute(
                "INSERT INTO orchestration_snapshots (run_id,revision,payload_json) "
                "VALUES (:run,:revision,:payload) ON CONFLICT (run_id) DO NOTHING",
                params,
            )
        else:
            count = session.execute(
                "UPDATE orchestration_snapshots SET revision=:revision,payload_json=:payload "
                "WHERE run_id=:run AND revision=:expected",
                params,
            )
        if count != 1:
            raise RevisionConflict("snapshot revision changed")
        session.execute(
            "INSERT INTO orchestration_events (run_id,revision,event_json) "
            "VALUES (:run,:revision,:event)",
            {
                "run": str(snapshot.run_id),
                "revision": snapshot.revision,
                "event": json.dumps(event, ensure_ascii=False),
            },
        )

    def events(self, run_id: UUID) -> list[tuple[int, str]]:
        with self.transaction() as session:
            rows = session.rows(
                "SELECT revision,event_json FROM orchestration_events WHERE run_id=:run "
                "ORDER BY revision",
                {"run": str(run_id)},
            )
        return [(r[0], json.loads(r[1])) for r in rows]
