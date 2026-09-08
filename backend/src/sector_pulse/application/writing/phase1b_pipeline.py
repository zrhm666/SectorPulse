import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sector_pulse.application.writing.attribution_agents import (
    run_attribution_agents,
)
from sector_pulse.application.writing.editorial_agents import (
    revise_sections,
    run_editorial_agent,
    run_review_agent,
    run_writing_agent,
)
from sector_pulse.application.writing.invocations import InvocationSink
from sector_pulse.application.writing.progress import NoopProgressSink, ProgressSink
from sector_pulse.config.llm_config import LLMRuntimeConfig
from sector_pulse.domain.llm import AgentInvocation, MoneyCny
from sector_pulse.domain.review.review import ReviewDecision, ReviewReport
from sector_pulse.domain.writing.article import ArticleDraft, ArticleSource, DraftStatus
from sector_pulse.domain.writing.attribution import (
    AttributionContext,
    AttributionGateResult,
    SectorAnalysisCard,
)
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.ports.llm import LLMPort
from sector_pulse.storage.ports.writing import AgentInvocationRepositoryPort, Phase1BRepositoryPort


class PipelineStatus(str):
    RUNNING = "RUNNING"
    ATTRIBUTION_BLOCKED = "ATTRIBUTION_BLOCKED"
    DRAFT_GENERATION_FAILED = "DRAFT_GENERATION_FAILED"
    UNREVIEWED = "UNREVIEWED"
    REVISE_REQUIRED = "REVISE_REQUIRED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"


