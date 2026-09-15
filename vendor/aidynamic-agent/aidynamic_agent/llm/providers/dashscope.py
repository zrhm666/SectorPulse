"""DashScope Provider - for Alibaba Qwen models."""

from __future__ import annotations

from aidynamic_agent.llm.adapters.dashscope_adapter import DashScopeAdapter
from aidynamic_agent.llm.providers.openai import OpenAIProvider


class DashScopeProvider(OpenAIProvider):
    """Provider for DashScope/Qwen API.

    DashScope uses OpenAI-compatible format but has some differences:
    - Doesn't support "tool_result" content type (only text/image_url/video_url/video)
    - Base URL: https://dashscope.aliyuncs.com/compatible-mode/v1

    Inherits from OpenAIProvider and uses DashScopeAdapter for message conversion.
    """

    # DashScope OpenAI-compatible endpoint
    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str = "qwen-plus",
        timeout: float = 120.0,
    ):
        """Initialize DashScope provider.

        Args:
            api_key: DashScope API key (sk-xxx format)
            base_url: Optional custom base URL (defaults to DashScope endpoint)
            model: Model name (qwen-plus, qwen-turbo, qwen-max, etc.)
            timeout: Request timeout in seconds
        """
        # Call parent constructor but don't use its adapter
        # We'll set our own adapter after
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self._client = None

        # Use DashScopeAdapter instead of OpenAIAdapter
        # This is the key fix for tool_result compatibility
        self.adapter = DashScopeAdapter()
