# backend/src/sector_pulse/web/app.py
# ruff: noqa: E501
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from sector_pulse.application.governance_service import GovernanceService
from sector_pulse.application.real_data_queries import RealDataRunQueries
from sector_pulse.application.run_commands import RunCommandService
from sector_pulse.application.run_queries import RunQueryService
from sector_pulse.application.schedule_service import ScheduleCreate, ScheduleService
from sector_pulse.application.scheduled_data_bridge import ScheduledDataRunBridge
from sector_pulse.application.scheduler import EmbeddedScheduler
from sector_pulse.application.task_run_service import TaskRunService
from sector_pulse.config.llm_config import load_llm_config
from sector_pulse.config.news_config import load_entity_config
from sector_pulse.config.settings import ApplicationSettings, load_environment
from sector_pulse.domain.real_data_run import RealDataRunRequest
from sector_pulse.infrastructure.llm.fixture_resources import load_default_fixture_responses
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.infrastructure.providers.real_data_factory import RealDataProviderFactory
from sector_pulse.storage.agent_invocation_repository import SQLiteAgentInvocationRepository
from sector_pulse.storage.draft_edit_repository import (
    DraftVersionConflict,
    SQLiteDraftEditRepository,
)
from sector_pulse.storage.news_evidence_repository import SQLiteNewsEvidenceRepository
from sector_pulse.storage.phase1b_repository import SQLitePhase1BRepository
from sector_pulse.storage.phase1b_runs_repository import SQLitePhase1BRunsRepository
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.release_audit_repository import SQLiteReleaseAuditRepository
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.storage.task_repository import SQLiteTaskRepository
from sector_pulse.web.data_run_schemas import NewDataRunRequest
from sector_pulse.web.data_run_service import DataRunService
from sector_pulse.web.data_run_writing_service import DataRunWritingService
from sector_pulse.web.editing_schemas import (
    DraftPatchRequest,
    DraftPatchResponse,
    GovernanceResponse,
)
from sector_pulse.web.progress_bus import ProgressBus
from sector_pulse.web.release_audit_schemas import ApprovalResponse, AuditEventResponse
from sector_pulse.web.run_service import ProviderUnavailable, RunService
from sector_pulse.web.schemas import NewRunRequest, NewRunResponse
from sector_pulse.web.task_schemas import ScheduleCreateRequest, ScheduleResponse


