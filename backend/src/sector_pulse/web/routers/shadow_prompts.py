from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException

from sector_pulse.domain.prompt_golden import PromptGoldenCase
from sector_pulse.domain.shadow_acceptance import (
    ComplianceRecord,
    RecoveryDrill,
    ShadowRun,
    ShadowRunStatus,
)
from sector_pulse.storage.ports import PromptGoldenRepositoryPort, ShadowAcceptanceRepositoryPort
from sector_pulse.web.prompt_golden_schemas import PromptGoldenRequest, PromptGoldenResponse
from sector_pulse.web.shadow_schemas import (
    ComplianceRecordRequest,
    RecoveryDrillRequest,
    ShadowProgressResponse,
    ShadowRunRequest,
    ShadowRunResponse,
    ShadowRunUpdateRequest,
)


def _shadow_response(item: ShadowRun) -> ShadowRunResponse:
    return ShadowRunResponse(
        shadow_id=item.shadow_id,
        run_id=item.run_id,
        trading_date=item.trading_date,
        mode=item.mode,
        status=item.status.value,
        created_at=item.created_at,
    )


def build_shadow_prompts_router(
    *,
    shadow_repository: ShadowAcceptanceRepositoryPort,
    prompt_golden_repository: PromptGoldenRepositoryPort,
) -> APIRouter:
    router = APIRouter(tags=["shadow-acceptance", "prompt-golden"])

    @router.post("/api/shadow-runs", response_model=ShadowRunResponse, status_code=201)
    async def create_shadow_run(request: ShadowRunRequest) -> ShadowRunResponse:
        item = ShadowRun(
            run_id=request.run_id,
            trading_date=request.trading_date,
            mode=request.mode,
            provider_status=request.provider_status,
            created_at=datetime.now(UTC),
        )
        shadow_repository.save_run(item)
        return _shadow_response(item)

    @router.get("/api/shadow-runs", response_model=list[ShadowRunResponse])
    async def list_shadow_runs() -> list[ShadowRunResponse]:
        return [_shadow_response(item) for item in shadow_repository.list_runs()]

    @router.get("/api/shadow-runs/summary", response_model=ShadowProgressResponse)
    async def shadow_progress() -> ShadowProgressResponse:
        runs = shadow_repository.list_runs(limit=1000)
        days = len({item.trading_date for item in runs})
        return ShadowProgressResponse(
            trading_days=days,
            passed=sum(item.status.value == "PASSED" for item in runs),
            failed=sum(item.status.value == "FAILED" for item in runs),
            blocked=sum(item.status.value == "BLOCKED" for item in runs),
            remaining=max(0, 20 - days),
            complete=days >= 20,
        )

    @router.patch("/api/shadow-runs/{shadow_id}", response_model=ShadowRunResponse)
    async def update_shadow_run(
        shadow_id: UUID, request: ShadowRunUpdateRequest
    ) -> ShadowRunResponse:
        item = next(
            (run for run in shadow_repository.list_runs(limit=1000) if run.shadow_id == shadow_id),
            None,
        )
        if item is None:
            raise HTTPException(404, "shadow run not found")
        try:
            status = ShadowRunStatus(request.status)
        except ValueError as exc:
            raise HTTPException(422, "invalid shadow run status") from exc
        values = item.model_dump()
        values.update(
            status=status,
            provider_status=request.provider_status,
            cutoff_at=request.cutoff_at,
            metrics=request.metrics,
            failure_reason=request.failure_reason,
            finished_at=datetime.now(UTC) if status is not ShadowRunStatus.STARTED else None,
        )
        updated = ShadowRun(**values)
        shadow_repository.update_run(shadow_id, updated)
        return _shadow_response(updated)

    @router.post("/api/shadow-runs/{shadow_id}/recovery-drills", status_code=201)
    async def record_recovery_drill(
        shadow_id: UUID, request: RecoveryDrillRequest
    ) -> dict[str, str]:
        item = RecoveryDrill(
            shadow_id=shadow_id,
            fault_type=request.fault_type,
            recovered=request.recovered,
            recovery_seconds=request.recovery_seconds,
            notes=request.notes,
            created_at=datetime.now(UTC),
        )
        shadow_repository.save_recovery(item)
        return {"drill_id": str(item.drill_id), "status": "RECORDED"}

    @router.post("/api/shadow-runs/{shadow_id}/compliance", status_code=201)
    async def record_compliance(
        shadow_id: UUID, request: ComplianceRecordRequest
    ) -> dict[str, str]:
        item = ComplianceRecord(
            shadow_id=shadow_id,
            rules_version=request.rules_version,
            decision=request.decision,
            reviewer=request.reviewer,
            notes=request.notes,
            created_at=datetime.now(UTC),
        )
        shadow_repository.save_compliance(item)
        return {"record_id": str(item.record_id), "status": "RECORDED"}

    @router.post("/api/prompt-golden", response_model=PromptGoldenResponse, status_code=201)
    async def create_prompt_golden(request: PromptGoldenRequest) -> PromptGoldenResponse:
        item = PromptGoldenCase(**request.model_dump(), created_at=datetime.now(UTC))
        prompt_golden_repository.save(item)
        return PromptGoldenResponse(
            **request.model_dump(), case_id=str(item.case_id), created_at=item.created_at
        )

    @router.get("/api/prompt-golden", response_model=list[PromptGoldenResponse])
    async def list_prompt_golden() -> list[PromptGoldenResponse]:
        return [
            PromptGoldenResponse(
                prompt_id=item.prompt_id,
                prompt_version=item.prompt_version,
                input_hash=item.input_hash,
                expected_schema=item.expected_schema,
                result=item.result,
                notes=item.notes,
                case_id=str(item.case_id),
                created_at=item.created_at,
            )
            for item in prompt_golden_repository.list()
        ]

    return router
