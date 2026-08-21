import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sector_pulse.domain.release_audit import ApprovalStatus, DraftApproval
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_release_audit_repository import PostgresReleaseAuditRepository


@pytest.mark.asyncio
async def test_postgres_release_audit_round_trip() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    item = DraftApproval(
        approval_id=uuid4(), run_id=uuid4(), draft_id=uuid4(), version=1,
        governance_hash="hash", actor="postgres-test",
        status=ApprovalStatus.APPROVED_FOR_COPY,
        approved_at=datetime.now(UTC),
    )
    repository = PostgresReleaseAuditRepository(database)
    await repository.approve(item)
    loaded = await repository.approval(item.draft_id, 1)
    assert loaded is not None
    assert loaded.approval_id == item.approval_id
    await database.engine.dispose()
