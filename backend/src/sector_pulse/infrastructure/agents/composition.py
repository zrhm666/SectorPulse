"""Explicit composition contract for deterministic business tools.

The parent/child framework can still run control-only fixtures, but a production
composition must register every A1-A4 business tool.  Keeping this check at the
composition boundary prevents a partially wired deployment from silently
falling back to an agent with no data, research, editorial, or review tools.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from aidynamic_agent.tools.base import Tool

from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.candidate_tools import RankSectorCandidatesService
from sector_pulse.application.orchestration.data_tools import (
    CollectMarketService,
    InspectDataQualityService,
    MarketCollectionContext,
)
from sector_pulse.application.orchestration.editorial_context import (
    BoundEditorialContext,
    BoundEditorialContextReader,
    BoundReviewContext,
    BoundReviewContextReader,
    BoundRevisionContext,
    BoundRevisionContextReader,
)
from sector_pulse.application.orchestration.editorial_tools import (
    SubmitDraftService,
    SubmitOutlineService,
    SubmitRevisionService,
)
from sector_pulse.application.orchestration.evidence_tools import (
    InspectSectorEvidenceService,
    SubmitSectorAnalysisService,
)
from sector_pulse.application.orchestration.news_tools import (
    CollectInitialNewsService,
    NewsCollectionLimits,
)
from sector_pulse.application.orchestration.proposal_tools import ProposeCandidatesService
from sector_pulse.application.orchestration.research_context import (
    BoundSectorResearchContext,
    BoundSectorResearchContextReader,
)
from sector_pulse.application.orchestration.research_news_tools import (
    ReadBoundNewsDetailService,
    SearchSectorNewsService,
)
from sector_pulse.application.orchestration.review_tools import (
    CheckDraftRulesService,
    SubmitReviewService,
)
from sector_pulse.application.research_library.artifacts import AcceptInternalEvidenceService
from sector_pulse.application.research_library.retrieval import ResearchRetrievalService
from sector_pulse.application.review.governance_service import GovernanceService
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.market.quality import QualityThresholds
from sector_pulse.domain.news.news_retrieval import SectorEntityConfig
from sector_pulse.domain.runs.time import AnalysisMode, AnalysisRun
from sector_pulse.infrastructure.agents.candidate_tools import RankSectorCandidatesTool
from sector_pulse.infrastructure.agents.data_tools import CollectMarketTool, InspectDataQualityTool
from sector_pulse.infrastructure.agents.editorial_tools import (
    SubmitDraftTool,
    SubmitOutlineTool,
    SubmitRevisionTool,
)
from sector_pulse.infrastructure.agents.evidence_tools import (
    InspectEvidenceTool,
    SubmitAnalysisTool,
)
from sector_pulse.infrastructure.agents.news_tools import CollectInitialNewsTool
from sector_pulse.infrastructure.agents.proposal_tools import ProposeCandidatesTool
from sector_pulse.infrastructure.agents.research_library_tools import (
    AcceptInternalEvidenceTool,
    InspectResearchSourceTool,
    SearchInternalResearchTool,
)
from sector_pulse.infrastructure.agents.research_tools import ReadNewsDetailTool, SearchNewsTool
from sector_pulse.infrastructure.agents.review_tools import CheckDraftRulesTool, SubmitReviewTool
from sector_pulse.infrastructure.agents.roles import AgentToolContext, ContextToolBuilder
from sector_pulse.ports.market_data import MarketDataPort
from sector_pulse.ports.news_detail import NewsDetailPort
from sector_pulse.ports.news_sources import (
    DisclosureSearchPort,
    GlobalNewsDiscoveryPort,
    KeywordNewsSearchPort,
    SectorConstituentPort,
)
from sector_pulse.ports.orchestration import SnapshotRepository
from sector_pulse.storage.ports.market import (
    CandidateBatchRepositoryPort,
    CandidateProposalRepositoryPort,
    MarketSnapshotRepositoryPort,
    OrchestrationSelectionRepositoryPort,
)
from sector_pulse.storage.ports.news import (
    NewsBatchRepositoryPort,
    NewsDetailSnapshotRepositoryPort,
    NewsEvidenceRepositoryPort,
    NewsRepositoryPort,
    ResearchSearchRepositoryPort,
)
from sector_pulse.storage.ports.research_library import (
    AcceptedEvidenceRepositoryPort,
    ResearchLibraryRepositoryPort,
)
from sector_pulse.storage.ports.writing import (
    DraftRulesRepositoryPort,
    EditorialDraftRepositoryPort,
    EditorialOutlineRepositoryPort,
    EvidenceInspectionRepositoryPort,
    IndependentReviewRepositoryPort,
    SectorAnalysisRepositoryPort,
)

REQUIRED_BUSINESS_TOOL_NAMES = frozenset(
    {
        "collect_market",
        "inspect_data_quality",
        "rank_sector_candidates",
        "collect_initial_news",
        "propose_candidates",
        "search_news",
        "read_news_detail",
        "inspect_evidence",
        "submit_analysis",
        "submit_outline",
        "submit_draft",
        "submit_revision",
        "check_draft_rules",
        "submit_review",
    }
)

#: RAG 打开时才存在的那三件 A2 工具。
RAG_BUSINESS_TOOL_NAMES = frozenset(
    {
        "search_internal_research",
        "inspect_research_source",
        "accept_internal_evidence",
    }
)

#: RAG 打开时的完整契约。
#:
#: 单独一份而不是就地改 `REQUIRED_BUSINESS_TOOL_NAMES`：关掉 RAG 的部署必须仍然拿到原来
#: 那一份契约，否则"少接了三件工具"与"没开 RAG"会变成同一件事，而它们是两件不同的事——
#: 前者是半接线的部署，后者是刻意关闭的能力。
#:
#: 这份是**期望**而不是"从结果里减去现存的名字"：谁决定开 RAG，谁就要提交这份契约。若从
#: 结果反推，一个只接了一半的部署会静默退化成"没有那三件工具"。
RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES = REQUIRED_BUSINESS_TOOL_NAMES | RAG_BUSINESS_TOOL_NAMES

BusinessToolBuilderSource = Callable[
    [UUID, Literal["fixture", "live"]], Mapping[str, ContextToolBuilder]
]


class BusinessToolFactory(Protocol):
    def build(
        self,
        *,
        run_id: UUID,
        provider: Literal["fixture", "live"],
    ) -> Mapping[str, ContextToolBuilder]: ...


@dataclass(frozen=True)
class A1ToolDependencies:
    """Deterministic dependencies needed to construct T01-T05."""

    orchestration: SnapshotRepository
    market_snapshots: MarketSnapshotRepositoryPort
    candidate_batches: CandidateBatchRepositoryPort
    candidate_proposals: CandidateProposalRepositoryPort
    news_batches: NewsBatchRepositoryPort
    news: NewsRepositoryPort
    market: MarketDataPort
    constituents: SectorConstituentPort
    global_news: GlobalNewsDiscoveryPort
    keyword_news: KeywordNewsSearchPort
    disclosure_news: DisclosureSearchPort
    entity_config: SectorEntityConfig
    mode: AnalysisMode = AnalysisMode.LIVE
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


class A1BusinessToolFactory:
    """Build the complete deterministic A1 T01-T05 contextual tool set."""

    def __init__(self, dependencies: A1ToolDependencies) -> None:
        self._dependencies = dependencies

    def build(
        self,
        *,
        run_id: UUID,
        provider: Literal["fixture", "live"],
    ) -> dict[str, ContextToolBuilder]:
        del provider
        deps = self._dependencies
        committer = AtomicArtifactCommitter(deps.orchestration, run_id)
        run = AnalysisRun.create_live(deps.clock(), run_id)

        def context_for(context: AgentToolContext) -> MarketCollectionContext:
            return MarketCollectionContext(
                run=run,
                task_id=context.task_id,
                attempt=context.attempt,
                worker_id=context.worker_id,
                orchestration=deps.orchestration,
                committer=committer,
            )

        def collect_market(context: AgentToolContext) -> Tool:
            return CollectMarketTool(
                CollectMarketService(deps.market, mode=deps.mode),
                context=context_for(context),
                snapshots=deps.market_snapshots,
                clock=deps.clock,
            )

        def inspect_quality(context: AgentToolContext) -> Tool:
            return InspectDataQualityTool(
                InspectDataQualityService(
                    QualityThresholds(min_industry_count=1, min_concept_count=1)
                ),
                context=context_for(context),
                snapshots=deps.market_snapshots,
                clock=deps.clock,
            )

        def rank_candidates(context: AgentToolContext) -> Tool:
            service = RankSectorCandidatesService(
                snapshots=deps.market_snapshots,
                news_batches=deps.news_batches,
                news=deps.news,
                orchestration=deps.orchestration,
                committer=committer,
            )
            return RankSectorCandidatesTool(
                service,
                batches=deps.candidate_batches,
                task_id=context.task_id,
                attempt=context.attempt,
                worker_id=context.worker_id,
                candidate_limit=4,
                clock=deps.clock,
            )

        def collect_news(context: AgentToolContext) -> Tool:
            service = CollectInitialNewsService(
                constituents=deps.constituents,
                global_news=deps.global_news,
                keyword_news=deps.keyword_news,
                disclosure_news=deps.disclosure_news,
                entity_config=deps.entity_config,
                snapshots=deps.market_snapshots,
                candidate_batches=deps.candidate_batches,
                orchestration=deps.orchestration,
                committer=committer,
                limits=NewsCollectionLimits(
                    lookback_hours=6,
                    keyword_budget=2,
                    disclosure_code_budget=1,
                    max_retries=0,
                ),
            )
            return CollectInitialNewsTool(
                service,
                batches=deps.news_batches,
                task_id=context.task_id,
                attempt=context.attempt,
                worker_id=context.worker_id,
                clock=deps.clock,
                retry_backoff=lambda _attempt: 0,
            )

        def propose_candidates(context: AgentToolContext) -> Tool:
            service = ProposeCandidatesService(
                candidate_batches=deps.candidate_batches,
                proposals=deps.candidate_proposals,
                orchestration=deps.orchestration,
                committer=committer,
            )
            return ProposeCandidatesTool(
                service,
                proposals=deps.candidate_proposals,
                task_id=context.task_id,
                attempt=context.attempt,
                worker_id=context.worker_id,
                clock=deps.clock,
            )

        return {
            "collect_market": collect_market,
            "inspect_data_quality": inspect_quality,
            "rank_sector_candidates": rank_candidates,
            "collect_initial_news": collect_news,
            "propose_candidates": propose_candidates,
        }


@dataclass(frozen=True)
class A2ResearchLibraryServices:
    """A2 能碰到的内部资料库三件东西（规格 15.2）。

    打包成一个可选的依赖，而不是三个各自可选的字段：检索、回库与上限必须同时在场，缺一个
    就是半接线的部署。它是 `None` 还是整体在场，正好就是"这个 run 有没有 RAG"。
    """

    retrieval: ResearchRetrievalService
    repository: ResearchLibraryRepositoryPort
    settings: RagSettings


@dataclass(frozen=True)
class A2ToolDependencies:
    orchestration: SnapshotRepository
    selections: OrchestrationSelectionRepositoryPort
    candidate_batches: CandidateBatchRepositoryPort
    market_snapshots: MarketSnapshotRepositoryPort
    news: NewsRepositoryPort
    news_batches: NewsBatchRepositoryPort
    research_searches: ResearchSearchRepositoryPort
    news_details: NewsDetailSnapshotRepositoryPort
    evidence_inspections: EvidenceInspectionRepositoryPort
    sector_analyses: SectorAnalysisRepositoryPort
    detail: NewsDetailPort
    keyword_news: KeywordNewsSearchPort
    research_library: A2ResearchLibraryServices | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


class A2BusinessToolFactory:
    """Build the complete contextual A2 research and evidence tool set."""

    def __init__(self, dependencies: A2ToolDependencies) -> None:
        self._dependencies = dependencies

    def build(
        self,
        *,
        run_id: UUID,
        provider: Literal["fixture", "live"],
    ) -> dict[str, ContextToolBuilder]:
        del provider
        deps = self._dependencies
        committer = AtomicArtifactCommitter(deps.orchestration, run_id)
        reader = BoundSectorResearchContextReader(
            orchestration=deps.orchestration,
            selections=deps.selections,
            candidate_batches=deps.candidate_batches,
            market_snapshots=deps.market_snapshots,
            run_id=run_id,
        )

        def context_for(context: AgentToolContext) -> BoundSectorResearchContext:
            return reader.read(
                task_id=context.task_id,
                attempt=context.attempt,
                worker_id=context.worker_id,
                now=deps.clock(),
            )

        def search_news(context: AgentToolContext) -> Tool:
            bound = context_for(context)
            return SearchNewsTool(
                SearchSectorNewsService(
                    search=deps.keyword_news,
                    orchestration=deps.orchestration,
                    committer=committer,
                ),
                searches=deps.research_searches,
                context=bound,
                clock=deps.clock,
            )

        def read_news_detail(context: AgentToolContext) -> Tool:
            bound = context_for(context)
            return ReadNewsDetailTool(
                ReadBoundNewsDetailService(
                    detail=deps.detail,
                    orchestration=deps.orchestration,
                    committer=committer,
                    news=deps.news,
                    research_searches=deps.research_searches,
                    news_batches=deps.news_batches,
                ),
                details=deps.news_details,
                context=bound,
                clock=deps.clock,
            )

        def inspect_evidence(context: AgentToolContext) -> Tool:
            bound = context_for(context)
            return InspectEvidenceTool(
                InspectSectorEvidenceService(
                    orchestration=deps.orchestration,
                    committer=committer,
                    candidate_batches=deps.candidate_batches,
                    market_snapshots=deps.market_snapshots,
                    news=deps.news,
                    research_searches=deps.research_searches,
                    news_details=deps.news_details,
                    news_batches=deps.news_batches,
                ),
                reports=deps.evidence_inspections,
                context=bound,
                clock=deps.clock,
            )

        def submit_analysis(context: AgentToolContext) -> Tool:
            bound = context_for(context)
            return SubmitAnalysisTool(
                SubmitSectorAnalysisService(
                    orchestration=deps.orchestration,
                    committer=committer,
                    inspections=deps.evidence_inspections,
                ),
                analyses=deps.sector_analyses,
                context=bound,
                clock=deps.clock,
            )

        builders: dict[str, ContextToolBuilder] = {
            "search_news": search_news,
            "read_news_detail": read_news_detail,
            "inspect_evidence": inspect_evidence,
            "submit_analysis": submit_analysis,
        }

        services = deps.research_library
        if services is not None:
            # 接纳台账与查看台账是同一个对象：`inspect` 记下的定位，就是 `accept` 唯一会
            # 认的出处。一次 run 一个，因为账本本身按 (run, task, attempt, retrieval, chunk)
            # 记账，跨任务不会串。
            acceptance = AcceptInternalEvidenceService(
                retrieval=services.retrieval,
                repository=services.repository,
                committer=committer,
                clock=deps.clock,
            )

            def search_internal_research(context: AgentToolContext) -> Tool:
                bound = context_for(context)
                return SearchInternalResearchTool(
                    services.retrieval,
                    repository=services.repository,
                    context=bound,
                    settings=services.settings,
                    clock=deps.clock,
                )

            def inspect_research_source(context: AgentToolContext) -> Tool:
                bound = context_for(context)
                return InspectResearchSourceTool(acceptance, context=bound, clock=deps.clock)

            def accept_internal_evidence(context: AgentToolContext) -> Tool:
                bound = context_for(context)
                return AcceptInternalEvidenceTool(acceptance, context=bound, clock=deps.clock)

            builders |= {
                "search_internal_research": search_internal_research,
                "inspect_research_source": inspect_research_source,
                "accept_internal_evidence": accept_internal_evidence,
            }
        return builders


@dataclass(frozen=True)
class A3A4ToolDependencies:
    orchestration: SnapshotRepository
    selections: OrchestrationSelectionRepositoryPort
    analyses: SectorAnalysisRepositoryPort
    outlines: EditorialOutlineRepositoryPort
    drafts: EditorialDraftRepositoryPort
    news_evidence: NewsEvidenceRepositoryPort
    reviews: IndependentReviewRepositoryPort
    draft_rules: DraftRulesRepositoryPort
    governance: GovernanceService
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    # 没接内部资料库时是 None：A3/A4 的确定性检查照常跑，只是没有任何内部引用算数。
    accepted_evidence: AcceptedEvidenceRepositoryPort | None = None


class A3A4BusinessToolFactory:
    """Build the contextual editorial, revision, and review tool set."""

    def __init__(self, dependencies: A3A4ToolDependencies) -> None:
        self._dependencies = dependencies

    def build(
        self,
        *,
        run_id: UUID,
        provider: Literal["fixture", "live"],
    ) -> dict[str, ContextToolBuilder]:
        del provider
        deps = self._dependencies
        committer = AtomicArtifactCommitter(deps.orchestration, run_id)
        editorial_reader = BoundEditorialContextReader(
            orchestration=deps.orchestration,
            selections=deps.selections,
            analyses=deps.analyses,
            run_id=run_id,
        )
        review_reader = BoundReviewContextReader(
            orchestration=deps.orchestration,
            drafts=deps.drafts,
            outlines=deps.outlines,
            analyses=deps.analyses,
            run_id=run_id,
        )
        revision_reader = BoundRevisionContextReader(
            orchestration=deps.orchestration,
            drafts=deps.drafts,
            reviews=deps.reviews,
            outlines=deps.outlines,
            analyses=deps.analyses,
            run_id=run_id,
        )

        def editorial_context(context: AgentToolContext) -> BoundEditorialContext:
            return editorial_reader.read(
                task_id=context.task_id,
                attempt=context.attempt,
                worker_id=context.worker_id,
                now=deps.clock(),
            )

        def review_context(context: AgentToolContext) -> BoundReviewContext:
            return review_reader.read(
                task_id=context.task_id,
                attempt=context.attempt,
                worker_id=context.worker_id,
                now=deps.clock(),
            )

        def revision_context(context: AgentToolContext) -> BoundRevisionContext:
            return revision_reader.read(
                task_id=context.task_id,
                attempt=context.attempt,
                worker_id=context.worker_id,
                now=deps.clock(),
            )

        def submit_outline(context: AgentToolContext) -> Tool:
            return SubmitOutlineTool(
                SubmitOutlineService(orchestration=deps.orchestration, committer=committer),
                outlines=deps.outlines,
                context=editorial_context(context),
                clock=deps.clock,
            )

        def submit_draft(context: AgentToolContext) -> Tool:
            return SubmitDraftTool(
                SubmitDraftService(
                    orchestration=deps.orchestration,
                    committer=committer,
                    outlines=deps.outlines,
                    news_evidence=deps.news_evidence,
                    accepted_evidence=deps.accepted_evidence,
                ),
                drafts=deps.drafts,
                context=editorial_context(context),
                clock=deps.clock,
            )

        def submit_revision(context: AgentToolContext) -> Tool:
            return SubmitRevisionTool(
                SubmitRevisionService(
                    orchestration=deps.orchestration,
                    committer=committer,
                    drafts=deps.drafts,
                ),
                drafts=deps.drafts,
                context=revision_context(context),
                clock=deps.clock,
            )

        def check_rules(context: AgentToolContext) -> Tool:
            return CheckDraftRulesTool(
                CheckDraftRulesService(
                    orchestration=deps.orchestration,
                    committer=committer,
                    governance=deps.governance,
                    accepted_evidence=deps.accepted_evidence,
                ),
                rules=deps.draft_rules,
                context=review_context(context),
                clock=deps.clock,
            )

        def submit_review(context: AgentToolContext) -> Tool:
            return SubmitReviewTool(
                SubmitReviewService(
                    orchestration=deps.orchestration,
                    committer=committer,
                    rules=deps.draft_rules,
                ),
                reviews=deps.reviews,
                context=review_context(context),
                clock=deps.clock,
            )

        return {
            "submit_outline": submit_outline,
            "submit_draft": submit_draft,
            "submit_revision": submit_revision,
            "check_draft_rules": check_rules,
            "submit_review": submit_review,
        }


class AgentBusinessToolFactory:
    """Build and validate the contextual A1-A4 tool registry for one run."""

    def __init__(
        self,
        builders: Mapping[str, ContextToolBuilder]
        | BusinessToolBuilderSource,
        *,
        required_names: frozenset[str] = REQUIRED_BUSINESS_TOOL_NAMES,
    ) -> None:
        self._source = builders
        self._required_names = frozenset(required_names)

    def build(
        self,
        *,
        run_id: UUID,
        provider: Literal["fixture", "live"],
    ) -> dict[str, ContextToolBuilder]:
        resolved = self._source(run_id, provider) if callable(self._source) else self._source
        result = dict(resolved)
        missing = sorted(self._required_names - result.keys())
        if missing:
            raise ValueError(f"missing business tools: {', '.join(missing)}")
        unexpected = sorted(set(result) - self._required_names)
        if unexpected:
            raise ValueError(f"unexpected business tools: {', '.join(unexpected)}")
        return result


class CompositeBusinessToolFactory:
    """Merge role-specific factories and enforce one complete registry."""

    def __init__(
        self,
        *factories: BusinessToolFactory,
        required_names: frozenset[str] = REQUIRED_BUSINESS_TOOL_NAMES,
    ) -> None:
        if not factories:
            raise ValueError("at least one business tool factory is required")
        self._factories = tuple(factories)
        self._required_names = frozenset(required_names)

    def build(
        self,
        *,
        run_id: UUID,
        provider: Literal["fixture", "live"],
    ) -> dict[str, ContextToolBuilder]:
        merged: dict[str, ContextToolBuilder] = {}
        for factory in self._factories:
            current = factory.build(run_id=run_id, provider=provider)
            duplicate = sorted(set(merged).intersection(current))
            if duplicate:
                raise ValueError(f"duplicate business tools: {', '.join(duplicate)}")
            merged.update(current)
        return AgentBusinessToolFactory(merged, required_names=self._required_names).build(
            run_id=run_id, provider=provider
        )


__all__ = [
    "A2BusinessToolFactory",
    "A2ResearchLibraryServices",
    "A2ToolDependencies",
    "A1BusinessToolFactory",
    "A1ToolDependencies",
    "AgentBusinessToolFactory",
    "BusinessToolFactory",
    "CompositeBusinessToolFactory",
    "RAG_BUSINESS_TOOL_NAMES",
    "RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES",
    "REQUIRED_BUSINESS_TOOL_NAMES",
]
