from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from sector_pulse.domain.llm import AgentInvocation
from sector_pulse.domain.review.review import ReviewReport
from sector_pulse.domain.writing.article import ArticleDraft, ArticleOutline
from sector_pulse.domain.writing.attribution import (
    AttributionContext,
    AttributionGateResult,
    SectorAnalysisCard,
)


@runtime_checkable
class Phase1BRepositoryPort(Protocol):
    def save_contexts(self, contexts: Sequence[AttributionContext]) -> None: ...

    def save_gate_results(self, results: Sequence[AttributionGateResult]) -> None: ...

    def save_cards(self, cards: Sequence[SectorAnalysisCard]) -> None: ...

    def save_outline(self, outline: ArticleOutline) -> None: ...

    def save_draft(self, draft: ArticleDraft) -> None: ...

    def save_review(self, report: ReviewReport) -> None: ...

    def list_drafts(self, draft_id: UUID) -> tuple[ArticleDraft, ...]: ...

    def get_contexts(self, run_id: UUID) -> tuple[AttributionContext, ...]: ...

    def get_gates(self, run_id: UUID) -> tuple[AttributionGateResult, ...]: ...

    def get_cards(self, run_id: UUID) -> tuple[SectorAnalysisCard, ...]: ...

    def get_outline(self, run_id: UUID) -> ArticleOutline | None: ...

    def get_drafts(self, run_id: UUID) -> tuple[ArticleDraft, ...]: ...

    def get_review(self, run_id: UUID) -> ReviewReport | None: ...



@runtime_checkable
class AgentInvocationRepositoryPort(Protocol):
    def save(self, invocations: Sequence[AgentInvocation]) -> None: ...

    def list_for_run(self, run_id: UUID) -> list[AgentInvocation]: ...
