from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from sector_pulse.application.comparison.run_comparison_queries import RunComparisonQueries
from sector_pulse.application.data_runs.candidate_selection_service import CandidateSelectionService
from sector_pulse.application.data_runs.data_run_workbench_queries import DataRunWorkbenchQueries
from sector_pulse.application.data_runs.phase1a2_probe import Phase1A2Dependencies
from sector_pulse.application.data_runs.real_data_queries import RealDataRunQueries
from sector_pulse.application.orchestration.commands import MultiAgentRunCommands
from sector_pulse.application.orchestration.multi_agent_run_service import MultiAgentRunService
from sector_pulse.application.orchestration.query_adapter import MultiAgentRunQueryAdapter
from sector_pulse.application.review.evidence_decision_service import EvidenceDecisionService
from sector_pulse.application.review.governance_service import GovernanceService
from sector_pulse.application.review.human_draft_edit import HumanDraftEditService
from sector_pulse.application.runs.run_commands import RunCommandService
from sector_pulse.application.runs.run_queries import RunQueryService
from sector_pulse.application.tasks.run_coordinator import RunCoordinator
from sector_pulse.application.tasks.schedule_service import ScheduleService
from sector_pulse.application.tasks.scheduled_data_bridge import ScheduledDataRunBridge
from sector_pulse.application.tasks.scheduler import EmbeddedScheduler
from sector_pulse.application.tasks.task_run_service import TaskRunService
from sector_pulse.application.writing.agent_runtime import AgentRuntime
from sector_pulse.config.llm_config import load_llm_config
from sector_pulse.config.news_config import load_entity_config
from sector_pulse.config.settings import ApplicationSettings
from sector_pulse.domain.news.news_retrieval import SectorEntityConfig
from sector_pulse.domain.writing.agent_execution import AgentLimits
from sector_pulse.infrastructure.agents.composition import (
    REQUIRED_BUSINESS_TOOL_NAMES,
    A1BusinessToolFactory,
    A1ToolDependencies,
    A2BusinessToolFactory,
    A2ToolDependencies,
    A3A4BusinessToolFactory,
    A3A4ToolDependencies,
    BusinessToolFactory,
    CompositeBusinessToolFactory,
)
from sector_pulse.infrastructure.agents.default_fixture_agent import (
    default_fixture_strategies,
)
from sector_pulse.infrastructure.agents.provider_factory import AgentProviderFactory
from sector_pulse.infrastructure.agents.reference_artifact_reader import (
    ReferenceArtifactReader,
)
from sector_pulse.infrastructure.agents.roles import ContextToolBuilder
from sector_pulse.infrastructure.llm.fixture_resources import load_default_fixture_responses
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.infrastructure.news.fixture_agent_news import FixtureAgentNewsSearch
from sector_pulse.infrastructure.news.news_detail_reader import PublicNewsDetailReader
from sector_pulse.infrastructure.providers.fixture_bundle import build_fixture_provider_bundle
from sector_pulse.infrastructure.providers.real_data_factory import RealDataProviderFactory
from sector_pulse.ports.market_data import MarketDataPort
from sector_pulse.ports.news_sources import (
    DisclosureSearchPort,
    GlobalNewsDiscoveryPort,
    KeywordNewsSearchPort,
    SectorConstituentPort,
)
from sector_pulse.storage.database_runtime import Database, build_database
from sector_pulse.storage.ports.tasks import RuntimeTaskRepositoryPort
from sector_pulse.storage.ports.writing import AgentTracePort, EditorialDraftRepositoryPort
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.writing.agent_execution_repository import (
    PostgresAgentExecutionRepository,
)
from sector_pulse.storage.runtime_bundle import (
    RuntimeStorageBundle,
    build_postgres_storage,
    build_sqlite_storage,
)
from sector_pulse.storage.sqlite.writing.agent_execution_repository import (
    SQLiteAgentExecutionRepository,
)
from sector_pulse.web.events.progress_bus import ProgressBus
from sector_pulse.web.routers.review import ReviewRouterDependencies
from sector_pulse.web.services.data_run_service import DataRunService
from sector_pulse.web.services.data_run_writing_service import (
    DataRunArticleStarter,
    DataRunWritingService,
    MultiAgentDataRunWritingService,
)
from sector_pulse.web.services.run_service import RunService


@dataclass(frozen=True)
class RuntimeDependencies:
    """Repositories and services, without a scheduler.

    The scheduler and its coordinator live in `WebRouterDependencies`, because only
    that layer knows which command service the run entry points were wired to.
    """

    database: Database
    storage: RuntimeStorageBundle
    schedule_service: ScheduleService
    data_run_service: DataRunService
    run_service: RunService
    task_run_service: TaskRunService
    writing_service: DataRunWritingService
    candidate_selection_service: CandidateSelectionService
    workbench_queries: DataRunWorkbenchQueries
    bus: ProgressBus
    multi_agent_service: MultiAgentRunService | None = None


