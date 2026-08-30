from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sector_pulse.application.candidate_selection_service import CandidateSelectionService
from sector_pulse.application.data_run_workbench_queries import DataRunWorkbenchQueries
from sector_pulse.application.evidence_decision_service import EvidenceDecisionService
from sector_pulse.application.governance_service import GovernanceService
from sector_pulse.application.phase1a2_probe import Phase1A2Dependencies
from sector_pulse.application.real_data_queries import RealDataRunQueries
from sector_pulse.application.run_commands import RunCommandService
from sector_pulse.application.run_coordinator import RunCoordinator
from sector_pulse.application.run_queries import RunQueryService
from sector_pulse.application.schedule_service import ScheduleService
from sector_pulse.application.scheduled_data_bridge import ScheduledDataRunBridge
from sector_pulse.application.scheduler import EmbeddedScheduler
from sector_pulse.application.task_run_service import TaskRunService
from sector_pulse.config.llm_config import load_llm_config
from sector_pulse.config.news_config import load_entity_config
from sector_pulse.config.settings import ApplicationSettings
from sector_pulse.domain.news_retrieval import SectorEntityConfig
from sector_pulse.infrastructure.llm.fixture_resources import load_default_fixture_responses
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.infrastructure.providers.real_data_factory import RealDataProviderFactory
from sector_pulse.ports.market_data import MarketDataPort
from sector_pulse.ports.news_sources import (
    DisclosureSearchPort,
    GlobalNewsDiscoveryPort,
    KeywordNewsSearchPort,
    SectorConstituentPort,
)
from sector_pulse.storage.database_runtime import Database, build_database
from sector_pulse.storage.ports import RuntimeTaskRepositoryPort
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.runtime_bundle import (
    RuntimeStorageBundle,
    build_postgres_storage,
    build_sqlite_storage,
)
from sector_pulse.web.data_run_service import DataRunService
from sector_pulse.web.data_run_writing_service import DataRunWritingService
from sector_pulse.web.progress_bus import ProgressBus
from sector_pulse.web.routers.runs_review import ReviewRouterDependencies
from sector_pulse.web.run_service import RunService


@dataclass(frozen=True)
class RuntimeDependencies:
    database: Database
    storage: RuntimeStorageBundle
    coordinator: RunCoordinator
    schedule_service: ScheduleService
    data_run_service: DataRunService
    run_service: RunService
    scheduler: EmbeddedScheduler
    task_run_service: TaskRunService
    writing_service: DataRunWritingService
    candidate_selection_service: CandidateSelectionService
    workbench_queries: DataRunWorkbenchQueries
    bus: ProgressBus


@dataclass(frozen=True)
class WebRouterDependencies:
    commands: RunCommandService
    queries: RunQueryService
    real_queries: RealDataRunQueries
    workbench_queries: DataRunWorkbenchQueries
    candidate_selection_service: CandidateSelectionService
    data_run_service: DataRunService
    writing_service: DataRunWritingService
    coordinator: RunCoordinator
    scheduler: EmbeddedScheduler
    review: ReviewRouterDependencies


@dataclass(frozen=True)
class _RealDataDependencies:
    market: MarketDataPort
    constituents: SectorConstituentPort
    global_news: GlobalNewsDiscoveryPort
    keyword_news: KeywordNewsSearchPort
    disclosure_news: DisclosureSearchPort
    database: Database
    storage: RuntimeStorageBundle
    entity_config: SectorEntityConfig


def _require_task_repository(storage: RuntimeStorageBundle) -> RuntimeTaskRepositoryPort:
    if storage.task is None:
        raise RuntimeError("task repository is not configured")
    return storage.task


