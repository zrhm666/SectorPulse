import json
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.quality import QualityStatus
from sector_pulse.domain.real_data_run import (
    RealDataCandidate,
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

    def insert(self, run: RealDataRun) -> None:
        quality = run.quality
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO real_data_runs
                    (run_id, mode, status, requested_at, cutoff_at, request_json,
                     market_quality_json, news_quality_json, downgrade_reasons_json,
                     cutoff_violation_count, duplicate_document_count, error_code, finished_at,
                     provider, retry_of_run_id)
                    VALUES (:run_id, :mode, :status, :requested_at, :cutoff_at, :request_json,
                     :market_quality_json, :news_quality_json, :downgrade_reasons_json,
                     :cutoff_violation_count, :duplicate_document_count, :error_code,
                     :finished_at, :provider, :retry_of_run_id)"""
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
                    "provider": run.provider,
                    "retry_of_run_id": (
                        str(run.retry_of_run_id) if run.retry_of_run_id else None
                    ),
                },
            )

    def get_run(self, run_id: UUID) -> RealDataRun | None:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text("SELECT * FROM real_data_runs WHERE run_id = :run_id"),
                {"run_id": str(run_id)},
            )
            row = result.mappings().first()
        return self._row_to_run(row) if row else None

    def list_runs(self, limit: int = 50) -> list[RealDataRun]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text(
                    "SELECT * FROM real_data_runs "
                    "ORDER BY requested_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
            rows = result.mappings().all()
        return [self._row_to_run(row) for row in rows]

    def update_status(
        self,
        run_id: UUID,
        status: RealDataRunStatus,
        *,
        cutoff_at: datetime | None = None,
        quality: RealDataQualitySummary | None = None,
        error_code: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        summary = quality or RealDataQualitySummary()
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    "UPDATE real_data_runs SET status = :status, cutoff_at = :cutoff_at, "
                    "market_quality_json = :market_quality_json, "
                    "news_quality_json = :news_quality_json, "
                    "downgrade_reasons_json = :downgrade_reasons_json, "
                    "cutoff_violation_count = :cutoff_violation_count, "
                    "duplicate_document_count = :duplicate_document_count, "
                    "error_code = :error_code, finished_at = :finished_at "
                    "WHERE run_id = :run_id"
                ),
                {
                    "run_id": str(run_id),
                    "status": status.value,
                    "cutoff_at": cutoff_at.isoformat() if cutoff_at else None,
                    "market_quality_json": json.dumps(
                        {key: value.value for key, value in summary.market_quality.items()}
                    ),
                    "news_quality_json": json.dumps(
                        {key: value.value for key, value in summary.news_quality.items()}
                    ),
                    "downgrade_reasons_json": json.dumps(summary.downgrade_reasons),
                    "cutoff_violation_count": summary.cutoff_violation_count,
                    "duplicate_document_count": summary.duplicate_document_count,
                    "error_code": error_code,
                    "finished_at": finished_at.isoformat() if finished_at else None,
                },
            )

    def save_candidates(
        self, run_id: UUID, candidates: tuple[RealDataCandidate, ...]
    ) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM real_data_candidates WHERE run_id = :run_id"),
                {"run_id": str(run_id)},
            )
            if candidates:
                connection.execute(
                    text(
                        "INSERT INTO real_data_candidates "
                        "(run_id, sector_id, sector_kind, rank, score, reasons_json) "
                        "VALUES (:run_id, :sector_id, :sector_kind, :rank, :score, :reasons_json)"
                    ),
                    [
                        {
                            "run_id": str(run_id),
                            "sector_id": item.sector_id,
                            "sector_kind": item.sector_kind.value,
                            "rank": item.rank,
                            "score": str(item.score),
                            "reasons_json": json.dumps(item.reasons),
                        }
                        for item in candidates
                    ],
                )

    def get_candidates(self, run_id: UUID) -> list[RealDataCandidate]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text(
                    "SELECT sector_id, sector_kind, rank, score, reasons_json "
                    "FROM real_data_candidates WHERE run_id = :run_id ORDER BY rank"
                ),
                {"run_id": str(run_id)},
            )
            rows = result.mappings().all()
        return [
            RealDataCandidate(
                sector_id=row["sector_id"],
                sector_kind=SectorKind(row["sector_kind"]),
                rank=row["rank"],
                score=row["score"],
                reasons=tuple(json.loads(row["reasons_json"])),
            )
            for row in rows
        ]

    def mark_interrupted(self) -> int:
        terminal = tuple(status.value for status in RealDataRunStatus if status.is_terminal)
        parameters = {f"terminal_{index}": value for index, value in enumerate(terminal)}
        placeholders = ", ".join(f":terminal_{index}" for index in range(len(terminal)))
        with self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE real_data_runs SET status = 'INTERRUPTED' "
                    f"WHERE status NOT IN ({placeholders})"
                ),
                parameters,
            )
        return result.rowcount

    @staticmethod
    def _row_to_run(row: RowMapping) -> RealDataRun:
        request = RealDataRunRequest.model_validate(
            json.loads(str(row["request_json"]))
        )
        quality = RealDataQualitySummary(
            market_quality={
                k: QualityStatus(v)
                for k, v in json.loads(str(row["market_quality_json"])).items()
            },
            news_quality={
                k: QualityStatus(v)
                for k, v in json.loads(str(row["news_quality_json"])).items()
            },
            downgrade_reasons=tuple(
                json.loads(str(row["downgrade_reasons_json"]))
            ),
            cutoff_violation_count=int(str(row["cutoff_violation_count"])),
            duplicate_document_count=int(str(row["duplicate_document_count"])),
        )
        provider_value = str(row["provider"])
        if provider_value not in {"fixture", "live"}:
            raise ValueError("stored provider is invalid")
        provider = cast(Literal["fixture", "live"], provider_value)
        return RealDataRun(
            run_id=UUID(str(row["run_id"])),
            provider=provider,
            request=request,
            status=RealDataRunStatus(str(row["status"])),
            cutoff_at=(
                datetime.fromisoformat(str(row["cutoff_at"]))
                if row["cutoff_at"]
                else None
            ),
            quality=quality,
            error_code=str(row["error_code"]) if row["error_code"] else None,
            finished_at=(
                datetime.fromisoformat(str(row["finished_at"]))
                if row["finished_at"]
                else None
            ),
            retry_of_run_id=(
                UUID(str(row["retry_of_run_id"])) if row["retry_of_run_id"] else None
            ),
        )
