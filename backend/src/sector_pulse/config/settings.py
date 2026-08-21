import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from sector_pulse.config.llm_config import LLMRuntimeConfig


def load_environment(dotenv_path: Path = Path(".env")) -> None:
    """加载项目级配置，保留调用进程已经显式设置的环境变量。"""
    load_dotenv(dotenv_path=dotenv_path, override=False)


class ApplicationSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_path: Path = Path("data/sector-pulse.db")
    database_url: str | None = None
    llm_provider: str = "fixture"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    budget_cny_per_run: Decimal = Field(default=Decimal("2.00"), gt=0)
    max_attribution_concurrency: int = Field(default=4, ge=1, le=32)
    max_revision_rounds: int = Field(default=2, ge=0, le=2)
    scheduler_enabled: bool = False
    scheduler_poll_seconds: int = Field(default=10, ge=1, le=3600)
    task_lease_seconds: int = Field(default=300, ge=1, le=86400)
    task_max_attempts: int = Field(default=3, ge=1, le=10)
    task_deadline_seconds: int = Field(default=900, ge=1, le=86400)
    task_retry_backoff_seconds: int = Field(default=2, ge=0, le=3600)

    def apply_runtime_overrides(self, yaml_config: LLMRuntimeConfig) -> LLMRuntimeConfig:
        """将环境变量中的运行限制合并到不可变的 YAML 配置副本。"""
        return yaml_config.model_copy(
            update={
                "budget_cny_per_run": self.budget_cny_per_run,
                "max_attribution_concurrency": self.max_attribution_concurrency,
                "max_revision_rounds": self.max_revision_rounds,
            }
        )

    @classmethod
    def from_environment(cls, yaml_config: LLMRuntimeConfig) -> "ApplicationSettings":
        def value(name: str, default: str | None = None) -> str | None:
            return os.environ.get(name, default)

        def boolean(name: str, default: bool) -> bool:
            raw = value(name, str(default).lower())
            if raw is None or raw.lower() not in {"true", "false"}:
                raise ValueError(f"{name} must be true or false")
            return raw.lower() == "true"

        return cls(
            database_path=value("SECTOR_PULSE_DATABASE_PATH", "data/sector-pulse.db"),
            database_url=value("SECTOR_PULSE_DATABASE_URL"),
            llm_provider=value("SECTOR_PULSE_LLM_PROVIDER", "fixture"),
            llm_base_url=value("SECTOR_PULSE_LLM_BASE_URL"),
            llm_api_key=SecretStr(value("SECTOR_PULSE_LLM_API_KEY"))
            if value("SECTOR_PULSE_LLM_API_KEY")
            else None,
            llm_model=value("SECTOR_PULSE_LLM_MODEL"),
            llm_timeout_seconds=float(
                value("SECTOR_PULSE_LLM_TIMEOUT_SECONDS", "60") or "60"
            ),
            budget_cny_per_run=Decimal(
                value("SECTOR_PULSE_LLM_BUDGET_CNY", str(yaml_config.budget_cny_per_run))
                or str(yaml_config.budget_cny_per_run)
            ),
            max_attribution_concurrency=int(
                value(
                    "SECTOR_PULSE_LLM_MAX_ATTRIBUTION_CONCURRENCY",
                    str(yaml_config.max_attribution_concurrency),
                )
                or yaml_config.max_attribution_concurrency
            ),
            max_revision_rounds=int(
                value(
                    "SECTOR_PULSE_LLM_MAX_REVISION_ROUNDS",
                    str(yaml_config.max_revision_rounds),
                )
                or yaml_config.max_revision_rounds
            ),
            scheduler_enabled=boolean("SECTOR_PULSE_SCHEDULER_ENABLED", False),
            scheduler_poll_seconds=int(value("SECTOR_PULSE_SCHEDULER_POLL_SECONDS", "10") or "10"),
            task_lease_seconds=int(value("SECTOR_PULSE_TASK_LEASE_SECONDS", "300") or "300"),
            task_max_attempts=int(value("SECTOR_PULSE_TASK_MAX_ATTEMPTS", "3") or "3"),
            task_deadline_seconds=int(value("SECTOR_PULSE_TASK_DEADLINE_SECONDS", "900") or "900"),
            task_retry_backoff_seconds=int(
                value("SECTOR_PULSE_TASK_RETRY_BACKOFF_SECONDS", "2") or "2"
            ),
        )
