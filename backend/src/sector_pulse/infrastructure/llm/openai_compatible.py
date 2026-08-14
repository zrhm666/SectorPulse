import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

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

    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        timeout_seconds: float,
        pricing: Mapping[str, ModelPrice],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._pricing = dict(pricing)
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def generate_structured(self, request: LLMRequest[Any]) -> LLMResult[Any]:
        payload = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": json.dumps(request.user_payload, ensure_ascii=False)},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.response_model.__name__,
                    "schema": request.response_model.model_json_schema(),
                    "strict": True,
                },
            },
        }
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException:
            return self._failure("LLM_TIMEOUT", "provider request timed out", True)
        except httpx.HTTPError:
            return self._failure("LLM_NETWORK_ERROR", "provider network error", True)
        if response.status_code == 429:
            return self._failure("LLM_RATE_LIMITED", "provider rate limited request", True)
        if response.status_code >= 400:
            return self._failure(
                "LLM_REQUEST_REJECTED", f"provider returned HTTP {response.status_code}", False
            )
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content) if isinstance(content, str) else content
            data = request.response_model.model_validate(parsed)
            usage = TokenUsage.model_validate(body.get("usage", {}))
        except Exception:
            return self._failure(
                "LLM_STRUCTURED_OUTPUT_INVALID", "provider returned invalid JSON", False
            )
        return LLMResult(
            status=LLMStatus.SUCCESS,
            data=data,
            usage=usage,
            estimated_cost_cny=self.estimate_cost(usage, request.model),
        )

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
