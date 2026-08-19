# ruff: noqa: E501
import hashlib
import json
from datetime import datetime
from uuid import UUID

from sector_pulse.domain.release_audit import ApprovalStatus, AuditEvent, DraftApproval, DraftExport
from sector_pulse.storage.sqlite import SQLiteDatabase


class SQLiteReleaseAuditRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def approve(self, approval: DraftApproval) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """INSERT INTO draft_approvals
                (approval_id, run_id, draft_id, version, governance_hash, actor, status, approved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(approval.approval_id),
                    str(approval.run_id),
                    str(approval.draft_id),
                    approval.version,
                    approval.governance_hash,
                    approval.actor,
                    approval.status.value,
                    approval.approved_at.isoformat(),
                ),
            )
            self._event(
                connection,
                approval.run_id,
                approval.draft_id,
                approval.version,
                "APPROVED",
                approval.actor,
                {},
            )

    def revoke(
        self, run_id: UUID, draft_id: UUID, version: int, actor: str, created_at: datetime
    ) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE draft_approvals SET status = 'REVOKED' WHERE draft_id = ? AND version = ?",
                (str(draft_id), version),
            )
            self._event(connection, run_id, draft_id, version, "REVOKED", actor, {})

    def approval(self, draft_id: UUID, version: int):
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT approval_id, run_id, draft_id, version, governance_hash, actor, status, approved_at FROM draft_approvals WHERE draft_id = ? AND version = ?",
                (str(draft_id), version),
            ).fetchone()
        if row is None:
            return None
        return DraftApproval(
            approval_id=UUID(row[0]),
            run_id=UUID(row[1]),
            draft_id=UUID(row[2]),
            version=row[3],
            governance_hash=row[4],
            actor=row[5],
            status=ApprovalStatus(row[6]),
            approved_at=datetime.fromisoformat(row[7]),
        )

    def audit(self, draft_id: UUID) -> tuple[AuditEvent, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT event_id, run_id, draft_id, version, event_type, actor, payload_json, created_at FROM audit_events WHERE draft_id = ? ORDER BY created_at",
                (str(draft_id),),
            ).fetchall()
        return tuple(
            AuditEvent(
                event_id=UUID(r[0]),
                run_id=UUID(r[1]),
                draft_id=UUID(r[2]),
                version=r[3],
                event_type=r[4],
                actor=r[5],
                payload=json.loads(r[6]),
                created_at=datetime.fromisoformat(r[7]),
            )
            for r in rows
        )

    def record_export(self, export: DraftExport) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """INSERT INTO draft_exports
                (export_id, run_id, draft_id, version, format, content_hash, actor, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(export.export_id), str(export.run_id), str(export.draft_id), export.version,
                 export.format, export.content_hash, export.actor, export.created_at.isoformat()),
            )
            self._event(connection, export.run_id, export.draft_id, export.version,
                        "EXPORTED", export.actor, {"format": export.format, "content_hash": export.content_hash})

    @staticmethod
    def content_hash(content: dict) -> str:
        return hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _event(connection, run_id, draft_id, version, event_type, actor, payload) -> None:
        from uuid import uuid4

        connection.execute(
            "INSERT INTO audit_events (event_id, run_id, draft_id, version, event_type, actor, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (
                str(uuid4()),
                str(run_id),
                str(draft_id),
                version,
                event_type,
                actor,
                json.dumps(payload),
            ),
        )
