from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sector_pulse.domain.candidate import SectorCandidate
from sector_pulse.domain.evidence import EvidenceLevel, EvidencePack
from sector_pulse.domain.market import SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.news import NewsEvent
from sector_pulse.domain.quality import QualityStatus

MARKET_SCORE_WEIGHT = Decimal("0.90")


def _normalized(value: Decimal, values: list[Decimal]) -> Decimal:
    minimum, maximum = min(values), max(values)
    if maximum == minimum:
        return Decimal("0.5")
    return (value - minimum) / (maximum - minimum)


def _field_available(universe: SectorUniverseSnapshot, field: str) -> bool:
    return not universe.available_fields or field in universe.available_fields


def _dimension_weights(
    universe: SectorUniverseSnapshot,
) -> tuple[tuple[str, Decimal], ...]:
    if not _field_available(universe, "pct_change"):
        return ()
    dimensions: list[tuple[str, Decimal]] = [
        ("pct_change", Decimal("0.45"))
    ]
    if _field_available(universe, "turnover_rate"):
        dimensions.append(("turnover_rate", Decimal("0.25")))
    if _field_available(universe, "advancers") and _field_available(
        universe, "decliners"
    ):
        dimensions.append(("breadth", Decimal("0.20")))
    return tuple(dimensions)


def _dimension_value(sector: SectorSnapshot, dimension: str) -> Decimal:
    if dimension == "pct_change":
        return abs(sector.pct_change)
    if dimension == "turnover_rate":
        return sector.turnover_rate or Decimal("0")
    return abs(sector.breadth_ratio - Decimal("0.5"))


def _rank_candidates(
    industry: SectorUniverseSnapshot,
    concept: SectorUniverseSnapshot,
    event_sector_ids: set[str],
    limit: int,
) -> tuple[SectorCandidate, ...]:
    """在行业/概念组内分别标准化，再合并为最多 limit 个候选。"""
    candidates: list[tuple[SectorSnapshot, Decimal, tuple[str, ...]]] = []
    for universe in (industry, concept):
        sectors = list(universe.sectors)
        dimensions = _dimension_weights(universe)
        if not sectors or not dimensions:
            continue
        values = {
            dimension: [_dimension_value(sector, dimension) for sector in sectors]
            for dimension, _weight in dimensions
        }
        weight_scale = MARKET_SCORE_WEIGHT / sum(
            (weight for _dimension, weight in dimensions),
            start=Decimal("0"),
        )
        for index, sector in enumerate(sectors):
            reasons: list[str] = []
            score = min(
                sum(
                    (
                        _normalized(values[dimension][index], values[dimension])
                        * weight
                        * weight_scale
                        for dimension, weight in dimensions
                    ),
                    start=Decimal("0"),
                ),
                MARKET_SCORE_WEIGHT,
            )
            if sector.provider_sector_id in event_sector_ids:
                score += Decimal("0.10")
                reasons.append("news")
            if abs(sector.pct_change) >= Decimal("3"):
                reasons.append("movement")
            if (
                any(dimension == "turnover_rate" for dimension, _weight in dimensions)
                and (sector.turnover_rate or Decimal("0")) >= Decimal("5")
            ):
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


def select_market_precandidates(
    industry: SectorUniverseSnapshot,
    concept: SectorUniverseSnapshot,
    limit: int = 30,
) -> tuple[SectorCandidate, ...]:
    """只基于市场事实生成预候选，明确不读取新闻事件。"""
    return _rank_candidates(industry, concept, set(), limit)


def select_candidates(
    industry: SectorUniverseSnapshot,
    concept: SectorUniverseSnapshot,
    events: Sequence[NewsEvent],
    limit: int = 12,
) -> tuple[SectorCandidate, ...]:
    """在预候选基础上加入去重新闻丰富度，生成最终候选。"""
    event_sector_ids = {sector_id for event in events for sector_id in event.sector_ids}
    return _rank_candidates(industry, concept, event_sector_ids, limit)


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
    # Phase 1A.2 只证明“市场与新闻存在关联”；催化或明确驱动需由 Phase 1B 结合时序与反事实判断。
    level = (
        EvidenceLevel.MARKET_ASSOCIATION
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
        sector_kind=candidate.kind,
        facts=facts,
        event_ids=related_event_ids,
        counter_evidence=(),
        quality_status=QualityStatus.NORMAL,
        max_level=level,
    )
