import asyncio
from datetime import UTC, datetime

from sector_pulse.application.phase1b_pipeline import Phase1BRequest, run_phase1b_pipeline
from sector_pulse.infrastructure.llm.fixture_provider import FixtureLLMProvider

from backend.tests.integration.test_phase1b_pipeline import (
    RUN_ID,
    contexts,
    dependencies,
    fixture_responses,
    gate,
)


class ListSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, stage: str, detail: dict) -> None:
        self.events.append((stage, detail))


def test_pipeline_emits_progress_events_in_order(tmp_path) -> None:
    sink = ListSink()
    deps = dependencies(tmp_path)
    result = asyncio.run(
        run_phase1b_pipeline(
            deps,
            Phase1BRequest(
                run_id=RUN_ID,
                requested_at=datetime(2026, 8, 14, 3, tzinfo=UTC),
                contexts=contexts(),
                gates={c.sector_id: gate(c) for c in contexts()},
            ),
            progress_sink=sink,
        )
    )
    assert result.status == "READY_FOR_HUMAN_REVIEW"
    stages = [s for s, _ in sink.events]
    assert stages[0] == "phase1b.start"
    assert stages[1] == "attribution.start"
    assert "attribution.progress" in stages
    assert "attribution.done" in stages
    assert "editorial.done" in stages
    assert "writing.done" in stages
    assert "review.done" in stages


def test_pipeline_records_invocations(tmp_path) -> None:
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
    invocations = deps.invocation_repository.list_for_run(RUN_ID)
    stages = {inv.stage for inv in invocations}
    assert {"attribution", "editorial", "writing", "review"} <= stages


def test_pipeline_emits_fallback_and_failure_events_for_invalid_draft(tmp_path) -> None:
    sink = ListSink()
    deps = dependencies(tmp_path)
    responses = fixture_responses()
    responses["editorial-outline"] = {}
    responses["article-draft"] = {}
    deps.llm = FixtureLLMProvider(responses)

    result = asyncio.run(
        run_phase1b_pipeline(
            deps,
            Phase1BRequest(
                run_id=RUN_ID,
                requested_at=datetime(2026, 8, 14, 3, tzinfo=UTC),
                contexts=contexts(),
                gates={context.sector_id: gate(context) for context in contexts()},
            ),
            progress_sink=sink,
        )
    )

    stages = [stage for stage, _ in sink.events]
    assert "editorial.fallback" in stages
    assert "writing.failed" in stages
    assert "writing.done" not in stages
    assert result.status == "DRAFT_GENERATION_FAILED"