def build_runtime_dependencies(
    settings: ApplicationSettings, database_path: Path
) -> RuntimeDependencies:
    database = build_database(settings, database_path)
    if isinstance(database, PostgresDatabase):
        database.healthcheck()
        storage = build_postgres_storage(database)
    else:
        storage = build_sqlite_storage(database)

    task_repository = _require_task_repository(storage)
    phase1b_repository = storage.phase1b
    if phase1b_repository is None:
        raise RuntimeError("phase1b repository is not configured")
    if storage.candidate_selections is None:
        raise RuntimeError("candidate selection repository is not configured")

    bus = ProgressBus()
    runtime_config = settings.apply_runtime_overrides(load_llm_config(Path("config/llm.yaml")))
    run_service = RunService(
        runs_repo=storage.phase1b_runs,
        phase1b_repo=phase1b_repository,
        invocation_repo=storage.invocations,
        news_evidence=storage.news_evidence,
        prompts=PromptRegistry(Path("config/prompts")),
        config=runtime_config,
        bus=bus,
        fixture_responses=load_default_fixture_responses(),
        llm_factory={},
    )
    provider_factory = RealDataProviderFactory()
    entity_config = load_entity_config(Path("config/sector_entities.yaml"))

    def real_dependencies(_provider: str) -> Phase1A2Dependencies:
        provider_bundle = provider_factory.build()
        return _RealDataDependencies(
            market=provider_bundle.market,
            constituents=provider_bundle.constituents,
            global_news=provider_bundle.global_news,
            keyword_news=provider_bundle.keyword_news,
            disclosure_news=provider_bundle.disclosure_news,
            database=database,
            storage=storage,
            entity_config=entity_config,
        )

    data_run_service = DataRunService(
        repository=storage.real_data_runs,
        bus=bus,
        dependencies_factory=real_dependencies,
    )
    candidate_selection_service = CandidateSelectionService(
        storage.real_data_runs, storage.candidate_selections
    )
    writing_service = DataRunWritingService(database, run_service, storage=storage)
    scheduled_bridge = ScheduledDataRunBridge(
        task_repository,
        storage.real_data_runs,
        data_run_service,
        writing_service,
        candidate_selection_service,
    )
    schedule_service = ScheduleService(task_repository)
    task_run_service = TaskRunService(task_repository)
    coordinator = RunCoordinator(
        task_repository,
        task_run_service,
        schedule_service,
        scheduled_bridge,
        storage.real_data_runs,
    )
    scheduler = EmbeddedScheduler(
        task_repository,
        schedule_service,
        None,
        poll_seconds=settings.scheduler_poll_seconds,
        bridge=scheduled_bridge,
        coordinator=coordinator,
    )
    return RuntimeDependencies(
        database=database,
        storage=storage,
        coordinator=coordinator,
        schedule_service=schedule_service,
        data_run_service=data_run_service,
        run_service=run_service,
        scheduler=scheduler,
        task_run_service=task_run_service,
        writing_service=writing_service,
        candidate_selection_service=candidate_selection_service,
        workbench_queries=DataRunWorkbenchQueries(storage),
        bus=bus,
    )


def build_web_router_dependencies(
    runtime: RuntimeDependencies,
    settings: ApplicationSettings,
    overrides: dict[str, Any] | None = None,
) -> WebRouterDependencies:
    service = overrides.get("service") if overrides else None
    if service is None:
        service = runtime.run_service
    workbench_queries = overrides.get("workbench_queries") if overrides else None
    if workbench_queries is None:
        workbench_queries = runtime.workbench_queries
    candidate_selection_service = (
        overrides.get("candidate_selection_service") if overrides else None
    )
    if candidate_selection_service is None:
        candidate_selection_service = runtime.candidate_selection_service
    data_run_service = overrides.get("data_run_service") if overrides else None
    if data_run_service is None:
        data_run_service = runtime.data_run_service
    writing_service = overrides.get("writing_service") if overrides else None
    if writing_service is None:
        writing_service = runtime.writing_service

    scheduled_bridge = ScheduledDataRunBridge(
        runtime.storage.task,
        runtime.storage.real_data_runs,
        data_run_service,
        writing_service,
        candidate_selection_service,
    )
    coordinator = RunCoordinator(
        runtime.storage.task,
        runtime.task_run_service,
        runtime.schedule_service,
        scheduled_bridge,
        runtime.storage.real_data_runs,
    )
    scheduler = EmbeddedScheduler(
        runtime.storage.task,
        runtime.schedule_service,
        None,
        poll_seconds=settings.scheduler_poll_seconds,
        bridge=scheduled_bridge,
        coordinator=coordinator,
    )
    evidence_service = EvidenceDecisionService(runtime.storage.governance)
    return WebRouterDependencies(
        commands=RunCommandService(service),
        queries=RunQueryService(service),
        real_queries=RealDataRunQueries(runtime.storage.real_data_runs),
        workbench_queries=workbench_queries,
        candidate_selection_service=candidate_selection_service,
        data_run_service=data_run_service,
        writing_service=writing_service,
        coordinator=coordinator,
        scheduler=scheduler,
        review=ReviewRouterDependencies(
            review_analytics=runtime.storage.review_analytics,
            draft_edits=runtime.storage.draft_edit,
            phase1b=runtime.storage.phase1b,
            governance_service=GovernanceService(),
            release_audit=runtime.storage.release_audit,
            evidence_repository=runtime.storage.governance,
            evidence_service=evidence_service,
        ),
    )
