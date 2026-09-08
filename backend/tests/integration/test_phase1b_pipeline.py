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
            "heading": f"{sector_id}观察",
            "body": "市场表现暂无可靠解释。" * 45,
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
    assert result.draft.status is DraftStatus.READY_FOR_HUMAN_REVIEW
    assert result.review is not None
    assert result.review.decision.value == "PASS"
    assert result.total_cost_cny.amount <= Decimal("2.00")


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
