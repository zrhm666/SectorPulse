from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx
from anthropic import (
    APIConnectionError as AnthropicAPIConnectionError,
)
from anthropic import (
    APIStatusError as AnthropicAPIStatusError,
)
from anthropic import (
    AsyncAnthropic,
    BadRequestError,
)
from anthropic import (
    AuthenticationError as AnthropicAuthError,
)
from anthropic import (
    RateLimitError as AnthropicRateLimit,
)

from aidynamic_agent.core.message import (
    Message,
    StreamChunk,
    ToolDefinition,
)
from aidynamic_agent.llm.adapters.anthropic_adapter import AnthropicAdapter
from aidynamic_agent.llm.base import LLMProvider, LLMResponse
from aidynamic_agent.llm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    ContextWindowExceededError,
    LLMError,
    ProviderUnavailableError,
    RateLimitError,
)

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider.

    Uses the official Anthropic SDK Messages API.
    Supports: text, thinking, tool_use content blocks.
    """

    DEFAULT_BASE_URL = "https://api.anthropic.com"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        api_version: str = "2023-06-01",
        timeout: float = 120.0,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.api_version = api_version
        self.timeout = timeout
        self._client: AsyncAnthropic | None = None
        self.adapter = AnthropicAdapter()

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None or self._client.is_closed():
            self._client = AsyncAnthropic(
                api_key=self.api_key,
                base_url=self.base_url or self.DEFAULT_BASE_URL,
                timeout=httpx.Timeout(
                    connect=10.0, read=self.timeout, write=self.timeout, pool=10.0
                ),
                max_retries=0,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed():
            await self._client.close()
            self._client = None

    async def create(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs,
    ) -> LLMResponse:
        client = self._get_client()
        payload = self.adapter.to_provider(messages, tools)

        body: dict = {
            "model": self.model,
            "max_tokens": kwargs.pop("max_tokens", 8192),
            "messages": payload.get("messages", []),
        }
        if "system" in payload:
            body["system"] = payload["system"]
        if "tools" in payload:
            body["tools"] = payload["tools"]
            body.setdefault("tool_choice", {"type": "auto"})

        body.update(kwargs)

        try:
            message = await client.messages.create(**body)
            return self.adapter.from_sdk_response(message)

        except AnthropicAuthError as e:
            raise AuthenticationError(str(e)) from e
        except AnthropicRateLimit as e:
            raise RateLimitError(str(e)) from e
        except BadRequestError as e:
            msg = str(e).lower()
            if "context" in msg or "too_long" in msg:
                raise ContextWindowExceededError(str(e)) from e
            raise LLMError(str(e)) from e
        except AnthropicAPIConnectionError as e:
            raise APIConnectionError(str(e)) from e
        except AnthropicAPIStatusError as e:
            if e.status_code >= 500:
                raise ProviderUnavailableError(str(e)) from e
            raise LLMError(str(e)) from e

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        client = self._get_client()
        payload = self.adapter.to_provider(messages, tools)

        body: dict = {
            "model": self.model,
            "max_tokens": kwargs.pop("max_tokens", 8192),
            "messages": payload.get("messages", []),
        }
        if "system" in payload:
            body["system"] = payload["system"]
        if "tools" in payload:
            body["tools"] = payload["tools"]
            body.setdefault("tool_choice", {"type": "auto"})

        body.update(kwargs)

        try:
            async with client.messages.stream(**body) as stream:
                async for event in stream:
                    chunk = self.adapter.from_sdk_stream_event(event)
                    if chunk:
                        yield chunk

        except AnthropicAuthError as e:
            raise AuthenticationError(str(e)) from e
        except AnthropicRateLimit as e:
            raise RateLimitError(str(e)) from e
        except BadRequestError as e:
            msg = str(e).lower()
            if "context" in msg or "too_long" in msg:
                raise ContextWindowExceededError(str(e)) from e
            raise LLMError(str(e)) from e
        except AnthropicAPIConnectionError as e:
            raise APIConnectionError(str(e)) from e
        except AnthropicAPIStatusError as e:
            if e.status_code >= 500:
                raise ProviderUnavailableError(str(e)) from e
            raise LLMError(str(e)) from e
