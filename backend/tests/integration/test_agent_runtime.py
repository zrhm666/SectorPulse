from sector_pulse.application.writing.agent_runtime import AgentRuntime
from sector_pulse.domain.writing.agent_execution import AgentLimits
from sector_pulse.infrastructure.news.fixture_agent_news import FixtureAgentNewsSearch
from sector_pulse.infrastructure.news.news_detail_reader import PublicNewsDetailReader
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.news.news_repository import SQLiteNewsRepository
from sector_pulse.storage.sqlite.writing.agent_execution_repository import (
    SQLiteAgentExecutionRepository,
)

from backend.tests.unit.web.services.test_run_service import _input_json, _service


async def test_same_input_modes_keep_drafts_isolated_and_require_human_review(tmp_path):
    # Detects accidental workflow fallback, shared draft identities, or auto-approval.
    service = _service(tmp_path)
    db = SQLiteDatabase(tmp_path / "test.db")
    trace = SQLiteAgentExecutionRepository(db)
    service._agent_trace = trace
    service._agent_runtime_factory = lambda provider: AgentRuntime(
        SQLiteNewsRepository(db),
        trace,
        FixtureAgentNewsSearch(),
        PublicNewsDetailReader(),
        AgentLimits(),
    )
    input_data = _input_json()
    runs = {}
    for mode in ("workflow", "agent"):
        run_id = service.create_run({**input_data, "attribution_mode": mode}, "fixture")
        await service.wait(run_id)
        runs[mode] = run_id
        summary = service.get_run(run_id)
        assert summary.status == "READY_FOR_HUMAN_REVIEW"
        assert summary.attribution_mode == mode
        assert summary.draft_id is not None
        saved = service._runs_repo.get_run(run_id).input_json
        assert saved["contexts"] == input_data["contexts"]
        assert saved["gates"] == input_data["gates"]
    assert service.get_run(runs["workflow"]).draft_id != service.get_run(runs["agent"]).draft_id
    assert trace.list_for_run(runs["workflow"]) == []
    assert any(step["event"]["type"] == "tool_result" for step in trace.list_for_run(runs["agent"]))
    drafts = [service._phase1b_repo.get_drafts(run_id)[0] for run_id in runs.values()]
    assert [draft.version for draft in drafts] == [1, 1]
    assert [section.sector_id for section in drafts[0].sections] == [
        section.sector_id for section in drafts[1].sections
    ]


async def test_storage_failure_cancels_other_sector_models(tmp_path):
    import asyncio

    import pytest
    from sector_pulse.application.writing.progress import NoopProgressSink

    from backend.tests.integration.test_phase1b_pipeline import contexts, gate

    db = SQLiteDatabase(tmp_path / "cancel.db")
    db.initialize()
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class Trace:
        def save(self, context, step, event):
            if context.sector_id == "industry-2":
                raise RuntimeError("storage unavailable")

    class Model:
        async def generate_structured(self, request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    runtime = AgentRuntime(
        SQLiteNewsRepository(db),
        Trace(),
        FixtureAgentNewsSearch(),
        PublicNewsDetailReader(),
        AgentLimits(),
    )
    with pytest.raises((RuntimeError, ExceptionGroup)):
        await runtime.run(
            contexts()[:2],
            {c.sector_id: gate(c) for c in contexts()[:2]},
            Model(),
            "test",
            lambda item: None,
            NoopProgressSink(),
            {},
        )
    assert entered.is_set()
    assert cancelled.is_set(), "failed runs must not leave models consuming quota in background"


async def test_new_search_evidence_is_saved_as_background_and_forwarded_to_sources(tmp_path):
    from datetime import UTC, datetime

    from sector_pulse.application.writing.progress import NoopProgressSink
    from sector_pulse.domain.llm import LLMResult, LLMStatus, MoneyCny, TokenUsage
    from sector_pulse.domain.provider import DataStatus, ProviderResult
    from sector_pulse.domain.writing.agent_execution import AgentDecision

    from backend.tests.integration.test_phase1b_pipeline import contexts, fixture_responses, gate
    from backend.tests.unit.application.writing.test_agent_tools import document

    db = SQLiteDatabase(tmp_path / "evidence.db")
    db.initialize()
    news = SQLiteNewsRepository(db)
    trace = SQLiteAgentExecutionRepository(db)
    context = contexts()[0].model_copy(update={"sector_name": "文化传媒"})

    class Search(FixtureAgentNewsSearch):
        async def search(self, query, start_at, cutoff):
            return ProviderResult(
                status=DataStatus.SUCCESS,
                provider_id="test",
                capability="news.keyword.search",
                collected_at=datetime.now(UTC),
                data=(document(), document(document_id="unrelated", title="电力新闻")),
            )

    class Model:
        async def generate_structured(self, request):
            if not request.user_payload["observations"]:
                action = {"action": "search_news", "query": "政策"}
            else:
                updated = request.user_payload["context"]
                assert updated["eligible_event_ids"] == []
                assert len(updated["background_event_ids"]) == 1
                action = {
                    "action": "finish",
                    "card": {
                        **fixture_responses()["sector-analysis:industry-1"],
                        "background_event_ids": updated["background_event_ids"],
                    },
                }
            return LLMResult(
                status=LLMStatus.SUCCESS,
                data=AgentDecision.model_validate({"next_action": action}),
                usage=TokenUsage(),
                estimated_cost_cny=MoneyCny(amount="0"),
            )

    sources = {}
    results, updated = await AgentRuntime(
        news, trace, Search(), PublicNewsDetailReader(), AgentLimits()
    ).run(
        (context,),
        {context.sector_id: gate(context)},
        Model(),
        "test",
        lambda item: None,
        NoopProgressSink(),
        sources,
    )
    assert results[0].error_code is None
    assert news.get_documents(("doc-1", "unrelated")).keys() == {"doc-1"}
    assert sources[context.sector_id][0].source_id == updated[0].background_event_ids[0]
    assert sources[context.sector_id][0].title == "文化传媒新闻"


async def test_agent_mode_produces_draft_and_durable_trace_without_network(tmp_path):
    service = _service(tmp_path)
    db = SQLiteDatabase(tmp_path / "test.db")
    trace = SQLiteAgentExecutionRepository(db)
    service._agent_trace = trace
    service._agent_runtime_factory = lambda provider: AgentRuntime(
        SQLiteNewsRepository(db),
        trace,
        FixtureAgentNewsSearch(),
        PublicNewsDetailReader(),
        AgentLimits(),
    )
    run_id = service.create_run({**_input_json(), "attribution_mode": "agent"}, "fixture")
    await service.wait(run_id)
    summary = service.get_run(run_id)
    assert summary.status == "READY_FOR_HUMAN_REVIEW"
    assert summary.attribution_mode == "agent"
    restored = SQLiteAgentExecutionRepository(SQLiteDatabase(tmp_path / "test.db"))
    steps = restored.list_for_run(run_id)
    assert any(s["event"]["type"] == "finished" for s in steps)
    assert {
        s["event"]["action"]["action"] for s in steps if s["event"]["type"] == "tool_started"
    } == {"inspect_market", "search_news"}
    retry = service.retry_run(run_id)
    await service.wait(retry)
    assert service.get_run(retry).attribution_mode == "agent"
    assert restored.list_for_run(run_id) == steps
    assert restored.list_for_run(retry)
    service._config = service._config.model_copy(update={"max_agent_calls": 1})
    limited = service.retry_run(run_id)
    await service.wait(limited)
    assert service.get_run(limited).status == "BUDGET_EXCEEDED"
