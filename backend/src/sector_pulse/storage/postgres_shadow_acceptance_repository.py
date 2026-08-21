import json
from datetime import date
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.shadow_acceptance import ShadowRun, ShadowRunStatus
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresShadowAcceptanceRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def save_run(self, item: ShadowRun) -> None:
        engine = self._database.start()
        async with engine.begin() as connection:
            await connection.execute(
                text("""INSERT INTO shadow_runs
                (shadow_id, run_id, trading_date, mode, status, provider_status_json,
                 cutoff_at, metrics_json, failure_reason, created_at, finished_at)
                VALUES (:shadow_id, :run_id, :trading_date, :mode, :status, :provider_status,
                        :cutoff_at, :metrics, :failure_reason, :created_at, :finished_at)
                ON CONFLICT (shadow_id) DO UPDATE SET status = EXCLUDED.status,
                  provider_status_json = EXCLUDED.provider_status_json,
                  cutoff_at = EXCLUDED.cutoff_at, metrics_json = EXCLUDED.metrics_json,
                  failure_reason = EXCLUDED.failure_reason, finished_at = EXCLUDED.finished_at"""),
                {
                    "shadow_id": str(item.shadow_id), "run_id": str(item.run_id),
                    "trading_date": item.trading_date.isoformat(), "mode": item.mode,
                    "status": item.status.value,
                    "provider_status": json.dumps(item.provider_status),
                    "cutoff_at": item.cutoff_at.isoformat() if item.cutoff_at else None,
                    "metrics": json.dumps(item.metrics),
                    "failure_reason": item.failure_reason,
                    "created_at": item.created_at.isoformat(),
                    "finished_at": item.finished_at.isoformat() if item.finished_at else None,
                },
            )

    async def get(self, shadow_id: UUID) -> ShadowRun | None:
        engine = self._database.start()
        async with engine.connect() as connection:
            row = (await connection.execute(
                text(
                    "SELECT shadow_id, run_id, trading_date, mode, status, "
                    "provider_status_json, cutoff_at, metrics_json, failure_reason, "
                    "created_at, finished_at FROM shadow_runs "
                    "WHERE shadow_id = :shadow_id"
                ),
                {"shadow_id": str(shadow_id)},
            )).mappings().first()
        if row is None:
            return None
        return ShadowRun(
            shadow_id=UUID(row["shadow_id"]), run_id=UUID(row["run_id"]),
            trading_date=date.fromisoformat(str(row["trading_date"])), mode=row["mode"],
            status=ShadowRunStatus(row["status"]),
            provider_status=json.loads(row["provider_status_json"]),
            cutoff_at=row["cutoff_at"],
            metrics=json.loads(row["metrics_json"]),
            failure_reason=row["failure_reason"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
        )
