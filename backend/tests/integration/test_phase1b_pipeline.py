import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from sector_pulse.application.writing.phase1b_pipeline import (
    Phase1BRequest,
    run_phase1b_pipeline,
)
from sector_pulse.config.llm_config import LLMRoute, LLMRuntimeConfig
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.news.evidence import EvidenceLevel
from sector_pulse.domain.writing.article import ArticleSource, DraftStatus
from sector_pulse.domain.writing.attribution import AttributionContext, AttributionGateResult
from sector_pulse.infrastructure.llm.fixture_provider import FixtureLLMProvider
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.writing.agent_invocation_repository import (
    SQLiteAgentInvocationRepository,
)
from sector_pulse.storage.sqlite.writing.phase1b_repository import SQLitePhase1BRepository

RUN_ID = UUID("00000000-0000-0000-0000-000000000001")


def contexts() -> tuple[AttributionContext, ...]:
    return tuple(
        AttributionContext(
            run_id=RUN_ID,
            sector_id=f"industry-{index}",
            sector_kind=SectorKind.INDUSTRY,
            cutoff_at=datetime(2026, 8, 14, 2, tzinfo=UTC),
            market_facts={"pct_change": Decimal("3.2"), "breadth_ratio": Decimal("0.7")},
            event_ids=(),
            eligible_event_ids=(),
            background_event_ids=(),
            excluded_event_ids=(),
            source_grades={},
            counter_evidence=(),
        )
        for index in range(1, 9)
    )


def gate(context: AttributionContext) -> AttributionGateResult:
    return AttributionGateResult(
        run_id=RUN_ID,
        sector_id=context.sector_id,
        allowed_max_level=EvidenceLevel.NO_RELIABLE_EXPLANATION,
        reasons=("NO_ELIGIBLE_EVENT",),
        eligible_evidence_ids=(),
        excluded_evidence_ids=(),
        counter_evidence=(),
    )


def fixture_responses() -> dict[str, object]:
    responses: dict[str, object] = {}
    for context in contexts():
        responses[f"sector-analysis:{context.sector_id}"] = {
            "run_id": str(RUN_ID),
            "sector_id": context.sector_id,
            "sector_kind": "INDUSTRY",
            "allowed_max_level": "NO_RELIABLE_EXPLANATION",
            "attribution_level": "NO_RELIABLE_EXPLANATION",
            "confidence": "0",
            "conclusion": "暂无可靠解释，相关新闻仅作背景参考。",
            "supporting_evidence_ids": [],
            "counter_evidence": [],
            "uncertainties": ["没有合格新闻"],
            "background_event_ids": [],
            "claims": [],
            "forbidden_inferences": ["不得强行归因"],
        }
    selected = [context.sector_id for context in contexts()[:3]]
    responses["editorial-outline"] = {
        "outline_id": str(uuid4()),
        "run_id": str(RUN_ID),
        "sector_ids": selected,
        "order_reasons": {sector_id: "热度" for sector_id in selected},
        "title_directions": ["今日板块观察"],
        "thesis": "观察市场异动及其证据边界。",
        "section_character_budgets": {sector_id: 300 for sector_id in selected},
        "excluded_sector_reasons": {},
    }
    sections = [
        {
            "section_id": sector_id,
            "sector_id": sector_id,
            "heading": f"行业板块〔{sector_id}〕观察",
            "body": f"行业板块〔{sector_id}〕表现分化。" + "市场表现暂无可靠解释。" * 35,
            "claims": [],
            "source_ids": [],
            "character_count": 405,
        }
        for sector_id in selected
    ]
    responses["article-draft"] = {
        "draft_id": "00000000-0000-0000-0000-000000000002",
        "run_id": str(RUN_ID),
        "version": 1,
        "status": "UNREVIEWED",
        "titles": ["今日板块观察"],
        "introduction": "今天市场出现多处异动。",
        "sections": sections,
        "conclusion": "保持证据边界。",
        "risk_notice": "仅供信息交流，不构成投资建议。",
        "sources": [{"source_id": "source-1", "title": "公开来源"}],
        "character_count": 1200,
    }
    responses["review:1"] = {
        "review_id": "review-1",
        "draft_id": "00000000-0000-0000-0000-000000000002",
        "draft_version": 1,
        "decision": "REVISE",
        "issues": [
            {
                "issue_id": "issue-1",
                "severity": "WARNING",
                "code": "STYLE",
                "message": "调整首段",
                "section_id": selected[0],
                "claim_id": None,
                "suggested_fix": "精简",
            }
        ],
        "revision_round": 0,
    }
    responses["review:2"] = {
        "review_id": "review-2",
        "draft_id": "00000000-0000-0000-0000-000000000002",
        "draft_version": 2,
        "decision": "PASS",
        "issues": [],
        "revision_round": 1,
    }
    responses["revision:1"] = {
        "sections": [
            {
                "section_id": selected[0],
                "heading": f"行业板块〔{selected[0]}〕观察",
                "body": f"行业板块〔{selected[0]}〕表现分化，仍需更多证据。"
                + "市场表现暂无可靠解释。" * 35,
                "claims": [],
                "source_ids": [],
            }
        ],
    }
    return responses


