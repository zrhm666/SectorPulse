from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException

from sector_pulse.application.tasks.run_coordinator import RunCoordinator
from sector_pulse.application.tasks.schedule_service import ScheduleCreate, ScheduleService
from sector_pulse.storage.ports.tasks import RuntimeTaskRepositoryPort
from sector_pulse.web.schemas.task import ScheduleCreateRequest, ScheduleResponse


def build_schedules_tasks_router(
    *,
    schedule_service: ScheduleService,
    run_coordinator: RunCoordinator | None,
    task_repository: RuntimeTaskRepositoryPort,
) -> APIRouter:
    router = APIRouter(tags=["schedules", "task-runs"])

    @router.post("/api/schedules", response_model=ScheduleResponse, status_code=201)
    async def create_schedule(req: ScheduleCreateRequest) -> ScheduleResponse:
        try:
            schedule = schedule_service.create(ScheduleCreate(**req.model_dump()))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return ScheduleResponse.model_validate(schedule.model_dump())

    @router.get("/api/schedules", response_model=list[ScheduleResponse])
    async def list_schedules() -> list[ScheduleResponse]:
        return [
            ScheduleResponse.model_validate(item.model_dump()) for item in schedule_service.list()
        ]

    @router.post("/api/schedules/{schedule_id}/trigger", status_code=202)
    async def trigger_schedule(
        schedule_id: UUID,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, UUID]:
        if run_coordinator is None:
            raise HTTPException(503, "run coordinator is not configured")
        try:
            run_id = run_coordinator.start_schedule_now(schedule_id, idempotency_key)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"run_id": run_id}

    def task_detail(run_id: UUID) -> dict[str, object]:
        detail = task_repository.get_task_detail(run_id)
        if detail is None:
            raise HTTPException(404, "task run not found")
        return detail

    @router.get("/api/task-runs/{run_id}")
    async def get_task_run(run_id: UUID) -> dict[str, object]:
        return task_detail(run_id)

    @router.get("/api/task-runs/{run_id}/stages")
    async def get_task_run_stages(run_id: UUID) -> list[dict[str, object]]:
        return cast(list[dict[str, object]], task_detail(run_id)["stages"])

    @router.get("/api/task-runs/{run_id}/events")
    async def get_task_run_events(run_id: UUID) -> list[dict[str, object]]:
        return cast(list[dict[str, object]], task_detail(run_id)["events"])

    return router
