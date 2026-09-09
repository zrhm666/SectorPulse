from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from sector_pulse.domain.review.editing import (
    DraftPatch,
    EvidenceDecision,
    PreferenceCandidate,
    PreferenceVersion,
)
from sector_pulse.domain.review.release_audit import AuditEvent, DraftApproval, DraftExport
from sector_pulse.domain.review.review_analytics import ReviewMetrics, ReviewSummary
from sector_pulse.domain.writing.article import ArticleDraft


@runtime_checkable
class DraftEditRepositoryPort(Protocol):
    def save_draft(self, draft: ArticleDraft) -> None: ...

    def get_version(self, draft_id: UUID, version: int) -> ArticleDraft: ...

    def latest_version(self, draft_id: UUID) -> ArticleDraft: ...

    def latest_for_run(self, run_id: UUID) -> ArticleDraft: ...

    def apply_patch(
        self,
        draft_id: UUID,
        base_version: int,
        operations: tuple[DraftPatch, ...],
        *,
        actor: str,
    ) -> ArticleDraft: ...



@runtime_checkable
class ReleaseAuditRepositoryPort(Protocol):
    def content_hash(self, content: dict[str, object]) -> str: ...

    def approve(self, approval: DraftApproval) -> None: ...

    def revoke(
        self,
        run_id: UUID,
        draft_id: UUID,
        version: int,
        actor: str,
        created_at: datetime,
    ) -> None: ...

    def approval(self, draft_id: UUID, version: int) -> DraftApproval | None: ...

    def audit(self, draft_id: UUID) -> tuple[AuditEvent, ...]: ...

    def record_export(self, export: DraftExport) -> None: ...

    def record_event(
        self,
        run_id: UUID,
        draft_id: UUID,
        version: int,
        event_type: str,
        actor: str,
        payload: dict[str, object],
    ) -> None: ...



@runtime_checkable
class GovernanceRepositoryPort(Protocol):
    def save_evidence_decision(self, decision: EvidenceDecision) -> None: ...

    def list_evidence_decisions(self, draft_id: UUID) -> tuple[EvidenceDecision, ...]: ...

    def save_preference_candidate(self, candidate: PreferenceCandidate) -> None: ...

    def adopt_preference(
        self, candidate_id: UUID, adopted_at: datetime
    ) -> PreferenceVersion: ...



@runtime_checkable
class ReviewAnalyticsPort(Protocol):
    def for_run(self, run_id: UUID) -> ReviewMetrics: ...

    def summary(self, from_at: datetime, to_at: datetime) -> ReviewSummary: ...
