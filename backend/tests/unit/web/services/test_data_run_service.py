import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sector_pulse.domain.runs.real_data_run import (
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.runs.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.web.events.progress_bus import ProgressBus
from sector_pulse.web.services.data_run_service import DataRunService


class RunRepository:
    def __init__(self, run: RealDataRun | None) -> None:
        self.run = run

    def get_run(self, run_id: UUID) -> RealDataRun | None:
        if self.run is None or self.run.run_id != run_id:
            return None
        return self.run


def _run(status: RealDataRunStatus) -> RealDataRun:
    return RealDataRun(
        provider="fixture",
        request=RealDataRunRequest(
            mode="post_close",
            requested_at=datetime(2026, 8, 25, 7, tzinfo=UTC),
            lookback_hours=36,
            precandidate_limit=20,
            final_candidate_limit=8,
        ),
        status=status,
    )


@pytest.mark.parametrize(
    "status",
    [
        RealDataRunStatus.DEGRADED,
        RealDataRunStatus.BLOCKED,
        RealDataRunStatus.FAILED,
        RealDataRunStatus.CANCELLED,
        RealDataRunStatus.INTERRUPTED,
    ],
)
def test_retry_reuses_original_request_and_provider(status: RealDataRunStatus) -> None:
    source = _run(status)
    service = DataRunService(RunRepository(source), ProgressBus())  # type: ignore[arg-type]
    created_id = uuid4()
    captured: list[tuple[RealDataRunRequest, str, UUID | None]] = []

    def create(request: RealDataRunRequest, provider: str, *, retry_of_run_id=None) -> UUID:
        captured.append((request, provider, retry_of_run_id))
        return created_id

    service.create = create  # type: ignore[method-assign,assignment]

    assert service.retry(source.run_id) == created_id
    assert captured == [(source.request, "fixture", source.run_id)]


@pytest.mark.asyncio
async def test_immediate_retry_cancellation_preserves_lineage(tmp_path):
    repository = SQLiteRealDataRunRepository(SQLiteDatabase(tmp_path / "lineage.db"))
    original = _run(RealDataRunStatus.FAILED)
    repository.insert(original)
    service = DataRunService(
        repository, ProgressBus(), dependencies_factory=lambda _: None, allow_fixture=True,
    )
    retry = service.retry(original.run_id)
    assert service.cancel(retry)
    await service.wait(retry)
    stored = repository.get_run(retry)
    assert stored.status is RealDataRunStatus.CANCELLED
    assert stored.retry_of_run_id == original.run_id
    assert repository.get_run(original.run_id).status is RealDataRunStatus.FAILED


@pytest.mark.asyncio
async def test_retry_workflow_persists_lineage_after_provider_failure(tmp_path, monkeypatch):
    database = SQLiteDatabase(tmp_path / "workflow-lineage.db")
    repository = SQLiteRealDataRunRepository(database)
    original = _run(RealDataRunStatus.FAILED)
    repository.insert(original)

    async def unavailable_provider(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "sector_pulse.application.data_runs.real_data_orchestrator.run_phase1a2_probe",
        unavailable_provider,
    )
    service = DataRunService(
        repository, ProgressBus(),
        dependencies_factory=lambda _: SimpleNamespace(database=database), allow_fixture=True,
    )
    retry = service.retry(original.run_id)
    await service.wait(retry)
    stored = repository.get_run(retry)
    assert stored.status is RealDataRunStatus.FAILED
    assert stored.retry_of_run_id == original.run_id
    assert stored.request == original.request


@pytest.mark.parametrize(
    "status",
    [RealDataRunStatus.FETCHING_NEWS, RealDataRunStatus.READY_FOR_ATTRIBUTION],
)
def test_retry_rejects_active_or_successful_run(status: RealDataRunStatus) -> None:
    source = _run(status)
    service = DataRunService(RunRepository(source), ProgressBus())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="cannot be retried"):
        service.retry(source.run_id)


def test_retry_rejects_missing_run() -> None:
    service = DataRunService(RunRepository(None), ProgressBus())  # type: ignore[arg-type]

    with pytest.raises(KeyError):
        service.retry(uuid4())


def test_fixture_preflight_requires_explicit_fixture_dependencies() -> None:
    service = DataRunService(RunRepository(None), ProgressBus())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="fixture data provider is not configured"):
        service.preflight("fixture")


def test_fixture_preflight_is_available_only_when_explicitly_enabled() -> None:
    service = DataRunService(  # type: ignore[arg-type]
        RunRepository(None), ProgressBus(), allow_fixture=True
    )

    service.preflight("fixture")


@pytest.mark.asyncio
async def test_cancelled_data_run_is_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = SQLiteRealDataRunRepository(SQLiteDatabase(tmp_path / "cancel.db"))
    started = asyncio.Event()

    async def slow_workflow(_dependencies, request, **kwargs):
        run_id = kwargs["run_id"]
        repository.insert(
            RealDataRun(
                run_id=run_id,
                provider="fixture",
                request=request,
                status=RealDataRunStatus.FETCHING_MARKET,
            )
        )
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "sector_pulse.web.services.data_run_service.run_real_data_workflow", slow_workflow
    )
    service = DataRunService(
        repository,
        ProgressBus(),
        dependencies_factory=lambda _provider: object(),
        allow_fixture=True,
    )
    request = RealDataRunRequest(mode="post_close")

    run_id = service.create(request, "fixture")
    await started.wait()
    assert service.cancel(run_id)
    await service.wait(run_id)

    stored = repository.get_run(run_id)
    assert stored is not None
    assert stored.status is RealDataRunStatus.CANCELLED
    assert stored.finished_at is not None
