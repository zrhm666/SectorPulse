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
from sector_pulse.application.review.governance_service import GovernanceService
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

        return {
            "search_news": search_news,
            "read_news_detail": read_news_detail,
            "inspect_evidence": inspect_evidence,
            "submit_analysis": submit_analysis,
        }


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

    def __init__(self, *factories: BusinessToolFactory) -> None:
        if not factories:
            raise ValueError("at least one business tool factory is required")
        self._factories = tuple(factories)

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
        return AgentBusinessToolFactory(merged).build(run_id=run_id, provider=provider)


__all__ = [
    "A2BusinessToolFactory",
    "A2ToolDependencies",
    "A1BusinessToolFactory",
    "A1ToolDependencies",
    "AgentBusinessToolFactory",
    "BusinessToolFactory",
    "CompositeBusinessToolFactory",
    "REQUIRED_BUSINESS_TOOL_NAMES",
]
