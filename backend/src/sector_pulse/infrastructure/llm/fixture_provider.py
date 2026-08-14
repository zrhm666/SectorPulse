from collections.abc import Mapping
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


class FixtureLLMProvider:
    """提供可重复模型结果；缺失 Fixture 时显式失败而不是生成猜测内容。"""

    provider_id = "fixture"

    def __init__(self, responses: Mapping[str, object]) -> None:
        self._responses = dict(responses)

    async def generate_structured(self, request: LLMRequest[Any]) -> LLMResult[Any]:
        if request.fixture_key not in self._responses:
            return LLMResult(
                status=LLMStatus.FAILED,
                usage=TokenUsage(),
                estimated_cost_cny=MoneyCny(amount=Decimal("0")),
                error=LLMError(
                    code="FIXTURE_RESPONSE_MISSING",
                    message=f"fixture response missing: {request.fixture_key}",
                ),
            )
        try:
            data = request.response_model.model_validate(self._responses[request.fixture_key])
        except Exception as exc:
            return LLMResult(
                status=LLMStatus.FAILED,
                usage=TokenUsage(),
                estimated_cost_cny=MoneyCny(amount=Decimal("0")),
                error=LLMError(code="FIXTURE_RESPONSE_INVALID", message=str(exc)),
            )
        return LLMResult(
            status=LLMStatus.SUCCESS,
            data=data,
            usage=TokenUsage(),
            estimated_cost_cny=MoneyCny(amount=Decimal("0")),
        )

    async def health_check(self) -> LLMHealth:
        return LLMHealth(available=True, provider_id=self.provider_id, message="fixture")

    def estimate_cost(self, usage: TokenUsage, model: str) -> MoneyCny:
        del usage, model
        return MoneyCny(amount=Decimal("0"))
