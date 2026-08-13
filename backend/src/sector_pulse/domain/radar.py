from decimal import Decimal

from pydantic import BaseModel


class DiagnosticRadarRow(BaseModel):
    rank: int
    provider_sector_id: str
    name: str
    diagnostic_score: Decimal
    pct_change: Decimal
    breadth_ratio: Decimal


def build_diagnostic_radar(universe):
    scored = [
        (
            s,
            abs(s.pct_change)
            + abs(s.breadth_ratio - Decimal(".5"))
            + abs(s.leader_pct_change or 0) / 10
            + (s.turnover_rate or 0) / 10,
        )
        for s in universe.sectors
    ]
    scored.sort(key=lambda x: (-x[1], x[0].provider_sector_id))
    return tuple(
        DiagnosticRadarRow(
            rank=i,
            provider_sector_id=s.provider_sector_id,
            name=s.name,
            diagnostic_score=score,
            pct_change=s.pct_change,
            breadth_ratio=s.breadth_ratio,
        )
        for i, (s, score) in enumerate(scored, 1)
    )
