from datetime import UTC, datetime
from uuid import uuid4

from sector_pulse.domain.editing import PreferenceCandidate
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.governance_repository import SQLiteGovernanceRepository


def test_adopt_preference_creates_active_version(tmp_path) -> None:
    repo = SQLiteGovernanceRepository(SQLiteDatabase(tmp_path / 'db.sqlite'))
    candidate = PreferenceCandidate(
        source_patch_id=uuid4(), content={'tone': 'concise'}, created_at=datetime.now(UTC)
    )
    repo.save_preference_candidate(candidate)
    version = repo.adopt_preference(candidate.candidate_id, datetime.now(UTC))
    assert version.version == 1
    assert version.content == {'tone': 'concise'}
