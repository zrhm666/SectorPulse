import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sector_pulse.application.agent_validation import validate_analysis_card
from sector_pulse.domain.attribution import (
    AttributionContext,
    AttributionGateResult,
    SectorAnalysisCard,
)
from sector_pulse.domain.evidence import EvidenceLevel
from sector_pulse.domain.llm import LLMRequest, LLMStatus
from sector_pulse.ports.llm import LLMPort


@dataclass(frozen=True)
class AttributionAgentResult:
    card: SectorAnalysisCard
    error_code: str | None = None


def _fallback(
    context: AttributionContext, gate: AttributionGateResult, code: str
) -> AttributionAgentResult:
    return AttributionAgentResult(
        card=SectorAnalysisCard(
            run_id=context.run_id,
            sector_id=context.sector_id,
            sector_kind=context.sector_kind,
            allowed_max_level=gate.allowed_max_level,
            attribution_level=EvidenceLevel.NO_RELIABLE_EXPLANATION,
            confidence=Decimal("0"),
            conclusion="暂无可靠解释，相关新闻仅作背景参考。",
            supporting_evidence_ids=(),
            counter_evidence=gate.counter_evidence,
            uncertainties=(code,),
            background_event_ids=context.background_event_ids,
            claims=(),
            forbidden_inferences=("不得将新闻直接表述为板块上涨原因",),
        ),
        error_code=code,
    )


async def run_attribution_agents(
    contexts: tuple[AttributionContext, ...],
    gates: dict[str, AttributionGateResult],
    llm: LLMPort,
    prompt: Any,
    concurrency: int = 4,
) -> tuple[AttributionAgentResult, ...]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(context: AttributionContext) -> AttributionAgentResult:
        gate = gates[context.sector_id]
        async with semaphore:
            request = LLMRequest[
                SectorAnalysisCard
            ](
                agent_name="attribution",
                model="fixture",
                prompt_id=getattr(prompt, "prompt_id", "attribution"),
                prompt_version=getattr(prompt, "version", "1"),
                system_prompt=getattr(prompt, "system", ""),
                user_payload=context.model_dump(mode="json"),
                response_model=SectorAnalysisCard,
                fixture_key=f"sector-analysis:{context.sector_id}",
            )
            result = await llm.generate_structured(request)
            if result.status is LLMStatus.SUCCESS and result.data is not None:
                try:
                    return AttributionAgentResult(
                        validate_analysis_card(result.data, gate, context)
                    )
                except ValueError as exc:
                    return _fallback(context, gate, type(exc).__name__)
            return _fallback(context, gate, result.error.code if result.error else "AGENT_FAILED")

    return tuple(await asyncio.gather(*(run_one(context) for context in contexts)))
