from decimal import Decimal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from sector_pulse.domain.market.market import SectorKind


class CandidateProposalItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_sector_id: str
    kind: SectorKind
    name: str
    rank: int = Field(ge=1)
    score: Decimal
    explanation: str = Field(min_length=1, max_length=1000)


class CandidateProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: UUID
    run_id: UUID
    candidate_batch_id: UUID
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime
    items: tuple[CandidateProposalItem, ...] = Field(min_length=3, max_length=12)

    @model_validator(mode="after")
    def validate_items(self) -> "CandidateProposal":
        identities = {(item.provider_sector_id, item.kind) for item in self.items}
        if len(identities) != len(self.items):
            raise ValueError("candidate proposal sector IDs must be unique")
        ranks = tuple(item.rank for item in self.items)
        if ranks != tuple(sorted(ranks)):
            raise ValueError("candidate proposal items must follow candidate rank")
        return self
