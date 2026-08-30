# backend/src/sector_pulse/web/app.py
# ruff: noqa: E501
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sector_pulse.config.llm_config import load_llm_config
from sector_pulse.config.settings import ApplicationSettings, load_environment
from sector_pulse.storage.database_runtime import close_database, initialize_database
from sector_pulse.web.dependencies import (
    build_runtime_dependencies,
    build_web_router_dependencies,
)
from sector_pulse.web.errors import register_error_handlers
from sector_pulse.web.routers.data_runs import build_data_runs_router
from sector_pulse.web.routers.operations import build_operations_router
from sector_pulse.web.routers.runs_review import (
    build_review_governance_router,
    build_runs_review_router,
)
from sector_pulse.web.routers.schedules_tasks import build_schedules_tasks_router
from sector_pulse.web.routers.shadow_prompts import build_shadow_prompts_router


def create_app(
    database_path: Path = Path("data/sector-pulse.db"),
    static_dir: Path | None = Path("web/dist"),
    overrides: dict[str, Any] | None = None,
) -> FastAPI:
    load_environment()
    yaml_config = load_llm_config(Path("config/llm.yaml"))
    settings = ApplicationSettings.from_environment(yaml_config)
    if database_path == Path("data/sector-pulse.db"):
        database_path = settings.database_path
    else:
        settings = settings.model_copy(update={"database_url": None})
    dependencies = build_runtime_dependencies(settings, database_path)
    database = dependencies.database
    storage = dependencies.storage
    router_dependencies = build_web_router_dependencies(dependencies, settings, overrides)
    scheduler = router_dependencies.scheduler
    run_coordinator = router_dependencies.coordinator

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await initialize_database(database)
        storage.phase1b_runs.mark_interrupted(datetime.now(UTC))
        if scheduler is not None:
            scheduler.reconcile_finished()
        storage.task.recover_expired_leases()
        if run_coordinator is not None:
            run_coordinator.recover_startup(datetime.now(UTC))
        if scheduler is not None:
            scheduler.reconcile_finished()
            scheduler.recover()
            scheduler.start()
        yield
        if scheduler is not None:
            await scheduler.stop()
        await close_database(database)

    app = FastAPI(title="SectorPulse Web", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(
        build_operations_router(
            settings=settings,
            database_path=database_path,
            database=database,
            storage=storage,
            queries=router_dependencies.queries,
            scheduler=scheduler,
        )
    )
    app.include_router(
        build_data_runs_router(
            data_run_service=router_dependencies.data_run_service,
            real_queries=router_dependencies.real_queries,
            workbench_queries=router_dependencies.workbench_queries,
            candidate_selection_service=router_dependencies.candidate_selection_service,
            writing_service=router_dependencies.writing_service,
        )
    )
    app.include_router(
        build_schedules_tasks_router(
            schedule_service=dependencies.schedule_service,
            run_coordinator=run_coordinator,
            task_repository=storage.task,
        )
    )
    app.include_router(
        build_runs_review_router(
            commands=router_dependencies.commands,
            queries=router_dependencies.queries,
            bus=dependencies.bus,
        )
    )
    app.include_router(build_review_governance_router(router_dependencies.review))
    app.include_router(
        build_shadow_prompts_router(
            shadow_repository=storage.shadow,
            prompt_golden_repository=storage.prompt_golden,
        )
    )

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
                raise HTTPException(404, "not found")
            return FileResponse(static_dir / "index.html")

    return app
