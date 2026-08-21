from pathlib import Path

from sector_pulse.config.settings import ApplicationSettings
from sector_pulse.storage.database_config import resolve_database_config
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.sqlite import SQLiteDatabase

type Database = SQLiteDatabase | PostgresDatabase


def build_database(settings: ApplicationSettings, database_path: Path) -> Database:
    """Build the configured backend without silently falling back."""
    config = resolve_database_config(settings.database_url, str(database_path))
    if config.backend == "sqlite":
        return SQLiteDatabase(Path(config.url or database_path))
    return PostgresDatabase(config.url or "")


async def initialize_database(database: Database) -> None:
    """Initialize either backend from an async application lifespan."""
    if isinstance(database, SQLiteDatabase):
        database.initialize()
    else:
        await database.initialize()


async def close_database(database: Database) -> None:
    if isinstance(database, PostgresDatabase):
        await database.close()
