from pathlib import Path

MIGRATION_DIR = Path("backend/src/sector_pulse/storage/migrations")


def test_reliable_runtime_has_postgres_dialect_migration() -> None:
    path = MIGRATION_DIR / "postgres" / "016_reliable_runtime.sql"
    assert path.is_file()
    sql = path.read_text(encoding="utf-8")
    assert "INTERRUPTED" in sql
    assert "PRAGMA" not in sql.upper()


def test_postgres_migration_files_are_split_safe() -> None:
    paths = list(MIGRATION_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    paths.extend((MIGRATION_DIR / "postgres").glob("[0-9][0-9][0-9]_*.sql"))
    for path in paths:
        statements = [
            part.strip()
            for part in path.read_text(encoding="utf-8").split(";")
            if part.strip()
        ]
        assert statements, path
        assert all("PRAGMA" not in statement.upper() for statement in statements)
