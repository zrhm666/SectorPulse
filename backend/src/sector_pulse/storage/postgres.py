from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


@dataclass
class PostgresDatabase:
    """PostgreSQL 连接层第一阶段：只负责连接池和健康检查。"""

    url: str
    engine: AsyncEngine | None = None

    def start(self) -> AsyncEngine:
        if self.engine is None:
            self.engine = create_async_engine(self.url, pool_pre_ping=True)
        return self.engine

    async def healthcheck(self) -> bool:
        engine = self.start()
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            return result.scalar_one() == 1

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None

    async def initialize(self, migration_dir: Path | None = None) -> None:
        """按文件版本执行 PostgreSQL 迁移；每条语句独立提交，避免 executescript 依赖。"""
        migration_dir = migration_dir or Path(__file__).parent / "migrations"
        engine = self.start()
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                """CREATE TABLE IF NOT EXISTS schema_migrations
                (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"""
            )
            rows = await connection.exec_driver_sql("SELECT version FROM schema_migrations")
            applied = {row[0] for row in rows.fetchall()}
            for path in sorted(migration_dir.glob("[0-9][0-9][0-9]_*.sql")):
                version = int(path.name[:3])
                if version in applied:
                    continue
                statements = [
                    part.strip()
                    for part in path.read_text(encoding="utf-8").split(";")
                    if part.strip()
                ]
                for statement in statements:
                    await connection.exec_driver_sql(statement)
                await connection.exec_driver_sql(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", (version,)
                )
