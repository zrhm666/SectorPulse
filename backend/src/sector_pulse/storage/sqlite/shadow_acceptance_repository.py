# ruff: noqa: E501
import json
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID

from sector_pulse.domain.shadow_acceptance import (
    ComplianceRecord,
    RecoveryDrill,
    ShadowRun,
    ShadowRunStatus,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteShadowAcceptanceRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def save_run(self, item: ShadowRun) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO shadow_runs
                (shadow_id, run_id, trading_date, mode, status, provider_status_json,
                 cutoff_at, metrics_json, failure_reason, created_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(item.shadow_id), str(item.run_id), item.trading_date.isoformat(), item.mode,
                 item.status.value, json.dumps(item.provider_status),
                 item.cutoff_at.isoformat() if item.cutoff_at else None, json.dumps(item.metrics),
                 item.failure_reason, item.created_at.isoformat(), item.finished_at.isoformat() if item.finished_at else None),
            )

    def list_runs(self, limit: int = 20) -> tuple[ShadowRun, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT shadow_id, run_id, trading_date, mode, status, provider_status_json, cutoff_at, metrics_json, failure_reason, created_at, finished_at FROM shadow_runs ORDER BY trading_date DESC, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(self._row_to_model(row) for row in rows)

    def get(self, shadow_id: UUID) -> ShadowRun | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT shadow_id, run_id, trading_date, mode, status, provider_status_json, cutoff_at, metrics_json, failure_reason, created_at, finished_at FROM shadow_runs WHERE shadow_id = ?",
                (str(shadow_id),),
            ).fetchone()
        return self._row_to_model(row) if row else None

    @staticmethod
    def _row_to_model(row: tuple[object, ...]) -> ShadowRun:
        values = cast(tuple[Any, ...], row)
        return ShadowRun(
            shadow_id=UUID(values[0]), run_id=UUID(values[1]),
            trading_date=date.fromisoformat(values[2]), mode=values[3],
            status=ShadowRunStatus(values[4]), provider_status=json.loads(values[5]),
            cutoff_at=datetime.fromisoformat(values[6]) if values[6] else None,
            metrics=json.loads(values[7]), failure_reason=values[8],
            created_at=datetime.fromisoformat(values[9]),
            finished_at=datetime.fromisoformat(values[10]) if values[10] else None,
        )

    def update_run(self, shadow_id: UUID, item: ShadowRun) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """UPDATE shadow_runs SET status = ?, provider_status_json = ?, cutoff_at = ?,
                   metrics_json = ?, failure_reason = ?, finished_at = ? WHERE shadow_id = ?""",
                (item.status.value, json.dumps(item.provider_status), item.cutoff_at.isoformat() if item.cutoff_at else None,
                 json.dumps(item.metrics), item.failure_reason, item.finished_at.isoformat() if item.finished_at else None,
                 str(shadow_id)),
            )

    def save_recovery(self, item: RecoveryDrill) -> None:
        with self._database.transaction() as connection:
            connection.execute("INSERT INTO recovery_drills (drill_id, shadow_id, fault_type, recovered, recovery_seconds, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (str(item.drill_id), str(item.shadow_id), item.fault_type, int(item.recovered), item.recovery_seconds, item.notes, item.created_at.isoformat()))

    def save_compliance(self, item: ComplianceRecord) -> None:
        with self._database.transaction() as connection:
            connection.execute("INSERT INTO compliance_records (record_id, shadow_id, rules_version, decision, reviewer, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (str(item.record_id), str(item.shadow_id), item.rules_version, item.decision, item.reviewer, item.notes, item.created_at.isoformat()))
