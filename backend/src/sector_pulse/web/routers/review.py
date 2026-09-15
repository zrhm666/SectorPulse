from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException

from sector_pulse.application.review.evidence_decision_service import EvidenceDecisionService
from sector_pulse.application.review.governance_service import GovernanceService
from sector_pulse.domain.review.release_audit import DraftApproval, DraftExport
from sector_pulse.domain.writing.article import ArticleDraft
from sector_pulse.ports.orchestration import RevisionConflict
from sector_pulse.storage.ports.review import (
    DraftEditRepositoryPort,
    GovernanceRepositoryPort,
    ReleaseAuditRepositoryPort,
    ReviewAnalyticsPort,
)
from sector_pulse.storage.ports.writing import Phase1BRepositoryPort
from sector_pulse.storage.sqlite.review.draft_edit_repository import DraftVersionConflict
from sector_pulse.web.schemas.analytics import ReviewMetricsResponse, ReviewSummaryResponse
from sector_pulse.web.schemas.editing import (
    DraftPatchRequest,
    DraftPatchResponse,
    GovernanceResponse,
)
from sector_pulse.web.schemas.release_audit import ApprovalResponse, AuditEventResponse
from sector_pulse.web.schemas.review import (
    EvidenceDecisionRequest,
    EvidenceDecisionResponse,
    ReturnDraftRequest,
    ReturnDraftResponse,
)


@dataclass(frozen=True)
class ReviewRouterDependencies:
    review_analytics: ReviewAnalyticsPort
    draft_edits: DraftEditRepositoryPort
    phase1b: Phase1BRepositoryPort
    governance_service: GovernanceService
    release_audit: ReleaseAuditRepositoryPort
    evidence_repository: GovernanceRepositoryPort
    evidence_service: EvidenceDecisionService
    orchestration_queries: Any | None = None
    draft_edits_service: Any | None = None



