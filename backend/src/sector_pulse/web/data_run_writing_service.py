from pathlib import Path
from uuid import UUID

from sector_pulse.application.real_data_writing_bridge import build_phase1b_request
from sector_pulse.domain.real_data_run import RealDataRunStatus
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.web.run_service import RunService


class DataRunWritingService:
    """将已就绪真实运行桥接到现有 Phase 1B 任务。"""

    def __init__(
        self,
        database: SQLiteDatabase,
        run_service: RunService,
        consent_file: Path | None = None,
        storage: object | None = None,
    ) -> None:
        self._database = database
        self._run_service = run_service
        self._repository = SQLiteRealDataRunRepository(database)
        if storage is not None:
            self._repository = storage.real_data_runs
        self._storage = storage
        self._consent_file = consent_file or Path(".live-llm-consent")

    def generate(self, run_id: UUID) -> UUID:
        if not self._consent_file.is_file():
            raise ValueError("LIVE_LLM_CONSENT_REQUIRED")
        run = self._repository.get_run(run_id)
        if run is None:
            raise ValueError("REAL_DATA_RUN_NOT_FOUND")
        if run.status is not RealDataRunStatus.READY_FOR_ATTRIBUTION:
            raise ValueError("REAL_DATA_RUN_NOT_READY")
        request = build_phase1b_request(self._database, run_id, self._storage)
        return self._run_service.create_run(request.model_dump(mode="json"), "live", run_id=run_id)
