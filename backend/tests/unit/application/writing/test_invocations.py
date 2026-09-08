from decimal import Decimal
from uuid import UUID

from sector_pulse.application.writing.invocations import build_invocation
from sector_pulse.domain.attribution import SectorAnalysisCard
from sector_pulse.domain.evidence import EvidenceLevel
from sector_pulse.domain.llm import LLMRequest, LLMResult, LLMStatus, MoneyCny, TokenUsage
from sector_pulse.domain.market import SectorKind

RUN_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_build_invocation_roundtrip() -> None:
    card = SectorAnalysisCard(
        run_id=RUN_ID,
        sector_id="industry-1",
        sector_kind=SectorKind.INDUSTRY,
        allowed_max_level=EvidenceLevel.NO_RELIABLE_EXPLANATION,
        attribution_level=EvidenceLevel.NO_RELIABLE_EXPLANATION,
        confidence=Decimal("0"),
        conclusion="暂无可靠解释",
        supporting_evidence_ids=(),
        counter_evidence=(),
        uncertainties=(),
        background_event_ids=(),
        claims=(),
        forbidden_inferences=(),
    )
    request = LLMRequest[SectorAnalysisCard](
        agent_name="attribution",
        model="fixture",
        prompt_id="attribution",
        prompt_version="1",
        system_prompt="sys",
        user_payload={"sector_id": "industry-1"},
        response_model=SectorAnalysisCard,
        fixture_key="x",
    )
    result = LLMResult[SectorAnalysisCard](
        status=LLMStatus.SUCCESS,
        data=card,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        estimated_cost_cny=MoneyCny(amount=Decimal("0.01")),
    )
    invocation = build_invocation(RUN_ID, "attribution", request, result, "fixture")
    assert invocation.run_id == RUN_ID
    assert invocation.stage == "attribution"
    assert invocation.usage.total_tokens == 15
    assert invocation.estimated_cost_cny.amount == Decimal("0.01")
