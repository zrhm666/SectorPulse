import asyncio
import inspect
from dataclasses import dataclass
from threading import Thread
from typing import Any

from sector_pulse.storage.evidence_repository import SQLiteEvidenceRepository
from sector_pulse.storage.market_snapshot_repository import SQLiteMarketSnapshotRepository
from sector_pulse.storage.news_repository import SQLiteNewsRepository
from sector_pulse.storage.news_retrieval_repository import SQLiteNewsRetrievalRepository
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_evidence_repository import PostgresEvidenceRepository
from sector_pulse.storage.postgres_market_snapshot_repository import (
    PostgresMarketSnapshotRepository,
)
from sector_pulse.storage.postgres_news_repository import PostgresNewsRepository
from sector_pulse.storage.postgres_news_retrieval_repository import PostgresNewsRetrievalRepository
from sector_pulse.storage.postgres_real_data_run_repository import PostgresRealDataRunRepository
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite import SQLiteDatabase


def _run_awaitable(awaitable: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    result: list[Any] = []
    error: list[BaseException] = []

    def execute() -> None:
        try:
            result.append(asyncio.run(awaitable))
        except BaseException as exc:  # pragma: no cover - forwarded to caller
            error.append(exc)

    thread = Thread(target=execute)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0] if result else None


class BlockingAsyncRepository:
    """Expose async PostgreSQL repositories to legacy synchronous services."""

    def __init__(self, target: object) -> None:
        self._target = target

    def __getattr__(self, name: str) -> Any:
        method = getattr(self._target, name)

        def call(*args: Any, **kwargs: Any) -> Any:
            value = method(*args, **kwargs)
            return _run_awaitable(value) if inspect.isawaitable(value) else value

        return call


@dataclass(frozen=True)
class RuntimeStorageBundle:
    market_snapshots: object
    news: object
    evidence: object
    news_retrieval: object
    real_data_runs: object


def build_sqlite_storage(database: SQLiteDatabase) -> RuntimeStorageBundle:
    return RuntimeStorageBundle(
        market_snapshots=SQLiteMarketSnapshotRepository(database),
        news=SQLiteNewsRepository(database),
        evidence=SQLiteEvidenceRepository(database),
        news_retrieval=SQLiteNewsRetrievalRepository(database),
        real_data_runs=SQLiteRealDataRunRepository(database),
    )


def build_postgres_storage(database: PostgresDatabase) -> RuntimeStorageBundle:
    return RuntimeStorageBundle(
        market_snapshots=BlockingAsyncRepository(PostgresMarketSnapshotRepository(database)),
        news=BlockingAsyncRepository(PostgresNewsRepository(database)),
        evidence=BlockingAsyncRepository(PostgresEvidenceRepository(database)),
        news_retrieval=BlockingAsyncRepository(PostgresNewsRetrievalRepository(database)),
        real_data_runs=BlockingAsyncRepository(PostgresRealDataRunRepository(database)),
    )
