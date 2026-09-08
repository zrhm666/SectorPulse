# ruff: noqa: E501
from dataclasses import dataclass

from sector_pulse.storage.ports.evaluation import (
    PromptGoldenRepositoryPort,
    ShadowAcceptanceRepositoryPort,
)
from sector_pulse.storage.ports.market import (
    CandidateSelectionRepositoryPort,
    MarketSnapshotRepositoryPort,
)
from sector_pulse.storage.ports.news import (
    EvidenceRepositoryPort,
    NewsEvidenceRepositoryPort,
    NewsRepositoryPort,
    NewsRetrievalRepositoryPort,
)
from sector_pulse.storage.ports.operations import OperationsQueryPort
from sector_pulse.storage.ports.review import (
    DraftEditRepositoryPort,
    GovernanceRepositoryPort,
    ReleaseAuditRepositoryPort,
    ReviewAnalyticsPort,
)
from sector_pulse.storage.ports.runs import Phase1BRunsRepositoryPort, RealDataRunRepositoryPort
from sector_pulse.storage.ports.tasks import RuntimeTaskRepositoryPort
from sector_pulse.storage.ports.writing import AgentInvocationRepositoryPort, Phase1BRepositoryPort
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.evaluation.prompt_golden_repository import (
    PostgresPromptGoldenRepository,
)
from sector_pulse.storage.postgres.evaluation.shadow_acceptance_repository import (
    PostgresShadowAcceptanceRepository,
)
from sector_pulse.storage.postgres.market.candidate_selection_repository import (
    PostgresCandidateSelectionRepository,
)
from sector_pulse.storage.postgres.market.market_snapshot_repository import (
    PostgresMarketSnapshotRepository,
)
from sector_pulse.storage.postgres.news.evidence_repository import PostgresEvidenceRepository
from sector_pulse.storage.postgres.news.news_evidence_repository import (
    PostgresNewsEvidenceRepository,
)
from sector_pulse.storage.postgres.news.news_repository import PostgresNewsRepository
from sector_pulse.storage.postgres.news.news_retrieval_repository import (
    PostgresNewsRetrievalRepository,
)
from sector_pulse.storage.postgres.operations_query import PostgresOperationsQuery
from sector_pulse.storage.postgres.review.draft_edit_repository import PostgresDraftEditRepository
from sector_pulse.storage.postgres.review.governance_repository import PostgresGovernanceRepository
from sector_pulse.storage.postgres.review.release_audit_repository import (
    PostgresReleaseAuditRepository,
)
from sector_pulse.storage.postgres.review.review_analytics import PostgresReviewAnalyticsQueries
from sector_pulse.storage.postgres.runs.phase1b_runs_repository import PostgresPhase1BRunsRepository
from sector_pulse.storage.postgres.runs.real_data_run_repository import (
    PostgresRealDataRunRepository,
)
from sector_pulse.storage.postgres.runs.task_repository import PostgresTaskRepository
from sector_pulse.storage.postgres.writing.agent_invocation_repository import (
    PostgresAgentInvocationRepository,
)
from sector_pulse.storage.postgres.writing.phase1b_repository import PostgresPhase1BRepository
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.evaluation.prompt_golden_repository import (
    SQLitePromptGoldenRepository,
)
from sector_pulse.storage.sqlite.evaluation.shadow_acceptance_repository import (
    SQLiteShadowAcceptanceRepository,
)
from sector_pulse.storage.sqlite.market.candidate_selection_repository import (
    SQLiteCandidateSelectionRepository,
)
from sector_pulse.storage.sqlite.market.market_snapshot_repository import (
    SQLiteMarketSnapshotRepository,
)
from sector_pulse.storage.sqlite.news.evidence_repository import SQLiteEvidenceRepository
from sector_pulse.storage.sqlite.news.news_evidence_repository import SQLiteNewsEvidenceRepository
from sector_pulse.storage.sqlite.news.news_repository import SQLiteNewsRepository
from sector_pulse.storage.sqlite.news.news_retrieval_repository import SQLiteNewsRetrievalRepository
from sector_pulse.storage.sqlite.operations_query import SQLiteOperationsQuery
from sector_pulse.storage.sqlite.review.draft_edit_repository import SQLiteDraftEditRepository
from sector_pulse.storage.sqlite.review.governance_repository import SQLiteGovernanceRepository
from sector_pulse.storage.sqlite.review.release_audit_repository import SQLiteReleaseAuditRepository
from sector_pulse.storage.sqlite.review.review_analytics import ReviewAnalyticsQueries
from sector_pulse.storage.sqlite.runs.phase1b_runs_repository import SQLitePhase1BRunsRepository
from sector_pulse.storage.sqlite.runs.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite.runs.task_repository import SQLiteTaskRepository
from sector_pulse.storage.sqlite.writing.agent_invocation_repository import (
    SQLiteAgentInvocationRepository,
)
from sector_pulse.storage.sqlite.writing.phase1b_repository import SQLitePhase1BRepository


