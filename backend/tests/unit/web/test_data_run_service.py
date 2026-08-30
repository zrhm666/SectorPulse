import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sector_pulse.domain.real_data_run import (
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.web.data_run_service import DataRunService
from sector_pulse.web.progress_bus import ProgressBus


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
    captured: list[tuple[RealDataRunRequest, str]] = []

    def create(request: RealDataRunRequest, provider: str) -> UUID:
        captured.append((request, provider))
        return created_id

    service.create = create  # type: ignore[method-assign,assignment]

    assert service.retry(source.run_id) == created_id
    assert captured == [(source.request, "fixture")]


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
        "sector_pulse.web.data_run_service.run_real_data_workflow", slow_workflow
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
