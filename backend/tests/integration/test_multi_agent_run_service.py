from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("aidynamic_agent")


@pytest.mark.asyncio
async def test_fixture_create_runs_real_parent_and_a1_without_legacy_pipeline(
    tmp_path, monkeypatch
):
    from sector_pulse.application.data_runs import real_data_orchestrator
    from sector_pulse.application.orchestration.multi_agent_run_service import (
        MultiAgentRunRequest,
        MultiAgentRunService,
    )
    from sector_pulse.application.writing import agent_runtime, phase1b_pipeline
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.orchestration.models import TaskStatus
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
        FixtureToolCall,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy execution path was called")

    monkeypatch.setattr(phase1b_pipeline, "run_phase1b_pipeline", forbidden)
    monkeypatch.setattr(real_data_orchestrator, "run_real_data_workflow", forbidden)
    monkeypatch.setattr(agent_runtime.AgentRuntime, "run", forbidden)

    database = SQLiteDatabase(tmp_path / "multi-agent-create.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    factory = AgentProviderFactory(
        fixture_turns={
            AgentRole.A0: (
                FixtureAgentTurn(
                    tool_calls=(
                        FixtureToolCall(
                            tool_call_id="delegate-a1",
                            tool_name="delegate",
                            tool_input={
                                "role": "A1",
                                "goal": "prepare candidate data",
                                "scope": "data-preparation",
                            },
                        ),
                    ),
                    total_tokens=11,
                ),
                FixtureAgentTurn(text="waiting for the next coordinator step", total_tokens=3),
            ),
            AgentRole.A1: (FixtureAgentTurn(text="data preparation inspected", total_tokens=5),),
        }
    )
    service = MultiAgentRunService(
        repository=repository,
        config=load_llm_config(Path("config/llm.yaml")),
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_factory=factory,
    )

    run_id = await service.create(
        MultiAgentRunRequest(goal="prepare a sector analysis"), provider="fixture"
    )

    state = repository.load(run_id)
    assert state is not None
    assert state.execution_engine == "multi_agent"
    assert state.provider == "fixture"
    root = next(task for task in state.tasks if task.parent_id is None)
    child = next(task for task in state.tasks if task.parent_id == root.task_id)
    assert root.role == "A0"
    assert root.status is TaskStatus.WAITING
    assert child.role == "A1"
    assert child.status is TaskStatus.COMPLETED
    assert [(call.role, call.attempt) for call in state.ledger.reservations] == [
        ("A0", 1),
        ("A1", 1),
        ("A0", 1),
    ]
    delegated = next(call for call in state.ledger.tool_invocations if call.tool_name == "delegate")
    assert delegated.task_id == root.task_id
    assert delegated.attempt == 1
    assert delegated.role == "A0"
    assert delegated.result_reference == f"task:{child.task_id}"


@pytest.mark.asyncio
async def test_create_resolves_business_tool_factory_for_each_run(tmp_path):
    from sector_pulse.application.orchestration.multi_agent_run_service import (
        MultiAgentRunRequest,
        MultiAgentRunService,
    )
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.infrastructure.agents.composition import (
        REQUIRED_BUSINESS_TOOL_NAMES,
        AgentBusinessToolFactory,
    )
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    calls: list[tuple[object, str]] = []

    def source(run_id, provider):
        calls.append((run_id, provider))
        return {name: (lambda context: object()) for name in REQUIRED_BUSINESS_TOOL_NAMES}

    database = SQLiteDatabase(tmp_path / "business-tool-factory.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    service = MultiAgentRunService(
        repository=repository,
        config=load_llm_config(Path("config/llm.yaml")),
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_factory=AgentProviderFactory(
            fixture_turns={AgentRole.A0: (FixtureAgentTurn(text="pause"),)}
        ),
        business_tool_factory=AgentBusinessToolFactory(source),
    )

    run_id = await service.create(MultiAgentRunRequest(goal="prepare"), provider="fixture")

    assert calls == [(run_id, "fixture")]


