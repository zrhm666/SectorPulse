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


@pytest.mark.asyncio
async def test_live_full_a0_to_a4_chain_reaches_human_review(tmp_path, monkeypatch):
    """Expensive opt-in acceptance: live reasoning over deterministic sandbox data."""
    from sector_pulse.application.orchestration.multi_agent_run_service import (
        MultiAgentRunRequest,
    )
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.config.settings import ApplicationSettings, load_environment
    from sector_pulse.domain.orchestration.models import TaskStatus
    from sector_pulse.web.dependencies import build_runtime_dependencies

    load_environment()
    packaged = load_llm_config(Path("config/llm.yaml"))
    settings = ApplicationSettings.from_environment(packaged)
    if settings.llm_api_key is None:
        pytest.skip("SECTOR_PULSE_LLM_API_KEY is absent")
    if not settings.llm_base_url or not settings.llm_model:
        pytest.skip("live LLM endpoint or model is absent")
    if packaged.model_pricing(settings.llm_model) is None:
        pytest.skip(f"live model price is not configured: {settings.llm_model}")

    monkeypatch.setenv("SECTOR_PULSE_LIVE_DATA_SANDBOX", "true")
    settings = settings.model_copy(
        update={
            "database_path": tmp_path / "live-full-chain.db",
            "budget_cny_per_run": Decimal("2.00"),
            "llm_timeout_seconds": min(settings.llm_timeout_seconds, 90),
        }
    )
    runtime = build_runtime_dependencies(
        settings,
        settings.database_path,
        enable_multi_agent=True,
    )
    service = runtime.multi_agent_service
    assert service is not None

    run_id = await service.create(
        MultiAgentRunRequest(
            goal="完成板块研究、归因、编辑写作和独立审校，形成待人工审阅稿。"
        ),
        provider="live",
    )
    proposal, _, selection_version, attempt = service.candidate_proposal(run_id)
    selected = tuple(item.provider_sector_id for item in proposal.items[:3])
    await service.confirm_selection(
        run_id=run_id,
        proposal_id=proposal.proposal_id,
        sector_ids=selected,
        expected_selection_version=selection_version,
        expected_attempt=attempt,
    )

    state = runtime.storage.orchestration.load(run_id)
    assert state is not None
    root = next(task for task in state.tasks if task.parent_id is None)
    assert root.status is TaskStatus.WAITING_USER_REVIEW
    assert {task.role for task in state.tasks if task.status is TaskStatus.COMPLETED} >= {
        "A1",
        "A2",
        "A3",
        "A4",
    }
    assert {artifact.kind for artifact in state.artifacts} >= {
        "candidate_selection",
        "sector_analysis",
        "article_outline",
        "article_draft",
        "draft_rules",
        "independent_review",
    }
    assert state.ledger.charged_cny <= Decimal("2.00")
