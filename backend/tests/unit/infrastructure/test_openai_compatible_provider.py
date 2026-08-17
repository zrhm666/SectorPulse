from decimal import Decimal

import httpx
import pytest
from pydantic import BaseModel, SecretStr
from sector_pulse.domain.llm import LLMRequest, LLMStatus
from sector_pulse.infrastructure.llm.openai_compatible import (
    ModelPrice,
    OpenAICompatibleProvider,
)


class ResultModel(BaseModel):
    value: str


def request() -> LLMRequest[ResultModel]:
    return LLMRequest(
        agent_name="test",
        model="test-model",
        prompt_id="test",
        prompt_version="1",
        system_prompt="return json",
        user_payload={"x": 1},
        response_model=ResultModel,
    )


def provider(payload: dict[str, object], status_code: int = 200) -> OpenAICompatibleProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(
        "https://example.test/v1/",
        SecretStr("secret-value"),
        2,
        {
            "test-model": ModelPrice(
                input_cny_per_million=Decimal("1"),
                output_cny_per_million=Decimal("2"),
            )
        },
        client,
    )


@pytest.mark.asyncio
async def test_parses_structured_response_and_cost() -> None:
    result = await provider(
        {
            "choices": [{"message": {"content": '{"value":"ok"}'}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        }
    ).generate_structured(request())
    assert result.status is LLMStatus.SUCCESS
    assert result.data == ResultModel(value="ok")
    assert result.estimated_cost_cny.amount == Decimal("0.002")


@pytest.mark.asyncio
async def test_http_429_is_retriable_and_secret_is_not_exposed() -> None:
    result = await provider(
        {"error": {"message": "rate limit"}}, status_code=429
    ).generate_structured(request())
    assert result.status is LLMStatus.FAILED
    assert result.error is not None
    assert result.error.code == "LLM_RATE_LIMITED"
    assert result.error.retriable is True
    assert "secret-value" not in result.error.message
