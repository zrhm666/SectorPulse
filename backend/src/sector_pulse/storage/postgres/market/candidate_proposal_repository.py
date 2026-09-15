from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.market.candidate_proposal import (
    CandidateProposal,
    CandidateProposalItem,
)
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresCandidateProposalRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get(self, proposal_id: UUID) -> CandidateProposal | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT run_id, candidate_batch_id, input_fingerprint, created_at "
                    "FROM candidate_proposals WHERE proposal_id = :proposal_id"
                ),
                {"proposal_id": str(proposal_id)},
            ).first()
            if row is None:
                return None
            items = connection.execute(
                text(
                    "SELECT provider_sector_id, sector_kind, sector_name, rank, score, "
                    "explanation FROM candidate_proposal_items "
                    "WHERE proposal_id = :proposal_id ORDER BY rank"
                ),
                {"proposal_id": str(proposal_id)},
            ).all()
        return CandidateProposal(
            proposal_id=proposal_id,
            run_id=UUID(str(row[0])),
            candidate_batch_id=UUID(str(row[1])),
            input_fingerprint=str(row[2]),
            created_at=datetime.fromisoformat(str(row[3])),
            items=tuple(
                CandidateProposalItem(
                    provider_sector_id=str(item[0]),
                    kind=SectorKind(str(item[1])),
                    name=str(item[2]),
                    rank=int(item[3]),
                    score=Decimal(str(item[4])),
                    explanation=str(item[5]),
                )
                for item in items
            ),
        )
