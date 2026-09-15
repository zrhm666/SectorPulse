# backend/tests/unit/test_postgres_isolation.py
import os

import pytest

from backend.tests.postgres_isolation import (
    BusinessDatabaseRefused,
    isolate_configured_postgres_url,
)

BUSINESS_URL = "postgresql+asyncpg://sectorpulse_app:secret@localhost:5432/sectorpulse_runtime"
TEST_URL = "postgresql+asyncpg://sectorpulse_app:secret@localhost:5432/sectorpulse_runtime_test"


def test_an_unset_url_is_blanked_so_dotenv_cannot_reintroduce_the_business_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SECTOR_PULSE_DATABASE_URL", raising=False)

    isolate_configured_postgres_url()

    # Present but empty: dotenv keeps an existing value, so the business URL in
    # `.env` cannot reach a contract test that reads this variable.
    assert os.environ["SECTOR_PULSE_DATABASE_URL"] == ""


def test_a_test_database_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECTOR_PULSE_DATABASE_URL", TEST_URL)

    isolate_configured_postgres_url()

    assert os.environ["SECTOR_PULSE_DATABASE_URL"] == TEST_URL


def test_the_business_database_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECTOR_PULSE_DATABASE_URL", BUSINESS_URL)

    with pytest.raises(BusinessDatabaseRefused, match="sectorpulse_runtime"):
        isolate_configured_postgres_url()
