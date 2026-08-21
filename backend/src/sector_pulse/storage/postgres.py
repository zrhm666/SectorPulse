from dataclasses import dataclass

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
