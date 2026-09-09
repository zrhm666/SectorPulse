from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from sector_pulse.domain.runs.real_data_run import (
    RealDataCandidate,
    RealDataQualitySummary,
    RealDataRun,
    RealDataRunStatus,
)
from sector_pulse.storage.sqlite.runs.phase1b_runs_repository import Phase1BRunRow


@runtime_checkable
class RealDataRunRepositoryPort(Protocol):
    def insert(self, run: RealDataRun) -> None: ...

    def update_status(
        self,
        run_id: UUID,
        status: RealDataRunStatus,
        *,
        cutoff_at: datetime | None = None,
        quality: RealDataQualitySummary | None = None,
        error_code: str | None = None,
        finished_at: datetime | None = None,
    ) -> None: ...

    def save_candidates(
        self, run_id: UUID, candidates: tuple[RealDataCandidate, ...]
    ) -> None: ...

    def get_run(self, run_id: UUID) -> RealDataRun | None: ...

    def list_runs(self, limit: int = 50) -> list[RealDataRun]: ...

    def list_comparison_runs(
        self, *, provider: Literal["fixture", "live"] | None = None,
        mode: Literal["intraday", "post_close"] | None = None,
        offset: int = 0, limit: int = 20,
    ) -> tuple[list[RealDataRun], int]: ...

    def get_candidates(self, run_id: UUID) -> list[RealDataCandidate]: ...

    def mark_interrupted(self) -> int: ...



@runtime_checkable
class Phase1BRunsRepositoryPort(Protocol):
    def mark_interrupted(self, now: datetime) -> int: ...

    def insert(self, run: Phase1BRunRow) -> None: ...

    def update_status(
        self,
        run_id: UUID,
        status: str,
        elapsed_ms: int | None = None,
        total_cost_cny: str | None = None,
        draft_id: UUID | None = None,
        error_message: str | None = None,
        finished_at: datetime | None = None,
    ) -> None: ...

    def list_runs(self, limit: int = 50) -> list[Phase1BRunRow]: ...

    def get_run(self, run_id: UUID) -> Phase1BRunRow | None: ...
