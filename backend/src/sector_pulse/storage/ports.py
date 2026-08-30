from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from sector_pulse.application.operations_summary import OperationalRun
from sector_pulse.domain.article import ArticleDraft, ArticleOutline
from sector_pulse.domain.attribution import (
    AttributionContext,
    AttributionGateResult,
    SectorAnalysisCard,
)
from sector_pulse.domain.candidate_selection import CandidateSelection
from sector_pulse.domain.editing import (
    DraftPatch,
    EvidenceDecision,
    PreferenceCandidate,
    PreferenceVersion,
)
from sector_pulse.domain.evidence import EvidencePack
from sector_pulse.domain.llm import AgentInvocation
from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.news import NewsDocument, NewsEvent
from sector_pulse.domain.news_retrieval import (
    NewsQuery,
    NewsQueryAuditRecord,
    NewsQueryDocumentLink,
    SectorEventLink,
    SourceRunMetric,
)
from sector_pulse.domain.prompt_golden import PromptGoldenCase
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.real_data_run import (
    RealDataCandidate,
    RealDataQualitySummary,
    RealDataRun,
    RealDataRunStatus,
)
from sector_pulse.domain.release_audit import AuditEvent, DraftApproval, DraftExport
from sector_pulse.domain.review import ReviewReport
from sector_pulse.domain.review_analytics import ReviewMetrics, ReviewSummary
from sector_pulse.domain.shadow_acceptance import ComplianceRecord, RecoveryDrill, ShadowRun
from sector_pulse.domain.task import Checkpoint, TaskRunKey, TaskRunStatus, TaskStage
from sector_pulse.domain.time import AnalysisRun
from sector_pulse.storage.news_evidence_repository import NewsEvidenceItem
from sector_pulse.storage.phase1b_runs_repository import Phase1BRunRow
from sector_pulse.storage.task_repository import TaskEvent


@runtime_checkable
class MarketSnapshotRepositoryPort(Protocol):
    def save(
        self, run: AnalysisRun, result: ProviderResult[SectorUniverseSnapshot]
    ) -> None: ...

    def get(self, run_id: UUID, kind: SectorKind) -> SectorUniverseSnapshot | None: ...


@runtime_checkable
class NewsRepositoryPort(Protocol):
    def save(self, documents: Sequence[NewsDocument], events: Sequence[NewsEvent]) -> None: ...

    def get_event(self, event_id: str) -> NewsEvent | None: ...

    def get_events(self, event_ids: Sequence[str]) -> tuple[NewsEvent, ...]: ...

    def get_documents(self, document_ids: Sequence[str]) -> dict[str, NewsDocument]: ...


@runtime_checkable
class EvidenceRepositoryPort(Protocol):
    def save(self, packs: Sequence[EvidencePack]) -> None: ...

    def list_for_run(self, run_id: UUID) -> tuple[EvidencePack, ...]: ...


@runtime_checkable
class NewsRetrievalRepositoryPort(Protocol):
    def save_audit(
        self,
        run_id: UUID,
        metrics: Sequence[SourceRunMetric],
        query_results: Sequence[tuple[NewsQuery, DataStatus, int, str | None]],
        links: Sequence[SectorEventLink],
        query_documents: Sequence[NewsQueryDocumentLink] = (),
    ) -> None: ...

    def list_links(self, run_id: UUID) -> tuple[SectorEventLink, ...]: ...

    def list_query_documents(self, run_id: UUID) -> tuple[NewsQueryDocumentLink, ...]: ...

    def list_queries(self, run_id: UUID) -> tuple[NewsQueryAuditRecord, ...]: ...

    def list_source_metrics(self, run_id: UUID) -> tuple[SourceRunMetric, ...]: ...


@runtime_checkable
class RealDataRunRepositoryPort(Protocol):
    def insert(self, run: RealDataRun) -> None: ...

    def update_status(
        self,
        run_id: UUID,
        status: RealDataRunStatus,
        *,
        cutoff_at: datetime | None = None,
        quality: RealDataQualitySummary | None = None,
        error_code: str | None = None,
        finished_at: datetime | None = None,
    ) -> None: ...

    def save_candidates(
        self, run_id: UUID, candidates: tuple[RealDataCandidate, ...]
    ) -> None: ...

    def get_run(self, run_id: UUID) -> RealDataRun | None: ...

    def list_runs(self, limit: int = 50) -> list[RealDataRun]: ...

    def get_candidates(self, run_id: UUID) -> list[RealDataCandidate]: ...

    def mark_interrupted(self) -> int: ...


