from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import ValidationError

from sector_pulse.application.review.evidence_decision_service import EvidenceDecisionService
from sector_pulse.application.review.governance_service import GovernanceService
from sector_pulse.application.runs.run_commands import RunCommandService
from sector_pulse.application.runs.run_queries import RunQueryService
from sector_pulse.domain.article import ArticleDraft
from sector_pulse.domain.release_audit import DraftApproval, DraftExport
from sector_pulse.infrastructure.llm.fixture_resources import load_default_fixture_input
from sector_pulse.storage.draft_edit_repository import DraftVersionConflict
from sector_pulse.storage.ports import (
    DraftEditRepositoryPort,
    GovernanceRepositoryPort,
    Phase1BRepositoryPort,
    ReleaseAuditRepositoryPort,
    ReviewAnalyticsPort,
)
from sector_pulse.web.analytics_schemas import ReviewMetricsResponse, ReviewSummaryResponse
from sector_pulse.web.editing_schemas import (
    DraftPatchRequest,
    DraftPatchResponse,
    GovernanceResponse,
)
from sector_pulse.web.progress_bus import ProgressBus
from sector_pulse.web.release_audit_schemas import ApprovalResponse, AuditEventResponse
from sector_pulse.web.review_schemas import (
    EvidenceDecisionRequest,
    EvidenceDecisionResponse,
    ReturnDraftRequest,
    ReturnDraftResponse,
)
from sector_pulse.web.run_service import ProviderUnavailable
from sector_pulse.web.schemas import NewRunRequest, NewRunResponse


def build_runs_review_router(
    *, commands: RunCommandService, queries: RunQueryService, bus: ProgressBus
) -> APIRouter:
    router = APIRouter(tags=["runs", "review"])

    @router.get("/api/fixture-input")
    async def fixture_input() -> dict[str, Any]:
        return load_default_fixture_input()

    @router.get("/api/runs")
    async def list_runs() -> list[Any]:
        return queries.list()

    @router.post("/api/runs", response_model=NewRunResponse, status_code=200)
    async def create_run(req: NewRunRequest) -> NewRunResponse:
        try:
            run_id = commands.create(req.input_json, req.provider)
        except ProviderUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return NewRunResponse(run_id=run_id)

    @router.get("/api/runs/{run_id}")
    async def get_run(run_id: UUID) -> dict[str, Any]:
        detail = queries.detail(run_id)
        if detail is None:
            raise HTTPException(404, "run not found")
        return detail.model_dump(mode="json")

    @router.get("/api/runs/{run_id}/events")
    async def run_events(run_id: UUID) -> StreamingResponse:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")

        async def event_stream() -> AsyncIterator[str]:
            async for event in bus.subscribe(run_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.post("/api/runs/{run_id}/retry", response_model=NewRunResponse)
    async def retry_run(run_id: UUID) -> NewRunResponse:
        try:
            new_run_id = commands.retry(run_id)
        except ProviderUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        return NewRunResponse(run_id=new_run_id)

    @router.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: UUID) -> dict[str, bool]:
        if not commands.cancel(run_id):
            raise HTTPException(404, "run not found or not running")
        return {"cancelled": True}

    @router.get("/api/runs/{run_id}/radar")
    async def get_radar(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.radar(run_id)

    @router.get("/api/runs/{run_id}/draft")
    async def get_draft(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.draft(run_id)

    @router.get("/api/runs/{run_id}/draft.md")
    async def get_draft_md(run_id: UUID) -> PlainTextResponse:
        body = queries.markdown(run_id)
        if body is None:
            raise HTTPException(404, "draft not ready")
        return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")

    @router.get("/api/runs/{run_id}/draft.txt")
    async def get_draft_txt(run_id: UUID) -> PlainTextResponse:
        body = queries.text(run_id)
        if body is None:
            raise HTTPException(404, "draft not ready")
        return PlainTextResponse(body, media_type="text/plain; charset=utf-8")

    @router.get("/api/runs/{run_id}/evidence")
    async def get_evidence(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.evidence(run_id)

    @router.get("/api/runs/{run_id}/review")
    async def get_review(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.review(run_id)

    return router


@dataclass(frozen=True)
class ReviewRouterDependencies:
    review_analytics: ReviewAnalyticsPort
    draft_edits: DraftEditRepositoryPort
    phase1b: Phase1BRepositoryPort
    governance_service: GovernanceService
    release_audit: ReleaseAuditRepositoryPort
    evidence_repository: GovernanceRepositoryPort
    evidence_service: EvidenceDecisionService


def build_review_governance_router(dependencies: ReviewRouterDependencies) -> APIRouter:
    router = APIRouter(tags=["review", "governance"])

    def latest_owned_draft(run_id: UUID, draft_id: UUID) -> ArticleDraft:
        try:
            draft = dependencies.draft_edits.latest_version(draft_id)
        except KeyError as exc:
            raise HTTPException(404, "draft not found") from exc
        if draft.run_id != run_id:
            raise HTTPException(404, "draft not found")
        return draft

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
            draft = dependencies.draft_edits.apply_patch(
                draft_id, request.base_version, request.operations, actor=actor
            )
        except DraftVersionConflict as exc:
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
        if not drafts:
            raise HTTPException(404, "draft not found")
        report = dependencies.governance_service.check(drafts[-1])
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
