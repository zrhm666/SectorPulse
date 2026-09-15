import inspect

import pytest
from sector_pulse.storage.postgres.market.candidate_batch_repository import (
    PostgresCandidateBatchRepository,
)
from sector_pulse.storage.postgres.market.candidate_proposal_repository import (
    PostgresCandidateProposalRepository,
)
from sector_pulse.storage.postgres.market.candidate_selection_repository import (
    PostgresCandidateSelectionRepository,
)
from sector_pulse.storage.postgres.market.market_snapshot_repository import (
    PostgresMarketSnapshotRepository,
)
from sector_pulse.storage.postgres.market.orchestration_selection_repository import (
    PostgresOrchestrationSelectionRepository,
)
from sector_pulse.storage.postgres.news.evidence_repository import PostgresEvidenceRepository
from sector_pulse.storage.postgres.news.news_batch_repository import PostgresNewsBatchRepository
from sector_pulse.storage.postgres.news.news_detail_snapshot_repository import (
    PostgresNewsDetailSnapshotRepository,
)
from sector_pulse.storage.postgres.news.news_repository import PostgresNewsRepository
from sector_pulse.storage.postgres.news.news_retrieval_repository import (
    PostgresNewsRetrievalRepository,
)
from sector_pulse.storage.postgres.news.research_search_repository import (
    PostgresResearchSearchRepository,
)
from sector_pulse.storage.postgres.runs.real_data_run_repository import (
    PostgresRealDataRunRepository,
)
from sector_pulse.storage.postgres.writing.editorial_repository import (
    PostgresDraftRulesRepository,
    PostgresEditorialDraftRepository,
    PostgresEditorialOutlineRepository,
    PostgresIndependentReviewRepository,
)
from sector_pulse.storage.postgres.writing.evidence_inspection_repository import (
    PostgresEvidenceInspectionRepository,
)
from sector_pulse.storage.postgres.writing.sector_analysis_repository import (
    PostgresSectorAnalysisRepository,
)


@pytest.mark.parametrize(
    ("repository", "methods"),
    [
        (
            PostgresRealDataRunRepository,
            (
                "insert",
                "get_run",
                "list_runs",
                "update_status",
                "save_candidates",
                "get_candidates",
                "mark_interrupted",
            ),
        ),
        (PostgresMarketSnapshotRepository, ("save", "get", "get_run")),
        (PostgresCandidateBatchRepository, ("get",)),
        (PostgresCandidateProposalRepository, ("get",)),
        (PostgresNewsRepository, ("save", "get_event", "get_events", "get_documents")),
        (PostgresNewsBatchRepository, ("get",)),
        (PostgresResearchSearchRepository, ("get",)),
        (PostgresNewsDetailSnapshotRepository, ("get",)),
        (PostgresEvidenceInspectionRepository, ("get",)),
        (PostgresSectorAnalysisRepository, ("get",)),
        (PostgresEditorialOutlineRepository, ("get",)),
        (PostgresEditorialDraftRepository, ("get", "get_version", "latest_version")),
        (PostgresDraftRulesRepository, ("get",)),
        (PostgresIndependentReviewRepository, ("get",)),
        (
            PostgresNewsRetrievalRepository,
            (
                "save_audit",
                "list_links",
                "list_query_documents",
                "list_queries",
                "list_source_metrics",
            ),
        ),
        (PostgresEvidenceRepository, ("save", "list_for_run")),
        (
            PostgresCandidateSelectionRepository,
            ("append", "latest", "list_versions"),
        ),
        (PostgresOrchestrationSelectionRepository, ("latest", "list_versions")),
    ],
)
def test_postgres_data_repository_methods_are_synchronous(
    repository: type[object], methods: tuple[str, ...]
) -> None:
    for method in methods:
        assert not inspect.iscoroutinefunction(getattr(repository, method))
