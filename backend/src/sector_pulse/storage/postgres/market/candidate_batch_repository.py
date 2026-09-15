import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.market.candidate import SectorCandidate
from sector_pulse.domain.market.candidate_batch import CandidateBatch, CandidateRankingStage
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresCandidateBatchRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get(self, batch_id: UUID) -> CandidateBatch | None:
        with self._database.start().connect() as connection:
            batch = connection.execute(
                text(
                    "SELECT run_id, input_fingerprint, ranking_stage, candidate_limit, "
                    "created_at FROM candidate_batches WHERE batch_id = :batch_id"
                ),
                {"batch_id": str(batch_id)},
            ).first()
            rows = connection.execute(
                text(
                    "SELECT provider_sector_id, sector_kind, sector_name, rank, score, "
                    "reasons_json FROM sector_candidate_versions "
                    "WHERE batch_id = :batch_id ORDER BY rank"
                ),
                {"batch_id": str(batch_id)},
            ).fetchall()
        if batch is None:
            return None

        def parsed(value: object) -> datetime:
            return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))

        return CandidateBatch(
            batch_id=batch_id,
            run_id=UUID(str(batch[0])),
            input_fingerprint=str(batch[1]),
            ranking_stage=CandidateRankingStage(str(batch[2])),
            candidate_limit=int(batch[3]),
            created_at=parsed(batch[4]),
            candidates=tuple(
                SectorCandidate(
                    provider_sector_id=str(row[0]),
                    kind=SectorKind(str(row[1])),
                    name=str(row[2]),
                    rank=int(row[3]),
                    score=Decimal(str(row[4])),
                    reasons=tuple(json.loads(str(row[5]))),
                )
                for row in rows
            ),
        )

