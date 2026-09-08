"""Test-only PostgreSQL guard. Never fall back to the business connection."""

import os
from collections.abc import Iterator

import pytest
from sector_pulse.storage.postgres.database import PostgresDatabase
from sqlalchemy import text


@pytest.fixture(name="comparison_postgres")
def comparison_postgres() -> Iterator[PostgresDatabase]:
    url = os.environ.get("SECTOR_PULSE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires verified isolated comparison PostgreSQL database")
    database = PostgresDatabase(url)
    try:
        with database.start().connect() as connection:
            name = connection.execute(text("SELECT current_database()")).scalar_one()
        if name != "sector_pulse_run_comparison_test":
            pytest.fail("refusing to seed a non-comparison database")
        database.initialize()
        yield database
    finally:
        database.close()
