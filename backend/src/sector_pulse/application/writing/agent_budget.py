"""A run-scoped model wrapper reserves budget before concurrent requests."""

import asyncio
import json
from decimal import Decimal
from typing import Any

from sector_pulse.domain.llm import (
    LLMError,
    LLMHealth,
    LLMRequest,
    LLMResult,
    LLMStatus,
    MoneyCny,
    TokenUsage,
)
from sector_pulse.ports.llm import LLMPort


class BudgetedLLM:
    def __init__(
        self,
        inner: LLMPort,
        budget: Decimal,
        pricing: dict[str, dict[str, str]],
        *,
        max_tokens: int = 500000,
        max_calls: int = 80,
    ) -> None:
        self.inner = inner
        self.provider_id = getattr(inner, "provider_id", "unknown")
        self.budget = budget
        self.pricing = pricing
        self.tokens_left = max_tokens
        self.calls_left = max_calls
        self.reserved_cost = Decimal("0")
        self.spent = Decimal("0")
        self.exhausted = False
        self._lock = asyncio.Lock()

    async def generate_structured(self, request: LLMRequest[Any]) -> LLMResult[Any]:
        # UTF-8 bytes bound ordinary text token counts conservatively; include schema twice
        # because compatibility providers may append it to the system prompt too.
        output_limit = request.max_output_tokens or 4096
        input_bound = (
            len(
                (
                    request.system_prompt
                    + json.dumps(request.user_payload, ensure_ascii=False)
                    + json.dumps(request.response_model.model_json_schema(), ensure_ascii=False)
                ).encode()
            )
            + 2048
        )
        token_reservation = 3 * (input_bound + output_limit)
        price = self.pricing.get(request.model)
        cost = (
            Decimal("0")
            if price is None
            else 3
            * (
                input_bound * Decimal(price["input_cny_per_million"])
                + output_limit * Decimal(price["output_cny_per_million"])
            )
            / 1000000
        )
        async with self._lock:
            if (
                self.calls_left < 1
                or self.tokens_left < token_reservation
                or self.spent + self.reserved_cost + cost > self.budget
            ):
                self.exhausted = True
                return LLMResult(
                    status=LLMStatus.BLOCKED,
                    usage=TokenUsage(),
                    estimated_cost_cny=MoneyCny(amount=Decimal("0")),
                    error=LLMError(code="AGENT_BUDGET_EXHAUSTED", message="运行额度已用尽"),
                )
            self.calls_left -= 1
            self.tokens_left -= token_reservation
            self.reserved_cost += cost
        completed = False
        try:
            result = await self.inner.generate_structured(
                request.model_copy(update={"max_output_tokens": output_limit})
            )
            completed = True
            async with self._lock:
                # Keep the reservation for failures: upstream may have charged an attempt.
                self.spent += max(result.estimated_cost_cny.amount, cost)
                if result.status is LLMStatus.SUCCESS and (
                    result.usage.total_tokens > 0 or self.provider_id == "fixture"
                ):
                    self.tokens_left += token_reservation - result.usage.total_tokens
            return result
        finally:
            async with self._lock:
                self.reserved_cost -= cost
                if not completed:
                    self.spent += cost

    def estimate_cost(self, usage: TokenUsage, model: str) -> MoneyCny:
        return self.inner.estimate_cost(usage, model)

    async def health_check(self) -> LLMHealth:
        return await self.inner.health_check()
