from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from sector_pulse.domain.market.market import SectorKind


class SectorCandidate(BaseModel):
    """候选板块及其可解释召回分数，不代表最终文章精选结果。"""

    model_config = ConfigDict(frozen=True)

    rank: int
    provider_sector_id: str
    name: str
    kind: SectorKind
    score: Decimal
    reasons: tuple[str, ...]
