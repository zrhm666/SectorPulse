from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.tests.integration.test_orchestration_review_tools import build_review_context


def build_revision_context(tmp_path):
    from sector_pulse.application.orchestration.editorial_context import (
        BoundRevisionContextReader,
    )
    from sector_pulse.domain.orchestration.models import ArtifactRef, TaskRecord, TaskStatus
    from sector_pulse.domain.review.review import (
        IssueSeverity,
        ReviewDecision,
        ReviewIssue,
        ReviewReport,
    )
    from sector_pulse.domain.writing.article import ArticleOutline
    from sector_pulse.domain.writing.editorial import (
        EditorialOutlineArtifact,
        IndependentReviewArtifact,
    )

    repository, review_context, reviewer, draft, newer = build_review_context(tmp_path)
    now = datetime.now(UTC)
    review_id = uuid4()
    review = IndependentReviewArtifact(
        artifact_id=review_id,
        run_id=review_context.run_id,
        task_id=reviewer.task_id,
        attempt=1,
        draft_artifact_id=draft.artifact_id,
        rules_artifact_id=uuid4(),
        input_fingerprint="1" * 64,
        report=ReviewReport(
            review_id=str(review_id),
            draft_id=str(draft.draft.draft_id),
            draft_version=1,
            decision=ReviewDecision.REVISE,
            issues=(
                ReviewIssue(
                    issue_id="review:section-1",
                    severity=IssueSeverity.WARNING,
                    code="CLARIFY",
                    message="补充边界",
                    section_id="section-1",
                ),
            ),
            revision_round=0,
        ),
        created_at=now,
    )
    revision_id = uuid4()
    state = repository.load(review_context.run_id)
    root_id = next(item.task_id for item in state.tasks if item.role == "A0")
    revision_task = TaskRecord(
        task_id=revision_id,
        parent_id=root_id,
        role="A3",
        scope=f"revision:{draft.draft.draft_id}:1",
        status=TaskStatus.RUNNING,
        worker_id="revision-worker",
        lease_expires_at=now + timedelta(minutes=3),
        input_artifact_ids=(draft.artifact_id, review_id),
    )
    current = repository.load(review_context.run_id)
    tasks = tuple(
        item.model_copy(
            update={
                "status": TaskStatus.COMPLETED,
                "worker_id": None,
                "lease_expires_at": None,
            }
        )
        if item.task_id == reviewer.task_id
        else item
        for item in current.tasks
    )
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "tasks": (*tasks, revision_task),
                "artifacts": (
                    *current.artifacts,
                    ArtifactRef(
                        artifact_id=review_id,
                        task_id=reviewer.task_id,
                        kind="independent_review",
                        reference=f"independent-review:{review_id}",
                    ),
                ),
            }
        ),
        current.revision,
        "revision.created",
    )
    outline = EditorialOutlineArtifact(
        outline_id=draft.outline_id,
        run_id=draft.run_id,
        task_id=draft.task_id,
        attempt=draft.attempt,
        selection_version=1,
        input_analysis_ids=tuple(item.analysis_id for item in review_context.analyses),
        input_fingerprint="2" * 64,
        outline_hash="3" * 64,
        outline=ArticleOutline(
            outline_id=draft.outline_id,
            run_id=draft.run_id,
            sector_ids=tuple(item.card.sector_id for item in review_context.analyses),
            order_reasons={item.card.sector_id: "排序" for item in review_context.analyses},
            title_directions=("观察",),
            thesis="梳理变化",
            section_character_budgets={
                item.card.sector_id: 400 for item in review_context.analyses
            },
            excluded_sector_reasons={},
        ),
        created_at=now,
    )

    class Drafts:
        latest = draft

        def get(self, identity):
            return {draft.artifact_id: draft, newer.artifact_id: newer}.get(identity)

        def get_version(self, identity, version):
            return {(draft.draft.draft_id, 1): draft, (draft.draft.draft_id, 2): newer}.get(
                (identity, version)
            )

        def latest_version(self, identity):
            return self.latest if identity == draft.draft.draft_id else None

    class Reviews:
        def get(self, identity):
            return review if identity == review_id else None

    class Outlines:
        def get(self, identity):
            return outline if identity == outline.outline_id else None

    analyses = {item.analysis_id: item for item in review_context.analyses}

    class Analyses:
        def get(self, identity):
            return analyses.get(identity)

    drafts = Drafts()
    context = BoundRevisionContextReader(
        orchestration=repository,
        drafts=drafts,
        reviews=Reviews(),
        outlines=Outlines(),
        analyses=Analyses(),
        run_id=review_context.run_id,
    ).read(task_id=revision_id, attempt=1, worker_id="revision-worker", now=now)
    return repository, context, drafts, review, newer