def dependencies(tmp_path):
    database = SQLiteDatabase(tmp_path / "phase1b.db")
    return SimpleNamespace(
        llm=FixtureLLMProvider(fixture_responses()),
        prompts=PromptRegistry(__import__("pathlib").Path("config/prompts")),
        repository=SQLitePhase1BRepository(database),
        invocation_repository=SQLiteAgentInvocationRepository(database),
        config=LLMRuntimeConfig(
            version="test",
            budget_cny_per_run=Decimal("2"),
            max_attribution_concurrency=4,
            max_revision_rounds=2,
            routes={
                name: LLMRoute(provider="fixture", model="fixture")
                for name in ("attribution", "editorial", "writing", "review", "revision")
            },
        ),
    )


def test_phase1b_pipeline_produces_reviewable_draft(tmp_path) -> None:
    deps = dependencies(tmp_path)
    result = asyncio.run(
        run_phase1b_pipeline(
            deps,
            Phase1BRequest(
                run_id=RUN_ID,
                requested_at=datetime(2026, 8, 14, 3, tzinfo=UTC),
                contexts=contexts(),
                gates={context.sector_id: gate(context) for context in contexts()},
            ),
        )
    )
    assert len(result.analysis_cards) == 8
    assert result.draft is not None
    assert len(result.draft.sections) == 3
    assert result.draft.version == 2
    assert "仍需更多证据" in result.draft.sections[0].body
    assert "（已复核）" not in result.draft.sections[0].body
    assert result.draft.status is DraftStatus.READY_FOR_HUMAN_REVIEW
    assert result.review is not None
    assert result.review.decision.value == "PASS"
    assert result.total_cost_cny.amount <= Decimal("2.00")


