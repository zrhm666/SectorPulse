from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sector_pulse.domain.market.candidate_proposal import (
    CandidateProposal,
    CandidateProposalItem,
)
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteCandidateProposalRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get(self, proposal_id: UUID) -> CandidateProposal | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT run_id, candidate_batch_id, input_fingerprint, created_at "
                "FROM candidate_proposals WHERE proposal_id = ?",
                (str(proposal_id),),
            ).fetchone()
            if row is None:
                return None
            items = connection.execute(
                "SELECT provider_sector_id, sector_kind, sector_name, rank, score, "
                "explanation FROM candidate_proposal_items WHERE proposal_id = ? "
                "ORDER BY rank",
                (str(proposal_id),),
            ).fetchall()
        return CandidateProposal(
            proposal_id=proposal_id,
            run_id=UUID(row[0]),
            candidate_batch_id=UUID(row[1]),
            input_fingerprint=row[2],
            created_at=datetime.fromisoformat(row[3]),
            items=tuple(
                CandidateProposalItem(
                    provider_sector_id=item[0],
                    kind=SectorKind(item[1]),
                    name=item[2],
                    rank=item[3],
                    score=Decimal(item[4]),
                    explanation=item[5],
                )
                for item in items
            ),
        )