@dataclass(frozen=True)
class RuntimeStorageBundle:
    market_snapshots: MarketSnapshotRepositoryPort
    news: NewsRepositoryPort
    evidence: EvidenceRepositoryPort
    news_retrieval: NewsRetrievalRepositoryPort
    real_data_runs: RealDataRunRepositoryPort
    review_analytics: ReviewAnalyticsPort
    task: RuntimeTaskRepositoryPort
    phase1b_runs: Phase1BRunsRepositoryPort
    phase1b: Phase1BRepositoryPort
    invocations: AgentInvocationRepositoryPort
    news_evidence: NewsEvidenceRepositoryPort
    draft_edit: DraftEditRepositoryPort
    prompt_golden: PromptGoldenRepositoryPort
    release_audit: ReleaseAuditRepositoryPort
    shadow: ShadowAcceptanceRepositoryPort
    governance: GovernanceRepositoryPort
    operations: OperationsQueryPort
    candidate_selections: CandidateSelectionRepositoryPort


def build_sqlite_storage(database: SQLiteDatabase) -> RuntimeStorageBundle:
    return RuntimeStorageBundle(
        market_snapshots=SQLiteMarketSnapshotRepository(database),
        news=SQLiteNewsRepository(database),
        evidence=SQLiteEvidenceRepository(database),
        news_retrieval=SQLiteNewsRetrievalRepository(database),
        real_data_runs=SQLiteRealDataRunRepository(database),
        review_analytics=ReviewAnalyticsQueries(database),
        task=SQLiteTaskRepository(database), phase1b_runs=SQLitePhase1BRunsRepository(database),
        phase1b=SQLitePhase1BRepository(database), invocations=SQLiteAgentInvocationRepository(database),
        news_evidence=SQLiteNewsEvidenceRepository(database), draft_edit=SQLiteDraftEditRepository(database),
        prompt_golden=SQLitePromptGoldenRepository(database), release_audit=SQLiteReleaseAuditRepository(database),
        shadow=SQLiteShadowAcceptanceRepository(database), governance=SQLiteGovernanceRepository(database),
        operations=SQLiteOperationsQuery(database),
        candidate_selections=SQLiteCandidateSelectionRepository(database),
    )


def build_postgres_storage(database: PostgresDatabase) -> RuntimeStorageBundle:
    return RuntimeStorageBundle(
        market_snapshots=PostgresMarketSnapshotRepository(database),
        news=PostgresNewsRepository(database),
        evidence=PostgresEvidenceRepository(database),
        news_retrieval=PostgresNewsRetrievalRepository(database),
        real_data_runs=PostgresRealDataRunRepository(database),
        review_analytics=PostgresReviewAnalyticsQueries(database),
        task=PostgresTaskRepository(database),
        phase1b_runs=PostgresPhase1BRunsRepository(database),
        phase1b=PostgresPhase1BRepository(database),
        invocations=PostgresAgentInvocationRepository(database),
        news_evidence=PostgresNewsEvidenceRepository(database),
        draft_edit=PostgresDraftEditRepository(database),
        prompt_golden=PostgresPromptGoldenRepository(database),
        release_audit=PostgresReleaseAuditRepository(database),
        shadow=PostgresShadowAcceptanceRepository(database),
        governance=PostgresGovernanceRepository(database),
        operations=PostgresOperationsQuery(database),
        candidate_selections=PostgresCandidateSelectionRepository(database),
    )