def section_change(context, *, body_suffix="补充说明"):
    from sector_pulse.application.writing.revision_agent import (
        RevisionChanges,
        SectionRevision,
    )

    section = context.draft.draft.sections[0]
    return RevisionChanges(
        sections=(
            SectionRevision(
                section_id=section.section_id,
                heading=section.heading,
                body=section.body + body_suffix,
                claims=section.claims,
                source_ids=section.source_ids,
            ),
        )
    )


def seed_revision_business(repository, context):
    now = datetime.now(UTC).isoformat()
    draft = context.draft
    with repository.database.transaction() as connection:
        connection.execute(
            "INSERT INTO analysis_runs (run_id, mode, requested_at) VALUES (?, ?, ?)",
            (str(context.run_id), "LIVE", now),
        )
        connection.execute(
            "INSERT INTO editorial_outline_artifacts "
            "(outline_id, run_id, task_id, attempt, selection_version, input_fingerprint, "
            "outline_hash, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(draft.outline_id),
                str(context.run_id),
                str(draft.task_id),
                draft.attempt,
                1,
                "8" * 64,
                "9" * 64,
                "{}",
                now,
            ),
        )
        connection.execute(
            "INSERT INTO editorial_draft_artifacts "
            "(artifact_id, draft_id, run_id, task_id, attempt, version, outline_id, "
            "input_fingerprint, draft_hash, payload_json, created_at, revision_round) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(draft.artifact_id),
                str(draft.draft.draft_id),
                str(context.run_id),
                str(draft.task_id),
                draft.attempt,
                draft.draft.version,
                str(draft.outline_id),
                draft.input_fingerprint,
                draft.draft_hash,
                draft.model_dump_json(),
                now,
                draft.revision_round,
            ),
        )

def test_revision_context_pins_revise_review_to_exact_base_version(tmp_path):
    from sector_pulse.application.orchestration.editorial_context import (
        BoundRevisionContextReader,
    )

    repository, context, _, review, newer = build_revision_context(tmp_path)
    assert context.draft.draft.version == 1
    assert context.review == review

    mismatched = review.model_copy(
        update={
            "draft_artifact_id": newer.artifact_id,
            "report": review.report.model_copy(update={"draft_version": 2}),
        }
    )

    class MismatchedReviews:
        def get(self, identity):
            return mismatched

    with pytest.raises(ValueError, match="review.*base draft"):
        BoundRevisionContextReader(
            orchestration=repository,
            drafts=type("Drafts", (), {"get": lambda self, identity: context.draft})(),
            reviews=MismatchedReviews(),
            outlines=type("Outlines", (), {"get": lambda self, identity: None})(),
            analyses=type("Analyses", (), {"get": lambda self, identity: None})(),
            run_id=context.run_id,
        ).read(
            task_id=context.task_id,
            attempt=1,
            worker_id="revision-worker",
        )


