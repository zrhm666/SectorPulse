"""Deterministic A1 data services used by the orchestration tool adapters."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, model_validator

from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.tasks import TaskOwnershipError
from sector_pulse.domain.market.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.market.quality import (
    QualityReport,
    QualityThresholds,
    evaluate_universe,
    lock_cutoff_from_core_market,
)
from sector_pulse.domain.orchestration.models import ArtifactRef, TaskStatus
from sector_pulse.domain.provider import ProviderResult
from sector_pulse.domain.runs.time import AnalysisMode, AnalysisRun, InvalidCutoffError
from sector_pulse.ports.market_data import MarketDataPort
from sector_pulse.ports.market_snapshot import SnapshotAfterCutoffError
from sector_pulse.ports.orchestration import SnapshotRepository, TransactionSession


class MarketCollectionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    kinds: tuple[SectorKind, ...]

    @model_validator(mode="after")
    def validate_kinds(self) -> "MarketCollectionRequest":
        if not self.kinds or len(set(self.kinds)) != len(self.kinds):
            raise ValueError("MARKET_KINDS_INVALID")
        return self


class MarketCollectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    results: Mapping[SectorKind, ProviderResult[SectorUniverseSnapshot]]


class CoreMarketCollectionResult(MarketCollectionResult):
    run: AnalysisRun


@dataclass(frozen=True)
class MarketCollectionContext:
    run: AnalysisRun
    task_id: UUID
    attempt: int
    worker_id: str
    orchestration: SnapshotRepository
    committer: AtomicArtifactCommitter


class MarketSnapshotPersistence:
    """Write one market snapshot through the orchestration transaction."""

    def __init__(
        self,
        run: AnalysisRun,
        result: ProviderResult[SectorUniverseSnapshot],
    ) -> None:
        if run.run_cutoff_at is None:
            raise InvalidCutoffError("market snapshot requires a locked run cutoff")
        if result.data is None:
            raise ValueError("only market results with data can be persisted")
        if result.data.observed_at > run.run_cutoff_at:
            raise SnapshotAfterCutoffError(
                "snapshot observed_at cannot be later than run_cutoff_at"
            )
        self._run = run
        self._snapshot = result.data

    def write(self, session: TransactionSession, artifact: ArtifactRef) -> None:
        del artifact
        run = self._run
        snapshot = self._snapshot
        cutoff = run.run_cutoff_at
        if cutoff is None:  # Constructor validation narrows this for runtime, not mypy.
            raise InvalidCutoffError("market snapshot requires a locked run cutoff")
        session.execute(
            "INSERT INTO analysis_runs (run_id, mode, requested_at, requested_cutoff_at, "
            "run_cutoff_at, cutoff_locked_at) VALUES (:run_id, :mode, :requested_at, "
            ":requested_cutoff_at, :run_cutoff_at, :cutoff_locked_at) "
            "ON CONFLICT(run_id) DO NOTHING",
            {
                "run_id": str(run.run_id),
                "mode": run.mode.value,
                "requested_at": run.requested_at.isoformat(),
                "requested_cutoff_at": (
                    run.requested_cutoff_at.isoformat() if run.requested_cutoff_at else None
                ),
                "run_cutoff_at": cutoff.isoformat(),
                "cutoff_locked_at": (
                    run.cutoff_locked_at.isoformat() if run.cutoff_locked_at else None
                ),
            },
        )
        session.execute(
            "INSERT INTO sector_snapshots (run_id, sector_kind, provider_id, "
            "classification_version, source_version, observed_at, collected_at, payload_json) "
            "VALUES (:run_id, :sector_kind, :provider_id, :classification_version, "
            ":source_version, :observed_at, :collected_at, :payload_json) "
            "ON CONFLICT(run_id, sector_kind) DO UPDATE SET "
            "provider_id=excluded.provider_id, "
            "classification_version=excluded.classification_version, "
            "source_version=excluded.source_version, observed_at=excluded.observed_at, "
            "collected_at=excluded.collected_at, payload_json=excluded.payload_json",
            {
                "run_id": str(run.run_id),
                "sector_kind": snapshot.kind.value,
                "provider_id": snapshot.provider_id,
                "classification_version": snapshot.classification_version,
                "source_version": snapshot.source_version,
                "observed_at": snapshot.observed_at.isoformat(),
                "collected_at": snapshot.collected_at.isoformat(),
                "payload_json": snapshot.model_dump_json(),
            },
        )

    def exists(self, session: TransactionSession, artifact: ArtifactRef) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM sector_snapshots WHERE run_id=:run_id AND sector_kind=:kind",
                {"run_id": str(self._run.run_id), "kind": self._snapshot.kind.value},
            )
        )


def require_live_task_owner(
    repository: SnapshotRepository,
    run_id: UUID,
    *,
    task_id: UUID,
    attempt: int,
    worker_id: str,
    now: datetime,
) -> None:
    state = repository.load(run_id)
    if state is None:
        raise KeyError("orchestration run not found")
    task = next((item for item in state.tasks if item.task_id == task_id), None)
    if task is None:
        raise KeyError("orchestration task not found")
    if task.attempt != attempt:
        raise TaskOwnershipError("stale task attempt")
    if task.status is not TaskStatus.RUNNING or task.worker_id != worker_id:
        raise TaskOwnershipError("worker does not own task")
    if task.lease_expires_at is None or task.lease_expires_at <= now:
        raise TaskOwnershipError("worker lease expired")


class CollectMarketService:
    """Fetch only the server-approved market gaps requested by A1."""

    def __init__(self, provider: MarketDataPort, *, mode: AnalysisMode) -> None:
        self._provider = provider
        self._mode = mode

    async def collect(self, request: MarketCollectionRequest) -> MarketCollectionResult:
        results: dict[SectorKind, ProviderResult[SectorUniverseSnapshot]] = {}
        for kind in request.kinds:
            results[kind] = await self._provider.fetch_sector_universe(kind, self._mode)
        return MarketCollectionResult(results=results)

    async def collect_and_persist(
        self,
        request: MarketCollectionRequest,
        *,
        context: MarketCollectionContext,
        now: datetime | None = None,
    ) -> MarketCollectionResult:
        observed_at = now or datetime.now(UTC)
        self._require_live_owner(context, observed_at)
        collected = await self.collect(request)
        self._persist(collected, context=context, run=context.run, now=observed_at)
        return collected

    async def collect_core_and_persist(
        self,
        *,
        context: MarketCollectionContext,
        locked_at: datetime,
        max_skew_seconds: int,
    ) -> CoreMarketCollectionResult:
        require_live_task_owner(
            context.orchestration,
            context.run.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=locked_at,
        )
        collected = await self.collect(
            MarketCollectionRequest(kinds=(SectorKind.INDUSTRY, SectorKind.CONCEPT))
        )
        ordered = tuple(
            collected.results[kind]
            for kind in (SectorKind.INDUSTRY, SectorKind.CONCEPT)
        )
        if any(result.data is None for result in ordered):
            raise ValueError("core market observations are missing")
        locked_run = lock_cutoff_from_core_market(
            context.run,
            ordered,
            locked_at,
            max_skew_seconds,
        )
        self._persist(collected, context=context, run=locked_run, now=locked_at)
        return CoreMarketCollectionResult(run=locked_run, results=collected.results)

    @staticmethod
    def _persist(
        collected: MarketCollectionResult,
        *,
        context: MarketCollectionContext,
        run: AnalysisRun,
        now: datetime,
    ) -> None:
        for kind, result in collected.results.items():
            if result.data is None:
                continue
            reference = (
                f"market:{run.run_id}:{kind.value}:{result.data.source_version}"
            )
            artifact = ArtifactRef(
                artifact_id=uuid5(
                    NAMESPACE_URL,
                    f"{reference}:{context.task_id}:{context.attempt}",
                ),
                task_id=context.task_id,
                attempt=context.attempt,
                kind="market_snapshot",
                reference=reference,
            )
            context.committer.commit(
                artifact,
                worker_id=context.worker_id,
                persistence=MarketSnapshotPersistence(run, result),
                now=now,
            )

    @staticmethod
    def _require_live_owner(context: MarketCollectionContext, now: datetime) -> None:
        require_live_task_owner(
            context.orchestration,
            context.run.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=now,
        )


class InspectDataQualityService:
    """Expose code-computed quality without accepting model-controlled thresholds."""

    def __init__(self, thresholds: QualityThresholds) -> None:
        self._thresholds = thresholds

    def inspect(self, result: ProviderResult[SectorUniverseSnapshot]) -> QualityReport:
        return evaluate_universe(result, self._thresholds)

    @property
    def thresholds(self) -> QualityThresholds:
        return self._thresholds


class MarketQualityPersistence:
    def __init__(
        self,
        *,
        report_id: UUID,
        run_id: UUID,
        source_artifact_id: UUID,
        input_fingerprint: str,
        report: QualityReport,
        created_at: datetime,
    ) -> None:
        self.report_id = report_id
        self.run_id = run_id
        self.source_artifact_id = source_artifact_id
        self.input_fingerprint = input_fingerprint
        self.report = report
        self.created_at = created_at

    def write(self, session: TransactionSession, artifact: ArtifactRef) -> None:
        del artifact
        session.execute(
            "INSERT INTO market_quality_reports (report_id, run_id, source_artifact_id, "
            "input_fingerprint, quality_status, sector_count, issues_json, created_at) "
            "VALUES (:report_id, :run_id, :source_artifact_id, :input_fingerprint, "
            ":quality_status, :sector_count, :issues_json, :created_at)",
            {
                "report_id": str(self.report_id),
                "run_id": str(self.run_id),
                "source_artifact_id": str(self.source_artifact_id),
                "input_fingerprint": self.input_fingerprint,
                "quality_status": self.report.status.value,
                "sector_count": self.report.sector_count,
                "issues_json": json.dumps(self.report.issues, ensure_ascii=False),
                "created_at": self.created_at.isoformat(),
            },
        )

    def exists(self, session: TransactionSession, artifact: ArtifactRef) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM market_quality_reports WHERE report_id=:report_id",
                {"report_id": str(self.report_id)},
            )
        )
