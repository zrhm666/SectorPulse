from uuid import UUID

from sector_pulse.domain.market.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.runs.time import AnalysisRun, InvalidCutoffError
from sector_pulse.ports.market_snapshot import SnapshotAfterCutoffError
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteMarketSnapshotRepository:
    """使用 JSON 保存稳定领域快照，避免数据库依赖供应商中文列名。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(
        self,
        run: AnalysisRun,
        result: ProviderResult[SectorUniverseSnapshot],
    ) -> None:
        if run.run_cutoff_at is None:
            raise InvalidCutoffError("market snapshot requires a locked run cutoff")
        if result.status is not DataStatus.SUCCESS or result.data is None:
            raise ValueError("only successful market snapshots can be persisted")
        if result.data.observed_at > run.run_cutoff_at:
            raise SnapshotAfterCutoffError(
                "snapshot observed_at cannot be later than run_cutoff_at"
            )

        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO analysis_runs (
                    run_id, mode, requested_at, requested_cutoff_at,
                    run_cutoff_at, cutoff_locked_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO NOTHING
                """,
                (
                    str(run.run_id),
                    run.mode.value,
                    run.requested_at.isoformat(),
                    run.requested_cutoff_at.isoformat()
                    if run.requested_cutoff_at
                    else None,
                    run.run_cutoff_at.isoformat(),
                    run.cutoff_locked_at.isoformat() if run.cutoff_locked_at else None,
                ),
            )
            connection.execute(
                """
                INSERT INTO sector_snapshots (
                    run_id, sector_kind, provider_id, classification_version,
                    source_version, observed_at, collected_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, sector_kind) DO UPDATE SET
                    provider_id = excluded.provider_id,
                    classification_version = excluded.classification_version,
                    source_version = excluded.source_version,
                    observed_at = excluded.observed_at,
                    collected_at = excluded.collected_at,
                    payload_json = excluded.payload_json
                """,
                (
                    str(run.run_id),
                    result.data.kind.value,
                    result.data.provider_id,
                    result.data.classification_version,
                    result.data.source_version,
                    result.data.observed_at.isoformat(),
                    result.data.collected_at.isoformat(),
                    result.data.model_dump_json(),
                ),
            )

    def get(
        self, run_id: UUID, kind: SectorKind
    ) -> SectorUniverseSnapshot | None:
        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM sector_snapshots
                WHERE run_id = ? AND sector_kind = ?
                """,
                (str(run_id), kind.value),
            ).fetchone()
        if row is None:
            return None
        return SectorUniverseSnapshot.model_validate_json(row[0])