def test_t12_enforces_review_scope_latest_version_and_two_round_limit(tmp_path):
    from sector_pulse.application.orchestration.editorial_tools import SubmitRevisionService
    from sector_pulse.domain.review.review import ReviewDecision
    from sector_pulse.domain.writing.editorial import IndependentReviewArtifact

    repository, context, drafts, review, newer = build_revision_context(tmp_path)

    class Committer:
        committed = []

        def commit(self, artifact, **kwargs):
            self.committed.append((artifact, kwargs["persistence"].draft))
            return artifact

    service = SubmitRevisionService(
        orchestration=repository,
        committer=Committer(),
        drafts=drafts,
    )
    revised = service.submit(
        context=context,
        base_draft_artifact_id=context.draft.artifact_id,
        review_artifact_id=review.artifact_id,
        changes=section_change(context),
    )
    assert revised.draft.version == 2
    assert revised.revision_round == 1
    assert revised.base_draft_artifact_id == context.draft.artifact_id
    assert revised.review_artifact_id == review.artifact_id

    with pytest.raises(ValueError, match="revision scope"):
        service.submit(
            context=context,
            base_draft_artifact_id=context.draft.artifact_id,
            review_artifact_id=review.artifact_id,
            changes=section_change(context).model_copy(update={"conclusion": "越界修改"}),
        )
    with pytest.raises(ValueError, match="no change"):
        service.submit(
            context=context,
            base_draft_artifact_id=context.draft.artifact_id,
            review_artifact_id=review.artifact_id,
            changes=section_change(context, body_suffix=""),
        )
    wrong_source = section_change(context)
    wrong_source = wrong_source.model_copy(
        update={
            "sections": (
                wrong_source.sections[0].model_copy(update={"source_ids": ("event-2",)}),
            )
        }
    )
    with pytest.raises(ValueError, match="scope or content"):
        service.submit(
            context=context,
            base_draft_artifact_id=context.draft.artifact_id,
            review_artifact_id=review.artifact_id,
            changes=wrong_source,
        )

    from sector_pulse.domain.writing.attribution import Claim

    excessive_claim = Claim(
        claim_id="revision:causal",
        kind="ATTRIBUTION",
        text="板块1上涨由该消息直接驱动",
        evidence_ids=("event-1",),
        attribution_level="EXPLICIT_DRIVER",
    )
    excessive = section_change(context)
    excessive = excessive.model_copy(
        update={
            "sections": (
                excessive.sections[0].model_copy(update={"claims": (excessive_claim,)}),
            )
        }
    )
    with pytest.raises(ValueError, match="scope or content"):
        service.submit(
            context=context,
            base_draft_artifact_id=context.draft.artifact_id,
            review_artifact_id=review.artifact_id,
            changes=excessive,
        )

    drafts.latest = newer
    with pytest.raises(ValueError, match="stale"):
        service.submit(
            context=context,
            base_draft_artifact_id=context.draft.artifact_id,
            review_artifact_id=review.artifact_id,
            changes=section_change(context),
        )

    review_v2 = IndependentReviewArtifact(
        **review.model_dump(
            exclude={"artifact_id", "draft_artifact_id", "report", "input_fingerprint"}
        ),
        artifact_id=uuid4(),
        draft_artifact_id=revised.artifact_id,
        input_fingerprint="4" * 64,
        report=review.report.model_copy(
            update={"draft_version": 2, "revision_round": 1}
        ),
    )
    context_v2 = context.model_copy(update={"draft": revised, "review": review_v2})
    drafts.latest = revised
    revised_twice = service.submit(
        context=context_v2,
        base_draft_artifact_id=revised.artifact_id,
        review_artifact_id=review_v2.artifact_id,
        changes=section_change(context_v2, body_suffix="再次说明"),
    )
    assert revised_twice.draft.version == 3
    assert revised_twice.revision_round == 2

    review_v3 = review_v2.model_copy(
        update={
            "artifact_id": uuid4(),
            "draft_artifact_id": revised_twice.artifact_id,
            "report": review_v2.report.model_copy(
                update={
                    "draft_version": 3,
                    "decision": ReviewDecision.REVISE,
                    "revision_round": 2,
                }
            ),
        }
    )
    context_v3 = context.model_copy(update={"draft": revised_twice, "review": review_v3})
    drafts.latest = revised_twice
    with pytest.raises(ValueError, match="maximum revision rounds"):
        service.submit(
            context=context_v3,
            base_draft_artifact_id=revised_twice.artifact_id,
            review_artifact_id=review_v3.artifact_id,
            changes=section_change(context_v3, body_suffix="第三次"),
        )


