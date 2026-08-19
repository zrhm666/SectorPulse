import json
import logging
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
async def test_sends_response_schema_with_json_object_request() -> None:
    captured: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(http_request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"value":"ok"}'}}],
                "usage": {},
            },
            request=http_request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = OpenAICompatibleProvider(
        "https://example.test/v1",
        SecretStr("secret-value"),
        2,
        {},
        client,
    )

    result = await llm.generate_structured(request())

    assert result.status is LLMStatus.SUCCESS
    assert captured["response_format"] == {"type": "json_object"}
    system_prompt = captured["messages"][0]["content"]  # type: ignore[index]
    assert '"value"' in system_prompt
    assert "必须严格返回" in system_prompt


@pytest.mark.asyncio
async def test_retries_rate_limit_then_returns_success() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": "limited"}, request=http_request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"value":"ok"}'}}],
                "usage": {},
            },
            request=http_request,
        )

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = OpenAICompatibleProvider(
        "https://example.test/v1",
        SecretStr("secret-value"),
        2,
        {},
        client,
        sleep=record_sleep,
    )

    result = await llm.generate_structured(request())

    assert result.status is LLMStatus.SUCCESS
    assert attempts == 2
    assert delays == [1.0]


@pytest.mark.asyncio
async def test_invalid_schema_log_identifies_stage_and_field(caplog) -> None:
    caplog.set_level(logging.WARNING)

    result = await provider(
        {
            "choices": [{"message": {"content": '{"wrong":"value"}'}}],
            "usage": {},
        }
    ).generate_structured(request())

    assert result.status is LLMStatus.FAILED
    assert "stage=test" in caplog.text
    assert "validation_paths=['value']" in caplog.text


@pytest.mark.asyncio
async def test_success_log_reports_stage_status_and_elapsed_time(caplog) -> None:
    caplog.set_level(logging.INFO)

    result = await provider(
        {
            "choices": [{"message": {"content": '{"value":"ok"}'}}],
            "usage": {},
        }
    ).generate_structured(request())

    assert result.status is LLMStatus.SUCCESS
    assert "LLM request started: stage=test" in caplog.text
    assert "LLM response received: stage=test" in caplog.text
    assert "status=200" in caplog.text
    assert "elapsed_ms=" in caplog.text


@pytest.mark.asyncio
async def test_malformed_choices_returns_structured_output_error() -> None:
    result = await provider({"choices": [None], "usage": {}}).generate_structured(request())

    assert result.status is LLMStatus.FAILED
    assert result.error is not None
    assert result.error.code == "LLM_STRUCTURED_OUTPUT_INVALID"


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


def test_parses_fenced_json_and_text_blocks() -> None:
    assert OpenAICompatibleProvider._parse_json_content(
        "Here is the result:\n```json\n{\"value\":\"ok\"}\n```"
    ) == {"value": "ok"}
    assert OpenAICompatibleProvider._parse_json_content(
        [{"type": "text", "text": '{"value":"ok"}'}]
    ) == {"value": "ok"}
