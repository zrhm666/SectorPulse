import json
from datetime import datetime
from typing import Literal
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
                 provider, retry_of_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

    def list_comparison_runs(
        self, *, provider: Literal["fixture", "live"] | None = None,
        mode: Literal["intraday", "post_close"] | None = None,
        offset: int = 0, limit: int = 20,
    ) -> tuple[list[RealDataRun], int]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("invalid comparison pagination")
        terminal = tuple(status.value for status in RealDataRunStatus if status.is_terminal)
        parameters: list[object] = list(terminal)
        where = f"status IN ({','.join('?' for _ in terminal)})"
        if provider is not None:
            where += " AND provider = ?"
            parameters.append(provider)
        if mode is not None:
            where += " AND mode = ?"
            parameters.append(mode)
        with self._database.connection() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM real_data_runs WHERE {where}", parameters,
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM real_data_runs WHERE {where} "
                "ORDER BY requested_at DESC, run_id DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
        return [self._row_to_run(row) for row in rows], int(total)

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
            str(run.retry_of_run_id) if run.retry_of_run_id else None,
        )

    @staticmethod
    def _required_str(value: object, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"stored {field} must be a string")
        return value

    @classmethod
    def _quality_map(cls, value: object, field: str) -> dict[str, QualityStatus]:
        decoded = json.loads(cls._required_str(value, field))
        if not isinstance(decoded, dict):
            raise ValueError(f"stored {field} must be an object")
        result: dict[str, QualityStatus] = {}
        for key, item in decoded.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise ValueError(f"stored {field} entries must be strings")
            result[key] = QualityStatus(item)
        return result

    @classmethod
    def _reasons(cls, value: object) -> tuple[str, ...]:
        decoded = json.loads(cls._required_str(value, "downgrade_reasons_json"))
        if not isinstance(decoded, list) or not all(
            isinstance(item, str) for item in decoded
        ):
            raise ValueError("stored downgrade reasons must be a string list")
        return tuple(decoded)

    @staticmethod
    def _required_int(value: object, field: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"stored {field} must be an integer")
        return value

    @classmethod
    def _row_to_run(cls, row: tuple[object, ...]) -> RealDataRun:
        request = RealDataRunRequest.model_validate(
            json.loads(cls._required_str(row[5], "request_json"))
        )
        quality = RealDataQualitySummary(
            market_quality=cls._quality_map(row[6], "market_quality_json"),
            news_quality=cls._quality_map(row[7], "news_quality_json"),
            downgrade_reasons=cls._reasons(row[8]),
            cutoff_violation_count=cls._required_int(row[9], "cutoff_violation_count"),
            duplicate_document_count=cls._required_int(
                row[10], "duplicate_document_count"
            ),
        )
        provider = cls._required_str(row[13], "provider")
        typed_provider: Literal["fixture", "live"]
        if provider == "fixture":
            typed_provider = "fixture"
        elif provider == "live":
            typed_provider = "live"
        else:
            raise ValueError("stored provider is invalid")
        return RealDataRun(
            run_id=UUID(cls._required_str(row[0], "run_id")),
            request=request,
            status=RealDataRunStatus(cls._required_str(row[2], "status")),
            provider=typed_provider,
            retry_of_run_id=(
                UUID(cls._required_str(row[14], "retry_of_run_id")) if row[14] else None
            ),
            cutoff_at=(
                datetime.fromisoformat(cls._required_str(row[4], "cutoff_at"))
                if row[4]
                else None
            ),
            quality=quality,
            error_code=(cls._required_str(row[11], "error_code") if row[11] else None),
            finished_at=(
                datetime.fromisoformat(cls._required_str(row[12], "finished_at"))
                if row[12]
                else None
            ),
        )
