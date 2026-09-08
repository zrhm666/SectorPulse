from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.market.quality import QualityStatus


class EvidenceLevel(StrEnum):
    EXPLICIT_DRIVER = "EXPLICIT_DRIVER"
    POSSIBLE_CATALYST = "POSSIBLE_CATALYST"
    MARKET_ASSOCIATION = "MARKET_ASSOCIATION"
    NO_RELIABLE_EXPLANATION = "NO_RELIABLE_EXPLANATION"


class EvidencePack(BaseModel):
    """提供给后续 Agent 的只读事实和证据边界。"""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    sector_id: str
    sector_kind: SectorKind = SectorKind.INDUSTRY
    facts: tuple[str, ...]
    event_ids: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    quality_status: QualityStatus
    max_level: EvidenceLevel
