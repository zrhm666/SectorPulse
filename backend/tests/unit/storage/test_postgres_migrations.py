from pathlib import Path


def test_postgres_migration_files_are_split_safe() -> None:
    migration_dir = Path("backend/src/sector_pulse/storage/migrations")
    for path in migration_dir.glob("[0-9][0-9][0-9]_*.sql"):
        statements = [
            part.strip()
            for part in path.read_text(encoding="utf-8").split(";")
            if part.strip()
        ]
        assert statements, path
        assert all("PRAGMA" not in statement.upper() for statement in statements)
