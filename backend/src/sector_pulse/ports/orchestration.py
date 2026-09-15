from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

from sector_pulse.domain.orchestration.models import ArtifactRef, RunSnapshot


class RevisionConflict(RuntimeError):
    """The snapshot changed since it was loaded; caller must reload."""


class TransactionSession(Protocol):
    def execute(self, sql: str, params: dict[str, Any]) -> int: ...

    def rows(self, sql: str, params: dict[str, Any]) -> list[tuple[Any, ...]]: ...


AtomicWrite = Callable[[TransactionSession], None]


class ArtifactPersistence(Protocol):
    """A business-specific adapter that writes and verifies one artifact."""

    def write(self, session: TransactionSession, artifact: ArtifactRef) -> None: ...

    def exists(self, session: TransactionSession, artifact: ArtifactRef) -> bool: ...


class SnapshotRepository(Protocol):
    def load(self, run_id: UUID) -> RunSnapshot | None: ...

    def list_snapshots(self, limit: int | None = 50) -> list[RunSnapshot]: ...

    def save(
        self, snapshot: RunSnapshot, expected_revision: int, event: str = "updated"
    ) -> None: ...

    def save_atomic(
        self,
        snapshot: RunSnapshot,
        expected_revision: int,
        event: str,
        operation: AtomicWrite,
    ) -> None: ...

    def events(self, run_id: UUID) -> list[tuple[int, str]]: ...
