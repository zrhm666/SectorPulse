from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import ValidationError

from sector_pulse.application.runs.run_commands import RunCommandService
from sector_pulse.application.runs.run_queries import RunQueryService
from sector_pulse.infrastructure.llm.fixture_resources import load_default_fixture_input
from sector_pulse.web.events.progress_bus import ProgressBus
from sector_pulse.web.schemas.runs import NewRunRequest, NewRunResponse
from sector_pulse.web.services.run_service import ProviderUnavailable


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
