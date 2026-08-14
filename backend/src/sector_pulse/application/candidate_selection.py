from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sector_pulse.domain.candidate import SectorCandidate
from sector_pulse.domain.evidence import EvidenceLevel, EvidencePack
from sector_pulse.domain.market import SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.news import NewsEvent
from sector_pulse.domain.quality import QualityStatus


def _normalized(value: Decimal, values: list[Decimal]) -> Decimal:
    minimum, maximum = min(values), max(values)
    if maximum == minimum:
        return Decimal("0.5")
    return (value - minimum) / (maximum - minimum)


def select_candidates(
    industry: SectorUniverseSnapshot,
    concept: SectorUniverseSnapshot,
    events: Sequence[NewsEvent],
    limit: int = 12,
) -> tuple[SectorCandidate, ...]:
    """在行业/概念组内分别标准化，再合并为最多 limit 个候选。"""
    event_sector_ids = {sector_id for event in events for sector_id in event.sector_ids}
    candidates: list[tuple[SectorSnapshot, Decimal, tuple[str, ...]]] = []
    for universe in (industry, concept):
        sectors = list(universe.sectors)
        pct_values = [abs(sector.pct_change) for sector in sectors]
        turnover_values = [sector.turnover_rate or Decimal("0") for sector in sectors]
        breadth_values = [abs(sector.breadth_ratio - Decimal("0.5")) for sector in sectors]
        for index, sector in enumerate(sectors):
            reasons: list[str] = []
            score = (
                _normalized(pct_values[index], pct_values) * Decimal("0.45")
                + _normalized(turnover_values[index], turnover_values) * Decimal("0.25")
                + _normalized(breadth_values[index], breadth_values) * Decimal("0.20")
            )
            if sector.provider_sector_id in event_sector_ids:
                score += Decimal("0.10")
                reasons.append("news")
            if abs(sector.pct_change) >= Decimal("3"):
                reasons.append("movement")
            if (sector.turnover_rate or Decimal("0")) >= Decimal("5"):
                reasons.append("turnover")
            candidates.append((sector, score, tuple(reasons)))
    candidates.sort(key=lambda item: (-item[1], item[0].provider_sector_id))
    return tuple(
        SectorCandidate(
            rank=index,
            provider_sector_id=sector.provider_sector_id,
            name=sector.name,
            kind=sector.kind,
            score=score,
            reasons=reasons,
        )
        for index, (sector, score, reasons) in enumerate(candidates[:limit], start=1)
    )


def build_evidence_pack(
    candidate: SectorCandidate,
    snapshots: Sequence[SectorUniverseSnapshot],
    events: Sequence[NewsEvent],
    run_id: UUID,
) -> EvidencePack:
    """把程序事实绑定到候选；没有事件时明确拒绝强行归因。"""
    sector: SectorSnapshot | None = next(
        (
            item
            for snapshot in snapshots
            for item in snapshot.sectors
            if item.provider_sector_id == candidate.provider_sector_id
        ),
        None,
    )
    if sector is None:
        raise ValueError("candidate sector snapshot is missing")
    related_event_ids = tuple(
        event.event_id for event in events if candidate.provider_sector_id in event.sector_ids
    )
    level = (
        EvidenceLevel.POSSIBLE_CATALYST
        if related_event_ids
        else EvidenceLevel.NO_RELIABLE_EXPLANATION
    )
    facts = (
        f"pct_change={sector.pct_change}",
        f"breadth_ratio={sector.breadth_ratio}",
        f"turnover_rate={sector.turnover_rate}",
    )
    return EvidencePack(
        run_id=run_id,
        sector_id=candidate.provider_sector_id,
        facts=facts,
        event_ids=related_event_ids,
        counter_evidence=(),
        quality_status=QualityStatus.NORMAL,
        max_level=level,
    )
