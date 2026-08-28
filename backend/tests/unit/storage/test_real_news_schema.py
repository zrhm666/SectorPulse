from pathlib import Path

from sector_pulse.storage.sqlite import SQLiteDatabase


def test_initialize_applies_real_news_migration(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "sector-pulse.db")
    database.initialize()
    with database.connection() as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(news_documents)")
        }
    assert {
        "news_source_runs",
        "news_queries",
        "sector_event_links",
        "news_query_documents",
    } <= names
    assert {"citation_url", "publisher", "summary", "source_observed_at"} <= columns


def test_initialize_is_idempotent_after_second_migration(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "sector-pulse.db")
    database.initialize()
    database.initialize()
    with database.connection() as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
