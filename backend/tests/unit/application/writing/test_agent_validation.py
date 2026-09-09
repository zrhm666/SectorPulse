from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sector_pulse.application.writing.agent_validation import (
    AgentOutputViolation,
    validate_analysis_card,
    validate_claim_numbers,
    validate_prohibited_language,
)
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.news.evidence import EvidenceLevel
from sector_pulse.domain.news.news import SourceGrade
from sector_pulse.domain.writing.attribution import (
    AttributionContext,
    AttributionGateResult,
    Claim,
    ClaimKind,
    SectorAnalysisCard,
)

RUN_ID = UUID("00000000-0000-0000-0000-000000000001")
CONTEXT = AttributionContext(
    run_id=RUN_ID,
    sector_id="industry-1",
    sector_kind=SectorKind.INDUSTRY,
    cutoff_at=datetime(2026, 8, 14, 2, tzinfo=UTC),
    market_facts={"pct_change": Decimal("3.2")},
    event_ids=("event-1",),
    eligible_event_ids=("event-1",),
    background_event_ids=(),
    excluded_event_ids=(),
    source_grades={"event-1": SourceGrade.PRIMARY},
    counter_evidence=(),
)
GATE = AttributionGateResult(
    run_id=RUN_ID,
    sector_id="industry-1",
    allowed_max_level=EvidenceLevel.MARKET_ASSOCIATION,
    reasons=(),
    eligible_evidence_ids=("event-1",),
    excluded_evidence_ids=(),
    counter_evidence=(),
)


def card_with(**updates: object) -> SectorAnalysisCard:
    values = {
        "run_id": RUN_ID,
        "sector_id": "industry-1",
        "sector_kind": SectorKind.INDUSTRY,
        "allowed_max_level": EvidenceLevel.MARKET_ASSOCIATION,
        "attribution_level": EvidenceLevel.MARKET_ASSOCIATION,
        "confidence": Decimal("0.7"),
        "conclusion": "市场可能产生联想",
        "supporting_evidence_ids": ("event-1",),
        "counter_evidence": (),
        "uncertainties": (),
        "background_event_ids": (),
        "claims": (),
        "forbidden_inferences": (),
    }
    values.update(updates)
    return SectorAnalysisCard(**values)


def test_rejects_unknown_evidence_id() -> None:
    with pytest.raises(AgentOutputViolation) as error:
        validate_analysis_card(
            card_with(supporting_evidence_ids=("invented-event",)), GATE, CONTEXT
        )
    assert error.value.code == "UNKNOWN_EVIDENCE_ID"


def test_rejects_changed_market_number() -> None:
    claim = Claim(
        claim_id="claim-1",
        kind=ClaimKind.MARKET_FACT,
        text="板块上涨9.9%",
        fact_keys=("pct_change",),
    )
    with pytest.raises(AgentOutputViolation) as error:
        validate_claim_numbers(claim, {"pct_change": Decimal("3.2")})
    assert error.value.code == "MARKET_NUMBER_MISMATCH"


def test_rejects_prohibited_language() -> None:
    with pytest.raises(AgentOutputViolation) as error:
        validate_prohibited_language("建议重仓该板块")
    assert error.value.code == "PROHIBITED_INVESTMENT_LANGUAGE"


def test_trusted_context_name_overrides_model_name() -> None:
    context = AttributionContext.model_validate({**CONTEXT.model_dump(), "sector_name": "文化传媒"})
    result = validate_analysis_card(card_with(sector_name="模型虚构板块"), GATE, context)
    assert result.sector_name == "文化传媒"


def test_unknown_context_name_does_not_accept_model_guess() -> None:
    result = validate_analysis_card(card_with(sector_name="模型猜测"), GATE, CONTEXT)
    assert result.sector_name is None


def test_rejects_same_id_with_wrong_sector_kind() -> None:
    with pytest.raises(AgentOutputViolation) as error:
        validate_analysis_card(card_with(sector_kind=SectorKind.CONCEPT), GATE, CONTEXT)
    assert error.value.code == "CARD_CONTEXT_MISMATCH"


def test_fallback_preserves_trusted_sector_name() -> None:
    import asyncio
    from types import SimpleNamespace

    from sector_pulse.application.writing.attribution_agents import run_attribution_agents
    from sector_pulse.infrastructure.llm.fixture_provider import FixtureLLMProvider

    context = AttributionContext.model_validate({**CONTEXT.model_dump(), "sector_name": "文化传媒"})
    results = asyncio.run(
        run_attribution_agents(
            (context,), {context.sector_id: GATE}, FixtureLLMProvider({}), SimpleNamespace()
        )
    )
    assert results[0].error_code == "FIXTURE_RESPONSE_MISSING"
    assert results[0].card.sector_name == "文化传媒"
