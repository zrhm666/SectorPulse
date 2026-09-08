import asyncio
from datetime import UTC, datetime

from sector_pulse.application.writing.phase1b_pipeline import Phase1BRequest, run_phase1b_pipeline

from backend.tests.integration.test_phase1b_pipeline import (
    RUN_ID,
    contexts,
    dependencies,
    gate,
)


def test_query_methods_after_run(tmp_path) -> None:
    deps = dependencies(tmp_path)
    asyncio.run(
        run_phase1b_pipeline(
            deps,
            Phase1BRequest(
                run_id=RUN_ID,
                requested_at=datetime(2026, 8, 14, 3, tzinfo=UTC),
                contexts=contexts(),
                gates={c.sector_id: gate(c) for c in contexts()},
            ),
        )
    )
    repo = deps.repository
    assert len(repo.get_contexts(RUN_ID)) == 8
    assert len(repo.get_gates(RUN_ID)) == 8
    assert len(repo.get_cards(RUN_ID)) == 8
    assert repo.get_outline(RUN_ID) is not None
    assert len(repo.get_drafts(RUN_ID)) >= 2
    assert repo.get_review(RUN_ID) is not None