def build_review_governance_router(dependencies: ReviewRouterDependencies) -> APIRouter:
    router = APIRouter(tags=["review", "governance"])

    def latest_owned_draft(run_id: UUID, draft_id: UUID) -> ArticleDraft:
        try:
            resolved: ArticleDraft | None = dependencies.draft_edits.latest_version(draft_id)
        except KeyError as exc:
            resolved = None
            if dependencies.orchestration_queries is not None:
                candidate = dependencies.orchestration_queries.latest_draft(run_id)
                if candidate is not None and candidate.draft_id == draft_id:
                    # Compatibility projection: human editing remains owned by the
                    # existing CAS repository and its audit trail.
                    dependencies.draft_edits.save_draft(candidate)
                    resolved = candidate
            if resolved is None:
                raise HTTPException(404, "draft not found") from exc
        if resolved is None or resolved.run_id != run_id:
            raise HTTPException(404, "draft not found")
        return resolved

    def require_current_version_review(run_id: UUID, draft: ArticleDraft) -> None:
        """Refuse to approve a version the agent never reviewed.

        An A4 PASS is bound to one immutable draft version. A human edit creates
        a higher version, so reusing the earlier verdict would approve text no
        reviewer ever read. Legacy runs have no orchestration review at all and
        keep their original governance-only gate.
        """
        queries = dependencies.orchestration_queries
        if queries is None:
            return
        detail = queries.get_run(run_id)
        if detail is None or getattr(detail, "execution_engine", "legacy") != "multi_agent":
            return
        review = queries.get_review(run_id)
        if review.get("decision") is None:
            raise HTTPException(409, "draft has no independent review yet")
        if review.get("draft_version") != draft.version:
            raise HTTPException(
                409,
                "draft version changed since the last independent review; "
                "a new review is required before approval",
            )

    @router.get("/api/analytics/summary", response_model=ReviewSummaryResponse)
    async def analytics_summary(from_at: str, to_at: str) -> ReviewSummaryResponse:
        try:
            result = dependencies.review_analytics.summary(
                datetime.fromisoformat(from_at), datetime.fromisoformat(to_at)
            )
        except ValueError as exc:
            raise HTTPException(422, "from_at and to_at must be ISO timestamps") from exc
        return ReviewSummaryResponse.model_validate(result.model_dump())

    @router.get("/api/analytics/runs/{run_id}", response_model=ReviewMetricsResponse)
    async def analytics_run(run_id: UUID) -> ReviewMetricsResponse:
        result = dependencies.review_analytics.for_run(run_id)
        return ReviewMetricsResponse.model_validate(result.model_dump())

    @router.post(
        "/api/runs/{run_id}/drafts/{draft_id}/patches",
        response_model=DraftPatchResponse,
        status_code=201,
    )
    async def apply_draft_patch(
        run_id: UUID,
        draft_id: UUID,
        request: DraftPatchRequest,
        actor: str = Header(default="local-user", alias="X-Actor"),
    ) -> DraftPatchResponse:
        latest_owned_draft(run_id, draft_id)
        try:
            if dependencies.draft_edits_service is None:
                draft = dependencies.draft_edits.apply_patch(
                    draft_id, request.base_version, request.operations, actor=actor
                )
            else:
                draft = dependencies.draft_edits_service.apply(
                    run_id,
                    draft_id,
                    request.base_version,
                    request.operations,
                    actor=actor,
                    base_revision=request.base_revision,
                )
        except (DraftVersionConflict, RevisionConflict) as exc:
            raise HTTPException(409, str(exc)) from exc
        if draft.run_id != run_id:
            raise HTTPException(404, "draft not found")
        return DraftPatchResponse(
            draft_id=draft.draft_id,
            version=draft.version,
            status=draft.status.value,
            content=draft.model_dump(mode="json"),
        )

    @router.get("/api/runs/{run_id}/governance", response_model=GovernanceResponse)
    async def get_governance(run_id: UUID) -> GovernanceResponse:
        drafts = dependencies.phase1b.get_drafts(run_id)
        draft = drafts[-1] if drafts else None
        if draft is None and dependencies.orchestration_queries is not None:
            draft = dependencies.orchestration_queries.latest_draft(run_id)
        if draft is None:
            raise HTTPException(404, "draft not found")
        report = dependencies.governance_service.check(draft)
        return GovernanceResponse(
            status=report.status, issues=report.issues, rules_version=report.rules_version
        )

    @router.post("/api/runs/{run_id}/drafts/{draft_id}/approve", response_model=ApprovalResponse)
    async def approve_draft(
        run_id: UUID,
        draft_id: UUID,
        actor: str = Header(default="local-user", alias="X-Actor"),
    ) -> ApprovalResponse:
        draft = latest_owned_draft(run_id, draft_id)
        require_current_version_review(run_id, draft)
        report = dependencies.governance_service.check(draft)
        if report.status != "PASS":
            raise HTTPException(422, "governance check must pass before approval")
        governance_hash = dependencies.release_audit.content_hash(
            {
                "status": report.status,
                "issues": report.issues,
                "rules_version": report.rules_version,
            }
        )
        approval = DraftApproval(
            run_id=run_id,
            draft_id=draft_id,
            version=draft.version,
            governance_hash=governance_hash,
            actor=actor,
            approved_at=datetime.now(UTC),
        )
        try:
            dependencies.release_audit.approve(approval)
        except Exception as exc:
            raise HTTPException(409, "draft version already approved") from exc
        return ApprovalResponse(
            draft_id=str(draft_id), version=draft.version, status=approval.status.value, actor=actor
        )

    @router.post("/api/runs/{run_id}/drafts/{draft_id}/revoke", response_model=ApprovalResponse)
    async def revoke_draft(
        run_id: UUID,
        draft_id: UUID,
        actor: str = Header(default="local-user", alias="X-Actor"),
    ) -> ApprovalResponse:
        draft = latest_owned_draft(run_id, draft_id)
        dependencies.release_audit.revoke(run_id, draft_id, draft.version, actor, datetime.now(UTC))
        return ApprovalResponse(
            draft_id=str(draft_id), version=draft.version, status="REVOKED", actor=actor
        )

    @router.get(
        "/api/runs/{run_id}/drafts/{draft_id}/approval",
        response_model=ApprovalResponse | None,
    )
    async def get_approval(run_id: UUID, draft_id: UUID) -> ApprovalResponse | None:
        draft = latest_owned_draft(run_id, draft_id)
        approval = dependencies.release_audit.approval(draft_id, draft.version)
        if approval is None:
            return None
        return ApprovalResponse(
            draft_id=str(draft_id),
            version=approval.version,
            status=approval.status.value,
            actor=approval.actor,
        )

    @router.get(
        "/api/runs/{run_id}/drafts/{draft_id}/audit",
        response_model=list[AuditEventResponse],
    )
    async def get_audit(run_id: UUID, draft_id: UUID) -> list[AuditEventResponse]:
        latest_owned_draft(run_id, draft_id)
        return [
            AuditEventResponse(
                event_type=event.event_type,
                version=event.version,
                actor=event.actor,
                created_at=event.created_at.isoformat(),
                payload=event.payload,
            )
            for event in dependencies.release_audit.audit(draft_id)
        ]

    @router.get(
        "/api/runs/{run_id}/drafts/{draft_id}/evidence-decisions",
        response_model=list[EvidenceDecisionResponse],
    )
    async def list_evidence_decisions(
        run_id: UUID, draft_id: UUID
    ) -> list[EvidenceDecisionResponse]:
        latest_owned_draft(run_id, draft_id)
        return [
            EvidenceDecisionResponse.model_validate(item.model_dump())
            for item in dependencies.evidence_repository.list_evidence_decisions(draft_id)
        ]

    @router.post(
        "/api/runs/{run_id}/drafts/{draft_id}/evidence-decisions",
        response_model=EvidenceDecisionResponse,
        status_code=201,
    )
    async def create_evidence_decision(
        run_id: UUID,
        draft_id: UUID,
        request: EvidenceDecisionRequest,
        actor: str = Header(default="local-user", alias="X-Actor"),
    ) -> EvidenceDecisionResponse:
        draft = latest_owned_draft(run_id, draft_id)
        try:
            dependencies.evidence_service.record(
                draft, request.source_id, request.decision, request.reason, actor=actor
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        item = dependencies.evidence_repository.list_evidence_decisions(draft_id)[-1]
        return EvidenceDecisionResponse.model_validate(item.model_dump())

    @router.post(
        "/api/runs/{run_id}/drafts/{draft_id}/return",
        response_model=ReturnDraftResponse,
        status_code=201,
    )
    async def return_draft(
        run_id: UUID,
        draft_id: UUID,
        request: ReturnDraftRequest,
        actor: str = Header(default="local-user", alias="X-Actor"),
    ) -> ReturnDraftResponse:
        draft = latest_owned_draft(run_id, draft_id)
        dependencies.release_audit.record_event(
            run_id, draft_id, draft.version, "RETURNED", actor, {"reason": request.reason}
        )
        return ReturnDraftResponse(
            draft_id=draft_id, version=draft.version, status="RETURNED", actor=actor
        )

    @router.get("/api/runs/{run_id}/drafts/{draft_id}/export.json")
    async def export_approved_json(
        run_id: UUID,
        draft_id: UUID,
        actor: str = Header(default="local-user", alias="X-Actor"),
    ) -> dict[str, Any]:
        draft = latest_owned_draft(run_id, draft_id)
        approval = dependencies.release_audit.approval(draft_id, draft.version)
        if approval is None or approval.status.value != "APPROVED_FOR_COPY":
            raise HTTPException(409, "draft version is not approved for copy")
        content = draft.model_dump(mode="json")
        dependencies.release_audit.record_export(
            DraftExport(
                run_id=run_id,
                draft_id=draft_id,
                version=draft.version,
                format="json",
                content_hash=dependencies.release_audit.content_hash(content),
                actor=actor,
                created_at=datetime.now(UTC),
            )
        )
        return content

    return router
