from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sector_pulse.domain.review.release_audit import DraftApproval, DraftExport


def test_approval_binds_version_and_export_format() -> None:
    now = datetime.now(UTC)
    approval = DraftApproval(
        run_id=uuid4(), draft_id=uuid4(), version=2, governance_hash='abc',
        actor='reviewer', approved_at=now
    )
    assert approval.version == 2
    export = DraftExport(
        run_id=approval.run_id, draft_id=approval.draft_id, version=2,
        format='json', content_hash='x', actor='reviewer', created_at=now
    )
    assert export.format == 'json'
    with pytest.raises(ValidationError):
        DraftExport(
            run_id=approval.run_id, draft_id=approval.draft_id, version=2,
            format='html', content_hash='x', actor='reviewer', created_at=now
        )
