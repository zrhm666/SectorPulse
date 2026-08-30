import inspect

import pytest
from sector_pulse.storage.postgres_candidate_selection_repository import (
    PostgresCandidateSelectionRepository,
)
from sector_pulse.storage.postgres_evidence_repository import PostgresEvidenceRepository
from sector_pulse.storage.postgres_market_snapshot_repository import (
    PostgresMarketSnapshotRepository,
)
from sector_pulse.storage.postgres_news_repository import PostgresNewsRepository
from sector_pulse.storage.postgres_news_retrieval_repository import (
    PostgresNewsRetrievalRepository,
)
from sector_pulse.storage.postgres_real_data_run_repository import (
    PostgresRealDataRunRepository,
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
        (PostgresMarketSnapshotRepository, ("save", "get")),
        (PostgresNewsRepository, ("save", "get_event", "get_events", "get_documents")),
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
    ],
)
def test_postgres_data_repository_methods_are_synchronous(
    repository: type[object], methods: tuple[str, ...]
) -> None:
    for method in methods:
        assert not inspect.iscoroutinefunction(getattr(repository, method))
