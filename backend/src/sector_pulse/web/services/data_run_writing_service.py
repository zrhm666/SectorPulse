from pathlib import Path
from typing import Literal, Protocol, cast
from uuid import UUID

from sector_pulse.application.data_runs.real_data_writing_bridge import build_phase1b_request
from sector_pulse.domain.market.candidate_selection import CandidateSelection
from sector_pulse.domain.runs.real_data_run import RealDataRunStatus
from sector_pulse.storage.database_runtime import Database
from sector_pulse.storage.ports.runs import RealDataRunRepositoryPort
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.runtime_bundle import RuntimeStorageBundle
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.runs.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.web.services.run_service import RunService


class DataRunContinuationCommands(Protocol):
    def continue_data_run(
        self,
        run_id: UUID,
        selection: CandidateSelection,
        *,
        provider: Literal["fixture", "live"],
    ) -> UUID: ...


class DataRunArticleStarter(Protocol):
    def generate(self, run_id: UUID, selection: CandidateSelection) -> UUID: ...


class MultiAgentDataRunWritingService:
    """Continue a confirmed data run through the sole parent-agent engine."""

    def __init__(
        self,
        runs: RealDataRunRepositoryPort,
        commands: DataRunContinuationCommands,
    ) -> None:
        self._runs = runs
        self._commands = commands

    def generate(self, run_id: UUID, selection: CandidateSelection) -> UUID:
        run = self._runs.get_run(run_id)
        if run is None:
            raise ValueError("REAL_DATA_RUN_NOT_FOUND")
        if run.status is not RealDataRunStatus.READY_FOR_ATTRIBUTION:
            raise ValueError("REAL_DATA_RUN_NOT_READY")
        if selection.run_id != run_id:
            raise ValueError("confirmed selection must belong to the data run")
        return self._commands.continue_data_run(
            run_id,
            selection,
            provider=run.provider,
        )


class DataRunWritingService:
    """将已就绪真实运行桥接到现有 Phase 1B 任务。"""

    def __init__(
        self,
        database: Database,
        run_service: RunService,
        consent_file: Path | None = None,
        storage: RuntimeStorageBundle | None = None,
    ) -> None:
        self._database = database
        self._run_service = run_service
        if isinstance(database, PostgresDatabase) and storage is None:
            raise ValueError("PostgreSQL writing service requires runtime storage")
        self._repository = (
            storage.real_data_runs
            if storage is not None
            else SQLiteRealDataRunRepository(cast(SQLiteDatabase, database))
        )
        self._storage = storage
        self._consent_file = consent_file or Path(".live-llm-consent")

    def generate(self, run_id: UUID, selection: CandidateSelection) -> UUID:
        if not self._consent_file.is_file():
            raise ValueError("LIVE_LLM_CONSENT_REQUIRED")
        run = self._repository.get_run(run_id)
        if run is None:
            raise ValueError("REAL_DATA_RUN_NOT_FOUND")
        if run.status is not RealDataRunStatus.READY_FOR_ATTRIBUTION:
            raise ValueError("REAL_DATA_RUN_NOT_READY")
        request = build_phase1b_request(
            self._database,
            run_id,
            self._storage,
            selected_sector_ids=selection.selected_sector_ids,
        )
        return self._run_service.create_run(request.model_dump(mode="json"), "live", run_id=run_id)
