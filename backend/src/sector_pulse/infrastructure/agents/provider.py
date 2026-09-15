"""Enforce the shared run ledger at every non-streaming framework model call."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from aidynamic_agent.core.message import Message, StreamChunk, ToolDefinition
from aidynamic_agent.llm.base import LLMProvider, LLMResponse

from sector_pulse.application.orchestration.budget import BudgetExceeded, SharedBudget
from sector_pulse.domain.orchestration.models import ModelPricing


class BudgetedProvider(LLMProvider):
    def __init__(
        self,
        inner: LLMProvider,
        budget: SharedBudget,
        *,
        output_limit: int = 4096,
        pricing: ModelPricing | None = None,
    ) -> None:
        if type(output_limit) is not int or output_limit <= 0:
            raise ValueError("output_limit must be positive")
        self.inner = inner
        self.budget = budget
        self.output_limit = output_limit
        self.pricing = pricing

    async def create(
        self, messages: list[Message], tools: list[ToolDefinition] | None = None, **kwargs: Any
    ) -> LLMResponse:
        allowed_options = {
            "max_tokens",
            "max_completion_tokens",
            "temperature",
            "top_p",
            "stop",
            "seed",
        }
        if set(kwargs) - allowed_options:
            raise ValueError("unsupported model options for budgeted execution")
        payload = {
            "messages": [asdict(message) for message in messages],
            "tools": [asdict(tool) for tool in (tools or [])],
        }
        input_bound = (
            len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")) + 2048
        )
        call_id = str(uuid4())
        reserved_cny = (
            self.pricing.estimate(input_bound, self.output_limit) if self.pricing else None
        )
        await asyncio.to_thread(
            self.budget.reserve,
            call_id,
            input_bound,
            self.output_limit,
            reserved_cny=reserved_cny,
        )
        actual: int | None = None
        actual_cny: Decimal | None = None
        succeeded: bool | None = None
        try:
            state = await asyncio.to_thread(self.budget.repository.load, self.budget.run_id)
            if state is None:
                raise KeyError("run not found")
            remaining = (state.deadline - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise BudgetExceeded("run deadline exceeded")
            # The server-owned limit cannot be overridden through tool/model kwargs.
            kwargs.pop("max_completion_tokens", None)
            kwargs["max_tokens"] = self.output_limit
            async with asyncio.timeout(remaining):
                result = await self.inner.create(messages, tools=tools, **kwargs)
            succeeded = True
            usage = result.usage.get("total_tokens")
            if type(usage) is int and usage >= 0:
                actual = usage
            prompt = result.usage.get("prompt_tokens")
            completion = result.usage.get("completion_tokens")
            if type(prompt) is int and prompt >= 0 and type(completion) is int and completion >= 0:
                # Inconsistent counters cannot justify a monetary refund. No discounts
                # are inferred from cached-token metadata; use configured base rates.
                if self.pricing and (actual is None or actual == prompt + completion):
                    actual_cny = self.pricing.estimate(prompt, completion)
                actual = max(actual or 0, prompt + completion)
            return result
        finally:
            # Unknown/cancelled requests may still have been billed upstream.
            await asyncio.shield(
                asyncio.to_thread(
                    self.budget.settle,
                    call_id,
                    actual,
                    actual_cny=actual_cny,
                    succeeded=succeeded,
                )
            )

    async def stream(
        self, messages: list[Message], tools: list[ToolDefinition] | None = None, **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        raise NotImplementedError("streaming requires an audited budget-aware implementation")
        yield  # pragma: no cover - async iterator protocol, no unmetered fallback

    async def close(self) -> None:
        # Shared transport lifecycle belongs to the composition root, not each role wrapper.
        return None
