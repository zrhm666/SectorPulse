from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlparse

from fastapi import APIRouter

from sector_pulse.application.operations_summary import (
    OperationsSummaryQueryPort,
    build_operations_snapshot,
)
from sector_pulse.application.run_queries import RunQueryService
from sector_pulse.application.scheduler import EmbeddedScheduler
from sector_pulse.config.settings import ApplicationSettings
from sector_pulse.infrastructure.providers.real_data_factory import RealDataProviderFactory
from sector_pulse.storage.database_runtime import Database
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.runtime_bundle import RuntimeStorageBundle
from sector_pulse.web.operations_schemas import (
    OperationsConsentStatus,
    OperationsCoreSummary,
    OperationsDatabaseStatus,
    OperationsLlmStatus,
    OperationsProviderStatus,
    OperationsReadiness,
    OperationsReadinessItem,
    OperationsRecentRun,
    OperationsRunSummary,
    OperationsSummaryResponse,
    OperationsTrend,
    OperationsTrendPoint,
)


def _readiness(
    *,
    database_backend: str,
    preflight_available: bool,
    missing_requirements: tuple[str, ...],
    llm_provider: str,
    llm_configured: bool,
    live_llm_consent: bool,
    scheduler_enabled: bool,
    scheduler_started: bool,
) -> OperationsReadiness:
    live_data = OperationsReadinessItem(
        status="ready" if preflight_available else "unavailable",
        label="实时数据",
        detail=(
            "Provider 与授权已就绪"
            if preflight_available
            else f"缺少：{'、'.join(missing_requirements) or '运行前置条件'}"
        ),
    )
    if not llm_configured:
        llm = OperationsReadinessItem(status="unavailable", label="LLM", detail="模型配置不完整")
    elif llm_provider == "fixture" or live_llm_consent:
        llm = OperationsReadinessItem(status="ready", label="LLM", detail=f"{llm_provider} 已就绪")
    else:
        llm = OperationsReadinessItem(
            status="warning", label="LLM", detail="配置完成，尚未确认实时 LLM 授权"
        )
    if not scheduler_enabled:
        scheduler_status = OperationsReadinessItem(
            status="disabled", label="调度器", detail="当前配置为停用"
        )
    elif scheduler_started:
        scheduler_status = OperationsReadinessItem(
            status="ready", label="调度器", detail="定时调度已启动"
        )
    else:
        scheduler_status = OperationsReadinessItem(
            status="warning", label="调度器", detail="已启用但尚未启动"
        )
    return OperationsReadiness(
        database=OperationsReadinessItem(
            status="ready",
            label="数据库",
            detail="PostgreSQL 已连接" if database_backend == "postgresql" else "SQLite 已连接",
        ),
        live_data=live_data,
        llm=llm,
        scheduler=scheduler_status,
    )


def build_operations_router(
    *,
    settings: ApplicationSettings,
    database_path: Path,
    database: Database,
    storage: RuntimeStorageBundle,
    queries: RunQueryService,
    scheduler: EmbeddedScheduler | None,
) -> APIRouter:
    router = APIRouter(tags=["operations"])

    @router.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/api/operations/summary", response_model=OperationsSummaryResponse)
    async def operations_summary() -> OperationsSummaryResponse:
        runs = queries.list()
        preflight = RealDataProviderFactory().preflight()
        generated_at = datetime.now(UTC)
        operations_query = cast(OperationsSummaryQueryPort | None, storage.operations)
        if operations_query is None:
            raise RuntimeError("operations query is not configured")
        snapshot = build_operations_snapshot(operations_query.list_records(), now=generated_at)
        database_backend: Literal["sqlite", "postgresql"] = (
            "postgresql" if isinstance(database, PostgresDatabase) else "sqlite"
        )
        database_name = (
            urlparse(settings.database_url).path.lstrip("/")
            if settings.database_url
            else database_path.name
        ) or "default"
        llm_configured = settings.llm_provider == "fixture" or bool(
            settings.llm_base_url and settings.llm_api_key
        )
        return OperationsSummaryResponse(
            database=OperationsDatabaseStatus(backend=database_backend, name=database_name),
            llm=OperationsLlmStatus(
                provider=settings.llm_provider,
                model=settings.llm_model,
                budget_cny_per_run=settings.budget_cny_per_run,
                configured=llm_configured,
            ),
            consent=OperationsConsentStatus(
                live_data=Path(".live-data-consent").is_file(),
                live_llm=Path(".live-llm-consent").is_file(),
            ),
            providers=OperationsProviderStatus(
                live_data_available=preflight.available,
                missing_requirements=preflight.missing,
            ),
            runs=OperationsRunSummary(
                total=len(runs),
                running=sum(run.status == "RUNNING" for run in runs),
                awaiting_review=sum(run.status == "READY_FOR_HUMAN_REVIEW" for run in runs),
                failed=sum(run.status == "FAILED" for run in runs),
                recent=runs[:8],
            ),
            summary=OperationsCoreSummary(
                total=snapshot.summary.total,
                completed_today=snapshot.summary.completed_today,
                active=snapshot.summary.active,
                attention=snapshot.summary.attention,
            ),
            trend=OperationsTrend(
                available=snapshot.trend.available,
                reason=snapshot.trend.reason,
                points=tuple(
                    OperationsTrendPoint(
                        date=point.date,
                        total=point.total,
                        completed=point.completed,
                        failed=point.failed,
                    )
                    for point in snapshot.trend.points
                ),
            ),
            readiness=_readiness(
                database_backend=database_backend,
                preflight_available=preflight.available,
                missing_requirements=preflight.missing,
                llm_provider=settings.llm_provider,
                llm_configured=llm_configured,
                live_llm_consent=Path(".live-llm-consent").is_file(),
                scheduler_enabled=settings.scheduler_enabled,
                scheduler_started=scheduler is not None,
            ),
            recent_runs=tuple(
                OperationsRecentRun(
                    run_id=run.run_id,
                    kind=run.kind,
                    mode=run.mode,
                    status=run.status,
                    provider=run.provider,
                    requested_at=run.requested_at,
                    finished_at=run.finished_at,
                    elapsed_ms=run.elapsed_ms,
                    total_cost_cny=run.total_cost_cny,
                    candidate_count=run.candidate_count,
                    detail_path=(
                        f"/runs/{run.run_id}"
                        if run.kind == "content"
                        else f"/data-runs/{run.run_id}"
                    ),
                )
                for run in snapshot.recent_runs
            ),
            generated_at=generated_at,
        )

    return router