class Phase1BRequest(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    requested_at: datetime
    output_dir: Path | None = None
    contexts: tuple[AttributionContext, ...]
    gates: dict[str, AttributionGateResult]
    verified_sources_by_sector: dict[str, tuple[ArticleSource, ...]] | None = None


@dataclass(frozen=True)
class Phase1BDependencies:
    llm: LLMPort
    prompts: PromptRegistry
    repository: Phase1BRepositoryPort
    invocation_repository: AgentInvocationRepositoryPort
    config: LLMRuntimeConfig


@dataclass(frozen=True)
class Phase1BRunResult:
    status: str
    analysis_cards: tuple[SectorAnalysisCard, ...]
    outline: Any | None
    draft: ArticleDraft | None
    review: ReviewReport | None
    total_cost_cny: MoneyCny
    elapsed_ms: int


async def run_phase1b_pipeline(
    dependencies: Phase1BDependencies,
    request: Phase1BRequest,
    progress_sink: ProgressSink = NoopProgressSink(),
    invocation_sink: InvocationSink | None = None,
) -> Phase1BRunResult:
    started = time.perf_counter()
    progress_sink.emit("phase1b.start", {"run_id": str(request.run_id)})
    collected: list[AgentInvocation] = []

    def record(invocation: AgentInvocation) -> None:
        collected.append(invocation)

    active_invocation_sink = invocation_sink or record

    def total_cost() -> MoneyCny:
        """汇总当前调用审计成本，供 Web 展示和预算门禁复用。"""
        amount = sum((item.estimated_cost_cny.amount for item in collected), Decimal("0"))
        return MoneyCny(amount=amount)

    def save_invocations() -> None:
        if collected:
            dependencies.invocation_repository.save(tuple(collected))

    if len(request.contexts) < 3:
        save_invocations()
        return Phase1BRunResult(
            status=PipelineStatus.ATTRIBUTION_BLOCKED,
            analysis_cards=(),
            outline=None,
            draft=None,
            review=None,
            total_cost_cny=total_cost(),
            elapsed_ms=0,
        )
    prompt_attribution = dependencies.prompts.get("attribution")
    progress_sink.emit("attribution.start", {"total": len(request.contexts)})
    agent_results = await run_attribution_agents(
        request.contexts,
        request.gates,
        dependencies.llm,
        prompt_attribution,
        dependencies.config.max_attribution_concurrency,
        progress_sink=progress_sink,
        invocation_sink=active_invocation_sink,
        model=dependencies.config.route_for("attribution").model,










    )
    cards = tuple(result.card for result in agent_results)
    dependencies.repository.save_contexts(request.contexts)
    dependencies.repository.save_gate_results(tuple(request.gates.values()))
    dependencies.repository.save_cards(cards)
    progress_sink.emit("attribution.done", {"cards": len(cards)})
    if total_cost().amount > dependencies.config.budget_cny_per_run:
        save_invocations()
        return Phase1BRunResult(
            status=PipelineStatus.BUDGET_EXCEEDED,
            analysis_cards=cards,
            outline=None, draft=None, review=None,
            total_cost_cny=total_cost(),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
    outline, used_editorial_fallback = await run_editorial_agent(
        cards, dependencies.llm, dependencies.prompts.get("editorial"),
        invocation_sink=active_invocation_sink,
        model=dependencies.config.route_for("editorial").model,
    )
    dependencies.repository.save_outline(outline)
    progress_sink.emit(
        "editorial.fallback" if used_editorial_fallback else "editorial.done",
        {"sector_ids": list(outline.sector_ids)},
    )
    cards_by_id = {card.sector_id: card for card in cards}
    verified_sources = (
        tuple(
            {
                source.source_id: source
                for sector_id in outline.sector_ids
                for source in request.verified_sources_by_sector.get(sector_id, ())
            }.values()
        )
        if request.verified_sources_by_sector is not None
        else None
    )
    draft = await run_writing_agent(
        outline, cards_by_id, dependencies.llm, dependencies.prompts.get("writing"),
        invocation_sink=active_invocation_sink,
        model=dependencies.config.route_for("writing").model,
        verified_sources=verified_sources,
    )
    if draft is None or not draft.sources:
        progress_sink.emit(
            "writing.failed",
            {"reason": "invalid_or_source_less_draft"},
        )
        save_invocations()
        return Phase1BRunResult(
            status=PipelineStatus.DRAFT_GENERATION_FAILED,
            analysis_cards=cards,
            outline=outline,
            draft=None,
            review=None,
            total_cost_cny=total_cost(),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
    progress_sink.emit("writing.done", {"version": draft.version})
    dependencies.repository.save_draft(draft)
    review = await run_review_agent(
        draft, cards_by_id, dependencies.llm, dependencies.prompts.get("review"),
        invocation_sink=active_invocation_sink,
        model=dependencies.config.route_for("review").model,
    )
    if review is None:
        save_invocations()
        return Phase1BRunResult(
            status=PipelineStatus.UNREVIEWED,
            analysis_cards=cards,
            outline=outline,
            draft=draft.model_copy(update={"status": DraftStatus.UNREVIEWED}),
            review=None,
            total_cost_cny=total_cost(),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
    dependencies.repository.save_review(review)
    progress_sink.emit(
        "review.done",
        {"decision": review.decision.value if review else None},
    )
    revision_round = 0
    while (
        review.decision is ReviewDecision.REVISE
        and revision_round < dependencies.config.max_revision_rounds
    ):
        revision_round += 1
        replacements = {
            section.section_id: section.model_copy(update={"body": section.body + "（已复核）"})
            for section in draft.sections
            if any(issue.section_id == section.section_id for issue in review.issues)
        }
        draft = revise_sections(draft, replacements)
        dependencies.repository.save_draft(draft)
        review = await run_review_agent(
            draft, cards_by_id, dependencies.llm, dependencies.prompts.get("review"),
            invocation_sink=active_invocation_sink,
        model=dependencies.config.route_for("review").model,
        )
        if review is None:
            save_invocations()
            return Phase1BRunResult(
                status=PipelineStatus.UNREVIEWED,
                analysis_cards=cards,
                outline=outline,
                draft=draft,
                review=None,
                total_cost_cny=total_cost(),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        dependencies.repository.save_review(review)
        progress_sink.emit(
            "review.done",
            {"decision": review.decision.value if review else None},
        )
    if review.decision is not ReviewDecision.PASS:
        save_invocations()
        return Phase1BRunResult(
            status=PipelineStatus.REVISE_REQUIRED,
            analysis_cards=cards,
            outline=outline,
            draft=draft,
            review=review,
            total_cost_cny=total_cost(),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
    ready_payload = draft.model_copy(
        update={"status": DraftStatus.READY_FOR_HUMAN_REVIEW}
    ).model_dump()
    ready_draft = ArticleDraft.model_validate(ready_payload)
    dependencies.repository.save_draft(ready_draft)
    save_invocations()
    return Phase1BRunResult(
        status=PipelineStatus.READY_FOR_HUMAN_REVIEW,
        analysis_cards=cards,
        outline=outline,
        draft=ready_draft,
        review=review,
        total_cost_cny=total_cost(),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
