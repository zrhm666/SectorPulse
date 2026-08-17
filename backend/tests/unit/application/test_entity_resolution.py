from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sector_pulse.application.candidate_selection import build_evidence_pack
from sector_pulse.application.entity_resolution import resolve_sector_links
from sector_pulse.domain.candidate import SectorCandidate
from sector_pulse.domain.evidence import EvidenceLevel
from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.news import NewsEvent
from sector_pulse.domain.news_retrieval import MappingConfidence, SectorEntityConfig
from sector_pulse.domain.quality import QualityStatus

RUN_ID = UUID("00000000-0000-0000-0000-000000000001")
ENTITY_CONFIG = SectorEntityConfig(
    version="test-v1",
    aliases={"industry-1": ("先进制造",)},
    industry_terms={"industry-1": ("机器人", "自动化")},
    ambiguous_terms=("AI",),
)
SECTORS = (
    SectorSnapshot(
        provider_sector_id="industry-1",
        name="高端制造",
        kind=SectorKind.INDUSTRY,
        pct_change=Decimal("3"),
        turnover_rate=Decimal("2"),
        advancers=10,
        decliners=2,
    ),
)


def event(title: str, sector_ids: tuple[str, ...] = ()) -> NewsEvent:
    return NewsEvent(
        event_id="event-1",
        canonical_title=title,
        first_published_at=datetime(2026, 8, 14, 2, tzinfo=UTC),
        document_ids=(),
        deduplication_reason="fixture",
        sector_ids=sector_ids,
    )


def test_stock_code_maps_with_high_confidence() -> None:
    links = resolve_sector_links(
        run_id=RUN_ID,
        events=(event("某公司600001发布公告"),),
        sectors=SECTORS,
        memberships={"600001": ("industry-1",)},
        entity_config=ENTITY_CONFIG,
    )
    assert {link.mapping_confidence for link in links} == {MappingConfidence.HIGH}


def test_ambiguous_term_alone_does_not_map() -> None:
    links = resolve_sector_links(
        RUN_ID,
        (event("AI今日活跃"),),
        SECTORS,
        {},
        ENTITY_CONFIG,
    )
    assert links == ()


def test_related_news_never_sets_possible_catalyst_in_phase1a2() -> None:
    candidate = SectorCandidate(
        rank=1,
        provider_sector_id="industry-1",
        name="高端制造",
        kind=SectorKind.INDUSTRY,
        score=Decimal("0.9"),
        reasons=("movement",),
    )
    snapshot = SectorUniverseSnapshot(
        provider_id="fixture",
        classification_version="v1",
        source_version="v1",
        kind=SectorKind.INDUSTRY,
        observed_at=datetime(2026, 8, 14, 2, tzinfo=UTC),
        collected_at=datetime(2026, 8, 14, 2, tzinfo=UTC),
        sectors=SECTORS,
    )
    related = event("机器人产业链消息", ("industry-1",))
    pack = build_evidence_pack(candidate, (snapshot,), (related,), RUN_ID)
    assert pack.max_level is EvidenceLevel.MARKET_ASSOCIATION
    assert pack.quality_status is QualityStatus.NORMAL
