from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from sector_pulse.application.data_runs.candidate_selection_service import (
    CandidateSelectionInvalid,
    CandidateSelectionNotFound,
    CandidateSelectionRequired,
    CandidateSelectionService,
)
from sector_pulse.application.data_runs.data_run_workbench_queries import DataRunWorkbenchQueries
from sector_pulse.application.data_runs.real_data_queries import RealDataRunQueries
from sector_pulse.domain.candidate_selection import CandidateSelectionVersionConflict
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.real_data_run import RealDataRunRequest
from sector_pulse.web.schemas.data_run import (
    CandidateSelectionConfirmRequest,
    CandidateSelectionResponse,
    DataRunCandidatePageResponse,
    DataRunNewsDetailResponse,
    DataRunWorkflowSummaryResponse,
    GenerateDataRunRequest,
    NewDataRunRequest,
)
from sector_pulse.web.services.data_run_service import DataRunService
from sector_pulse.web.services.data_run_writing_service import DataRunWritingService


def build_data_runs_router(
    *,
    data_run_service: DataRunService,
    real_queries: RealDataRunQueries,
    workbench_queries: DataRunWorkbenchQueries,
    candidate_selection_service: CandidateSelectionService,
    writing_service: DataRunWritingService,
) -> APIRouter:
    router = APIRouter(prefix="/api/data-runs", tags=["data-runs"])

    @router.post("")
    async def create_data_run(req: NewDataRunRequest) -> dict[str, object]:
        try:
            run_id = data_run_service.create(
                RealDataRunRequest(
                    mode=req.mode,
                    lookback_hours=req.lookback_hours,
                    precandidate_limit=req.precandidate_limit,
                    final_candidate_limit=req.final_candidate_limit,
                ),
                req.provider,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"run_id": run_id}

    @router.get("")
    async def list_data_runs() -> list[dict[str, object]]:
        return real_queries.list()

    @router.get("/{run_id}")
    async def get_data_run(run_id: UUID) -> dict[str, object]:
        result = real_queries.get(run_id)
        if result is None:
            raise HTTPException(404, "run not found")
        return result

    @router.get("/{run_id}/candidates", response_model=DataRunCandidatePageResponse)
    async def get_data_run_candidates(
        run_id: UUID,
        query: str | None = Query(default=None, max_length=100),
        sort: str = Query(default="rank", pattern="^(rank|score|name|pct_change|news_count)$"),
        direction: str = Query(default="asc", pattern="^(asc|desc)$"),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, object]:
        try:
            return workbench_queries.candidates(
                run_id, query=query, sort=sort, direction=direction, offset=offset, limit=limit
            )
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

    @router.get("/{run_id}/summary", response_model=DataRunWorkflowSummaryResponse)
    async def get_data_run_summary(run_id: UUID) -> dict[str, object]:
        try:
            return workbench_queries.summary(run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

    @router.get("/{run_id}/selection", response_model=CandidateSelectionResponse)
    async def get_data_run_selection(run_id: UUID) -> CandidateSelectionResponse:
        try:
            value = candidate_selection_service.view(run_id)
        except CandidateSelectionNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        return CandidateSelectionResponse.model_validate(value)

    @router.put("/{run_id}/selection", response_model=CandidateSelectionResponse)
    async def confirm_data_run_selection(
        run_id: UUID, req: CandidateSelectionConfirmRequest
    ) -> CandidateSelectionResponse:
        try:
            value = candidate_selection_service.confirm(
                run_id, tuple(req.sector_ids), expected_version=req.expected_version
            )
        except CandidateSelectionNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except CandidateSelectionVersionConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except CandidateSelectionInvalid as exc:
            raise HTTPException(422, str(exc)) from exc
        return CandidateSelectionResponse.model_validate(value)

    @router.get("/{run_id}/acquisition")
    async def get_data_run_acquisition(run_id: UUID) -> dict[str, object]:
        try:
            return workbench_queries.acquisition(run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

    @router.get("/{run_id}/news-records")
    async def get_data_run_news_records(
        run_id: UUID,
        source_id: str | None = None,
        status: DataStatus | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, object]:
        try:
            return workbench_queries.news_records(
                run_id, source_id=source_id, status=status, offset=offset, limit=limit
            )
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

    @router.get("/{run_id}/news-records/{document_id}", response_model=DataRunNewsDetailResponse)
    async def get_data_run_news_record(run_id: UUID, document_id: str) -> dict[str, object]:
        try:
            return workbench_queries.news_record(run_id, document_id)
        except KeyError as exc:
            raise HTTPException(404, "news record not found") from exc

    @router.get("/{run_id}/market")
    async def get_data_run_market(
        run_id: UUID,
        kind: SectorKind,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, object]:
        try:
            return workbench_queries.market(run_id, kind, offset=offset, limit=limit)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

    @router.get("/{run_id}/evidence")
    async def get_data_run_evidence(run_id: UUID) -> dict[str, object]:
        try:
            return workbench_queries.evidence(run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

    @router.get("/{run_id}/quality")
    async def get_data_run_quality(run_id: UUID) -> dict[str, object]:
        try:
            return workbench_queries.quality(run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

    @router.get("/{run_id}/content-run")
    async def get_data_run_content_run(run_id: UUID) -> dict[str, object] | None:
        try:
            return workbench_queries.content_run(run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

    @router.post("/{run_id}/retry")
    async def retry_data_run(run_id: UUID) -> dict[str, object]:
        try:
            retried_id = data_run_service.retry(run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"run_id": retried_id}

    @router.post("/{run_id}/cancel")
    async def cancel_data_run(run_id: UUID) -> dict[str, object]:
        if not data_run_service.cancel(run_id):
            raise HTTPException(404, "run not found or not running")
        return {"run_id": run_id, "status": "CANCELLED"}

    @router.post("/{run_id}/generate")
    async def generate_data_run_article(
        run_id: UUID, _req: GenerateDataRunRequest | None = None
    ) -> dict[str, object]:
        try:
            selection = candidate_selection_service.require_confirmed(run_id)
            generated_id = writing_service.generate(run_id, selection.selected_sector_ids)
        except CandidateSelectionNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except CandidateSelectionRequired as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"run_id": generated_id}

    return router
