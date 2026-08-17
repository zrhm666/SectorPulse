import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from sector_pulse.domain.llm import AgentInvocation, LLMRequest, LLMResult

InvocationSink = Callable[[AgentInvocation], None]


def noop_invocation_sink(invocation: AgentInvocation) -> None:
    pass


def build_invocation(
    run_id: UUID,
    stage: str,
    request: LLMRequest[Any],
    result: LLMResult[Any],
    provider_id: str,
) -> AgentInvocation:
    input_hash = hashlib.sha256(
        json.dumps(request.user_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return AgentInvocation(
        invocation_id=uuid4(),
        run_id=run_id,
        stage=stage,
        provider_id=provider_id,
        model=request.model,
        prompt_id=request.prompt_id,
        prompt_version=request.prompt_version,
        input_hash=input_hash,
        status=result.status,
        usage=result.usage,
        estimated_cost_cny=result.estimated_cost_cny,
        error_code=result.error.code if result.error else None,
    )
