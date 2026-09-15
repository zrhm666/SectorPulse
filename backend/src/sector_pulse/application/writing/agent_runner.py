"""Bounded decision/tool/observation loop for one attribution subject.

Budget admission and durable step storage are supplied by the run coordinator.
This module does not open network connections or write business records itself.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sector_pulse.application.writing.agent_validation import validate_analysis_card
from sector_pulse.application.writing.attribution_agents import _fallback
from sector_pulse.application.writing.invocations import build_invocation
from sector_pulse.domain.llm import AgentInvocation, LLMRequest, LLMStatus
from sector_pulse.domain.writing.agent_execution import (
    AgentDecision,
    AgentLimits,
    FinishAttribution,
    ToolObservation,
)
from sector_pulse.domain.writing.attribution import (
    AttributionContext,
    AttributionGateResult,
    SectorAnalysisCard,
)
from sector_pulse.infrastructure.llm.prompt_registry import PromptDefinition, PromptRegistry
from sector_pulse.ports.attribution_tools import AttributionToolsPort
from sector_pulse.ports.llm import LLMPort


@dataclass(frozen=True)
class AgentLoopResult:
    card: SectorAnalysisCard
    stop_reason: str
    decisions: int
    tool_calls: int


async def run_agent_loop(
    context: AttributionContext,
    gate: AttributionGateResult,
    llm: LLMPort,
    tools: AttributionToolsPort,
    *,
    model: str,
    limits: AgentLimits,
    admit: Callable[[LLMRequest[Any]], Awaitable[bool]],
    record_invocation: Callable[[AgentInvocation], None],
    record_step: Callable[[int, dict[str, Any]], None],
    refresh_state: Callable[[], tuple[AttributionContext, AttributionGateResult]] | None = None,
    prompt: PromptDefinition | None = None,
    feedback_prompt: PromptDefinition | None = None,
) -> AgentLoopResult:
    """Callbacks are mandatory so callers cannot accidentally skip budget/audit integration."""
    if prompt is None or feedback_prompt is None:
        registry = PromptRegistry(Path("config/prompts"))
        prompt = prompt or registry.get("attribution_agent")
        feedback_prompt = feedback_prompt or registry.get("agent_validation_feedback")
    decisions = 0
    tool_calls = 0
    history: list[dict[str, Any]] = []
    called: set[str] = set()

    def stopped(reason: str) -> AgentLoopResult:
        record_step(decisions, {"type": "stopped", "reason": reason})
        return AgentLoopResult(_fallback(context, gate, reason).card, reason, decisions, tool_calls)

    try:
        async with asyncio.timeout(limits.timeout_seconds):
            for decision_index in range(1, limits.max_decisions + 1):
                if refresh_state is not None:
                    context, gate = refresh_state()
                request: LLMRequest[Any] = LLMRequest(
                    agent_name="attribution_agent",
                    model=model,
                    prompt_id=prompt.prompt_id,
                    prompt_version=prompt.version,
                    system_prompt=prompt.render(),
                    user_payload={
                        "context": context.model_dump(mode="json"),
                        "gate": gate.model_dump(mode="json"),
                        "observations": list(history),
                        "remaining_decisions": limits.max_decisions - decision_index + 1,
                        "remaining_tool_calls": limits.max_tool_calls - tool_calls,
                        "response_schema": AgentDecision.model_json_schema(),
                    },
                    response_model=AgentDecision,
                    fixture_key=f"attribution-agent:{context.sector_id}:{decision_index}",
                )
                if not await admit(request):
                    return stopped("AGENT_BUDGET_EXHAUSTED")
                decisions += 1
                result = await llm.generate_structured(request)
                record_invocation(
                    build_invocation(
                        context.run_id,
                        "attribution_agent",
                        request,
                        result,
                        getattr(llm, "provider_id", "unknown"),
                    )
                )
                if result.status is not LLMStatus.SUCCESS or result.data is None:
                    return stopped(result.error.code if result.error else "AGENT_DECISION_FAILED")
                try:
                    decision = AgentDecision.model_validate(result.data)
                except ValueError:
                    return stopped("AGENT_INVALID_ACTION")
                action = decision.next_action
                if isinstance(action, FinishAttribution):
                    try:
                        # Reject excluded IDs and claim-level references too.
                        allowed = set(gate.eligible_evidence_ids) - set(gate.excluded_evidence_ids)
                        references = set(action.card.supporting_evidence_ids)
                        if not references <= allowed:
                            raise ValueError("unknown or excluded evidence")
                        for claim in action.card.claims:
                            claim_allowed = allowed | (
                                set(context.background_event_ids)
                                if claim.kind.value == "BACKGROUND"
                                else set()
                            )
                            if not set(claim.evidence_ids) <= claim_allowed:
                                raise ValueError("unverified claim evidence")
                        if not set(action.card.background_event_ids) <= set(
                            context.background_event_ids
                        ):
                            raise ValueError("unknown background event")
                        card = validate_analysis_card(action.card, gate, context)
                    except ValueError:
                        history.append(
                            {
                                "type": "validation_feedback",
                                "error_code": "AGENT_INVALID_CONCLUSION",
                                "instruction": feedback_prompt.render(),
                            }
                        )
                        if decision_index < limits.max_decisions:
                            continue
                        return stopped("AGENT_INVALID_CONCLUSION")
                    record_step(
                        decisions, {"type": "finished", "card": card.model_dump(mode="json")}
                    )
                    return AgentLoopResult(card, "finished", decisions, tool_calls)
                if tool_calls >= limits.max_tool_calls:
                    return stopped("AGENT_TOOL_LIMIT")
                key = action.model_dump_json()
                if key in called:
                    return stopped("AGENT_NO_PROGRESS")
                called.add(key)
                tool_calls += 1
                record_step(decisions, {"type": "tool_started", "action": action.model_dump()})
                try:
                    observation = await tools.execute(action)
                except Exception:
                    observation = ToolObservation(
                        action=action.action, status="error", error_code="TOOL_FAILED"
                    )
                data = observation.model_dump(mode="json")
                encoded = json.dumps(data, ensure_ascii=False)
                if len(encoded) > limits.max_observation_chars:
                    data = {
                        "action": action.action,
                        "status": "partial",
                        "truncated": True,
                        "excerpt": encoded[: limits.max_observation_chars],
                    }
                entry = {"action": action.model_dump(mode="json"), "observation": data}
                history.append(entry)
                record_step(decisions, {"type": "tool_result", **entry})
                if refresh_state is not None:
                    context, gate = refresh_state()
            return stopped("AGENT_DECISION_LIMIT")
    except TimeoutError:
        return stopped("AGENT_TIME_LIMIT")
    except asyncio.CancelledError:
        record_step(decisions, {"type": "stopped", "reason": "AGENT_CANCELLED"})
        raise
