import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from sector_pulse.domain.release_audit import ApprovalStatus, AuditEvent, DraftApproval
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresReleaseAuditRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def approve(self, approval: DraftApproval) -> None:
        async with self._database.engine.begin() as connection:
            await connection.execute(
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
            await self._event(connection, approval.run_id, approval.draft_id, approval.version,
                              "APPROVED", approval.actor, {})

    async def approval(self, draft_id: UUID, version: int) -> DraftApproval | None:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(
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

    async def audit(self, draft_id: UUID) -> tuple[AuditEvent, ...]:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(
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

    async def record_event(self, run_id: UUID, draft_id: UUID, version: int,
                           event_type: str, actor: str, payload: dict) -> None:
        async with self._database.engine.begin() as connection:
            await self._event(connection, run_id, draft_id, version, event_type, actor, payload)

    @staticmethod
    def content_hash(content: dict) -> str:
        payload = json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()

    async def _event(
        self, connection, run_id, draft_id, version, event_type, actor, payload
    ) -> None:
        await connection.execute(
            text(
                "INSERT INTO audit_events (event_id, run_id, draft_id, version, event_type, actor, "
                "payload_json, created_at) VALUES (:event_id, :run_id, :draft_id, :version, "
                ":event_type, :actor, :payload_json, :created_at)"
            ),
            {"event_id": str(uuid4()), "run_id": str(run_id), "draft_id": str(draft_id),
             "version": version, "event_type": event_type, "actor": actor,
             "payload_json": json.dumps(payload),
             "created_at": datetime.now(UTC).isoformat()},
        )
