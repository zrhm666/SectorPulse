from typing import Any, Protocol

from sector_pulse.domain.llm import (
    LLMHealth,
    LLMRequest,
    LLMResult,
    MoneyCny,
    TokenUsage,
)


class LLMPort(Protocol):
    async def generate_structured(
        self, request: LLMRequest[Any]
    ) -> LLMResult[Any]: ...

    async def health_check(self) -> LLMHealth: ...

    def estimate_cost(self, usage: TokenUsage, model: str) -> MoneyCny: ...
