from pathlib import Path
from unittest.mock import Mock

import pytest
from sector_pulse.config.settings import ApplicationSettings
from sector_pulse.storage.ports import RuntimeTaskRepositoryPort
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.web.dependencies import build_runtime_dependencies


def test_sqlite_dependencies_are_fully_typed(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"

    dependencies = build_runtime_dependencies(
        ApplicationSettings(database_path=database_path), database_path
    )

    assert isinstance(dependencies.database, SQLiteDatabase)
    assert isinstance(dependencies.storage.task, RuntimeTaskRepositoryPort)
    assert dependencies.schedule_service is not None
    assert dependencies.data_run_service is not None
    assert dependencies.run_service is not None


def test_postgres_configuration_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthcheck = Mock(side_effect=ConnectionError("postgres unavailable"))
    monkeypatch.setattr(PostgresDatabase, "healthcheck", healthcheck)
    settings = ApplicationSettings(
        database_url="postgresql://sectorpulse:secret@localhost/sectorpulse"
    )

    with pytest.raises(ConnectionError, match="postgres unavailable"):
        build_runtime_dependencies(settings, Path("unused.db"))

    healthcheck.assert_called_once_with()
