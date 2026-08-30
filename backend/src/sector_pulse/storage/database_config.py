from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class DatabaseConfig:
    backend: str
    url: str | None = None


def resolve_database_config(database_url: str | None, database_path: str) -> DatabaseConfig:
    """识别数据库后端；PostgreSQL 配置先进入显式迁移边界，不回退到 SQLite。"""
    if not database_url:
        return DatabaseConfig(backend="sqlite", url=database_path)
    scheme = urlparse(database_url).scheme
    if scheme in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg", "postgres"}:
        remainder = database_url.split("://", 1)[1]
        return DatabaseConfig(
            backend="postgresql", url=f"postgresql+psycopg://{remainder}"
        )
    raise ValueError(f"unsupported database URL scheme: {scheme}")
