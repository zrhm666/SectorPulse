from decimal import Decimal

import pytest
from pydantic import BaseModel
from sector_pulse.domain.llm import LLMRequest, LLMStatus
from sector_pulse.infrastructure.llm.fixture_provider import FixtureLLMProvider


class ResultModel(BaseModel):
    value: str


def request(key: str) -> LLMRequest[ResultModel]:
    return LLMRequest(
        agent_name="test",
        model="fixture",
        prompt_id="test",
        prompt_version="1",
        system_prompt="test",
        user_payload={},
        response_model=ResultModel,
        fixture_key=key,
    )


@pytest.mark.asyncio
async def test_fixture_provider_returns_registered_response() -> None:
    provider = FixtureLLMProvider({"key": {"value": "ok"}})
    result = await provider.generate_structured(request("key"))
    assert result.status is LLMStatus.SUCCESS
    assert result.data == ResultModel(value="ok")
    assert result.estimated_cost_cny.amount == Decimal("0")


@pytest.mark.asyncio
async def test_missing_fixture_is_explicit_failure() -> None:
    result = await FixtureLLMProvider({}).generate_structured(request("missing"))
    assert result.status is LLMStatus.FAILED
    assert result.error is not None
    assert result.error.code == "FIXTURE_RESPONSE_MISSING"
