import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from sector_pulse.domain.llm import (
    LLMError,
    LLMHealth,
    LLMRequest,
    LLMResult,
    LLMStatus,
    MoneyCny,
    TokenUsage,
)


class ModelPrice(BaseModel):
    model_config = ConfigDict(frozen=True)
    input_cny_per_million: Decimal = Field(ge=0)
    output_cny_per_million: Decimal = Field(ge=0)


class OpenAICompatibleProvider:
    """调用 OpenAI-compatible chat/completions，并将网络错误转换为安全错误码。"""

    provider_id = "openai-compatible"
    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        timeout_seconds: float,
        pricing: Mapping[str, ModelPrice],
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._pricing = dict(pricing)
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._sleep = sleep

    async def generate_structured(self, request: LLMRequest[Any]) -> LLMResult[Any]:
        schema = json.dumps(request.response_model.model_json_schema(), ensure_ascii=False)
        payload = {
            "model": request.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{request.system_prompt}\n\n"
                        "必须严格返回一个 JSON 对象，不得输出 Markdown 或解释文字。"
                        f"返回值必须符合以下 JSON Schema：\n{schema}"
                    ),
                },
                {"role": "user", "content": json.dumps(request.user_payload, ensure_ascii=False)},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_object",
            },
        }
        body: Any = None
        response: httpx.Response | None = None
        request_started = time.perf_counter()
        self._logger.info(
            "LLM request started: stage=%s model=%s timeout_seconds=%s",
            request.agent_name,
            request.model,
            self._timeout_seconds,
        )
        for attempt in range(3):
            try:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                    json=payload,
                    timeout=self._timeout_seconds,
                )
            except httpx.TimeoutException:
                self._logger.warning(
                    "LLM request timed out: stage=%s model=%s attempt=%s elapsed_ms=%s",
                    request.agent_name,
                    request.model,
                    attempt + 1,
                    int((time.perf_counter() - request_started) * 1000),
                )
                return self._failure("LLM_TIMEOUT", "provider request timed out", True)
            except httpx.HTTPError:
                self._logger.warning(
                    "LLM network error: stage=%s model=%s attempt=%s elapsed_ms=%s",
                    request.agent_name,
                    request.model,
                    attempt + 1,
                    int((time.perf_counter() - request_started) * 1000),
                )
                return self._failure("LLM_NETWORK_ERROR", "provider network error", True)
            self._logger.info(
                "LLM response received: stage=%s model=%s attempt=%s status=%s elapsed_ms=%s",
                request.agent_name,
                request.model,
                attempt + 1,
                response.status_code,
                int((time.perf_counter() - request_started) * 1000),
            )
            if response.status_code != 429:
                break
            if attempt == 2:
                return self._failure("LLM_RATE_LIMITED", "provider rate limited request", True)
            delay = float(2**attempt)
            self._logger.warning(
                "LLM rate limited: stage=%s model=%s attempt=%s retry_in_seconds=%s",
                request.agent_name,
                request.model,
                attempt + 1,
                delay,
            )
            await self._sleep(delay)
        if response is None:
            return self._failure("LLM_NETWORK_ERROR", "provider returned no response", True)
        if response.status_code >= 400:
            return self._failure(
                "LLM_REQUEST_REJECTED", f"provider returned HTTP {response.status_code}", False
            )
        message: Any = None
        try:
            body = response.json()
            choice = (
                body.get("choices", [None])[0]
                if isinstance(body, dict) and body.get("choices")
                else None
            )
            message = choice.get("message") if isinstance(choice, dict) else None
            if not isinstance(message, dict):
                raise ValueError("provider response has no message object")
            content = message["content"]
            parsed = self._parse_json_content(content)
            data = request.response_model.model_validate(parsed)
            usage = TokenUsage.model_validate(body.get("usage", {}))
        except Exception as exc:
            validation_paths = (
                [
                    ".".join(str(part) for part in error["loc"])
                    for error in exc.errors(include_url=False, include_input=False)
                ]
                if isinstance(exc, ValidationError)
                else []
            )
            self._logger.warning(
                "structured LLM response invalid: stage=%s model=%s status=%s body_keys=%s "
                "message_keys=%s content_type=%s content_length=%s error_type=%s "
                "validation_paths=%s",
                request.agent_name,
                request.model,
                response.status_code,
                sorted(body.keys()) if isinstance(body, dict) else type(body).__name__,
                sorted(message.keys()) if isinstance(message, dict) else (),
                type(message.get("content")) if isinstance(message, dict) else type(None),
                len(message.get("content", ""))
                if isinstance(message, dict) and isinstance(message.get("content"), str)
                else 0,
                type(exc).__name__,
                validation_paths,
            )
            return self._failure(
                "LLM_STRUCTURED_OUTPUT_INVALID", "provider returned invalid JSON", False
            )
        return LLMResult(
            status=LLMStatus.SUCCESS,
            data=data,
            usage=usage,
            estimated_cost_cny=self.estimate_cost(usage, request.model),
        )

    @staticmethod
    def _parse_json_content(content: Any) -> Any:
        """兼容第三方服务返回的代码块、前后说明文字和文本块数组。"""
        if isinstance(content, list):
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        if not isinstance(content, str):
            return content
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = min(
                (index for index in (text.find("{"), text.find("[")) if index >= 0),
                default=-1,
            )
            if start < 0:
                raise
            end = max(text.rfind("}"), text.rfind("]"))
            if end <= start:
                raise
            return json.loads(text[start : end + 1])

    def _failure(self, code: str, message: str, retriable: bool) -> LLMResult[Any]:
        return LLMResult(
            status=LLMStatus.FAILED,
            usage=TokenUsage(),
            estimated_cost_cny=MoneyCny(amount=Decimal("0")),
            error=LLMError(code=code, message=message, retriable=retriable),
        )

    async def health_check(self) -> LLMHealth:
        return LLMHealth(available=True, provider_id=self.provider_id, message="configured")

    def estimate_cost(self, usage: TokenUsage, model: str) -> MoneyCny:
        price = self._pricing.get(
            model,
            ModelPrice(input_cny_per_million=Decimal("0"), output_cny_per_million=Decimal("0")),
        )
        cost = (
            Decimal(usage.prompt_tokens) * price.input_cny_per_million / Decimal(1_000_000)
            + Decimal(usage.completion_tokens)
            * price.output_cny_per_million
            / Decimal(1_000_000)
        )
        return MoneyCny(amount=cost)
