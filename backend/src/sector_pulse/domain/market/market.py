from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, computed_field


class SectorKind(StrEnum):
    INDUSTRY = "INDUSTRY"
    CONCEPT = "CONCEPT"


class SectorSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_sector_id: str
    name: str
    kind: SectorKind
    pct_change: Decimal
    turnover_rate: Decimal | None = None
    total_market_cap: Decimal | None = None
    advancers: int = 0
    decliners: int = 0
    leader_name: str | None = None
    leader_pct_change: Decimal | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def breadth_ratio(self) -> Decimal:
        total = self.advancers + self.decliners
        return Decimal(self.advancers) / Decimal(total) if total else Decimal("0.5")


class SectorUniverseSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_id: str
    classification_version: str
    source_version: str
    kind: SectorKind
    observed_at: datetime
    collected_at: datetime
    sectors: tuple[SectorSnapshot, ...]
    available_fields: frozenset[str] = frozenset()
    raw_artifact_sha256: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sector_count(self) -> int:
        return len(self.sectors)
