from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sector_pulse.application.candidate_selection import (
    build_evidence_pack,
    select_candidates,
)
from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.news import NewsEvent


def universe(kind: SectorKind) -> SectorUniverseSnapshot:
    return SectorUniverseSnapshot(
        provider_id="fixture",
        classification_version="v1",
        source_version="v1",
        kind=kind,
        observed_at=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
        collected_at=datetime(2026, 8, 14, 9, 1, tzinfo=UTC),
        sectors=(
            SectorSnapshot(
                provider_sector_id=f"{kind.value}-A",
                name="高热度板块",
                kind=kind,
                pct_change=Decimal("6"),
                turnover_rate=Decimal("8"),
                advancers=20,
                decliners=2,
            ),
            SectorSnapshot(
                provider_sector_id=f"{kind.value}-B",
                name="平淡板块",
                kind=kind,
                pct_change=Decimal("0.2"),
                turnover_rate=Decimal("1"),
                advancers=5,
                decliners=10,
            ),
        ),
    )


def test_candidate_selection_prioritizes_standardized_hot_and_news_linked_sector() -> None:
    events = (
        NewsEvent(
            event_id="event-a",
            canonical_title="政策发布",
            first_published_at=datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
            document_ids=("doc-a",),
            deduplication_reason="content_hash",
            sector_ids=("INDUSTRY-A",),
        ),
    )

    candidates = select_candidates(
        universe(SectorKind.INDUSTRY), universe(SectorKind.CONCEPT), events, limit=3
    )

    assert len(candidates) == 3
    assert candidates[0].provider_sector_id == "INDUSTRY-A"
    assert "news" in candidates[0].reasons
    assert candidates[0].score > candidates[-1].score


def test_evidence_pack_binds_market_fact_and_related_event() -> None:
    candidates = select_candidates(
        universe(SectorKind.INDUSTRY), universe(SectorKind.CONCEPT), (), limit=4
    )
    candidate = next(item for item in candidates if item.kind is SectorKind.INDUSTRY)
    pack = build_evidence_pack(
        candidate,
        (universe(SectorKind.INDUSTRY),),
        (),
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    assert pack.sector_id == candidate.provider_sector_id
    assert "pct_change" in pack.facts[0]