@pytest.mark.asyncio
async def test_live_preflight_fails_before_snapshot_is_written(tmp_path):
    from sector_pulse.application.orchestration.multi_agent_run_service import (
        MultiAgentRunRequest,
        MultiAgentRunService,
    )
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.infrastructure.agents.provider_factory import AgentProviderFactory
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "multi-agent-live-preflight.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    run_id = uuid4()
    service = MultiAgentRunService(
        repository=repository,
        config=load_llm_config(Path("config/llm.yaml")),
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_factory=AgentProviderFactory(
            base_url="https://host/v1",
            api_key="key",
            live_model="unpriced-live-model",
            consent_file=tmp_path / "missing-consent",
        ),
    )

    with pytest.raises(ValueError, match="consent"):
        await service.create(
            MultiAgentRunRequest(goal="must not persist", run_id=run_id), provider="live"
        )
    assert repository.load(run_id) is None


@pytest.mark.asyncio
async def test_server_default_policy_is_frozen_and_duplicate_create_keeps_one_root(tmp_path):
    from sector_pulse.application.orchestration.multi_agent_run_service import (
        MultiAgentRunRequest,
        MultiAgentRunService,
    )
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "multi-agent-default-policy.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    service = MultiAgentRunService(
        repository=repository,
        config=load_llm_config(Path("config/llm.yaml")),
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_factory=AgentProviderFactory(
            fixture_turns={AgentRole.A0: (FixtureAgentTurn(text="scheduled pause"),)}
        ),
    )
    run_id = uuid4()
    request = MultiAgentRunRequest(
        run_id=run_id,
        goal="scheduled analysis",
        selection_policy="server_default",
    )
    await service.create(request, provider="fixture")
    with pytest.raises(ValueError, match="already exists"):
        await service.create(request, provider="fixture")

    state = repository.load(run_id)
    assert state.selection_policy == "server_default"
    assert len([task for task in state.tasks if task.parent_id is None]) == 1