@dataclass(frozen=True)
class WebRouterDependencies:
    commands: RunCommandService | MultiAgentRunCommands
    queries: RunQueryService
    real_queries: RealDataRunQueries
    comparison_queries: RunComparisonQueries
    workbench_queries: DataRunWorkbenchQueries
    candidate_selection_service: CandidateSelectionService
    data_run_service: DataRunService
    writing_service: DataRunArticleStarter
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


def _review_scope(drafts: EditorialDraftRepositoryPort, artifact_id: UUID) -> str:
    draft = drafts.get(artifact_id)
    if draft is None:
        raise ValueError("review draft artifact is unavailable")
    return f"review:{draft.draft.draft_id}:{draft.draft.version}"


def _require_task_repository(storage: RuntimeStorageBundle) -> RuntimeTaskRepositoryPort:
    if storage.task is None:
        raise RuntimeError("task repository is not configured")
    return storage.task


def _build_default_business_tool_factory(
    *,
    storage: RuntimeStorageBundle,
    entity_config: SectorEntityConfig,
) -> BusinessToolFactory:
    real_factory = RealDataProviderFactory()

    def build(
        run_id: UUID, provider: Literal["fixture", "live"]
    ) -> Mapping[str, ContextToolBuilder]:
        fixture_bundle = build_fixture_provider_bundle()
        sandbox_live = os.getenv("SECTOR_PULSE_LIVE_DATA_SANDBOX", "").lower() in {
            "1",
            "true",
            "yes",
        }
        real_bundle = (
            real_factory.build() if provider == "live" and not sandbox_live else None
        )
        bundle = fixture_bundle if real_bundle is None else real_bundle
        detail = fixture_bundle.detail if real_bundle is None else PublicNewsDetailReader()
        a1 = A1BusinessToolFactory(
            A1ToolDependencies(
                orchestration=storage.orchestration,
                market_snapshots=storage.market_snapshots,
                candidate_batches=storage.candidate_batches,
                candidate_proposals=storage.candidate_proposals,
                news_batches=storage.news_batches,
                news=storage.news,
                market=bundle.market,
                constituents=bundle.constituents,
                global_news=bundle.global_news,
                keyword_news=bundle.keyword_news,
                disclosure_news=bundle.disclosure_news,
                entity_config=entity_config,
            )
        )
        a2 = A2BusinessToolFactory(
            A2ToolDependencies(
                orchestration=storage.orchestration,
                selections=storage.orchestration_selections,
                candidate_batches=storage.candidate_batches,
                market_snapshots=storage.market_snapshots,
                news=storage.news,
                news_batches=storage.news_batches,
                research_searches=storage.research_searches,
                news_details=storage.news_details,
                evidence_inspections=storage.evidence_inspections,
                sector_analyses=storage.sector_analyses,
                detail=detail,
                keyword_news=bundle.keyword_news,
            )
        )
        a34 = A3A4BusinessToolFactory(
            A3A4ToolDependencies(
                orchestration=storage.orchestration,
                selections=storage.orchestration_selections,
                analyses=storage.sector_analyses,
                outlines=storage.editorial_outlines,
                drafts=storage.editorial_drafts,
                news_evidence=storage.news_evidence,
                reviews=storage.independent_reviews,
                draft_rules=storage.draft_rules,
                governance=GovernanceService(),
            )
        )
        return CompositeBusinessToolFactory(a1, a2, a34).build(run_id=run_id, provider=provider)

    class _DefaultFactory:
        def build(
            self,
            *,
            run_id: UUID,
            provider: Literal["fixture", "live"],
        ) -> Mapping[str, ContextToolBuilder]:
            return build(run_id, provider)

    return _DefaultFactory()


