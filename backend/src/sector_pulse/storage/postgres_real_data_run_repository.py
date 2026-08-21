import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.quality import QualityStatus
from sector_pulse.domain.real_data_run import (
    RealDataQualitySummary,
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresRealDataRunRepository:
    """PostgreSQL implementation for real-data run state and candidates."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def insert(self, run: RealDataRun) -> None:
        quality = run.quality
        async with self._database.engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO real_data_runs
                    (run_id, mode, status, requested_at, cutoff_at, request_json,
                     market_quality_json, news_quality_json, downgrade_reasons_json,
                     cutoff_violation_count, duplicate_document_count, error_code, finished_at)
                    VALUES (:run_id, :mode, :status, :requested_at, :cutoff_at, :request_json,
                     :market_quality_json, :news_quality_json, :downgrade_reasons_json,
                     :cutoff_violation_count, :duplicate_document_count, :error_code,
                     :finished_at)"""
                ),
                {
                    "run_id": str(run.run_id),
                    "mode": run.request.mode,
                    "status": run.status.value,
                    "requested_at": run.request.requested_at.isoformat(),
                    "cutoff_at": run.cutoff_at.isoformat() if run.cutoff_at else None,
                    "request_json": json.dumps(run.request.model_dump(mode="json"), sort_keys=True),
                    "market_quality_json": json.dumps(
                        {k: v.value for k, v in quality.market_quality.items()}
                    ),
                    "news_quality_json": json.dumps(
                        {k: v.value for k, v in quality.news_quality.items()}
                    ),
                    "downgrade_reasons_json": json.dumps(quality.downgrade_reasons),
                    "cutoff_violation_count": quality.cutoff_violation_count,
                    "duplicate_document_count": quality.duplicate_document_count,
                    "error_code": run.error_code,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                },
            )

    async def get_run(self, run_id: UUID) -> RealDataRun | None:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(
                text("SELECT * FROM real_data_runs WHERE run_id = :run_id"),
                {"run_id": str(run_id)},
            )
            row = result.mappings().first()
        return self._row_to_run(row) if row else None

    @staticmethod
    def _row_to_run(row: object) -> RealDataRun:
        request = RealDataRunRequest.model_validate(json.loads(row["request_json"]))
        quality = RealDataQualitySummary(
            market_quality={
                k: QualityStatus(v) for k, v in json.loads(row["market_quality_json"]).items()
            },
            news_quality={
                k: QualityStatus(v) for k, v in json.loads(row["news_quality_json"]).items()
            },
            downgrade_reasons=tuple(json.loads(row["downgrade_reasons_json"])),
            cutoff_violation_count=row["cutoff_violation_count"],
            duplicate_document_count=row["duplicate_document_count"],
        )
        return RealDataRun(
            run_id=UUID(row["run_id"]),
            request=request,
            status=RealDataRunStatus(row["status"]),
            cutoff_at=datetime.fromisoformat(row["cutoff_at"]) if row["cutoff_at"] else None,
            quality=quality,
            error_code=row["error_code"],
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        )