def create_app(
    database_path: Path = Path("data/sector-pulse.db"),
    static_dir: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> FastAPI:
    load_environment()
    yaml_config = load_llm_config(Path("config/llm.yaml"))
    settings = ApplicationSettings.from_environment(yaml_config)
    runtime_config = settings.apply_runtime_overrides(yaml_config)
    if database_path == Path("data/sector-pulse.db"):
        database_path = settings.database_path
    database = SQLiteDatabase(database_path)
    task_repository = SQLiteTaskRepository(database)
    schedule_service = ScheduleService(task_repository)
    task_run_service = TaskRunService(task_repository)
    draft_edit_repository = SQLiteDraftEditRepository(database)
    governance_service = GovernanceService()
    release_audit_repository = SQLiteReleaseAuditRepository(database)
    scheduler: EmbeddedScheduler | None = None
    bus = ProgressBus()
    service = overrides.get("service") if overrides else None
    if service is None:
        service = RunService(
            runs_repo=SQLitePhase1BRunsRepository(database),
            phase1b_repo=SQLitePhase1BRepository(database),
            invocation_repo=SQLiteAgentInvocationRepository(database),
            news_evidence=SQLiteNewsEvidenceRepository(database),
            prompts=PromptRegistry(Path("config/prompts")),
            config=runtime_config,
            bus=bus,
            fixture_responses=load_default_fixture_responses(),
            llm_factory={},
        )

    commands = RunCommandService(service)
    queries = RunQueryService(service)
    real_repository = SQLiteRealDataRunRepository(database)
    real_queries = RealDataRunQueries(real_repository)
    data_run_service = overrides.get("data_run_service") if overrides else None
    if data_run_service is None:
        provider_factory = RealDataProviderFactory()
        entity_config = load_entity_config(Path("config/sector_entities.yaml"))

        def real_dependencies(_provider: str) -> object:
            bundle = provider_factory.build()
            return type(
                "Phase1A2RuntimeDependencies",
                (),
                {
                    "market": bundle.market,
                    "constituents": bundle.constituents,
                    "global_news": bundle.global_news,
                    "keyword_news": bundle.keyword_news,
                    "disclosure_news": bundle.disclosure_news,
                    "database": database,
                    "entity_config": entity_config,
                },
            )()

        data_run_service = DataRunService(
            repository=real_repository,
            bus=bus,
            dependencies_factory=real_dependencies,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        task_repository.recover_expired_leases()
        if scheduler is not None and settings.scheduler_enabled:
            scheduler.recover()
            scheduler.start()
        yield
        if scheduler is not None and settings.scheduler_enabled:
            await scheduler.stop()

    app = FastAPI(title="SectorPulse Web", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
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
        try:
            draft = draft_edit_repository.apply_patch(
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

    @app.get("/api/runs/{run_id}/governance", response_model=GovernanceResponse)
    async def get_governance(run_id: UUID) -> GovernanceResponse:
        drafts = draft_edit_repository._drafts.get_drafts(run_id)
        if not drafts:
            raise HTTPException(404, "draft not found")
        report = governance_service.check(drafts[-1])
        return GovernanceResponse(
            status=report.status, issues=report.issues, rules_version=report.rules_version
        )

    @app.post("/api/runs/{run_id}/drafts/{draft_id}/approve", response_model=ApprovalResponse)
    async def approve_draft(
        run_id: UUID, draft_id: UUID, actor: str = Header(default="local-user", alias="X-Actor")
    ) -> ApprovalResponse:
        try:
            draft = draft_edit_repository.latest_version(draft_id)
        except KeyError as exc:
            raise HTTPException(404, "draft not found") from exc
        if draft.run_id != run_id:
            raise HTTPException(404, "draft not found")
        report = governance_service.check(draft)
        if report.status != "PASS":
            raise HTTPException(422, "governance check must pass before approval")
        from datetime import UTC, datetime

        from sector_pulse.domain.release_audit import DraftApproval

        governance_hash = release_audit_repository.content_hash(
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
            release_audit_repository.approve(approval)
        except Exception as exc:
            raise HTTPException(409, "draft version already approved") from exc
        return ApprovalResponse(
            draft_id=str(draft_id), version=draft.version, status=approval.status.value, actor=actor
        )

    @app.post("/api/runs/{run_id}/drafts/{draft_id}/revoke", response_model=ApprovalResponse)
    async def revoke_draft(
        run_id: UUID, draft_id: UUID, actor: str = Header(default="local-user", alias="X-Actor")
    ) -> ApprovalResponse:
        draft = draft_edit_repository.latest_version(draft_id)
        if draft.run_id != run_id:
            raise HTTPException(404, "draft not found")
        from datetime import UTC, datetime

        release_audit_repository.revoke(run_id, draft_id, draft.version, actor, datetime.now(UTC))
        return ApprovalResponse(
            draft_id=str(draft_id), version=draft.version, status="REVOKED", actor=actor
        )

    @app.get(
        "/api/runs/{run_id}/drafts/{draft_id}/approval", response_model=ApprovalResponse | None
    )
    async def get_approval(run_id: UUID, draft_id: UUID) -> ApprovalResponse | None:
        draft = draft_edit_repository.latest_version(draft_id)
        if draft.run_id != run_id:
            raise HTTPException(404, "draft not found")
        approval = release_audit_repository.approval(draft_id, draft.version)
        return (
            None
            if approval is None
            else ApprovalResponse(
                draft_id=str(draft_id),
                version=approval.version,
                status=approval.status.value,
                actor=approval.actor,
            )
        )

    @app.get("/api/runs/{run_id}/drafts/{draft_id}/audit", response_model=list[AuditEventResponse])
    async def get_audit(run_id: UUID, draft_id: UUID) -> list[AuditEventResponse]:
        return [
            AuditEventResponse(
                event_type=e.event_type,
                version=e.version,
                actor=e.actor,
                created_at=e.created_at.isoformat(),
                payload=e.payload,
            )
            for e in release_audit_repository.audit(draft_id)
        ]

    @app.post("/api/schedules", response_model=ScheduleResponse, status_code=201)
    async def create_schedule(req: ScheduleCreateRequest) -> ScheduleResponse:
        try:
            schedule = schedule_service.create(ScheduleCreate(**req.model_dump()))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return ScheduleResponse.model_validate(schedule.model_dump())

    @app.get("/api/schedules", response_model=list[ScheduleResponse])
    async def list_schedules() -> list[ScheduleResponse]:
        return [
            ScheduleResponse.model_validate(item.model_dump()) for item in schedule_service.list()
        ]

    @app.post("/api/schedules/{schedule_id}/trigger", status_code=202)
    async def trigger_schedule(
        schedule_id: UUID,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, UUID]:
        try:
            run_id = task_run_service.trigger_schedule(schedule_id, idempotency_key)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"run_id": run_id}

    @app.get("/api/task-runs/{run_id}")
    async def get_task_run(run_id: UUID) -> dict[str, object]:
        detail = task_repository.get_task_detail(run_id)
        if detail is None:
            raise HTTPException(404, "task run not found")
        return detail

    @app.get("/api/task-runs/{run_id}/stages")
    async def get_task_run_stages(run_id: UUID) -> list[dict[str, object]]:
        detail = task_repository.get_task_detail(run_id)
        if detail is None:
            raise HTTPException(404, "task run not found")
        return detail["stages"]

    @app.get("/api/task-runs/{run_id}/events")
    async def get_task_run_events(run_id: UUID) -> list[dict[str, object]]:
        detail = task_repository.get_task_detail(run_id)
        if detail is None:
            raise HTTPException(404, "task run not found")
        return detail["events"]

    if data_run_service is not None:

        @app.post("/api/data-runs")
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

        @app.get("/api/data-runs")
        async def list_data_runs() -> list[dict[str, object]]:
            return real_queries.list()

        @app.get("/api/data-runs/{run_id}")
        async def get_data_run(run_id: UUID) -> dict[str, object]:
            result = real_queries.get(run_id)
            if result is None:
                raise HTTPException(404, "run not found")
            return result

        @app.get("/api/data-runs/{run_id}/candidates")
        async def get_data_run_candidates(run_id: UUID) -> list[dict[str, object]]:
            if real_queries.get(run_id) is None:
                raise HTTPException(404, "run not found")
            return real_queries.candidates(run_id)

        @app.post("/api/data-runs/{run_id}/cancel")
        async def cancel_data_run(run_id: UUID) -> dict[str, object]:
            if not data_run_service.cancel(run_id):
                raise HTTPException(404, "run not found or not running")
            return {"run_id": run_id, "status": "CANCELLED"}

        writing_service = DataRunWritingService(database, service)
        scheduler = EmbeddedScheduler(
            task_repository,
            schedule_service,
            service,
            poll_seconds=settings.scheduler_poll_seconds,
            bridge=ScheduledDataRunBridge(
                task_repository, real_repository, data_run_service, writing_service
            ),
        )

        @app.post("/api/data-runs/{run_id}/generate")
        async def generate_data_run_article(run_id: UUID) -> dict[str, object]:
            try:
                generated_id = writing_service.generate(run_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            return {"run_id": generated_id}

    @app.get("/api/fixture-input")
    async def fixture_input() -> dict[str, Any]:
        # 提供开发期可复现的示例输入，避免用户手工编写内部 Phase 1B JSON。
        path = Path("data/phase1b/fixture-input.json")
        if not path.is_file():
            raise HTTPException(404, "fixture input not found")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/runs")
    async def list_runs() -> list[Any]:
        return queries.list()

    @app.post("/api/runs", response_model=NewRunResponse, status_code=200)
    async def create_run(req: NewRunRequest) -> NewRunResponse:
        try:
            run_id = commands.create(req.input_json, req.provider)
        except ProviderUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return NewRunResponse(run_id=run_id)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: UUID) -> dict[str, Any]:
        detail = queries.detail(run_id)
        if detail is None:
            raise HTTPException(404, "run not found")
        return detail.model_dump(mode="json")

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: UUID) -> StreamingResponse:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")

        async def event_stream() -> AsyncIterator[str]:
            async for event in bus.subscribe(run_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/runs/{run_id}/retry", response_model=NewRunResponse)
    async def retry_run(run_id: UUID) -> NewRunResponse:
        try:
            new_run_id = commands.retry(run_id)
        except ProviderUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        return NewRunResponse(run_id=new_run_id)

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: UUID) -> dict[str, bool]:
        if not commands.cancel(run_id):
            raise HTTPException(404, "run not found or not running")
        return {"cancelled": True}

    @app.get("/api/runs/{run_id}/radar")
    async def get_radar(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.radar(run_id)

    @app.get("/api/runs/{run_id}/draft")
    async def get_draft(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.draft(run_id)

    @app.get("/api/runs/{run_id}/draft.md")
    async def get_draft_md(run_id: UUID) -> PlainTextResponse:
        body = queries.markdown(run_id)
        if body is None:
            raise HTTPException(404, "draft not ready")
        return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")

    @app.get("/api/runs/{run_id}/draft.txt")
    async def get_draft_txt(run_id: UUID) -> PlainTextResponse:
        body = queries.text(run_id)
        if body is None:
            raise HTTPException(404, "draft not ready")
        return PlainTextResponse(body, media_type="text/plain; charset=utf-8")

    @app.get("/api/runs/{run_id}/evidence")
    async def get_evidence(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.evidence(run_id)

    @app.get("/api/runs/{run_id}/review")
    async def get_review(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.review(run_id)

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
