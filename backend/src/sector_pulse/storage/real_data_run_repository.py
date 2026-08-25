import json
from datetime import datetime
from uuid import UUID

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.quality import QualityStatus
from sector_pulse.domain.real_data_run import (
    RealDataCandidate,
    RealDataQualitySummary,
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)
from sector_pulse.storage.sqlite import SQLiteDatabase


class SQLiteRealDataRunRepository:
    """持久化真实数据运行的可审计摘要，不保存密钥、原始响应或新闻正文。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def insert(self, run: RealDataRun) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """INSERT INTO real_data_runs
                (run_id, mode, status, requested_at, cutoff_at, request_json,
                 market_quality_json, news_quality_json, downgrade_reasons_json,
                 cutoff_violation_count, duplicate_document_count, error_code, finished_at,
                 provider)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                self._run_values(run),
            )

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
        with self._database.transaction() as connection:
            connection.execute(
                """UPDATE real_data_runs SET status = ?, cutoff_at = ?,
                market_quality_json = ?, news_quality_json = ?, downgrade_reasons_json = ?,
                cutoff_violation_count = ?, duplicate_document_count = ?, error_code = ?,
                finished_at = ? WHERE run_id = ?""",
                (
                    status.value,
                    cutoff_at.isoformat() if cutoff_at else None,
                    json.dumps({key: value.value for key, value in summary.market_quality.items()}),
                    json.dumps({key: value.value for key, value in summary.news_quality.items()}),
                    json.dumps(summary.downgrade_reasons, ensure_ascii=False),
                    summary.cutoff_violation_count,
                    summary.duplicate_document_count,
                    error_code,
                    finished_at.isoformat() if finished_at else None,
                    str(run_id),
                ),
            )

    def save_candidates(self, run_id: UUID, candidates: tuple[RealDataCandidate, ...]) -> None:
        with self._database.transaction() as connection:
            connection.execute("DELETE FROM real_data_candidates WHERE run_id = ?", (str(run_id),))
            connection.executemany(
                """INSERT INTO real_data_candidates
                (run_id, sector_id, sector_kind, rank, score, reasons_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        str(run_id), item.sector_id, item.sector_kind.value, item.rank,
                        str(item.score), json.dumps(item.reasons, ensure_ascii=False),
                    )
                    for item in candidates
                ],
            )

    def get_run(self, run_id: UUID) -> RealDataRun | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM real_data_runs WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        return self._row_to_run(row) if row else None

    def list_runs(self, limit: int = 50) -> list[RealDataRun]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM real_data_runs ORDER BY requested_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def get_candidates(self, run_id: UUID) -> list[RealDataCandidate]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT sector_id, sector_kind, rank, score, reasons_json "
                "FROM real_data_candidates WHERE run_id = ? ORDER BY rank", (str(run_id),)
            ).fetchall()
        return [
            RealDataCandidate(
                sector_id=row[0], sector_kind=SectorKind(row[1]), rank=row[2],
                score=row[3], reasons=tuple(json.loads(row[4])),
            )
            for row in rows
        ]

    def mark_interrupted(self) -> int:
        terminal = tuple(status.value for status in RealDataRunStatus if status.is_terminal)
        placeholders = ",".join("?" for _ in terminal)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE real_data_runs SET status = 'INTERRUPTED' "
                f"WHERE status NOT IN ({placeholders})", terminal
            )
        return cursor.rowcount

    @staticmethod
    def _run_values(run: RealDataRun) -> tuple[object, ...]:
        quality = run.quality
        return (
            str(run.run_id), run.request.mode, run.status.value,
            run.request.requested_at.isoformat(),
            run.cutoff_at.isoformat() if run.cutoff_at else None,
            json.dumps(run.request.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
            json.dumps({key: value.value for key, value in quality.market_quality.items()}),
            json.dumps({key: value.value for key, value in quality.news_quality.items()}),
            json.dumps(quality.downgrade_reasons, ensure_ascii=False),
            quality.cutoff_violation_count, quality.duplicate_document_count,
            run.error_code, run.finished_at.isoformat() if run.finished_at else None,
            run.provider,
        )

    @staticmethod
    def _row_to_run(row: tuple[object, ...]) -> RealDataRun:
        request = RealDataRunRequest.model_validate(json.loads(row[5]))
        quality = RealDataQualitySummary(
            market_quality={key: QualityStatus(value) for key, value in json.loads(row[6]).items()},
            news_quality={key: QualityStatus(value) for key, value in json.loads(row[7]).items()},
            downgrade_reasons=tuple(json.loads(row[8])),
            cutoff_violation_count=row[9], duplicate_document_count=row[10],
        )
        return RealDataRun(
            run_id=UUID(row[0]), request=request, status=RealDataRunStatus(row[2]),
            provider=row[13],
            cutoff_at=datetime.fromisoformat(row[4]) if row[4] else None,
            quality=quality, error_code=row[11],
            finished_at=datetime.fromisoformat(row[12]) if row[12] else None,
        )
