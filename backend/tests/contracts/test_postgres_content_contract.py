import inspect

import pytest
from sector_pulse.storage.postgres.agent_invocation_repository import (
    PostgresAgentInvocationRepository,
)
from sector_pulse.storage.postgres.draft_edit_repository import (
    PostgresDraftEditRepository,
)
from sector_pulse.storage.postgres.governance_repository import (
    PostgresGovernanceRepository,
)
from sector_pulse.storage.postgres.news_evidence_repository import (
    PostgresNewsEvidenceRepository,
)
from sector_pulse.storage.postgres.phase1b_repository import PostgresPhase1BRepository
from sector_pulse.storage.postgres.phase1b_runs_repository import (
    PostgresPhase1BRunsRepository,
)
from sector_pulse.storage.postgres.prompt_golden_repository import (
    PostgresPromptGoldenRepository,
)
from sector_pulse.storage.postgres.release_audit_repository import (
    PostgresReleaseAuditRepository,
)
from sector_pulse.storage.postgres.review_analytics import (
    PostgresReviewAnalyticsQueries,
)
from sector_pulse.storage.postgres.shadow_acceptance_repository import (
    PostgresShadowAcceptanceRepository,
)


@pytest.mark.parametrize(
    ("repository", "methods"),
    [
        (
            PostgresPhase1BRepository,
            (
                "save_contexts",
                "save_gate_results",
                "save_cards",
                "save_outline",
                "save_draft",
                "save_review",
                "get_contexts",
                "get_gates",
                "get_cards",
                "get_outline",
                "get_drafts",
                "get_review",
            ),
        ),
        (PostgresPhase1BRunsRepository,
         ("insert", "get_run", "update_status", "list_runs", "mark_interrupted")),
        (PostgresAgentInvocationRepository, ("save", "list_for_run")),
        (PostgresNewsEvidenceRepository, ("get_events",)),
        (
            PostgresDraftEditRepository,
            ("save_draft", "get_version", "latest_version", "latest_for_run", "apply_patch"),
        ),
        (
            PostgresGovernanceRepository,
            (
                "save_evidence_decision",
                "list_evidence_decisions",
                "save_preference_candidate",
                "adopt_preference",
            ),
        ),
        (
            PostgresReleaseAuditRepository,
            ("approve", "approval", "audit", "revoke", "record_event", "record_export"),
        ),
        (PostgresPromptGoldenRepository, ("save", "list")),
        (
            PostgresShadowAcceptanceRepository,
            ("save_run", "get", "list_runs", "update_run", "save_recovery", "save_compliance"),
        ),
        (PostgresReviewAnalyticsQueries, ("for_run", "summary")),
    ],
)
def test_postgres_content_repository_methods_are_synchronous(
    repository: type[object], methods: tuple[str, ...]
) -> None:
    for method in methods:
        assert not inspect.iscoroutinefunction(getattr(repository, method))
