from __future__ import annotations

import asyncio
import logging

from aidynamic_agent.agents.factory import AgentFactory
from aidynamic_agent.agents.parent import ParentAgent
from aidynamic_agent.config import AppConfig
from aidynamic_agent.core.message import Message, Role
from aidynamic_agent.llm.exceptions import LLMError
from aidynamic_agent.llm.factory import ProviderFactory
from aidynamic_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class LegacyAdapter:
    """Compatibility adapter that bridges old and new agent architectures.

    Provides both sync and async entry points for running the agent.
    """

    def __init__(self, config: AppConfig | None = None):
        self.config = config or AppConfig.load()
        self._agent: ParentAgent | None = None

    async def _build_agent(self) -> ParentAgent:
        """Build a ParentAgent instance from config."""
        provider = ProviderFactory.create(self.config.provider)

        system_prompt = getattr(self.config.agent, "system_prompt", None) or ""
        registry = ToolRegistry()

        factory = AgentFactory(provider=provider, tool_registry=registry)
        agent = factory.create_parent_agent(system_prompt=system_prompt)
        self._agent = agent
        return agent

    async def run_agent_async(
        self,
        prompt: str,
        history: list[dict] | None = None,
    ) -> str:
        """Async entry point - runs the new agent architecture.

        Args:
            prompt: User input/prompt
            history: Optional conversation history as list of dicts

        Returns:
            Agent response text
        """
        agent = await self._build_agent()

        # Ensure context exists so history can be injected before the prompt
        context = await agent._ensure_context()

        # Inject history before the prompt
        if history:
            for entry in history:
                role_str = entry.get("role", "user")
                try:
                    role = Role(role_str)
                except ValueError:
                    role = Role.USER
                text = entry.get("content", "")
                msg = Message.from_text(role, text)
                await context.add_message(msg)

        try:
            result = await agent.run(prompt)
            return result.text
        except LLMError as e:
            logger.error(f"LLM error: {e}")
            return f"Error: {e}"
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return f"Error: {e}"

    def run_agent(
        self,
        prompt: str,
        history: list[dict] | None = None,
    ) -> str:
        """Sync entry point - smart event loop detection."""
        try:
            loop = asyncio.get_running_loop()
            future = asyncio.ensure_future(self.run_agent_async(prompt, history))
            return loop.run_until_complete(future)
        except RuntimeError:
            return asyncio.run(self.run_agent_async(prompt, history))


# Global singleton
_adapter_instance: LegacyAdapter | None = None


def get_adapter(config: AppConfig | None = None) -> LegacyAdapter:
    """Get or create the global adapter singleton."""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = LegacyAdapter(config=config)
    return _adapter_instance


def run_agent(prompt: str, history: list[dict] | None = None) -> str:
    """Convenience function to run agent synchronously."""
    return get_adapter().run_agent(prompt, history)