@runtime_checkable
class TaskRepositoryPort(Protocol):
    def create_or_get_run(
        self,
        key: TaskRunKey,
        provider: str,
        input_json: dict[str, object],
        *,
        retry_of_run_id: UUID | None = None,
    ) -> UUID: ...

    def claim_run(
        self,
        run_id: UUID,
        worker_id: str,
        lease_until: datetime,
        *,
        now: datetime | None = None,
    ) -> bool: ...

    def transition(
        self,
        run_id: UUID,
        expected: TaskRunStatus,
        target: TaskRunStatus,
        *,
        source: str,
        summary: str,
        idempotency_key: str | None = None,
        error_code: str | None = None,
    ) -> bool: ...

    def save_checkpoint(
        self,
        run_id: UUID,
        stage: TaskStage,
        input_fingerprint: str,
        implementation_version: str,
        payload: dict[str, object],
    ) -> Checkpoint: ...

    def get_latest_valid_checkpoint(
        self,
        run_id: UUID,
        stage: TaskStage,
        input_fingerprint: str,
        implementation_version: str,
    ) -> Checkpoint | None: ...

    def list_events(self, run_id: UUID) -> list[TaskEvent]: ...

    def record_task_event(
        self,
        run_id: UUID,
        *,
        source: str,
        event_type: str,
        summary: str,
        idempotency_key: str | None,
        created_at: datetime,
    ) -> None: ...

    def count_runs(self) -> int: ...

    def get_task_detail(self, run_id: UUID) -> dict[str, object] | None: ...

    def recover_expired_leases(self, now: datetime | None = None) -> int: ...

    def request_cancel(self, run_id: UUID, requested_at: datetime) -> bool: ...

    def recover_interrupted(self, now: datetime, reason: str) -> int: ...

    def link_data_run(self, run_id: UUID, data_run_id: UUID) -> None: ...

    def list_linked_runs(self) -> list[tuple[UUID, UUID]]: ...

    def claim_ready_linked_run(self, run_id: UUID, data_run_id: UUID) -> bool: ...

    def fail_claimed_run(self, run_id: UUID, error_code: str) -> bool: ...

    def mark_content_started(self, run_id: UUID, created_at: datetime) -> None: ...


@runtime_checkable
class ScheduleRepositoryPort(Protocol):
    def insert_schedule(self, values: Mapping[str, object]) -> None: ...

    def list_schedules(self) -> list[dict[str, object]]: ...

    def get_schedule(self, schedule_id: UUID) -> dict[str, object] | None: ...

    def list_due_schedules(self, now: datetime) -> list[dict[str, object]]: ...

    def record_schedule_trigger(
        self,
        schedule_id: UUID,
        triggered_at: datetime,
        next_run_at: datetime | None,
    ) -> None: ...

    def update_schedule_next_run(self, schedule_id: UUID, next_run_at: datetime) -> None: ...


@runtime_checkable
class RuntimeTaskRepositoryPort(TaskRepositoryPort, ScheduleRepositoryPort, Protocol):
    """Combined task/schedule adapter exposed by the current runtime bundle."""


@runtime_checkable
class CandidateSelectionRepositoryPort(Protocol):
    def append(self, selection: CandidateSelection, *, expected_version: int) -> None: ...

    def latest(self, run_id: UUID) -> CandidateSelection | None: ...

    def list_versions(self, run_id: UUID) -> list[CandidateSelection]: ...


@runtime_checkable
class Phase1BRunsRepositoryPort(Protocol):
    def insert(self, run: Phase1BRunRow) -> None: ...

    def update_status(
        self,
        run_id: UUID,
        status: str,
        elapsed_ms: int | None = None,
        total_cost_cny: str | None = None,
        draft_id: UUID | None = None,
        error_message: str | None = None,
        finished_at: datetime | None = None,
    ) -> None: ...

    def list_runs(self, limit: int = 50) -> list[Phase1BRunRow]: ...

    def get_run(self, run_id: UUID) -> Phase1BRunRow | None: ...


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


@runtime_checkable
class NewsEvidenceRepositoryPort(Protocol):
    def get_events(self, event_ids: tuple[str, ...]) -> tuple[NewsEvidenceItem, ...]: ...


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
class PromptGoldenRepositoryPort(Protocol):
    def save(self, item: PromptGoldenCase) -> None: ...

    def list(self) -> tuple[PromptGoldenCase, ...]: ...


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
class ShadowAcceptanceRepositoryPort(Protocol):
    def save_run(self, item: ShadowRun) -> None: ...

    def get(self, shadow_id: UUID) -> ShadowRun | None: ...

    def list_runs(self, limit: int = 20) -> tuple[ShadowRun, ...]: ...

    def update_run(self, shadow_id: UUID, item: ShadowRun) -> None: ...

    def save_recovery(self, item: RecoveryDrill) -> None: ...

    def save_compliance(self, item: ComplianceRecord) -> None: ...


@runtime_checkable
class GovernanceRepositoryPort(Protocol):
    def save_evidence_decision(self, decision: EvidenceDecision) -> None: ...

    def list_evidence_decisions(self, draft_id: UUID) -> tuple[EvidenceDecision, ...]: ...

    def save_preference_candidate(self, candidate: PreferenceCandidate) -> None: ...

    def adopt_preference(
        self, candidate_id: UUID, adopted_at: datetime
    ) -> PreferenceVersion: ...


@runtime_checkable
class OperationsQueryPort(Protocol):
    def list_records(
        self, *, since: datetime | None = None, limit: int | None = None
    ) -> list[OperationalRun]: ...


@runtime_checkable
class ReviewAnalyticsPort(Protocol):
    def for_run(self, run_id: UUID) -> ReviewMetrics: ...

    def summary(self, from_at: datetime, to_at: datetime) -> ReviewSummary: ...
