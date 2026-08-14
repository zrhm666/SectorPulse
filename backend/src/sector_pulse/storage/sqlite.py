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

    def initialize(self) -> None:
        """按版本顺序执行未应用迁移；重复调用不会重复写入版本。"""
        migration_dir = Path(__file__).parent / "migrations"
        migrations = sorted(migration_dir.glob("[0-9][0-9][0-9]_*.sql"))
        with self.transaction() as connection:
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
                connection.executescript(migration_path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
                )
