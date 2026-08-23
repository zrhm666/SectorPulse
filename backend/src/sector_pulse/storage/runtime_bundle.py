# ruff: noqa: E501
import asyncio
import inspect
from dataclasses import dataclass
from threading import Thread
from typing import Any

from sector_pulse.application.postgres_review_analytics import PostgresReviewAnalyticsQueries
from sector_pulse.storage.agent_invocation_repository import SQLiteAgentInvocationRepository
from sector_pulse.storage.draft_edit_repository import SQLiteDraftEditRepository
from sector_pulse.storage.evidence_repository import SQLiteEvidenceRepository
from sector_pulse.storage.governance_repository import SQLiteGovernanceRepository
from sector_pulse.storage.market_snapshot_repository import SQLiteMarketSnapshotRepository
from sector_pulse.storage.news_evidence_repository import SQLiteNewsEvidenceRepository
from sector_pulse.storage.news_repository import SQLiteNewsRepository
from sector_pulse.storage.news_retrieval_repository import SQLiteNewsRetrievalRepository
from sector_pulse.storage.phase1b_repository import SQLitePhase1BRepository
from sector_pulse.storage.phase1b_runs_repository import SQLitePhase1BRunsRepository
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_agent_invocation_repository import (
    PostgresAgentInvocationRepository,
)
from sector_pulse.storage.postgres_draft_edit_repository import PostgresDraftEditRepository
from sector_pulse.storage.postgres_evidence_repository import PostgresEvidenceRepository
from sector_pulse.storage.postgres_governance_repository import PostgresGovernanceRepository
from sector_pulse.storage.postgres_market_snapshot_repository import (
    PostgresMarketSnapshotRepository,
)
from sector_pulse.storage.postgres_news_evidence_repository import PostgresNewsEvidenceRepository
from sector_pulse.storage.postgres_news_repository import PostgresNewsRepository
from sector_pulse.storage.postgres_news_retrieval_repository import PostgresNewsRetrievalRepository
from sector_pulse.storage.postgres_phase1b_repository import PostgresPhase1BRepository
from sector_pulse.storage.postgres_phase1b_runs_repository import PostgresPhase1BRunsRepository
from sector_pulse.storage.postgres_prompt_golden_repository import PostgresPromptGoldenRepository
from sector_pulse.storage.postgres_real_data_run_repository import PostgresRealDataRunRepository
from sector_pulse.storage.postgres_release_audit_repository import PostgresReleaseAuditRepository
from sector_pulse.storage.postgres_shadow_acceptance_repository import (
    PostgresShadowAcceptanceRepository,
)
from sector_pulse.storage.postgres_task_repository import PostgresTaskRepository
from sector_pulse.storage.prompt_golden_repository import SQLitePromptGoldenRepository
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.release_audit_repository import SQLiteReleaseAuditRepository
from sector_pulse.storage.shadow_acceptance_repository import SQLiteShadowAcceptanceRepository
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.storage.task_repository import SQLiteTaskRepository


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
    review_analytics: object | None = None
    task: object | None = None
    phase1b_runs: object | None = None
    phase1b: object | None = None
    invocations: object | None = None
    news_evidence: object | None = None
    draft_edit: object | None = None
    prompt_golden: object | None = None
    release_audit: object | None = None
    shadow: object | None = None
    governance: object | None = None


def build_sqlite_storage(database: SQLiteDatabase) -> RuntimeStorageBundle:
    return RuntimeStorageBundle(
        market_snapshots=SQLiteMarketSnapshotRepository(database),
        news=SQLiteNewsRepository(database),
        evidence=SQLiteEvidenceRepository(database),
        news_retrieval=SQLiteNewsRetrievalRepository(database),
        real_data_runs=SQLiteRealDataRunRepository(database),
        review_analytics=None,
        task=SQLiteTaskRepository(database), phase1b_runs=SQLitePhase1BRunsRepository(database),
        phase1b=SQLitePhase1BRepository(database), invocations=SQLiteAgentInvocationRepository(database),
        news_evidence=SQLiteNewsEvidenceRepository(database), draft_edit=SQLiteDraftEditRepository(database),
        prompt_golden=SQLitePromptGoldenRepository(database), release_audit=SQLiteReleaseAuditRepository(database),
        shadow=SQLiteShadowAcceptanceRepository(database), governance=SQLiteGovernanceRepository(database),
    )


def build_postgres_storage(database: PostgresDatabase) -> RuntimeStorageBundle:
    return RuntimeStorageBundle(
        market_snapshots=BlockingAsyncRepository(PostgresMarketSnapshotRepository(database)),
        news=BlockingAsyncRepository(PostgresNewsRepository(database)),
        evidence=BlockingAsyncRepository(PostgresEvidenceRepository(database)),
        news_retrieval=BlockingAsyncRepository(PostgresNewsRetrievalRepository(database)),
        real_data_runs=BlockingAsyncRepository(PostgresRealDataRunRepository(database)),
        review_analytics=BlockingAsyncRepository(PostgresReviewAnalyticsQueries(database)),
        task=BlockingAsyncRepository(PostgresTaskRepository(database)),
        phase1b_runs=BlockingAsyncRepository(PostgresPhase1BRunsRepository(database)),
        phase1b=BlockingAsyncRepository(PostgresPhase1BRepository(database)),
        invocations=BlockingAsyncRepository(PostgresAgentInvocationRepository(database)),
        news_evidence=BlockingAsyncRepository(PostgresNewsEvidenceRepository(database)),
        draft_edit=BlockingAsyncRepository(PostgresDraftEditRepository(database)),
        prompt_golden=BlockingAsyncRepository(PostgresPromptGoldenRepository(database)),
        release_audit=BlockingAsyncRepository(PostgresReleaseAuditRepository(database)),
        shadow=BlockingAsyncRepository(PostgresShadowAcceptanceRepository(database)), governance=BlockingAsyncRepository(PostgresGovernanceRepository(database)),
    )
