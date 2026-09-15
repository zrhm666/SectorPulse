from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest


def build_editorial_context(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.domain.market.candidate_selection import (
        CandidateSelection,
        CandidateSelectionMethod,
    )
    from sector_pulse.domain.market.market import SectorKind
    from sector_pulse.domain.news.evidence import EvidenceLevel
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.domain.writing.attribution import SectorAnalysisCard
    from sector_pulse.domain.writing.research import SectorAnalysisArtifact
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    now = datetime.now(UTC)
    run_id, root_id, writer_id = uuid4(), uuid4(), uuid4()
    root = TaskRecord(task_id=root_id, role="A0", scope="run")
    researchers = tuple(
        TaskRecord(
            task_id=uuid4(),
            parent_id=root_id,
            role="A2",
            scope=f"sector:INDUSTRY:sector-{index}",
        )
        for index in range(1, 4)
    )
    selection_ref = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root_id,
        kind="candidate_selection",
        reference="selection:1",
    )
    analyses = {}
    analysis_refs = []
    for index, researcher in enumerate(researchers, start=1):
        analysis_id = uuid4()
        card = SectorAnalysisCard(
            run_id=run_id,
            sector_id=f"sector-{index}",
            sector_kind=SectorKind.INDUSTRY,
            sector_name=f"板块{index}",
            allowed_max_level=EvidenceLevel.MARKET_ASSOCIATION,
            attribution_level=EvidenceLevel.MARKET_ASSOCIATION,
            confidence=Decimal("0.6"),
            conclusion="存在市场联想",
            supporting_evidence_ids=(f"event-{index}",),
            counter_evidence=(),
            uncertainties=(),
            background_event_ids=(),
            claims=(),
            forbidden_inferences=(),
        )
        analyses[analysis_id] = SectorAnalysisArtifact(
            analysis_id=analysis_id,
            run_id=run_id,
            task_id=researcher.task_id,
            attempt=1,
            inspection_id=uuid4(),
            input_fingerprint="a" * 64,
            card_hash="b" * 64,
            card=card,
            created_at=now,
        )
        analysis_refs.append(
            ArtifactRef(
                artifact_id=analysis_id,
                task_id=researcher.task_id,
                kind="sector_analysis",
                reference=f"sector-analysis:{analysis_id}",
            )
        )
    writer = TaskRecord(
        task_id=writer_id,
        parent_id=root_id,
        role="A3",
        scope=f"article:{run_id}",
        input_artifact_ids=(
            selection_ref.artifact_id,
            *(item.artifact_id for item in analysis_refs),
        ),
        selection_version=1,
    )
    snapshot = RunSnapshot(
        run_id=run_id,
        deadline=now + timedelta(minutes=10),
        tasks=(root, *researchers, writer),
        artifacts=(selection_ref, *analysis_refs),
    )
    database = SQLiteDatabase(tmp_path / "editorial-context.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    repository.save(snapshot, -1, "created")
    coordinator = TaskCoordinator(repository, run_id)
    for researcher in researchers:
        coordinator.start(
            researcher.task_id,
            attempt=1,
            worker_id=f"worker-{researcher.task_id}",
            lease_expires_at=now + timedelta(minutes=2),
        )
        coordinator.transition(
            researcher.task_id,
            attempt=1,
            worker_id=f"worker-{researcher.task_id}",
            target=TaskStatus.COMPLETED,
        )
    coordinator.start(
        writer_id,
        attempt=1,
        worker_id="writer-worker",
        lease_expires_at=now + timedelta(minutes=2),
    )
    selection = CandidateSelection(
        run_id=run_id,
        version=1,
        selected_sector_ids=("sector-1", "sector-2", "sector-3"),
        method=CandidateSelectionMethod.MANUAL,
        confirmed_at=now,
        data_version="c" * 64,
    )

    class Selections:
        def list_versions(self, identity):
            return [selection] if identity == run_id else []

    class Analyses:
        def get(self, identity):
            return analyses.get(identity)

    return repository, snapshot, writer, Selections(), Analyses(), analyses


def test_a3_context_resolves_only_pinned_selection_and_current_sector_analyses(tmp_path):
    from sector_pulse.application.orchestration.editorial_context import (
        BoundEditorialContextReader,
    )

    repository, snapshot, writer, selections, analyses, _ = build_editorial_context(tmp_path)
    context = BoundEditorialContextReader(
        orchestration=repository,
        selections=selections,
        analyses=analyses,
        run_id=snapshot.run_id,
    ).read(
        task_id=writer.task_id,
        attempt=1,
        worker_id="writer-worker",
    )

    assert context.run_id == snapshot.run_id
    assert context.selection.version == 1
    assert tuple(item.card.sector_id for item in context.analyses) == (
        "sector-1",
        "sector-2",
        "sector-3",
    )
    assert context.input_artifacts == tuple(snapshot.artifacts)


def test_a3_context_rejects_missing_analysis_and_stale_attempt_artifact(tmp_path):
    from sector_pulse.application.orchestration.editorial_context import (
        BoundEditorialContextReader,
    )

    repository, snapshot, writer, selections, analyses, stored = build_editorial_context(tmp_path)
    missing_id = next(iter(stored))
    removed = stored.pop(missing_id)
    reader = BoundEditorialContextReader(
        orchestration=repository,
        selections=selections,
        analyses=analyses,
        run_id=snapshot.run_id,
    )
    with pytest.raises(ValueError, match="analysis is unavailable"):
        reader.read(task_id=writer.task_id, attempt=1, worker_id="writer-worker")

    stored[missing_id] = removed
    current = repository.load(snapshot.run_id)
    stale = current.artifacts[1].model_copy(update={"attempt": 2})
    artifacts = (current.artifacts[0], stale, *current.artifacts[2:])
    repository.save(
        current.model_copy(
            update={"revision": current.revision + 1, "artifacts": artifacts}
        ),
        current.revision,
        "analysis.stale",
    )
    with pytest.raises(ValueError, match="current task attempt"):
        reader.read(task_id=writer.task_id, attempt=1, worker_id="writer-worker")


def test_a3_context_rejects_cross_run_analysis_and_invalid_scope(tmp_path):
    from sector_pulse.application.orchestration.editorial_context import (
        BoundEditorialContextReader,
    )

    repository, snapshot, writer, selections, analyses, stored = build_editorial_context(tmp_path)
    analysis_id = next(iter(stored))
    stored[analysis_id] = stored[analysis_id].model_copy(update={"run_id": uuid4()})
    reader = BoundEditorialContextReader(
        orchestration=repository,
        selections=selections,
        analyses=analyses,
        run_id=snapshot.run_id,
    )
    with pytest.raises(ValueError, match="outside this run"):
        reader.read(task_id=writer.task_id, attempt=1, worker_id="writer-worker")

    current = repository.load(snapshot.run_id)
    tasks = tuple(
        task.model_copy(update={"scope": "article:another-run"})
        if task.task_id == writer.task_id
        else task
        for task in current.tasks
    )
    repository.save(
        current.model_copy(update={"revision": current.revision + 1, "tasks": tasks}),
        current.revision,
        "writer.scope-tampered",
    )
    with pytest.raises(ValueError, match="scope"):
        reader.read(task_id=writer.task_id, attempt=1, worker_id="writer-worker")


def test_t10_submit_outline_uses_server_identity_and_requires_exact_sector_maps(tmp_path):
    from sector_pulse.application.orchestration.editorial_context import (
        BoundEditorialContextReader,
    )
    from sector_pulse.application.orchestration.editorial_tools import SubmitOutlineService
    from sector_pulse.domain.writing.editorial import ArticleOutlineSubmission

    repository, snapshot, writer, selections, analyses, _ = build_editorial_context(tmp_path)
    context = BoundEditorialContextReader(
        orchestration=repository,
        selections=selections,
        analyses=analyses,
        run_id=snapshot.run_id,
    ).read(task_id=writer.task_id, attempt=1, worker_id="writer-worker")

    class Committer:
        committed = []

        def commit(self, artifact, **kwargs):
            self.committed.append((artifact, kwargs))
            return artifact

    committer = Committer()
    service = SubmitOutlineService(orchestration=repository, committer=committer)
    submission = ArticleOutlineSubmission(
        sector_ids=("sector-2", "sector-1", "sector-3"),
        order_reasons={
            "sector-2": "催化更直接",
            "sector-1": "涨幅居前",
            "sector-3": "补充观察",
        },
        title_directions=("今日板块异动观察",),
        thesis="按证据强弱梳理三个已确认板块。",
        section_character_budgets={
            "sector-2": 320,
            "sector-1": 300,
            "sector-3": 280,
        },
        excluded_sector_reasons={},
    )
    artifact = service.submit(context=context, submission=submission)
    assert artifact.run_id == snapshot.run_id
    assert artifact.task_id == writer.task_id
    assert artifact.attempt == 1
    assert artifact.outline.run_id == snapshot.run_id
    assert artifact.outline.sector_ids == submission.sector_ids
    assert committer.committed[0][0].kind == "article_outline"
    assert committer.committed[0][1]["worker_id"] == "writer-worker"

    with pytest.raises(ValueError, match="map keys"):
        service.submit(
            context=context,
            submission=submission.model_copy(
                update={"order_reasons": {"sector-1": "only one"}}
            ),
        )


@pytest.mark.asyncio
async def test_t10_tool_schema_is_bounded_and_replays_exact_persisted_outline(tmp_path):
    import json

    from sector_pulse.application.orchestration.editorial_context import (
        BoundEditorialContextReader,
    )
    from sector_pulse.application.orchestration.editorial_tools import SubmitOutlineService
    from sector_pulse.infrastructure.agents.editorial_tools import SubmitOutlineTool

    repository, snapshot, writer, selections, analyses, _ = build_editorial_context(tmp_path)
    context = BoundEditorialContextReader(
        orchestration=repository,
        selections=selections,
        analyses=analyses,
        run_id=snapshot.run_id,
    ).read(task_id=writer.task_id, attempt=1, worker_id="writer-worker")

    class Committer:
        business = None

        def commit(self, artifact, **kwargs):
            self.business = kwargs["persistence"].outline
            return artifact

    persisted = {}

    class Outlines:
        def get(self, identity):
            return persisted.get(identity)

    committer = Committer()
    service = SubmitOutlineService(orchestration=repository, committer=committer)
    tool = SubmitOutlineTool(service, outlines=Outlines(), context=context)
    assert set(tool.parameters["properties"]) == {"submission"}
    result = await tool.run(
        submission={
            "sector_ids": ["sector-1", "sector-2", "sector-3"],
            "order_reasons": {
                "sector-1": "一",
                "sector-2": "二",
                "sector-3": "三",
            },
            "title_directions": ["方向"],
            "thesis": "证据边界内的观察",
            "section_character_budgets": {
                "sector-1": 300,
                "sector-2": 300,
                "sector-3": 300,
            },
            "excluded_sector_reasons": {},
        }
    )
    assert result.success
    outline_id = UUID(json.loads(result.content)["artifact_refs"][0])
    persisted[outline_id] = committer.business
    replayed = tool.replay(f"article-outline:{outline_id}")
    assert replayed.content == result.content
    rejected = await tool.run(
        submission={}, run_id=str(snapshot.run_id), worker_id="forged"
    )
    assert not rejected.success


def test_t10_sqlite_persists_outline_and_artifact_reference_atomically(tmp_path):
    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.editorial_context import (
        BoundEditorialContextReader,
    )
    from sector_pulse.application.orchestration.editorial_tools import SubmitOutlineService
    from sector_pulse.domain.writing.editorial import ArticleOutlineSubmission
    from sector_pulse.storage.sqlite.writing.editorial_repository import (
        SQLiteEditorialOutlineRepository,
    )

    repository, snapshot, writer, selections, analyses, _ = build_editorial_context(tmp_path)
    with repository.database.transaction() as connection:
        connection.execute(
            "INSERT INTO analysis_runs (run_id, mode, requested_at) VALUES (?, ?, ?)",
            (str(snapshot.run_id), "LIVE", datetime.now(UTC).isoformat()),
        )
    context = BoundEditorialContextReader(
        orchestration=repository,
        selections=selections,
        analyses=analyses,
        run_id=snapshot.run_id,
    ).read(task_id=writer.task_id, attempt=1, worker_id="writer-worker")
    service = SubmitOutlineService(
        orchestration=repository,
        committer=AtomicArtifactCommitter(repository, snapshot.run_id),
    )
    submission = ArticleOutlineSubmission(
        sector_ids=("sector-1", "sector-2", "sector-3"),
        order_reasons={
            "sector-1": "一",
            "sector-2": "二",
            "sector-3": "三",
        },
        title_directions=("方向",),
        thesis="证据边界内的观察",
        section_character_budgets={
            "sector-1": 300,
            "sector-2": 300,
            "sector-3": 300,
        },
        excluded_sector_reasons={},
    )
    result = service.submit(
        context=context,
        submission=submission,
    )

    outlines = SQLiteEditorialOutlineRepository(repository.database)
    assert outlines.get(result.outline_id) == result
    revised = service.submit(
        context=context,
        submission=submission.model_copy(update={"thesis": "第二版结构方向"}),
    )
    assert revised.outline_id != result.outline_id
    assert outlines.get(result.outline_id) == result
    assert outlines.get(revised.outline_id) == revised
    state = repository.load(snapshot.run_id)
    stored = next(item for item in state.artifacts if item.kind == "article_outline")
    assert stored.artifact_id == result.outline_id
    assert stored.reference == f"article-outline:{result.outline_id}"


@pytest.mark.postgres
def test_t10_t11_postgres_persist_editorial_artifacts_atomically(tmp_path):
    import os

    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.editorial_context import (
        BoundEditorialContext,
    )
    from sector_pulse.application.orchestration.editorial_tools import (
        EditorialDraftPersistence,
        SubmitOutlineService,
    )
    from sector_pulse.domain.market.candidate_selection import (
        CandidateSelection,
        CandidateSelectionMethod,
    )
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
    from sector_pulse.domain.writing.editorial import (
        ArticleOutlineSubmission,
        EditorialDraftArtifact,
    )
    from sector_pulse.storage.postgres.database import PostgresDatabase
    from sector_pulse.storage.postgres.orchestration.repository import (
        PostgresOrchestrationRepository,
    )
    from sector_pulse.storage.postgres.writing.editorial_repository import (
        PostgresEditorialDraftRepository,
        PostgresEditorialOutlineRepository,
    )
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    del tmp_path
    url = os.getenv("SECTOR_PULSE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires dedicated SECTOR_PULSE_TEST_DATABASE_URL")
    assert (make_url(url).database or "").endswith("_test"), "business database refused"
    database = PostgresDatabase(url)
    database.initialize()
    now = datetime.now(UTC)
    run_id, root_id, writer_id = uuid4(), uuid4(), uuid4()
    root = TaskRecord(task_id=root_id, role="A0", scope="run")
    writer = TaskRecord(
        task_id=writer_id,
        parent_id=root_id,
        role="A3",
        scope=f"article:{run_id}",
        status=TaskStatus.RUNNING,
        worker_id="pg-writer",
        lease_expires_at=now + timedelta(minutes=3),
        selection_version=1,
    )
    orchestration = PostgresOrchestrationRepository(database)
    selection = CandidateSelection(
        run_id=run_id,
        version=1,
        selected_sector_ids=("sector-1", "sector-2", "sector-3"),
        method=CandidateSelectionMethod.MANUAL,
        confirmed_at=now,
        data_version="d" * 64,
    )
    context = BoundEditorialContext(
        run_id=run_id,
        task_id=writer_id,
        attempt=1,
        worker_id="pg-writer",
        selection=selection,
        analyses=(),
        input_artifacts=(),
    )
    try:
        with database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO analysis_runs (run_id, mode, requested_at) "
                    "VALUES (:run_id, 'LIVE', :now)"
                ),
                {"run_id": str(run_id), "now": now.isoformat()},
            )
        orchestration.save(
            RunSnapshot(
                run_id=run_id,
                deadline=now + timedelta(minutes=10),
                tasks=(root, writer),
            ),
            -1,
            "editorial.created",
        )
        result = SubmitOutlineService(
            orchestration=orchestration,
            committer=AtomicArtifactCommitter(orchestration, run_id),
        ).submit(
            context=context,
            submission=ArticleOutlineSubmission(
                sector_ids=selection.selected_sector_ids,
                order_reasons={item: item for item in selection.selected_sector_ids},
                title_directions=("方向",),
                thesis="证据边界内的观察",
                section_character_budgets={
                    item: 300 for item in selection.selected_sector_ids
                },
                excluded_sector_reasons={},
            ),
        )
        assert PostgresEditorialOutlineRepository(database).get(result.outline_id) == result
        draft_id, draft_artifact_id = uuid4(), uuid4()
        draft = EditorialDraftArtifact(
            artifact_id=draft_artifact_id,
            run_id=run_id,
            task_id=writer_id,
            attempt=1,
            outline_id=result.outline_id,
            input_fingerprint="e" * 64,
            draft_hash="f" * 64,
            draft=ArticleDraft(
                draft_id=draft_id,
                run_id=run_id,
                version=1,
                status=DraftStatus.UNREVIEWED,
                titles=("测试稿",),
                introduction="导语",
                sections=(),
                conclusion="结语",
                risk_notice="风险提示",
                sources=(),
                character_count=4,
            ),
            created_at=now,
        )
        AtomicArtifactCommitter(orchestration, run_id).commit(
            ArtifactRef(
                artifact_id=draft_artifact_id,
                task_id=writer_id,
                kind="article_draft",
                reference=f"article-draft:{draft_artifact_id}",
            ),
            worker_id="pg-writer",
            persistence=EditorialDraftPersistence(draft),
            now=now,
        )
        drafts = PostgresEditorialDraftRepository(database)
        assert drafts.get(draft_artifact_id) == draft
        assert drafts.get_version(draft_id, 1) == draft
        state = orchestration.load(run_id)
        assert state is not None
        assert [item.kind for item in state.artifacts] == [
            "article_outline",
            "article_draft",
        ]
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM orchestration_events WHERE run_id=:run_id"),
                {"run_id": str(run_id)},
            )
            connection.execute(
                text("DELETE FROM orchestration_snapshots WHERE run_id=:run_id"),
                {"run_id": str(run_id)},
            )
            connection.execute(
                text("DELETE FROM analysis_runs WHERE run_id=:run_id"),
                {"run_id": str(run_id)},
            )
