import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class SQLiteDatabase:
    """管理本地 SQLite 连接和迁移，不向领域层暴露 SQL。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """创建启用外键的短连接，由调用方负责查询但不负责关闭。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """事务成功时提交，异常时回滚，保证一批领域对象不会只写入一半。"""
        with self.connection() as connection:
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _statements(path: Path) -> tuple[str, ...]:
        return tuple(
            statement.strip()
            for statement in path.read_text(encoding="utf-8").split(";")
            if statement.strip()
        )

    def initialize(self, migration_dir: Path | None = None) -> None:
        """在单一事务中应用公共及 SQLite 方言迁移，失败时不记录半成品版本。"""
        migration_dir = migration_dir or Path(__file__).resolve().parents[1] / "migrations"
        migrations = sorted(migration_dir.glob("[0-9][0-9][0-9]_*.sql"))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, isolation_level=None)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            applied_versions = {
                row[0] for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for migration_path in migrations:
                version = int(migration_path.name[:3])
                if version in applied_versions:
                    continue
                paths = [migration_path]
                dialect_path = migration_dir / "sqlite" / migration_path.name
                if dialect_path.is_file():
                    paths.append(dialect_path)
                for path in paths:
                    for statement in self._statements(path):
                        connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
                )
            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise sqlite3.IntegrityError(
                    f"migration foreign key check failed: {len(foreign_key_errors)} violation(s)"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.close()
