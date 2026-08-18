import json
import logging
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
    _logger = logging.getLogger(__name__)

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
                "type": "json_object",
            },
        }
        body: Any = None
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
            parsed = self._parse_json_content(content)
            data = request.response_model.model_validate(parsed)
            usage = TokenUsage.model_validate(body.get("usage", {}))
        except Exception as exc:
            self._logger.warning(
                "structured LLM response invalid: model=%s status=%s body_keys=%s "
                "message_keys=%s content_type=%s content_length=%s error_type=%s",
                request.model,
                response.status_code,
                sorted(body.keys()) if isinstance(body, dict) else type(body).__name__,
                sorted(body.get("choices", [{}])[0].get("message", {}).keys())
                if isinstance(body, dict) and body.get("choices")
                else (),
                type(body.get("choices", [{}])[0].get("message", {}).get("content"))
                if isinstance(body, dict) and body.get("choices")
                else type(None),
                len(body.get("choices", [{}])[0].get("message", {}).get("content", ""))
                if isinstance(body, dict) and body.get("choices")
                and isinstance(body.get("choices", [{}])[0].get("message", {}).get("content"), str)
                else 0,
                type(exc).__name__,
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