@pytest.mark.asyncio
async def test_t12_sqlite_persists_replays_and_rejects_competing_revision(tmp_path):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.editorial_tools import SubmitRevisionService
    from sector_pulse.infrastructure.agents.editorial_tools import SubmitRevisionTool
    from sector_pulse.storage.sqlite.writing.editorial_repository import (
        SQLiteEditorialDraftRepository,
    )

    repository, context, _, review, _ = build_revision_context(tmp_path)
    seed_revision_business(repository, context)
    drafts = SQLiteEditorialDraftRepository(repository.database)
    service = SubmitRevisionService(
        orchestration=repository,
        committer=AtomicArtifactCommitter(repository, context.run_id),
        drafts=drafts,
    )
    tool = SubmitRevisionTool(service, drafts=drafts, context=context)
    assert set(tool.parameters["properties"]) == {
        "base_draft_artifact_id",
        "review_artifact_id",
        "changes",
    }
    result = await tool.run(
        base_draft_artifact_id=str(context.draft.artifact_id),
        review_artifact_id=str(review.artifact_id),
        changes=section_change(context).model_dump(mode="json"),
    )
    assert result.success
    artifact_id = json.loads(result.content)["artifact_refs"][0]
    persisted = drafts.get(uuid4())
    assert persisted is None
    revised = drafts.get_version(context.draft.draft.draft_id, 2)
    assert revised is not None
    assert str(revised.artifact_id) == artifact_id
    assert revised.revision_round == 1
    assert tool.replay(f"article-draft:{artifact_id}").content == result.content

    competing_path = tmp_path / "competing"
    competing_path.mkdir()
    competing_repository, competing_context, _, competing_review, _ = (
        build_revision_context(competing_path)
    )
    seed_revision_business(competing_repository, competing_context)
    inner = SQLiteEditorialDraftRepository(competing_repository.database)
    barrier = Barrier(2)

    class SynchronizedDrafts:
        def get(self, identity):
            return inner.get(identity)

        def get_version(self, draft_id, version):
            return inner.get_version(draft_id, version)

        def latest_version(self, draft_id):
            latest = inner.latest_version(draft_id)
            barrier.wait(timeout=5)
            return latest

    competing_service = SubmitRevisionService(
        orchestration=competing_repository,
        committer=AtomicArtifactCommitter(
            competing_repository, competing_context.run_id
        ),
        drafts=SynchronizedDrafts(),
    )

    def submit_once():
        return competing_service.submit(
            context=competing_context,
            base_draft_artifact_id=competing_context.draft.artifact_id,
            review_artifact_id=competing_review.artifact_id,
            changes=section_change(competing_context),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [executor.submit(submit_once) for _ in range(2)]
    successes = []
    failures = []
    for outcome in outcomes:
        try:
            successes.append(outcome.result())
        except Exception as exc:  # noqa: BLE001 - asserting the transaction loser
            failures.append(exc)
    assert len(successes) == 1
    assert len(failures) == 1
    assert inner.latest_version(competing_context.draft.draft.draft_id).draft.version == 2


@pytest.mark.postgres
def test_t12_postgres_persists_revision_and_rejects_stale_base(tmp_path):
    import os

    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.editorial_tools import SubmitRevisionService
    from sector_pulse.storage.postgres.database import PostgresDatabase
    from sector_pulse.storage.postgres.orchestration.repository import (
        PostgresOrchestrationRepository,
    )
    from sector_pulse.storage.postgres.writing.editorial_repository import (
        PostgresEditorialDraftRepository,
    )
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    url = os.getenv("SECTOR_PULSE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires dedicated SECTOR_PULSE_TEST_DATABASE_URL")
    assert (make_url(url).database or "").endswith("_test"), "business database refused"
    _, context, _, review, _ = build_revision_context(tmp_path)
    database = PostgresDatabase(url)
    database.initialize()
    orchestration = PostgresOrchestrationRepository(database)
    draft = context.draft
    now = datetime.now(UTC)
    from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord, TaskStatus

    root_id, writer_id, reviewer_id = uuid4(), draft.task_id, review.task_id
    snapshot = RunSnapshot(
        run_id=context.run_id,
        deadline=now + timedelta(minutes=10),
        tasks=(
            TaskRecord(task_id=root_id, role="A0", scope="run"),
            TaskRecord(
                task_id=writer_id,
                parent_id=root_id,
                role="A3",
                scope=f"article:{context.run_id}",
                status=TaskStatus.COMPLETED,
            ),
            TaskRecord(
                task_id=reviewer_id,
                parent_id=root_id,
                role="A4",
                scope=f"review:{draft.draft.draft_id}:1",
                status=TaskStatus.COMPLETED,
            ),
            TaskRecord(
                task_id=context.task_id,
                parent_id=root_id,
                role="A3",
                scope=f"revision:{draft.draft.draft_id}:1",
                status=TaskStatus.RUNNING,
                worker_id=context.worker_id,
                lease_expires_at=now + timedelta(minutes=3),
                input_artifact_ids=tuple(item.artifact_id for item in context.input_artifacts),
            ),
        ),
        artifacts=context.input_artifacts,
    )
    try:
        with database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO analysis_runs (run_id, mode, requested_at) "
                    "VALUES (:run_id, 'LIVE', :now)"
                ),
                {"run_id": str(context.run_id), "now": now.isoformat()},
            )
            connection.execute(
                text(
                    "INSERT INTO editorial_outline_artifacts "
                    "(outline_id, run_id, task_id, attempt, selection_version, "
                    "input_fingerprint, outline_hash, payload_json, created_at) VALUES "
                    "(:outline_id, :run_id, :task_id, 1, 1, :fingerprint, :hash, '{}', :now)"
                ),
                {
                    "outline_id": str(draft.outline_id),
                    "run_id": str(context.run_id),
                    "task_id": str(draft.task_id),
                    "fingerprint": "6" * 64,
                    "hash": "7" * 64,
                    "now": now.isoformat(),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO editorial_draft_artifacts "
                    "(artifact_id, draft_id, run_id, task_id, attempt, version, outline_id, "
                    "input_fingerprint, draft_hash, payload_json, created_at, revision_round) "
                    "VALUES (:artifact_id, :draft_id, :run_id, :task_id, 1, 1, "
                    ":outline_id, :fingerprint, :hash, :payload, :now, 0)"
                ),
                {
                    "artifact_id": str(draft.artifact_id),
                    "draft_id": str(draft.draft.draft_id),
                    "run_id": str(context.run_id),
                    "task_id": str(draft.task_id),
                    "outline_id": str(draft.outline_id),
                    "fingerprint": draft.input_fingerprint,
                    "hash": draft.draft_hash,
                    "payload": draft.model_dump_json(),
                    "now": now.isoformat(),
                },
            )
        orchestration.save(snapshot, -1, "revision.pg-created")
        pg_context = context.model_copy(update={"input_artifacts": snapshot.artifacts})
        drafts = PostgresEditorialDraftRepository(database)
        service = SubmitRevisionService(
            orchestration=orchestration,
            committer=AtomicArtifactCommitter(orchestration, context.run_id),
            drafts=drafts,
        )
        result = service.submit(
            context=pg_context,
            base_draft_artifact_id=draft.artifact_id,
            review_artifact_id=review.artifact_id,
            changes=section_change(pg_context),
            now=now,
        )
        assert drafts.get(result.artifact_id) == result
        assert drafts.latest_version(draft.draft.draft_id) == result
        with pytest.raises(ValueError, match="stale|already used"):
            service.submit(
                context=pg_context,
                base_draft_artifact_id=draft.artifact_id,
                review_artifact_id=review.artifact_id,
                changes=section_change(pg_context, body_suffix="再次"),
                now=now,
            )
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM orchestration_events WHERE run_id=:run_id"),
                {"run_id": str(context.run_id)},
            )
            connection.execute(
                text("DELETE FROM orchestration_snapshots WHERE run_id=:run_id"),
                {"run_id": str(context.run_id)},
            )
            connection.execute(
                text("DELETE FROM analysis_runs WHERE run_id=:run_id"),
                {"run_id": str(context.run_id)},
            )