@pytest.mark.asyncio
async def test_service_cancel_is_idempotent_and_recovery_requires_expired_lease(tmp_path):
    from sector_pulse.application.orchestration.multi_agent_run_service import (
        MultiAgentRunRequest,
        MultiAgentRunService,
    )
    from sector_pulse.application.orchestration.runtime import OrchestrationRunStarter
    from sector_pulse.application.orchestration.tasks import TaskOwnershipError
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
    config = load_llm_config(Path("config/llm.yaml"))
    prompts = PromptRegistry(Path("config/prompts"))
    cancellation_service = MultiAgentRunService(
        repository=repository,
        config=config,
        prompt_registry=prompts,
        provider_factory=AgentProviderFactory(
            fixture_turns={AgentRole.A0: (FixtureAgentTurn(text="pause"),)}
        ),
    )
    cancelled_run = await cancellation_service.create(
        MultiAgentRunRequest(goal="cancel me"), provider="fixture"
    )
    cancellation_service.cancel(cancelled_run)
    cancellation_service.cancel(cancelled_run)
    assert repository.load(cancelled_run).tasks[0].status is TaskStatus.CANCELLED

    run_id, root_id = uuid4(), uuid4()
    started_at = datetime.now(UTC)
    OrchestrationRunStarter(repository, config).start(
        run_id=run_id,
        task_id=root_id,
        worker_id="dead-worker",
        goal="recover me",
        now=started_at,
    )
    recovery_service = MultiAgentRunService(
        repository=repository,
        config=config,
        prompt_registry=prompts,
        provider_factory=AgentProviderFactory(
            fixture_turns={AgentRole.A0: (FixtureAgentTurn(text="recovered"),)}
        ),
    )
    with pytest.raises(TaskOwnershipError, match="active lease"):
        await recovery_service.recover(run_id, expected_attempt=1, now=started_at)
    current = repository.load(run_id)
    expired_root = current.tasks[0].model_copy(
        update={"lease_expires_at": started_at - timedelta(seconds=1)}
    )
    repository.save(
        current.model_copy(
            update={"revision": current.revision + 1, "tasks": (expired_root,)}
        ),
        current.revision,
        "test.lease_expired",
    )

    await recovery_service.recover(run_id, expected_attempt=1, now=started_at)
    recovered = repository.load(run_id)
    assert recovered.tasks[0].attempt == 2
    assert recovered.tasks[0].status is TaskStatus.WAITING
    assert [(call.role, call.attempt) for call in recovered.ledger.reservations] == [("A0", 2)]


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgres_fixture_create_has_same_parent_a1_and_audit_contract():
    import os

    from sector_pulse.application.orchestration.multi_agent_run_service import (
        MultiAgentRunRequest,
        MultiAgentRunService,
    )
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.orchestration.models import TaskStatus
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
        FixtureToolCall,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.postgres.database import PostgresDatabase
    from sector_pulse.storage.postgres.orchestration.repository import (
        PostgresOrchestrationRepository,
    )
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    url = os.getenv("SECTOR_PULSE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires dedicated SECTOR_PULSE_TEST_DATABASE_URL")
    assert (make_url(url).database or "").endswith("_test"), "business database refused"
    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresOrchestrationRepository(database)
    factory = AgentProviderFactory(
        fixture_turns={
            AgentRole.A0: (
                FixtureAgentTurn(
                    tool_calls=(
                        FixtureToolCall(
                            tool_call_id="delegate-a1-pg",
                            tool_name="delegate",
                            tool_input={
                                "role": "A1",
                                "goal": "prepare data",
                                "scope": "data-preparation",
                            },
                        ),
                    ),
                    total_tokens=2,
                ),
                FixtureAgentTurn(text="parent paused", total_tokens=1),
            ),
            AgentRole.A1: (FixtureAgentTurn(text="child complete", total_tokens=1),),
        }
    )
    service = MultiAgentRunService(
        repository=repository,
        config=load_llm_config(Path("config/llm.yaml")),
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_factory=factory,
    )
    run_id = None
    try:
        run_id = await service.create(
            MultiAgentRunRequest(goal="postgres contract"), provider="fixture"
        )
        state = PostgresOrchestrationRepository(database).load(run_id)
        assert state is not None
        assert state.execution_engine == "multi_agent"
        assert state.provider == "fixture"
        assert [task.role for task in state.tasks] == ["A0", "A1"]
        assert [task.status for task in state.tasks] == [
            TaskStatus.WAITING,
            TaskStatus.COMPLETED,
        ]
        assert [call.role for call in state.ledger.reservations] == ["A0", "A1", "A0"]
        assert [call.tool_name for call in state.ledger.tool_invocations] == ["delegate"]
        service.cancel(run_id)
        assert PostgresOrchestrationRepository(database).load(run_id).tasks[0].status is (
            TaskStatus.CANCELLED
        )
    finally:
        if run_id is not None:
            with database.start().begin() as connection:
                connection.execute(
                    text("DELETE FROM orchestration_events WHERE run_id=:run"),
                    {"run": str(run_id)},
                )
                connection.execute(
                    text("DELETE FROM orchestration_snapshots WHERE run_id=:run"),
                    {"run": str(run_id)},
                )
        database.close()


@pytest.mark.asyncio
async def test_orchestration_events_record_names_and_never_copy_the_snapshot(
    tmp_path,
) -> None:
    """Events are an audit trail of *what happened*, not a second copy of the run.

    The snapshot already holds tasks, budget and artifacts. If an event carried a
    payload copy, business text would be duplicated in a table that is meant to
    stay small and greppable.
    """
    import json

    from sector_pulse.application.orchestration.multi_agent_run_service import (
        MultiAgentRunRequest,
        MultiAgentRunService,
    )
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "orchestration-events.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    service = MultiAgentRunService(
        repository=repository,
        config=load_llm_config(Path("config/llm.yaml")),
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_factory=AgentProviderFactory(
            fixture_turns={AgentRole.A0: (FixtureAgentTurn(text="pause"),)}
        ),
    )

    run_id = await service.create(
        MultiAgentRunRequest(goal="仅用于事件卫生检查的目标"), provider="fixture"
    )

    state = repository.load(run_id)
    assert state is not None
    events = repository.events(run_id)
    assert events, "a created run must leave an audit trail"

    payload = state.model_dump_json()
    for _, event in events:
        assert isinstance(event, str), "an event payload must stay a bare name"
        assert event
        assert event != payload
        assert "tasks" not in event and "ledger" not in event
        assert json.loads(json.dumps(event)) == event
    assert [revision for revision, _ in events] == sorted(revision for revision, _ in events)
