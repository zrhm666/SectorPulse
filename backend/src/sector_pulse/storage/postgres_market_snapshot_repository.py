# ruff: noqa: E501
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.time import AnalysisRun, InvalidCutoffError
from sector_pulse.ports.market_snapshot import SnapshotAfterCutoffError
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresMarketSnapshotRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save(self, run: AnalysisRun, result: ProviderResult[SectorUniverseSnapshot]) -> None:
        if run.run_cutoff_at is None:
            raise InvalidCutoffError("market snapshot requires a locked run cutoff")
        if result.status is not DataStatus.SUCCESS or result.data is None:
            raise ValueError("only successful market snapshots can be persisted")
        if result.data.observed_at > run.run_cutoff_at:
            raise SnapshotAfterCutoffError("snapshot observed_at cannot be later than run_cutoff_at")
        with self._database.start().begin() as connection:
            connection.execute(
                text("INSERT INTO analysis_runs (run_id, mode, requested_at, requested_cutoff_at, "
                     "run_cutoff_at, cutoff_locked_at) VALUES (:run_id, :mode, :requested_at, "
                     ":requested_cutoff_at, :run_cutoff_at, :cutoff_locked_at) ON CONFLICT (run_id) DO NOTHING"),
                {"run_id": str(run.run_id), "mode": run.mode.value,
                 "requested_at": run.requested_at.isoformat(),
                 "requested_cutoff_at": run.requested_cutoff_at.isoformat() if run.requested_cutoff_at else None,
                 "run_cutoff_at": run.run_cutoff_at.isoformat(),
                 "cutoff_locked_at": run.cutoff_locked_at.isoformat() if run.cutoff_locked_at else None},
            )
            item = result.data
            connection.execute(
                text("INSERT INTO sector_snapshots (run_id, sector_kind, provider_id, classification_version, "
                     "source_version, observed_at, collected_at, payload_json) VALUES (:run_id, :sector_kind, "
                     ":provider_id, :classification_version, :source_version, :observed_at, :collected_at, :payload) "
                     "ON CONFLICT (run_id, sector_kind) DO UPDATE SET provider_id = EXCLUDED.provider_id, "
                     "classification_version = EXCLUDED.classification_version, source_version = EXCLUDED.source_version, "
                     "observed_at = EXCLUDED.observed_at, collected_at = EXCLUDED.collected_at, payload_json = EXCLUDED.payload_json"),
                {"run_id": str(run.run_id), "sector_kind": item.kind.value, "provider_id": item.provider_id,
                 "classification_version": item.classification_version, "source_version": item.source_version,
                 "observed_at": item.observed_at.isoformat(), "collected_at": item.collected_at.isoformat(),
                 "payload": item.model_dump_json()},
            )

    def get(self, run_id: UUID, kind: SectorKind) -> SectorUniverseSnapshot | None:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text("SELECT payload_json FROM sector_snapshots WHERE run_id = :run_id AND sector_kind = :kind"),
                {"run_id": str(run_id), "kind": kind.value},
            )
            row = result.first()
        return SectorUniverseSnapshot.model_validate_json(row[0]) if row else None