def test_revision_missing_keeps_original_version(tmp_path) -> None:
    deps = dependencies(tmp_path)
    responses = fixture_responses()
    del responses["revision:1"]
    deps.llm = FixtureLLMProvider(responses)
    result = asyncio.run(
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
    assert result.status == "REVISE_REQUIRED"
    assert result.draft.version == 1
    assert result.draft.status is DraftStatus.REVISE_REQUIRED
    assert any(i.code == "REVISION_REQUEST_FAILED" for i in result.review.issues)


def test_wrong_version_review_cannot_approve_draft(tmp_path) -> None:
    deps = dependencies(tmp_path)
    responses = fixture_responses()
    responses["review:1"]["decision"] = "PASS"
    responses["review:1"]["issues"] = []
    responses["review:1"]["draft_version"] = 99
    deps.llm = FixtureLLMProvider(responses)
    result = asyncio.run(
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
    assert result.status == "UNREVIEWED"
    assert result.review is None


def test_model_pass_does_not_hide_missing_subject(tmp_path) -> None:
    deps = dependencies(tmp_path)
    responses = fixture_responses()
    responses["article-draft"]["sections"][0]["body"] = "该板块缺少主体。"
    responses["review:1"].update(decision="PASS", issues=[])
    del responses["revision:1"]
    deps.llm = FixtureLLMProvider(responses)
    result = asyncio.run(
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
    assert result.status == "REVISE_REQUIRED"
    assert any(i.code == "SECTOR_SUBJECT_MISSING" for i in result.review.issues)


def test_external_invocation_sink_does_not_disable_budget(tmp_path) -> None:
    from sector_pulse.domain.llm import MoneyCny

    class CostedFixture(FixtureLLMProvider):
        async def generate_structured(self, request):
            result = await super().generate_structured(request)
            return result.model_copy(update={"estimated_cost_cny": MoneyCny(amount=Decimal("1"))})

    deps = dependencies(tmp_path)
    deps.llm = CostedFixture(fixture_responses())
    recorded = []
    result = asyncio.run(
        run_phase1b_pipeline(
            deps,
            Phase1BRequest(
                run_id=RUN_ID,
                requested_at=datetime(2026, 8, 14, 3, tzinfo=UTC),
                contexts=contexts(),
                gates={c.sector_id: gate(c) for c in contexts()},
            ),
            invocation_sink=recorded.append,
        )
    )
    assert result.status == "BUDGET_EXCEEDED"
    assert result.total_cost_cny.amount == Decimal("8")
    assert {i.stage for i in recorded} == {"attribution"}


def test_budget_exhausted_after_revision_preserves_new_unreviewed_version(tmp_path) -> None:
    from sector_pulse.domain.llm import MoneyCny

    class CostedRevision(FixtureLLMProvider):
        async def generate_structured(self, request):
            result = await super().generate_structured(request)
            if request.agent_name == "revision":
                return result.model_copy(
                    update={"estimated_cost_cny": MoneyCny(amount=Decimal("2"))}
                )
            return result

    deps = dependencies(tmp_path)
    deps.llm = CostedRevision(fixture_responses())
    result = asyncio.run(
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
    assert result.status == "BUDGET_EXCEEDED"
    assert result.draft.version == 2
    assert result.draft.status == DraftStatus.UNREVIEWED
    assert result.review is None


def test_writer_cannot_bind_draft_to_unknown_sector(tmp_path) -> None:
    deps = dependencies(tmp_path)
    responses = fixture_responses()
    responses["article-draft"]["sections"][0]["sector_id"] = "not-in-outline"
    deps.llm = FixtureLLMProvider(responses)
    result = asyncio.run(
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
    assert result.status == "DRAFT_GENERATION_FAILED"
    assert result.draft is None


def test_shipped_fixture_has_identifiable_reviewable_sections(tmp_path) -> None:
    from sector_pulse.infrastructure.llm.fixture_resources import (
        load_default_fixture_input,
        load_default_fixture_responses,
    )

    deps = dependencies(tmp_path)
    deps.llm = FixtureLLMProvider(load_default_fixture_responses())
    request = Phase1BRequest.model_validate({"run_id": str(RUN_ID), **load_default_fixture_input()})
    result = asyncio.run(run_phase1b_pipeline(deps, request))
    assert result.status == "READY_FOR_HUMAN_REVIEW"
    assert result.draft.character_count == (
        len(result.draft.introduction)
        + len(result.draft.conclusion)
        + sum(len(s.body) for s in result.draft.sections)
    )


def test_revision_is_limited_to_two_rounds(tmp_path) -> None:
    deps = dependencies(tmp_path)
    responses = fixture_responses()
    responses["review:2"].update(decision="REVISE", issues=responses["review:1"]["issues"])
    responses["revision:2"] = {
        "sections": [
            {
                **responses["revision:1"]["sections"][0],
                "body": responses["revision:1"]["sections"][0]["body"] + "需持续观察。",
            }
        ]
    }
    responses["review:3"] = {**responses["review:2"], "review_id": "review-3", "draft_version": 3}
    deps.llm = FixtureLLMProvider(responses)
    result = asyncio.run(
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
    assert result.status == "REVISE_REQUIRED"
    assert result.draft.version == 3
    assert result.review.revision_round == 2
    invocations = deps.invocation_repository.list_for_run(RUN_ID)
    assert sum(i.stage == "revision" for i in invocations) == 2


def test_failed_review_of_revision_cannot_reuse_old_review(tmp_path) -> None:
    deps = dependencies(tmp_path)
    responses = fixture_responses()
    del responses["review:2"]
    deps.llm = FixtureLLMProvider(responses)
    result = asyncio.run(
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
    assert result.status == "UNREVIEWED"
    assert result.draft.version == 2
    assert result.review is None


def test_phase1b_pipeline_hydrates_verified_sources_when_writer_omits_them(tmp_path) -> None:
    deps = dependencies(tmp_path)
    responses = fixture_responses()
    responses["article-draft"]["sources"] = []
    responses["article-draft"]["status"] = "READY_FOR_HUMAN_REVIEW"
    deps.llm = FixtureLLMProvider(responses)

    result = asyncio.run(
        run_phase1b_pipeline(
            deps,
            Phase1BRequest(
                run_id=RUN_ID,
                requested_at=datetime(2026, 8, 14, 3, tzinfo=UTC),
                contexts=contexts(),
                gates={context.sector_id: gate(context) for context in contexts()},
                verified_sources_by_sector={
                    context.sector_id: (
                        ArticleSource(
                            source_id="event-1",
                            title="已持久化新闻来源",
                            publisher="测试媒体",
                            citation_url="https://example.test/news/1",
                        ),
                    )
                    for context in contexts()[:3]
                },
            ),
        )
    )

    assert result.status == "READY_FOR_HUMAN_REVIEW"
    assert result.draft is not None
    assert result.draft.sources[0].source_id == "event-1"


def test_phase1b_pipeline_rejects_source_less_draft_before_review(tmp_path) -> None:
    deps = dependencies(tmp_path)
    responses = fixture_responses()
    responses["article-draft"]["sources"] = [
        {"source_id": "model-invented", "title": "未经验证的来源"}
    ]
    deps.llm = FixtureLLMProvider(responses)

    result = asyncio.run(
        run_phase1b_pipeline(
            deps,
            Phase1BRequest(
                run_id=RUN_ID,
                requested_at=datetime(2026, 8, 14, 3, tzinfo=UTC),
                contexts=contexts(),
                gates={context.sector_id: gate(context) for context in contexts()},
                verified_sources_by_sector={},
            ),
        )
    )

    assert result.status == "DRAFT_GENERATION_FAILED"
    assert result.review is None
