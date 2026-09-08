from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from sector_pulse.application.writing.attribution_gate import evaluate_attribution_gate
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.news.evidence import EvidenceLevel
from sector_pulse.domain.news.news import NewsDocument, SourceGrade
from sector_pulse.domain.writing.attribution import AttributionContext

RUN_ID = UUID("00000000-0000-0000-0000-000000000001")
CUTOFF = datetime(2026, 8, 14, 2, tzinfo=UTC)
MOVE = datetime(2026, 8, 14, 2, tzinfo=UTC)


def make_context(breadth_ratio: str, source_grade: SourceGrade) -> AttributionContext:
    return AttributionContext(
        run_id=RUN_ID,
        sector_id="industry-1",
        sector_kind=SectorKind.INDUSTRY,
        cutoff_at=CUTOFF,
        market_facts={"breadth_ratio": Decimal(breadth_ratio)},
        event_ids=("event-1",),
        eligible_event_ids=("event-1",),
        background_event_ids=(),
        excluded_event_ids=(),
        source_grades={"doc-1": source_grade},
        counter_evidence=(),
    )


def make_document(case: dict[str, object]) -> NewsDocument:
    published = case["published_at"]
    published_at = (
        datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if published
        else None
    )
    return NewsDocument(
        document_id="doc-1",
        source_id="fixture",
        canonical_locator=f"urn:fixture:{case['id']}",
        citation_url=case["citation_url"],
        title="测试新闻",
        publisher="测试发布方",
        summary="摘要",
        published_at=published_at,
        source_observed_at=published_at,
        collected_at=CUTOFF,
        content_hash=f"hash-{case['id']}",
        source_grade=SourceGrade(str(case["source_grade"])),
    )


CASES = yaml.safe_load(
    (Path(__file__).parents[3] / "fixtures" / "attribution" / "gate_cases.yaml").read_text(
        encoding="utf-8"
    )
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_gate_cases(case: dict[str, object]) -> None:
    context = make_context(
        str(case["breadth_ratio"]), SourceGrade(str(case["source_grade"]))
    )
    document = make_document(case)
    result = evaluate_attribution_gate(
        context,
        {document.document_id: document},
        MOVE,
        broad_market_alternative=False,
    )
    assert result.allowed_max_level is EvidenceLevel(str(case["expected_max"]))
