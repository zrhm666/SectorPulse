import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sector_pulse.application.writing.attribution_agents import run_attribution_agents
from sector_pulse.domain.attribution import AttributionContext, AttributionGateResult
from sector_pulse.domain.evidence import EvidenceLevel
from sector_pulse.domain.llm import (
    LLMRequest,
    LLMResult,
    LLMStatus,
    MoneyCny,
    TokenUsage,
)
from sector_pulse.domain.market import SectorKind

RUN_ID = UUID("00000000-0000-0000-0000-000000000001")


def context(sector_id: str) -> AttributionContext:
    return AttributionContext(
        run_id=RUN_ID,
        sector_id=sector_id,
        sector_kind=SectorKind.INDUSTRY,
        cutoff_at=datetime(2026, 8, 14, 2, tzinfo=UTC),
        market_facts={"pct_change": Decimal("3.2"), "breadth_ratio": Decimal("0.7")},
        event_ids=(),
        eligible_event_ids=(),
        background_event_ids=(),
        excluded_event_ids=(),
        source_grades={},
        counter_evidence=(),
    )


class SlowFixture:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    async def generate_structured(self, request: LLMRequest):
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        return LLMResult(
            status=LLMStatus.FAILED,
            usage=TokenUsage(),
            estimated_cost_cny=MoneyCny(amount=Decimal("0")),
            error={"code": "TEMP", "message": request.fixture_key or "", "retriable": False},
        )


def test_attribution_agents_isolate_failures_and_limit_concurrency() -> None:
    provider = SlowFixture()
    contexts = tuple(context(f"industry-{index}") for index in range(8))
    gates = {
        item.sector_id: AttributionGateResult(
            run_id=RUN_ID,
            sector_id=item.sector_id,
            allowed_max_level=EvidenceLevel.NO_RELIABLE_EXPLANATION,
            reasons=("NO_ELIGIBLE_EVENT",),
            eligible_evidence_ids=(),
            excluded_evidence_ids=(),
            counter_evidence=(),
        )
        for item in contexts
    }
    results = asyncio.run(run_attribution_agents(contexts, gates, provider, None, concurrency=4))
    assert len(results) == 8
    assert provider.peak <= 4
    assert all(
        item.card.attribution_level is EvidenceLevel.NO_RELIABLE_EXPLANATION
        for item in results
    )
