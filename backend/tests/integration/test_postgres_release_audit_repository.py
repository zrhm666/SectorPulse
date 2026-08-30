import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sector_pulse.domain.release_audit import ApprovalStatus, DraftApproval, DraftExport
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_release_audit_repository import PostgresReleaseAuditRepository


def test_postgres_release_audit_matches_runtime_contract() -> None:
    for method in ("approve", "approval", "revoke", "audit", "record_event", "record_export"):
        assert callable(getattr(PostgresReleaseAuditRepository, method, None)), method


def test_postgres_release_audit_round_trip() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    item = DraftApproval(
        approval_id=uuid4(), run_id=uuid4(), draft_id=uuid4(), version=1,
        governance_hash="hash", actor="postgres-test",
        status=ApprovalStatus.APPROVED_FOR_COPY,
        approved_at=datetime.now(UTC),
    )
    repository = PostgresReleaseAuditRepository(database)
    repository.approve(item)
    loaded = repository.approval(item.draft_id, 1)
    assert loaded is not None
    assert loaded.approval_id == item.approval_id
    revoked_at = datetime.now(UTC)
    repository.revoke(item.run_id, item.draft_id, 1, "postgres-test", revoked_at)
    revoked = repository.approval(item.draft_id, 1)
    assert revoked is not None
    assert revoked.status is ApprovalStatus.REVOKED
    repository.record_export(
        DraftExport(
            run_id=item.run_id,
            draft_id=item.draft_id,
            version=1,
            format="json",
            content_hash="export-hash",
            actor="postgres-test",
            created_at=datetime.now(UTC),
        )
    )
    assert [event.event_type for event in repository.audit(item.draft_id)] == [
        "APPROVED",
        "REVOKED",
        "EXPORTED",
    ]
    database.close()
