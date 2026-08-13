from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from sector_pulse.domain.market import SectorUniverseSnapshot


class DiagnosticRadarRow(BaseModel):
    """Phase 0 的确定性诊断行；只用于发现异动，不构成选股或投资建议。"""

    model_config = ConfigDict(frozen=True)

    rank: int
    provider_sector_id: str
    name: str
    diagnostic_score: Decimal
    pct_change: Decimal
    breadth_ratio: Decimal


def build_diagnostic_radar(
    universe: SectorUniverseSnapshot,
) -> tuple[DiagnosticRadarRow, ...]:
    """按涨跌、广度、龙头涨幅和换手率给板块做稳定排序。"""
    scored = [
        (
            sector,
            abs(sector.pct_change)
            + abs(sector.breadth_ratio - Decimal("0.5"))
            + abs(sector.leader_pct_change or Decimal("0")) / Decimal("10")
            + (sector.turnover_rate or Decimal("0")) / Decimal("10"),
        )
        for sector in universe.sectors
    ]
    scored.sort(key=lambda item: (-item[1], item[0].provider_sector_id))
    return tuple(
        DiagnosticRadarRow(
            rank=index,
            provider_sector_id=sector.provider_sector_id,
            name=sector.name,
            diagnostic_score=score,
            pct_change=sector.pct_change,
            breadth_ratio=sector.breadth_ratio,
        )
        for index, (sector, score) in enumerate(scored, start=1)
    )
