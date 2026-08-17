# backend/src/sector_pulse/web/app.py
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from sector_pulse.config.llm_config import load_llm_config
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.storage.agent_invocation_repository import SQLiteAgentInvocationRepository
from sector_pulse.storage.news_evidence_repository import SQLiteNewsEvidenceRepository
from sector_pulse.storage.phase1b_repository import SQLitePhase1BRepository
from sector_pulse.storage.phase1b_runs_repository import SQLitePhase1BRunsRepository
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.web.progress_bus import ProgressBus
from sector_pulse.web.run_service import ProviderUnavailable, RunService
from sector_pulse.web.schemas import NewRunRequest, NewRunResponse


def create_app(
    database_path: Path = Path("data/sector-pulse.db"),
    static_dir: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> FastAPI:
    database = SQLiteDatabase(database_path)
    bus = ProgressBus()
    service = overrides.get("service") if overrides else None
    if service is None:
        service = RunService(
            runs_repo=SQLitePhase1BRunsRepository(database),
            phase1b_repo=SQLitePhase1BRepository(database),
            invocation_repo=SQLiteAgentInvocationRepository(database),
            news_evidence=SQLiteNewsEvidenceRepository(database),
            prompts=PromptRegistry(Path("config/prompts")),
            config=load_llm_config(Path("config/llm.yaml")),
            bus=bus,
            fixture_responses=json.loads(
                Path("backend/tests/fixtures/phase1b/fixture_responses.json").read_text(
                    encoding="utf-8"
                )
            ),
            llm_factory={},
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        yield

    app = FastAPI(title="SectorPulse Web", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/runs")
    async def list_runs() -> list[Any]:
        return service.list_runs()

    @app.post("/api/runs", response_model=NewRunResponse, status_code=200)
    async def create_run(req: NewRunRequest) -> NewRunResponse:
        try:
            run_id = service.create_run(req.input_json, req.provider)
        except ProviderUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return NewRunResponse(run_id=run_id)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: UUID) -> dict[str, Any]:
        detail = service.get_run(run_id)
        if detail is None:
            raise HTTPException(404, "run not found")
        return detail.model_dump(mode="json")

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: UUID) -> StreamingResponse:
        async def event_stream() -> AsyncIterator[str]:
            async for event in bus.subscribe(run_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: UUID) -> dict[str, bool]:
        if not service.cancel_run(run_id):
            raise HTTPException(404, "run not found or not running")
        return {"cancelled": True}

    @app.get("/api/runs/{run_id}/radar")
    async def get_radar(run_id: UUID) -> dict[str, Any]:
        if service.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return service.get_radar(run_id)

    @app.get("/api/runs/{run_id}/draft")
    async def get_draft(run_id: UUID) -> dict[str, Any]:
        if service.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return service.get_draft(run_id)

    @app.get("/api/runs/{run_id}/draft.md")
    async def get_draft_md(run_id: UUID) -> PlainTextResponse:
        body = service.render_draft_markdown(run_id)
        if body is None:
            raise HTTPException(404, "draft not ready")
        return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")

    @app.get("/api/runs/{run_id}/draft.txt")
    async def get_draft_txt(run_id: UUID) -> PlainTextResponse:
        body = service.render_draft_text(run_id)
        if body is None:
            raise HTTPException(404, "draft not ready")
        return PlainTextResponse(body, media_type="text/plain; charset=utf-8")

    @app.get("/api/runs/{run_id}/evidence")
    async def get_evidence(run_id: UUID) -> dict[str, Any]:
        if service.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return service.get_evidence(run_id)

    @app.get("/api/runs/{run_id}/review")
    async def get_review(run_id: UUID) -> dict[str, Any]:
        if service.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return service.get_review(run_id)

    if static_dir is not None and static_dir.exists():
        assets = static_dir / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        async def spa_index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

        @app.get("/{path:path}", response_model=None)
        async def spa_fallback(path: str) -> FileResponse | dict[str, str]:
            if path.startswith("api/"):
                return {"detail": "not found"}
            return FileResponse(static_dir / "index.html")

    return app