def build_runtime_dependencies(
    settings: ApplicationSettings,
    database_path: Path,
    *,
    business_tool_factory: BusinessToolFactory | None = None,
    agent_provider_factory: AgentProviderFactory | None = None,
    enable_multi_agent: bool = False,
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
    agent_trace: AgentTracePort = (
        PostgresAgentExecutionRepository(database)
        if isinstance(database, PostgresDatabase)
        else SQLiteAgentExecutionRepository(database)
    )

    prompts = PromptRegistry(Path("config/prompts"))
    for prompt_id in (
        "attribution",
        "attribution_agent",
        "editorial",
        "writing",
        "review",
        "revision",
        "agent_validation_feedback",
        "structured_output",
    ):
        prompts.get(prompt_id)

    def agent_runtime_factory(provider: str) -> AgentRuntime:
        return AgentRuntime(
            news=storage.news,
            trace=agent_trace,
            search=FixtureAgentNewsSearch()
            if provider == "fixture"
            else RealDataProviderFactory().build().keyword_news,
            detail=PublicNewsDetailReader(),
            limits=AgentLimits(),
            prompt=prompts.get("attribution_agent"),
            feedback_prompt=prompts.get("agent_validation_feedback"),
        )

    runtime_config = settings.apply_runtime_overrides(load_llm_config(Path("config/llm.yaml")))
    run_service = RunService(
        runs_repo=storage.phase1b_runs,
        phase1b_repo=phase1b_repository,
        invocation_repo=storage.invocations,
        news_evidence=storage.news_evidence,
        prompts=prompts,
        config=runtime_config,
        bus=bus,
        fixture_responses=load_default_fixture_responses(),
        llm_factory={},
        market_snapshots=storage.market_snapshots,
        agent_runtime_factory=agent_runtime_factory,
        agent_trace=agent_trace,
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
    schedule_service = ScheduleService(task_repository)
    task_run_service = TaskRunService(task_repository)
    if enable_multi_agent and business_tool_factory is None:
        business_tool_factory = _build_default_business_tool_factory(
            storage=storage,
            entity_config=entity_config,
        )
    if agent_provider_factory is None and (enable_multi_agent or business_tool_factory is not None):
        agent_provider_factory = AgentProviderFactory(
            fixture_strategies=default_fixture_strategies(),
            base_url=settings.llm_base_url,
            api_key=(
                settings.llm_api_key.get_secret_value()
                if settings.llm_api_key is not None
                else None
            ),
            live_model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    multi_agent_service = None
    if business_tool_factory is not None:
        if agent_provider_factory is None:
            raise RuntimeError("multi-agent provider factory is not configured")
        multi_agent_service = MultiAgentRunService(
            repository=storage.orchestration,
            config=runtime_config,
            prompt_registry=prompts,
            provider_factory=agent_provider_factory,
            business_tool_factory=business_tool_factory,
            tool_reserved_cny={name: Decimal("0") for name in REQUIRED_BUSINESS_TOOL_NAMES},
            artifact_reader=ReferenceArtifactReader(),
            candidate_proposals=storage.candidate_proposals,
            review_scope_resolver=lambda artifact_id: _review_scope(
                storage.editorial_drafts, artifact_id
            ),
        )
    return RuntimeDependencies(
        database=database,
        storage=storage,
        schedule_service=schedule_service,
        data_run_service=data_run_service,
        run_service=run_service,
        task_run_service=task_run_service,
        writing_service=writing_service,
        candidate_selection_service=candidate_selection_service,
        workbench_queries=DataRunWorkbenchQueries(storage),
        bus=bus,
        multi_agent_service=multi_agent_service,
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
    writing_service_overridden = writing_service is not None
    if writing_service is None:
        writing_service = runtime.writing_service

    if overrides is not None and "multi_agent_service" in overrides:
        multi_agent_service = overrides["multi_agent_service"]
    elif overrides is not None and "service" in overrides:
        multi_agent_service = None
    else:
        multi_agent_service = runtime.multi_agent_service
    commands = overrides.get("commands") if overrides else None
    if commands is None:
        if multi_agent_service is not None:
            commands = MultiAgentRunCommands(
                service=multi_agent_service,
                repository=runtime.storage.orchestration,
                real_runs=runtime.storage.real_data_runs,
            )
        else:
            commands = RunCommandService(service)
    if multi_agent_service is not None and not writing_service_overridden:
        if not isinstance(commands, MultiAgentRunCommands):
            raise RuntimeError("multi-agent data-run continuation requires multi-agent commands")
        writing_service = MultiAgentDataRunWritingService(
            runtime.storage.real_data_runs,
            commands,
        )

    scheduled_bridge = ScheduledDataRunBridge(
        runtime.storage.task,
        runtime.storage.real_data_runs,
        data_run_service,
        writing_service,
        candidate_selection_service,
        content_runs=runtime.storage.phase1b_runs,
        multi_agent_commands=(commands if multi_agent_service is not None else None),
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
        dispatch_enabled=settings.scheduler_enabled,
    )
    evidence_service = EvidenceDecisionService(runtime.storage.governance)
    comparison_queries = overrides.get("comparison_queries") if overrides else None
    if comparison_queries is None:
        comparison_queries = RunComparisonQueries(runtime.storage)
    query_port = (
        MultiAgentRunQueryAdapter(
            runtime.storage.orchestration,
            runtime.storage,
            legacy=service,
        )
        if multi_agent_service is not None
        else service
    )
    return WebRouterDependencies(
        commands=commands,
        queries=RunQueryService(query_port),
        real_queries=RealDataRunQueries(runtime.storage.real_data_runs),
        comparison_queries=comparison_queries,
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
            orchestration_queries=(
                MultiAgentRunQueryAdapter(
                    runtime.storage.orchestration,
                    runtime.storage,
                    legacy=service,
                )
                if multi_agent_service is not None
                else None
            ),
            draft_edits_service=HumanDraftEditService(
                draft_edits=runtime.storage.draft_edit,
                orchestration=runtime.storage.orchestration,
            ),
        ),
    )
