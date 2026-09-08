# backend/tests/unit/web/test_run_service.py
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sector_pulse.application.writing.phase1b_pipeline import Phase1BRequest
from sector_pulse.config.llm_config import LLMRuntimeConfig
from sector_pulse.domain.news import NewsDocument, NewsEvent, SourceGrade
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.storage.agent_invocation_repository import SQLiteAgentInvocationRepository
from sector_pulse.storage.news_evidence_repository import SQLiteNewsEvidenceRepository
from sector_pulse.storage.news_repository import SQLiteNewsRepository
from sector_pulse.storage.phase1b_repository import SQLitePhase1BRepository
from sector_pulse.storage.phase1b_runs_repository import SQLitePhase1BRunsRepository
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.web.progress_bus import ProgressBus
from sector_pulse.web.run_service import RunService

from backend.tests.integration.test_phase1b_pipeline import contexts, fixture_responses, gate


def _service(tmp_path) -> RunService:
    db = SQLiteDatabase(tmp_path / "test.db")
    config = LLMRuntimeConfig(
        version="test",
        budget_cny_per_run=2,
        max_attribution_concurrency=4,
        max_revision_rounds=2,
        routes={},
    )
    return RunService(
        runs_repo=SQLitePhase1BRunsRepository(db),
        phase1b_repo=SQLitePhase1BRepository(db),
        invocation_repo=SQLiteAgentInvocationRepository(db),
        news_evidence=SQLiteNewsEvidenceRepository(db),
        prompts=PromptRegistry(Path("config/prompts")),
        config=config,
        bus=ProgressBus(),
        fixture_responses=fixture_responses(),
        llm_factory={},
    )


def _input_json() -> dict:
    return {
        "requested_at": datetime(2026, 8, 14, 12, tzinfo=UTC).isoformat(),
        "contexts": [c.model_dump(mode="json") for c in contexts()],
        "gates": {c.sector_id: gate(c).model_dump(mode="json") for c in contexts()},
    }


async def test_content_retry_persists_lineage_and_preserves_original(tmp_path):
    service = _service(tmp_path)
    original = service.create_run(_input_json(), "fixture")
    await service.wait(original)
    before = service._runs_repo.get_run(original)
    retry = service.retry_run(original)
    await service.wait(retry)
    stored = service._runs_repo.get_run(retry)
    assert retry != original
    assert stored.retry_of_run_id == original
    assert stored.input_json == before.input_json
    assert service._runs_repo.get_run(original) == before
    assert service.get_run(retry).retry_of_run_id == original


async def test_create_run_lifecycle(tmp_path) -> None:
    svc = _service(tmp_path)
    run_id = svc.create_run(_input_json(), "fixture")
    detail = svc.get_run(run_id)
    assert detail is not None
    assert detail.status == "RUNNING"
    assert detail.retryable is False
    # 后台任务在 asyncio 事件循环里运行；轮询直到状态离开 RUNNING（最多 5s）。
    for _ in range(50):
        if svc.get_run(run_id).status != "RUNNING":
            break
        await asyncio.sleep(0.1)
    detail = svc.get_run(run_id)
    assert detail is not None
    assert detail.status == "READY_FOR_HUMAN_REVIEW"
    assert detail.retryable is True
    assert detail.sector_count == 8
    # 给后台任务的 finally 收尾（保存 invocations / 关闭 bus）留出时间。
    await asyncio.sleep(0.2)

    # run_id 一致性：全部落库产物都应归属本次创建的 run_id，而不是 fixture 的 RUN_ID。
    repo = svc._phase1b_repo
    cards = repo.get_cards(run_id)
    assert len(cards) == 8
    assert all(card.run_id == run_id for card in cards)
    # 证明不是 fallback 占位卡片：fallback 的 uncertainties 是异常类型名 "AgentOutputViolation"，
    # 而 fixture 卡片是 "没有合格新闻"。fixture 卡片 attribution_level 全为
    # NO_RELIABLE_EXPLANATION 且无 supporting_evidence_ids，无法用级别/证据区分。
    assert all(
        "AgentOutputViolation" not in uncertainty
        for card in cards
        for uncertainty in card.uncertainties
    )
    assert any(card.uncertainties == ("没有合格新闻",) for card in cards)
    drafts = repo.get_drafts(run_id)
    assert len(drafts) >= 2
    review = repo.get_review(run_id)
    assert review is not None
    assert review.decision.value == "PASS"


async def test_cancelled_content_run_is_persisted(tmp_path) -> None:
    service = _service(tmp_path)
    run_id = service.create_run(_input_json(), "fixture")

    assert service.cancel_run(run_id)
    await service.wait(run_id)

    detail = service.get_run(run_id)
    assert detail is not None
    assert detail.status == "CANCELLED"


async def test_consecutive_fixture_runs_receive_distinct_draft_ids(tmp_path) -> None:
    svc = _service(tmp_path)
    completed = []
    for _ in range(2):
        run_id = svc.create_run(_input_json(), "fixture")
        for _ in range(50):
            detail = svc.get_run(run_id)
            if detail is not None and detail.status != "RUNNING":
                break
            await asyncio.sleep(0.1)
        detail = svc.get_run(run_id)
        assert detail is not None
        assert detail.status == "READY_FOR_HUMAN_REVIEW"
        assert detail.draft_id is not None
        completed.append(detail)

    assert completed[0].draft_id != completed[1].draft_id


async def test_create_run_uses_persisted_news_as_verified_draft_sources(tmp_path) -> None:
    svc = _service(tmp_path)
    now = datetime(2026, 8, 14, 2, tzinfo=UTC)
    SQLiteNewsRepository(svc._news_evidence._database).save(
        (
            NewsDocument(
                document_id="doc-1",
                source_id="test-news",
                canonical_locator="https://example.test/news/1",
                citation_url="https://example.test/news/1",
                title="已持久化新闻",
                publisher="测试媒体",
                published_at=now,
                collected_at=now,
                content_hash="hash-1",
                source_grade=SourceGrade.REPUTABLE_MEDIA,
            ),
        ),
        (
            NewsEvent(
                event_id="event-1",
                canonical_title="已持久化新闻事件",
                first_published_at=now,
                document_ids=("doc-1",),
                deduplication_reason="test",
            ),
        ),
    )
    input_json = _input_json()
    for context in input_json["contexts"]:
        context["event_ids"] = ["event-1"]
        context["eligible_event_ids"] = ["event-1"]

    request = Phase1BRequest.model_validate({"run_id": str(uuid4()), **input_json})
    sources_by_sector = svc._load_verified_sources(request)

    assert sources_by_sector
    source = sources_by_sector[next(iter(sources_by_sector))][0]
    assert source.source_id == "event-1"
    assert source.citation_url == "https://example.test/news/1"
