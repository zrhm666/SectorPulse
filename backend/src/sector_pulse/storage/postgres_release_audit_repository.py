import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from sector_pulse.domain.release_audit import (
    ApprovalStatus,
    AuditEvent,
    DraftApproval,
    DraftExport,
)
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresReleaseAuditRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def approve(self, approval: DraftApproval) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO draft_approvals (approval_id, run_id, draft_id, version, "
                    "governance_hash, actor, status, approved_at) VALUES (:approval_id, :run_id, "
                    ":draft_id, :version, :governance_hash, :actor, :status, :approved_at)"
                ),
                {"approval_id": str(approval.approval_id), "run_id": str(approval.run_id),
                 "draft_id": str(approval.draft_id), "version": approval.version,
                 "governance_hash": approval.governance_hash, "actor": approval.actor,
                 "status": approval.status.value, "approved_at": approval.approved_at.isoformat()},
            )
            self._event(connection, approval.run_id, approval.draft_id, approval.version,
                              "APPROVED", approval.actor, {})

    def approval(self, draft_id: UUID, version: int) -> DraftApproval | None:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text(
                    "SELECT approval_id, run_id, draft_id, version, governance_hash, actor, "
                    "status, approved_at FROM draft_approvals "
                    "WHERE draft_id = :draft_id AND version = :version"
                ),
                {"draft_id": str(draft_id), "version": version},
            )
            row = result.first()
        if row is None:
            return None
        return DraftApproval(
            approval_id=UUID(row[0]), run_id=UUID(row[1]), draft_id=UUID(row[2]), version=row[3],
            governance_hash=row[4], actor=row[5], status=ApprovalStatus(row[6]),
            approved_at=datetime.fromisoformat(row[7]),
        )

    def audit(self, draft_id: UUID) -> tuple[AuditEvent, ...]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text(
                    "SELECT event_id, run_id, draft_id, version, event_type, actor, "
                    "payload_json, created_at FROM audit_events "
                    "WHERE draft_id = :draft_id ORDER BY created_at"
                ),
                {"draft_id": str(draft_id)},
            )
            rows = result.fetchall()
        return tuple(
            AuditEvent(event_id=UUID(row[0]), run_id=UUID(row[1]), draft_id=UUID(row[2]),
                       version=row[3], event_type=row[4], actor=row[5], payload=json.loads(row[6]),
                       created_at=datetime.fromisoformat(row[7]))
            for row in rows
        )

    def revoke(
        self,
        run_id: UUID,
        draft_id: UUID,
        version: int,
        actor: str,
        created_at: datetime,
    ) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    "UPDATE draft_approvals SET status = 'REVOKED' "
                    "WHERE draft_id = :draft_id AND version = :version"
                ),
                {"draft_id": str(draft_id), "version": version},
            )
            self._event(
                connection,
                run_id,
                draft_id,
                version,
                "REVOKED",
                actor,
                {},
                created_at=created_at,
            )

    def record_event(self, run_id: UUID, draft_id: UUID, version: int,
                           event_type: str, actor: str, payload: dict[str, object]) -> None:
        with self._database.start().begin() as connection:
            self._event(connection, run_id, draft_id, version, event_type, actor, payload)

    def record_export(self, export: DraftExport) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO draft_exports (export_id, run_id, draft_id, version, format, "
                    "content_hash, actor, created_at) VALUES (:export_id, :run_id, :draft_id, "
                    ":version, :format, :content_hash, :actor, :created_at)"
                ),
                {
                    "export_id": str(export.export_id),
                    "run_id": str(export.run_id),
                    "draft_id": str(export.draft_id),
                    "version": export.version,
                    "format": export.format,
                    "content_hash": export.content_hash,
                    "actor": export.actor,
                    "created_at": export.created_at.isoformat(),
                },
            )
            self._event(
                connection,
                export.run_id,
                export.draft_id,
                export.version,
                "EXPORTED",
                export.actor,
                {"format": export.format, "content_hash": export.content_hash},
                created_at=export.created_at,
            )

    @staticmethod
    def content_hash(content: dict[str, object]) -> str:
        payload = json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()

    def _event(
        self,
        connection: Connection,
        run_id: UUID,
        draft_id: UUID,
        version: int,
        event_type: str,
        actor: str,
        payload: dict[str, object],
        *,
        created_at: datetime | None = None,
    ) -> None:
        connection.execute(
            text(
                "INSERT INTO audit_events (event_id, run_id, draft_id, version, event_type, actor, "
                "payload_json, created_at) VALUES (:event_id, :run_id, :draft_id, :version, "
                ":event_type, :actor, :payload_json, :created_at)"
            ),
            {"event_id": str(uuid4()), "run_id": str(run_id), "draft_id": str(draft_id),
             "version": version, "event_type": event_type, "actor": actor,
             "payload_json": json.dumps(payload),
             "created_at": (created_at or datetime.now(UTC)).isoformat()},
        )
