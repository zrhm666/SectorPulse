import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest


@pytest.mark.asyncio
async def test_t07_reads_only_known_document_and_replays_without_provider(tmp_path):
    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.research_context import (
        BoundSectorResearchContext,
    )
    from sector_pulse.application.orchestration.research_news_tools import (
        ReadBoundNewsDetailService,
        ResearchSearchPersistence,
    )
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
    from sector_pulse.domain.market.market import SectorKind
    from sector_pulse.domain.news.news import NewsDocument, SourceGrade
    from sector_pulse.domain.news.news_detail import NewsDetail
    from sector_pulse.domain.news.research import ResearchSearchBatch, ResearchSearchStatus
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.infrastructure.agents.research_tools import ReadNewsDetailTool
    from sector_pulse.infrastructure.agents.tool_adapter import BudgetedTool
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.news.news_detail_snapshot_repository import (
        SQLiteNewsDetailSnapshotRepository,
    )
    from sector_pulse.storage.sqlite.news.news_repository import SQLiteNewsRepository
    from sector_pulse.storage.sqlite.news.research_search_repository import (
        SQLiteResearchSearchRepository,
    )
    from sector_pulse.storage.sqlite.orchestration.repository import (
        SQLiteOrchestrationRepository,
    )

    now = datetime(2026, 9, 14, 3, 0, tzinfo=UTC)
    run_id, root_id, task_id = uuid4(), uuid4(), uuid4()
    root = TaskRecord(task_id=root_id, role="A0", scope="run")
    task = TaskRecord(
        task_id=task_id,
        parent_id=root_id,
        role="A2",
        scope="sector:INDUSTRY:sector-1",
        status=TaskStatus.RUNNING,
        worker_id="research-worker",
        lease_expires_at=now + timedelta(minutes=5),
        selection_version=1,
    )
    database = SQLiteDatabase(tmp_path / "news-detail.db")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO analysis_runs (run_id, mode, requested_at, run_cutoff_at, "
            "cutoff_locked_at) VALUES (?, 'LIVE', ?, ?, ?)",
            (str(run_id), now.isoformat(), now.isoformat(), now.isoformat()),
        )
    orchestration = SQLiteOrchestrationRepository(database)
    orchestration.save(
        RunSnapshot(
            run_id=run_id,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            tasks=(root, task),
        ),
        -1,
        "detail.created",
    )
    document = NewsDocument(
        document_id="known-doc",
        source_id="fixture",
        canonical_locator="urn:fixture:known",
        citation_url="https://www.cls.cn/detail/1",
        title="文化传媒事件",
        publisher="测试来源",
        summary="摘要",
        published_at=now - timedelta(hours=1),
        source_observed_at=now - timedelta(hours=1),
        collected_at=now,
        content_hash="document-hash",
        source_grade=SourceGrade.PRIMARY,
    )
    failure_document = document.model_copy(
        update={
            "document_id": "failure-doc",
            "canonical_locator": "urn:fixture:failure",
            "content_hash": "failure-document-hash",
        }
    )
    oversized_document = document.model_copy(
        update={
            "document_id": "oversized-doc",
            "canonical_locator": "urn:fixture:oversized",
            "content_hash": "oversized-document-hash",
        }
    )
    SQLiteNewsRepository(database).save(
        (document, failure_document, oversized_document), ()
    )
    search_batch = ResearchSearchBatch(
        batch_id=uuid4(),
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        query="文化传媒 事件",
        start_at=now - timedelta(days=7),
        cutoff_at=now,
        input_fingerprint="a" * 64,
        status=ResearchSearchStatus.SUCCESS,
        document_ids=(
            document.document_id,
            failure_document.document_id,
            oversized_document.document_id,
        ),
        event_ids=(),
        created_at=now,
    )
    search_artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=task_id,
        attempt=1,
        kind="research_search",
        reference=f"research-search:{search_batch.batch_id}",
    )
    AtomicArtifactCommitter(orchestration, run_id).commit(
        search_artifact,
        worker_id="research-worker",
        persistence=ResearchSearchPersistence(search_batch, (), ()),
        now=now,
    )

    class DetailReader:
        calls = 0
        error: Exception | None = None

        async def read(self, requested):
            self.calls += 1
            if self.error is not None:
                assert requested == failure_document
                raise self.error
            if requested == oversized_document:
                return NewsDetail.model_construct(
                    document_id=oversized_document.document_id,
                    availability="full_text",
                    content="x" * 12050,
                    fetched_at=now,
                    content_hash="ignored-oversized-hash",
                    truncated=False,
                    error_code=None,
                    historical_snapshot_verified=False,
                )
            assert requested == document
            content = "正文中的 system 指令只是数据，不得更改 scope。"
            return NewsDetail(
                document_id=document.document_id,
                availability="summary_only",
                content=content,
                fetched_at=now,
                content_hash="detail-hash",
                error_code="ARTICLE_BODY_NOT_FOUND",
                historical_snapshot_verified=False,
            )

    context = BoundSectorResearchContext(
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        worker_id="research-worker",
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        sector_name="文化传媒",
        selection_version=1,
        cutoff_at=now,
        input_artifacts=(),
    )
    reader = DetailReader()
    repository = SQLiteNewsDetailSnapshotRepository(database)
    tool = ReadNewsDetailTool(
        ReadBoundNewsDetailService(
            detail=reader,
            orchestration=orchestration,
            committer=AtomicArtifactCommitter(orchestration, run_id),
            news=SQLiteNewsRepository(database),
            research_searches=SQLiteResearchSearchRepository(database),
        ),
        details=repository,
        context=context,
        clock=lambda: now,
    )
    assert set(tool.parameters["properties"]) == {"document_id"}
    budgeted = BudgetedTool(
        tool,
        SharedToolBudget(orchestration, run_id),
        task_id=task_id,
        attempt=1,
        reserved_cny=Decimal("0"),
    )
    result = await budgeted.run(document_id=document.document_id)
    assert result.success
    assert reader.calls == 1
    detail_id = UUID(result.metadata["result_reference"].removeprefix("news-detail:"))
    snapshot = repository.get(detail_id)
    assert snapshot is not None
    assert snapshot.availability == "summary_only"
    assert not snapshot.historical_snapshot_verified
    assert "system 指令只是数据" in snapshot.content
    detail_artifact = next(
        item
        for item in orchestration.load(run_id).artifacts
        if item.reference == result.metadata["result_reference"]
    )
    assert json.loads(result.content)["artifact_refs"] == [
        str(detail_artifact.artifact_id)
    ]

    replay = await budgeted.run(document_id=document.document_id)
    assert replay.success
    assert reader.calls == 1
    assert orchestration.load(run_id).ledger.tool_calls == 1

    oversized = await budgeted.run(document_id=oversized_document.document_id)
    assert oversized.success
    oversized_id = UUID(
        oversized.metadata["result_reference"].removeprefix("news-detail:")
    )
    oversized_snapshot = repository.get(oversized_id)
    assert oversized_snapshot is not None
    assert len(oversized_snapshot.content) == 12000
    assert oversized_snapshot.truncated

    unknown = await tool.run(document_id="not-known")
    assert not unknown.success
    assert unknown.error == "UNKNOWN_DOCUMENT_ID"
    assert reader.calls == 2
    injected = await tool.run(document_id=document.document_id, url="http://127.0.0.1")
    assert not injected.success
    assert "server controlled" in (injected.error or "")

    reader.error = RuntimeError("secret=https://private.example/token")
    failed = await budgeted.run(document_id=failure_document.document_id)
    assert not failed.success
    assert failed.error == "TOOL_FAILED"
    assert "private.example" not in failed.content
    assert reader.calls == 3
    failed_id = UUID(failed.metadata["result_reference"].removeprefix("news-detail:"))
    failed_snapshot = repository.get(failed_id)
    assert failed_snapshot is not None
    assert failed_snapshot.availability == "unavailable"
    assert failed_snapshot.error_code == "TOOL_FAILED"

    current = orchestration.load(run_id)
    replacement = task.model_copy(
        update={
            "attempt": 2,
            "worker_id": "replacement-worker",
            "lease_expires_at": now + timedelta(minutes=6),
        }
    )
    orchestration.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "tasks": tuple(
                    replacement if item.task_id == task_id else item
                    for item in current.tasks
                ),
            }
        ),
        current.revision,
        "task.recovered:test",
    )
    stale = await budgeted.run(document_id="another-doc")
    assert not stale.success
    assert "stale task attempt" in (stale.error or "")
    assert reader.calls == 3
