"""Explicit, bounded live acceptance for the aidynamic-agent production provider path."""

from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = pytest.mark.live_llm


@pytest.mark.asyncio
async def test_live_parent_uses_one_read_only_tool_with_audited_budget(tmp_path):
    from sector_pulse.application.orchestration.multi_agent_run_service import (
        MultiAgentRunRequest,
        MultiAgentRunService,
    )
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.config.settings import ApplicationSettings, load_environment
    from sector_pulse.domain.orchestration.models import TaskStatus
    from sector_pulse.infrastructure.agents.provider_factory import AgentProviderFactory
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    load_environment()
    packaged = load_llm_config(Path("config/llm.yaml"))
    settings = ApplicationSettings.from_environment(packaged)
    if settings.llm_api_key is None:
        pytest.skip("SECTOR_PULSE_LLM_API_KEY is absent")
    if not settings.llm_base_url or not settings.llm_model:
        pytest.skip("live LLM endpoint or model is absent")
    price = packaged.model_pricing(settings.llm_model)
    if price is None:
        pytest.skip(f"live model price is not configured: {settings.llm_model}")
    config = settings.apply_runtime_overrides(packaged).model_copy(
        update={
            "budget_cny_per_run": Decimal("0.10"),
            "max_agent_calls": 3,
            "max_agent_tokens": 12000,
            "max_orchestration_tool_calls": 2,
            "orchestration_timeout_seconds": 60,
        }
    )
    database = SQLiteDatabase(tmp_path / "live-agent-acceptance.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    service = MultiAgentRunService(
        repository=repository,
        config=config,
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_factory=AgentProviderFactory(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
            live_model=settings.llm_model,
            timeout_seconds=min(settings.llm_timeout_seconds, 45),
        ),
    )

    run_id = await service.create(
        MultiAgentRunRequest(
            goal=(
                "This is a read-only provider acceptance. Call inspect_tasks exactly once, "
                "then briefly report the root task status. Do not delegate and do not request "
                "selection or completion."
            )
        ),
        provider="live",
    )

    state = repository.load(run_id)
    assert state is not None
    assert state.provider == "live"
    assert state.tasks[0].status is TaskStatus.WAITING
    assert [call.tool_name for call in state.ledger.tool_invocations] == ["inspect_tasks"]
    assert 1 <= state.ledger.calls <= 3
    assert state.ledger.charged_tokens <= config.max_agent_tokens
    assert state.ledger.charged_cny <= Decimal("0.10")
    assert all(call.provider == "live" for call in state.ledger.reservations)
    assert all(call.model == settings.llm_model for call in state.ledger.reservations)
