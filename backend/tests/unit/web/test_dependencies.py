from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sector_pulse.application.comparison.run_comparison_queries import RunComparisonQueries
from sector_pulse.application.orchestration.commands import MultiAgentRunCommands
from sector_pulse.config.settings import ApplicationSettings
from sector_pulse.storage.ports.tasks import RuntimeTaskRepositoryPort
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.web.dependencies import build_runtime_dependencies, build_web_router_dependencies
from sector_pulse.web.services.data_run_writing_service import (
    MultiAgentDataRunWritingService,
)

from backend.tests.comparison_fixtures import seed_pair


def test_sqlite_dependencies_are_fully_typed(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"

    dependencies = build_runtime_dependencies(
        ApplicationSettings(database_path=database_path), database_path
    )

    assert isinstance(dependencies.database, SQLiteDatabase)
    assert isinstance(dependencies.storage.task, RuntimeTaskRepositoryPort)
    assert dependencies.schedule_service is not None
    assert dependencies.data_run_service is not None
    assert dependencies.run_service is not None


def test_postgres_configuration_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthcheck = Mock(side_effect=ConnectionError("postgres unavailable"))
    monkeypatch.setattr(PostgresDatabase, "healthcheck", healthcheck)
    settings = ApplicationSettings(
        database_url="postgresql://sectorpulse:secret@localhost/sectorpulse"
    )

    with pytest.raises(ConnectionError, match="postgres unavailable"):
        build_runtime_dependencies(settings, Path("unused.db"))

    healthcheck.assert_called_once_with()


def test_comparison_dependency_reads_runtime_storage_and_accepts_override(tmp_path: Path) -> None:
    settings = ApplicationSettings(database_path=tmp_path / "app.sqlite")
    runtime = build_runtime_dependencies(settings, settings.database_path)
    base, compare = seed_pair(runtime.storage)
    dependencies = build_web_router_dependencies(runtime, settings)
    result = dependencies.comparison_queries.compare(base.run_id, compare.run_id)
    assert result.candidates.both == 2
    custom = RunComparisonQueries(runtime.storage)
    overridden = build_web_router_dependencies(runtime, settings, {"comparison_queries": custom})
    assert overridden.comparison_queries is custom


def test_explicit_multi_agent_service_override_selects_new_commands(tmp_path: Path) -> None:
    settings = ApplicationSettings(database_path=tmp_path / "app.sqlite")
    runtime = build_runtime_dependencies(settings, settings.database_path)

    dependencies = build_web_router_dependencies(
        runtime,
        settings,
        {"multi_agent_service": Mock()},
    )

    assert isinstance(dependencies.commands, MultiAgentRunCommands)


def test_runtime_dependencies_build_multi_agent_service_only_with_tool_factory(
    tmp_path: Path,
) -> None:
    settings = ApplicationSettings(database_path=tmp_path / "app.sqlite")
    runtime = build_runtime_dependencies(
        settings,
        settings.database_path,
        business_tool_factory=Mock(),
    )

    assert runtime.multi_agent_service is not None
    dependencies = build_web_router_dependencies(runtime, settings)
    assert isinstance(dependencies.commands, MultiAgentRunCommands)


def test_runtime_dependencies_can_build_default_multi_agent_service_explicitly(
    tmp_path: Path,
) -> None:
    settings = ApplicationSettings(database_path=tmp_path / "app.sqlite")
    runtime = build_runtime_dependencies(
        settings,
        settings.database_path,
        enable_multi_agent=True,
    )

    assert runtime.multi_agent_service is not None
    dependencies = build_web_router_dependencies(runtime, settings)
    assert isinstance(dependencies.commands, MultiAgentRunCommands)
    assert isinstance(dependencies.writing_service, MultiAgentDataRunWritingService)


def test_runtime_dependencies_wire_live_provider_settings_into_multi_agent_factory(
    tmp_path: Path,
) -> None:
    from pydantic import SecretStr

    settings = ApplicationSettings(
        database_path=tmp_path / "app.sqlite",
        llm_base_url="https://llm.example/v1",
        llm_api_key=SecretStr("test-key"),
        llm_model="deepseek-flash",
        llm_timeout_seconds=17,
    )
    runtime = build_runtime_dependencies(
        settings,
        settings.database_path,
        enable_multi_agent=True,
    )

    assert runtime.multi_agent_service is not None
    provider_factory = runtime.multi_agent_service.provider_factory
    assert provider_factory.base_url == settings.llm_base_url
    assert provider_factory.api_key == "test-key"
    assert provider_factory.live_model == settings.llm_model
    assert provider_factory.timeout_seconds == settings.llm_timeout_seconds


def test_multi_agent_data_run_continuation_rejects_a_selection_from_another_run() -> None:
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from sector_pulse.domain.market.candidate_selection import (
        CandidateSelection,
        CandidateSelectionMethod,
    )
    from sector_pulse.domain.runs.real_data_run import RealDataRunStatus

    run_id = uuid4()
    commands = Mock()
    runs = Mock()
    runs.get_run.return_value = SimpleNamespace(
        run_id=run_id,
        status=RealDataRunStatus.READY_FOR_ATTRIBUTION,
        provider="fixture",
    )
    service = MultiAgentDataRunWritingService(runs, commands)
    foreign_selection = CandidateSelection(
        run_id=uuid4(),
        version=1,
        selected_sector_ids=("sector-1", "sector-2", "sector-3"),
        method=CandidateSelectionMethod.MANUAL,
        confirmed_at=datetime.now(UTC),
        data_version="a" * 64,
    )

    with pytest.raises(ValueError, match="belong"):
        service.generate(run_id, foreign_selection)

    commands.continue_data_run.assert_not_called()


def test_the_runtime_bundle_does_not_carry_a_second_scheduler(tmp_path: Path) -> None:
    """The app runs the router bundle's scheduler, and only that one knows the engine.

    The bridge in the router bundle is told which commands to use; a second stack
    built alongside it here would be dormant *and* bound to the old engine, so it
    is exactly the kind of leftover that makes "one engine" untrue on paper.
    """
    settings = ApplicationSettings(database_path=tmp_path / "app.sqlite")
    runtime = build_runtime_dependencies(settings, settings.database_path)

    assert not hasattr(runtime, "scheduler")
    assert not hasattr(runtime, "coordinator")
