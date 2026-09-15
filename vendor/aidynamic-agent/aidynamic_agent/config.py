"""Configuration for the Agent OOP refactor project."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(env_prefix="LLM_", env_file=".env", extra="ignore")

    LLM_PROVIDER: str = "anthropic"
    API_KEY: str = ""
    BASE_URL: str | None = None
    MODEL_ID: str = "claude-sonnet-4-20250514"


class AgentConfig(BaseSettings):
    """Agent runtime configuration."""

    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=".env", extra="ignore")

    MAX_LOOPS: int = 30
    MAX_TOKENS: int = 8000
    TOTAL_TIMEOUT: int = 300
    TOKEN_BUDGET: int = 100000
    MAX_RETRIES: int = 3


class ToolConfig(BaseSettings):
    """Tool subsystem configuration."""

    model_config = SettingsConfigDict(env_prefix="TOOL_", env_file=".env", extra="ignore")

    WORKDIR: str = "."
    DEBUG_MODE: bool = False
    USE_LEGACY: bool = False


class AppConfig(BaseModel):
    """Combined application configuration."""

    provider: ProviderConfig
    agent: AgentConfig
    tool: ToolConfig

    @classmethod
    def load(cls, env_file: Path | str | None = None) -> AppConfig:
        """Load configuration from environment / .env file.

        Args:
            env_file: Optional path to a .env file. If None, the default
                ``.env`` in the current working directory is used.

        Returns:
            A fully populated ``AppConfig`` instance.
        """
        provider = ProviderConfig(_env_file=env_file) if env_file else ProviderConfig()
        agent = AgentConfig(_env_file=env_file) if env_file else AgentConfig()
        tool = ToolConfig(_env_file=env_file) if env_file else ToolConfig()
        return cls(provider=provider, agent=agent, tool=tool)
