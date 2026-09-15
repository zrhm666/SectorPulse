import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sector_pulse.domain.market.candidate import SectorCandidate
from sector_pulse.domain.market.candidate_batch import CandidateBatch, CandidateRankingStage
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteCandidateBatchRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get(self, batch_id: UUID) -> CandidateBatch | None:
        with self._database.connection() as connection:
            batch = connection.execute(
                "SELECT run_id, input_fingerprint, ranking_stage, candidate_limit, created_at "
                "FROM candidate_batches WHERE batch_id = ?",
                (str(batch_id),),
            ).fetchone()
            rows = connection.execute(
                "SELECT provider_sector_id, sector_kind, sector_name, rank, score, reasons_json "
                "FROM sector_candidate_versions WHERE batch_id = ? ORDER BY rank",
                (str(batch_id),),
            ).fetchall()
        if batch is None:
            return None
        return CandidateBatch(
            batch_id=batch_id,
            run_id=UUID(batch[0]),
            input_fingerprint=batch[1],
            ranking_stage=CandidateRankingStage(batch[2]),
            candidate_limit=batch[3],
            created_at=datetime.fromisoformat(batch[4]),
            candidates=tuple(
                SectorCandidate(
                    provider_sector_id=row[0],
                    kind=SectorKind(row[1]),
                    name=row[2],
                    rank=row[3],
                    score=Decimal(row[4]),
                    reasons=tuple(json.loads(row[5])),
                )
                for row in rows
            ),
        )

