from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_commands_create_retry_and_cancel_use_only_multi_agent_snapshots(tmp_path):
    from sector_pulse.application.orchestration.commands import MultiAgentRunCommands
    from sector_pulse.application.orchestration.multi_agent_run_service import MultiAgentRunService
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.orchestration.models import TaskStatus
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "multi-agent-commands.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    service = MultiAgentRunService(
        repository=repository,
        config=load_llm_config(Path("config/llm.yaml")),
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_factory=AgentProviderFactory(
            fixture_turns={
                AgentRole.A0: (
                    FixtureAgentTurn(text="first pause"),
                    FixtureAgentTurn(text="retry pause"),
                )
            }
        ),
    )
    commands = MultiAgentRunCommands(service=service, repository=repository)

    first = commands.create_run(
        {"goal": "full analysis"},
        "fixture",
        selection_policy="server_default",
    )
    await commands.wait(first)
    first_state = repository.load(first)
    assert first_state.execution_engine == "multi_agent"
    assert first_state.selection_policy == "server_default"
    assert first_state.tasks[0].status is TaskStatus.WAITING

    retry = commands.retry_run(first)
    await commands.wait(retry)
    retry_state = repository.load(retry)
    assert retry != first
    assert retry_state.retry_of_run_id == first
    assert retry_state.tasks[0].scope == first_state.tasks[0].scope
    assert repository.load(first) == first_state

    assert commands.cancel_run(retry) is True
    assert commands.cancel_run(retry) is True
    assert repository.load(retry).tasks[0].status is TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_commands_recover_expired_multi_agent_root_once(tmp_path):
    from sector_pulse.application.orchestration.commands import MultiAgentRunCommands
    from sector_pulse.application.orchestration.multi_agent_run_service import MultiAgentRunService
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.orchestration.models import TaskStatus
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "multi-agent-recovery.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    service = MultiAgentRunService(
        repository=repository,
        config=load_llm_config(Path("config/llm.yaml")),
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_factory=AgentProviderFactory(
            fixture_turns={AgentRole.A0: (FixtureAgentTurn(text="recovered"),)}
        ),
    )
    commands = MultiAgentRunCommands(service=service, repository=repository)
    run_id = commands.create_run({"goal": "recover me"}, "fixture")
    await commands.wait(run_id)
    state = repository.load(run_id)
    root = state.tasks[0]
    expired = state.model_copy(
        update={
            "revision": state.revision + 1,
            "tasks": (
                root.model_copy(
                    update={
                        "status": TaskStatus.INTERRUPTED,
                        "worker_id": "stale-worker",
                        "lease_expires_at": datetime.now(UTC),
                    }
                ),
            )
        }
    )
    repository.save(expired, state.revision)

    assert commands.recover_expired(datetime.now(UTC)) == 1
    await commands.wait(run_id)
    recovered = repository.load(run_id)
    assert recovered.tasks[0].attempt == root.attempt + 1
    assert commands.recover_expired(datetime.now(UTC)) == 0


def test_commands_live_preflight_is_synchronous_and_writes_nothing(tmp_path):
    from sector_pulse.application.orchestration.commands import MultiAgentRunCommands
    from sector_pulse.application.orchestration.multi_agent_run_service import MultiAgentRunService
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.infrastructure.agents.provider_factory import AgentProviderFactory
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "multi-agent-command-preflight.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    commands = MultiAgentRunCommands(
        service=MultiAgentRunService(
            repository=repository,
            config=load_llm_config(Path("config/llm.yaml")),
            prompt_registry=PromptRegistry(Path("config/prompts")),
            provider_factory=AgentProviderFactory(
                base_url="https://host/v1",
                api_key="key",
                live_model="unpriced",
                consent_file=tmp_path / "missing-consent",
            ),
        ),
        repository=repository,
    )

    with pytest.raises(ValueError, match="consent"):
        commands.create_run({"goal": "do not persist"}, "live")


@pytest.mark.asyncio
async def test_continue_data_run_seeds_confirmed_selection_on_the_same_run(tmp_path):
    from sector_pulse.application.orchestration.commands import MultiAgentRunCommands
    from sector_pulse.application.orchestration.multi_agent_run_service import MultiAgentRunService
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.market.candidate_selection import (
        CandidateSelection,
        CandidateSelectionMethod,
    )
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "continued-data-run.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    commands = MultiAgentRunCommands(
        service=MultiAgentRunService(
            repository=repository,
            config=load_llm_config(Path("config/llm.yaml")),
            prompt_registry=PromptRegistry(Path("config/prompts")),
            provider_factory=AgentProviderFactory(
                fixture_turns={AgentRole.A0: (FixtureAgentTurn(text="continue later"),)}
            ),
        ),
        repository=repository,
    )
    run_id = uuid4()
    selection = CandidateSelection(
        run_id=run_id,
        version=3,
        selected_sector_ids=("sector-1", "sector-2", "sector-3"),
        method=CandidateSelectionMethod.MANUAL,
        confirmed_at=datetime.now(UTC),
        data_version="a" * 64,
    )

    continued = commands.continue_data_run(run_id, selection, provider="fixture")
    await commands.wait(run_id)

    assert continued == run_id
    state = repository.load(run_id)
    assert state is not None
    root = state.tasks[0]
    assert root.selection_version == 3
    assert root.input_artifact_ids == (state.artifacts[0].artifact_id,)
    assert state.artifacts[0].kind == "candidate_selection"
    assert state.artifacts[0].reference == "candidate-selection:3"


@pytest.mark.asyncio
async def test_retry_historical_data_run_creates_multi_agent_lineage(tmp_path):
    from sector_pulse.application.orchestration.commands import MultiAgentRunCommands
    from sector_pulse.application.orchestration.multi_agent_run_service import MultiAgentRunService
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.runs.real_data_run import RealDataRun, RealDataRunRequest
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository
    from sector_pulse.storage.sqlite.runs.real_data_run_repository import (
        SQLiteRealDataRunRepository,
    )

    database = SQLiteDatabase(tmp_path / "retry-historical-data-run.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    real_runs = SQLiteRealDataRunRepository(database)
    source = RealDataRun(
        request=RealDataRunRequest(mode="post_close"),
        provider="fixture",
    )
    real_runs.insert(source)
    commands = MultiAgentRunCommands(
        service=MultiAgentRunService(
            repository=repository,
            config=load_llm_config(Path("config/llm.yaml")),
            prompt_registry=PromptRegistry(Path("config/prompts")),
            provider_factory=AgentProviderFactory(
                fixture_turns={AgentRole.A0: (FixtureAgentTurn(text="retry waiting"),)}
            ),
        ),
        repository=repository,
        real_runs=real_runs,
    )

    retried = commands.retry_data_run(source.run_id)
    await commands.wait(retried)

    state = repository.load(retried)
    assert state is not None
    assert retried != source.run_id
    assert state.retry_of_run_id == source.run_id
    assert state.provider == "fixture"
    assert "盘后" in state.tasks[0].scope
