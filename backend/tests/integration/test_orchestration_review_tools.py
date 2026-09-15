from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest


def build_review_context(tmp_path, *, with_quality_issue: bool = False):
    from sector_pulse.application.orchestration.editorial_context import (
        BoundReviewContextReader,
    )
    from sector_pulse.domain.market.market import SectorKind
    from sector_pulse.domain.news.evidence import EvidenceLevel
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.domain.writing.article import (
        ArticleDraft,
        ArticleOutline,
        ArticleSection,
        ArticleSource,
        DraftStatus,
    )
    from sector_pulse.domain.writing.attribution import SectorAnalysisCard
    from sector_pulse.domain.writing.editorial import (
        EditorialDraftArtifact,
        EditorialOutlineArtifact,
    )
    from sector_pulse.domain.writing.research import SectorAnalysisArtifact
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import (
        SQLiteOrchestrationRepository,
    )

    now = datetime.now(UTC)
    run_id, root_id, writer_id, reviewer_id = uuid4(), uuid4(), uuid4(), uuid4()
    draft_id, draft_artifact_id, outline_id = uuid4(), uuid4(), uuid4()
    cards = []
    analysis_artifacts = []
    for index in range(1, 4):
        analysis_id = uuid4()
        card = SectorAnalysisCard(
            run_id=run_id,
            sector_id=f"sector-{index}",
            sector_kind=SectorKind.INDUSTRY,
            sector_name=f"板块{index}",
            allowed_max_level=EvidenceLevel.MARKET_ASSOCIATION,
            attribution_level=EvidenceLevel.MARKET_ASSOCIATION,
            confidence="0.6",
            conclusion="存在市场联想",
            supporting_evidence_ids=(f"event-{index}",),
            counter_evidence=(),
            uncertainties=(),
            background_event_ids=(),
            claims=(),
            forbidden_inferences=(),
        )
        cards.append(
            SectorAnalysisArtifact(
                analysis_id=analysis_id,
                run_id=run_id,
                task_id=writer_id,
                attempt=1,
                inspection_id=uuid4(),
                input_fingerprint="a" * 64,
                card_hash="b" * 64,
                card=card,
                created_at=now,
            )
        )
        analysis_artifacts.append(analysis_id)
    sections = tuple(
        ArticleSection(
            section_id=f"section-{index}",
            sector_id=f"sector-{index}",
            heading=("错误标题" if with_quality_issue and index == 1 else f"板块{index}观察"),
            body=(
                ("主体缺失。" if with_quality_issue and index == 1 else f"板块{index}出现异动。")
                + "中性分析" * 110
            ),
            claims=(),
            source_ids=(f"event-{index}",),
            character_count=450,
        )
        for index in range(1, 4)
    )
    article = ArticleDraft(
        draft_id=draft_id,
        run_id=run_id,
        version=1,
        status=DraftStatus.UNREVIEWED,
        titles=("板块观察",),
        introduction="今日市场出现结构性变化。",
        sections=sections,
        conclusion="以上仅为公开信息梳理。",
        risk_notice="市场有风险，信息仅供研究参考。",
        sources=tuple(
            ArticleSource(
                source_id=f"event-{index}",
                title=f"来源{index}",
                citation_url=f"https://example.test/{index}",
            )
            for index in range(1, 4)
        ),
        character_count=1400,
    )
    draft = EditorialDraftArtifact(
        artifact_id=draft_artifact_id,
        run_id=run_id,
        task_id=writer_id,
        attempt=1,
        outline_id=outline_id,
        input_fingerprint="c" * 64,
        draft_hash="d" * 64,
        draft=article,
        created_at=now,
    )
    newer = draft.model_copy(
        update={
            "artifact_id": uuid4(),
            "draft": article.model_copy(update={"version": 2, "conclusion": "人工编辑版"}),
        }
    )
    outline = EditorialOutlineArtifact(
        outline_id=outline_id,
        run_id=run_id,
        task_id=writer_id,
        attempt=1,
        selection_version=1,
        input_analysis_ids=tuple(analysis_artifacts),
        input_fingerprint="e" * 64,
        outline_hash="f" * 64,
        outline=ArticleOutline(
            outline_id=outline_id,
            run_id=run_id,
            sector_ids=("sector-1", "sector-2", "sector-3"),
            order_reasons={f"sector-{i}": str(i) for i in range(1, 4)},
            title_directions=("观察",),
            thesis="梳理市场变化",
            section_character_budgets={f"sector-{i}": 400 for i in range(1, 4)},
            excluded_sector_reasons={},
        ),
        created_at=now,
    )
    draft_ref = ArtifactRef(
        artifact_id=draft_artifact_id,
        task_id=writer_id,
        kind="article_draft",
        reference=f"article-draft:{draft_artifact_id}",
    )
    root = TaskRecord(task_id=root_id, role="A0", scope="run")
    writer = TaskRecord(
        task_id=writer_id,
        parent_id=root_id,
        role="A3",
        scope=f"article:{run_id}",
        status=TaskStatus.COMPLETED,
    )
    reviewer = TaskRecord(
        task_id=reviewer_id,
        parent_id=root_id,
        role="A4",
        scope=f"review:{draft_id}:1",
        status=TaskStatus.RUNNING,
        worker_id="review-worker",
        lease_expires_at=now + timedelta(minutes=3),
        input_artifact_ids=(draft_artifact_id,),
    )
    database = SQLiteDatabase(tmp_path / "review-tools.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    repository.save(
        RunSnapshot(
            run_id=run_id,
            deadline=now + timedelta(minutes=10),
            tasks=(root, writer, reviewer),
            artifacts=(draft_ref,),
        ),
        -1,
        "review.created",
    )

    class Drafts:
        def get(self, identity):
            return {draft.artifact_id: draft, newer.artifact_id: newer}.get(identity)

        def get_version(self, identity, version):
            return {(draft_id, 1): draft, (draft_id, 2): newer}.get((identity, version))

    class Outlines:
        def get(self, identity):
            return outline if identity == outline_id else None

    analyses_by_id = {item.analysis_id: item for item in cards}

    class Analyses:
        def get(self, identity):
            return analyses_by_id.get(identity)

    context = BoundReviewContextReader(
        orchestration=repository,
        drafts=Drafts(),
        outlines=Outlines(),
        analyses=Analyses(),
        run_id=run_id,
    ).read(task_id=reviewer_id, attempt=1, worker_id="review-worker", now=now)
    return repository, context, reviewer, draft, newer


def test_a4_context_is_pinned_to_explicit_draft_artifact_and_version(tmp_path):
    repository, context, reviewer, draft, newer = build_review_context(tmp_path)

    assert context.draft == draft
    assert context.draft.draft.version == 1
    assert context.draft != newer

    state = repository.load(context.run_id)
    tasks = tuple(
        item.model_copy(update={"scope": f"review:{draft.draft.draft_id}:2"})
        if item.task_id == reviewer.task_id
        else item
        for item in state.tasks
    )
    repository.save(
        state.model_copy(update={"revision": state.revision + 1, "tasks": tasks}),
        state.revision,
        "review.scope.changed",
    )
    from sector_pulse.application.orchestration.editorial_context import (
        BoundReviewContextReader,
    )

    with pytest.raises(ValueError, match="scope"):
        BoundReviewContextReader(
            orchestration=repository,
            drafts=type("Drafts", (), {"get": lambda self, identity: draft})(),
            outlines=type("Outlines", (), {"get": lambda self, identity: None})(),
            analyses=type("Analyses", (), {"get": lambda self, identity: None})(),
            run_id=context.run_id,
        ).read(task_id=reviewer.task_id, attempt=1, worker_id="review-worker")


def test_t13_runs_deterministic_quality_and_governance_checks(tmp_path, monkeypatch):
    from sector_pulse.application.orchestration.review_tools import CheckDraftRulesService
    from sector_pulse.application.review.governance_service import GovernanceService
    from sector_pulse.application.writing.draft_quality import draft_quality_issues

    repository, context, _, draft, _ = build_review_context(
        tmp_path, with_quality_issue=True
    )
    calls = {"quality": 0, "governance": 0}

    def checked_quality(article, cards):
        calls["quality"] += 1
        return draft_quality_issues(article, cards)

    class CheckedGovernance(GovernanceService):
        def check(self, article):
            calls["governance"] += 1
            return super().check(article)

    monkeypatch.setattr(
        "sector_pulse.application.orchestration.review_tools.draft_quality_issues",
        checked_quality,
    )
    service = CheckDraftRulesService(
        orchestration=repository,
        committer=type("Committer", (), {"commit": lambda self, artifact, **kwargs: artifact})(),
        governance=CheckedGovernance(),
    )
    result = service.check(context=context, draft_artifact_id=draft.artifact_id)

    assert calls == {"quality": 1, "governance": 1}
    assert result.report.draft_id == draft.draft.draft_id
    assert result.report.draft_version == 1
    assert result.report.quality_issues[0].code == "SECTOR_SUBJECT_MISSING"
    assert result.report.governance.rules_version == "phase2b-v1"


def test_t14_rejects_pass_over_program_findings_and_unknown_issue_targets(tmp_path):
    from sector_pulse.application.orchestration.review_tools import SubmitReviewService
    from sector_pulse.application.review.governance_service import GovernanceReport
    from sector_pulse.domain.review.review import (
        IssueSeverity,
        ReviewDecision,
        ReviewIssue,
    )
    from sector_pulse.domain.writing.editorial import (
        DraftRulesArtifact,
        DraftRulesReport,
        ReviewSubmission,
    )

    repository, context, _, draft, newer = build_review_context(tmp_path)
    rules = DraftRulesArtifact(
        artifact_id=uuid4(),
        run_id=context.run_id,
        task_id=context.task_id,
        attempt=1,
        draft_artifact_id=draft.artifact_id,
        input_fingerprint="1" * 64,
        report=DraftRulesReport(
            draft_id=draft.draft.draft_id,
            draft_version=1,
            quality_issues=(
                ReviewIssue(
                    issue_id="quality:TEST:global",
                    severity=IssueSeverity.WARNING,
                    code="TEST",
                    message="程序发现",
                ),
            ),
            governance=GovernanceReport(status="PASS", issues=()),
        ),
        created_at=datetime.now(UTC),
    )
    state = repository.load(context.run_id)
    from sector_pulse.domain.orchestration.models import ArtifactRef

    repository.save(
        state.model_copy(
            update={
                "revision": state.revision + 1,
                "artifacts": (
                    *state.artifacts,
                    ArtifactRef(
                        artifact_id=rules.artifact_id,
                        task_id=context.task_id,
                        kind="draft_rules",
                        reference=f"draft-rules:{rules.artifact_id}",
                    ),
                ),
            }
        ),
        state.revision,
        "rules.added",
    )

    class Rules:
        def get(self, identity):
            return rules if identity == rules.artifact_id else None

    service = SubmitReviewService(
        orchestration=repository,
        committer=type("Committer", (), {"commit": lambda self, artifact, **kwargs: artifact})(),
        rules=Rules(),
    )
    with pytest.raises(ValueError, match="program findings"):
        service.submit(
            context=context,
            draft_artifact_id=draft.artifact_id,
            rules_artifact_id=rules.artifact_id,
            submission=ReviewSubmission(decision=ReviewDecision.PASS, issues=()),
        )
    with pytest.raises(ValueError, match="unknown section"):
        service.submit(
            context=context,
            draft_artifact_id=draft.artifact_id,
            rules_artifact_id=rules.artifact_id,
            submission=ReviewSubmission(
                decision=ReviewDecision.REVISE,
                issues=(
                    ReviewIssue(
                        issue_id="review:unknown",
                        severity=IssueSeverity.WARNING,
                        code="UNCLEAR",
                        message="需修改",
                        section_id="not-a-section",
                    ),
                ),
            ),
        )
    corrected = service.submit(
        context=context,
        draft_artifact_id=draft.artifact_id,
        rules_artifact_id=rules.artifact_id,
        submission=ReviewSubmission(
            decision=ReviewDecision.REVISE,
            issues=(
                ReviewIssue(
                    issue_id="review:section-1",
                    severity=IssueSeverity.WARNING,
                    code="CLARIFY",
                    message="明确主体",
                    section_id="section-1",
                ),
            ),
        ),
    )
    assert corrected.report.draft_version == 1

    with pytest.raises(ValueError, match="pinned draft version"):
        service.submit(
            context=context.model_copy(update={"draft": newer}),
            draft_artifact_id=newer.artifact_id,
            rules_artifact_id=rules.artifact_id,
            submission=ReviewSubmission(
                decision=ReviewDecision.REVISE,
                issues=corrected.report.issues,
            ),
        )
    with pytest.raises(ValueError, match="A4"):
        service.submit(
            context=context.model_copy(update={"role": "A3"}),
            draft_artifact_id=draft.artifact_id,
            rules_artifact_id=rules.artifact_id,
            submission=ReviewSubmission(
                decision=ReviewDecision.REVISE,
                issues=corrected.report.issues,
            ),
        )


@pytest.mark.asyncio
async def test_t13_t14_sqlite_persist_immutable_artifacts_and_replay(tmp_path):
    import json

    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.review_tools import (
        CheckDraftRulesService,
        SubmitReviewService,
    )
    from sector_pulse.application.review.governance_service import GovernanceService
    from sector_pulse.domain.review.review import ReviewDecision
    from sector_pulse.infrastructure.agents.review_tools import (
        CheckDraftRulesTool,
        SubmitReviewTool,
    )
    from sector_pulse.storage.sqlite.writing.editorial_repository import (
        SQLiteDraftRulesRepository,
        SQLiteIndependentReviewRepository,
    )

    repository, context, _, draft, _ = build_review_context(tmp_path)
    with repository.database.transaction() as connection:
        connection.execute(
            "INSERT INTO analysis_runs (run_id, mode, requested_at) VALUES (?, ?, ?)",
            (str(context.run_id), "LIVE", datetime.now(UTC).isoformat()),
        )
        connection.execute(
            "INSERT INTO editorial_outline_artifacts "
            "(outline_id, run_id, task_id, attempt, selection_version, input_fingerprint, "
            "outline_hash, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(draft.outline_id), str(context.run_id), str(draft.task_id), 1, 1,
                "a" * 64, "b" * 64, "{}", datetime.now(UTC).isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO editorial_draft_artifacts "
            "(artifact_id, draft_id, run_id, task_id, attempt, version, outline_id, "
            "input_fingerprint, draft_hash, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(draft.artifact_id), str(draft.draft.draft_id), str(context.run_id),
                str(draft.task_id), 1, 1, str(draft.outline_id), "c" * 64, "d" * 64,
                draft.model_dump_json(), datetime.now(UTC).isoformat(),
            ),
        )
    rules_repo = SQLiteDraftRulesRepository(repository.database)
    review_repo = SQLiteIndependentReviewRepository(repository.database)
    committer = AtomicArtifactCommitter(repository, context.run_id)
    check_tool = CheckDraftRulesTool(
        CheckDraftRulesService(
            orchestration=repository,
            committer=committer,
            governance=GovernanceService(),
        ),
        rules=rules_repo,
        context=context,
    )
    assert set(check_tool.parameters["properties"]) == {"draft_artifact_id"}
    checked = await check_tool.run(draft_artifact_id=str(draft.artifact_id))
    assert checked.success
    rules_id = json.loads(checked.content)["artifact_refs"][0]
    assert check_tool.replay(f"draft-rules:{rules_id}").content == checked.content

    review_tool = SubmitReviewTool(
        SubmitReviewService(
            orchestration=repository,
            committer=committer,
            rules=rules_repo,
        ),
        reviews=review_repo,
        context=context,
    )
    assert set(review_tool.parameters["properties"]) == {
        "draft_artifact_id", "rules_artifact_id", "submission"
    }
    reviewed = await review_tool.run(
        draft_artifact_id=str(draft.artifact_id),
        rules_artifact_id=rules_id,
        submission={"decision": ReviewDecision.PASS.value, "issues": []},
    )
    assert reviewed.success
    review_id = json.loads(reviewed.content)["artifact_refs"][0]
    assert review_tool.replay(f"independent-review:{review_id}").content == reviewed.content
    rejected_second = await review_tool.run(
        draft_artifact_id=str(draft.artifact_id),
        rules_artifact_id=rules_id,
        submission={
            "decision": ReviewDecision.BLOCK.value,
            "issues": [
                {
                    "issue_id": "review:block",
                    "severity": "BLOCKING",
                    "code": "BLOCK",
                    "message": "阻断",
                }
            ],
        },
    )
    assert not rejected_second.success
    assert review_repo.get(UUID(review_id)).report.decision is ReviewDecision.PASS
    assert rules_repo.get(uuid4()) is None
    assert review_repo.get(uuid4()) is None


@pytest.mark.postgres
def test_t13_t14_postgres_persist_version_bound_review_artifacts():
    import os

    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.editorial_context import BoundReviewContext
    from sector_pulse.application.orchestration.review_tools import (
        CheckDraftRulesService,
        SubmitReviewService,
    )
    from sector_pulse.application.review.governance_service import GovernanceService
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.domain.review.review import ReviewDecision
    from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
    from sector_pulse.domain.writing.editorial import (
        EditorialDraftArtifact,
        ReviewSubmission,
    )
    from sector_pulse.storage.postgres.database import PostgresDatabase
    from sector_pulse.storage.postgres.orchestration.repository import (
        PostgresOrchestrationRepository,
    )
    from sector_pulse.storage.postgres.writing.editorial_repository import (
        PostgresDraftRulesRepository,
        PostgresIndependentReviewRepository,
    )
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    url = os.getenv("SECTOR_PULSE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires dedicated SECTOR_PULSE_TEST_DATABASE_URL")
    assert (make_url(url).database or "").endswith("_test"), "business database refused"
    database = PostgresDatabase(url)
    database.initialize()
    now = datetime.now(UTC)
    run_id, root_id, writer_id, reviewer_id = uuid4(), uuid4(), uuid4(), uuid4()
    outline_id, draft_id, draft_artifact_id = uuid4(), uuid4(), uuid4()
    draft = EditorialDraftArtifact(
        artifact_id=draft_artifact_id,
        run_id=run_id,
        task_id=writer_id,
        attempt=1,
        outline_id=outline_id,
        input_fingerprint="a" * 64,
        draft_hash="b" * 64,
        draft=ArticleDraft(
            draft_id=draft_id,
            run_id=run_id,
            version=1,
            status=DraftStatus.UNREVIEWED,
            titles=("测试",),
            introduction="导语",
            sections=(),
            conclusion="结语",
            risk_notice="风险",
            sources=(),
            character_count=4,
        ),
        created_at=now,
    )
    draft_ref = ArtifactRef(
        artifact_id=draft_artifact_id,
        task_id=writer_id,
        kind="article_draft",
        reference=f"article-draft:{draft_artifact_id}",
    )
    reviewer = TaskRecord(
        task_id=reviewer_id,
        parent_id=root_id,
        role="A4",
        scope=f"review:{draft_id}:1",
        status=TaskStatus.RUNNING,
        worker_id="pg-reviewer",
        lease_expires_at=now + timedelta(minutes=3),
        input_artifact_ids=(draft_artifact_id,),
    )
    orchestration = PostgresOrchestrationRepository(database)
    try:
        with database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO analysis_runs (run_id, mode, requested_at) "
                    "VALUES (:run_id, 'LIVE', :now)"
                ),
                {"run_id": str(run_id), "now": now.isoformat()},
            )
            connection.execute(
                text(
                    "INSERT INTO editorial_outline_artifacts "
                    "(outline_id, run_id, task_id, attempt, selection_version, "
                    "input_fingerprint, outline_hash, payload_json, created_at) VALUES "
                    "(:outline_id, :run_id, :task_id, 1, 1, :fingerprint, :hash, '{}', :now)"
                ),
                {
                    "outline_id": str(outline_id),
                    "run_id": str(run_id),
                    "task_id": str(writer_id),
                    "fingerprint": "c" * 64,
                    "hash": "d" * 64,
                    "now": now.isoformat(),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO editorial_draft_artifacts "
                    "(artifact_id, draft_id, run_id, task_id, attempt, version, outline_id, "
                    "input_fingerprint, draft_hash, payload_json, created_at) VALUES "
                    "(:artifact_id, :draft_id, :run_id, :task_id, 1, 1, :outline_id, "
                    ":fingerprint, :hash, :payload, :now)"
                ),
                {
                    "artifact_id": str(draft_artifact_id),
                    "draft_id": str(draft_id),
                    "run_id": str(run_id),
                    "task_id": str(writer_id),
                    "outline_id": str(outline_id),
                    "fingerprint": "a" * 64,
                    "hash": "b" * 64,
                    "payload": draft.model_dump_json(),
                    "now": now.isoformat(),
                },
            )
        orchestration.save(
            RunSnapshot(
                run_id=run_id,
                deadline=now + timedelta(minutes=10),
                tasks=(
                    TaskRecord(task_id=root_id, role="A0", scope="run"),
                    TaskRecord(
                        task_id=writer_id,
                        parent_id=root_id,
                        role="A3",
                        scope=f"article:{run_id}",
                        status=TaskStatus.COMPLETED,
                    ),
                    reviewer,
                ),
                artifacts=(draft_ref,),
            ),
            -1,
            "review.pg-created",
        )
        context = BoundReviewContext(
            run_id=run_id,
            task_id=reviewer_id,
            attempt=1,
            worker_id="pg-reviewer",
            role="A4",
            draft=draft,
            analyses=(),
            input_artifacts=(draft_ref,),
        )
        committer = AtomicArtifactCommitter(orchestration, run_id)
        rules = CheckDraftRulesService(
            orchestration=orchestration,
            committer=committer,
            governance=GovernanceService(),
        ).check(context=context, draft_artifact_id=draft_artifact_id, now=now)
        rules_repo = PostgresDraftRulesRepository(database)
        assert rules_repo.get(rules.artifact_id) == rules
        review = SubmitReviewService(
            orchestration=orchestration,
            committer=committer,
            rules=rules_repo,
        ).submit(
            context=context,
            draft_artifact_id=draft_artifact_id,
            rules_artifact_id=rules.artifact_id,
            submission=ReviewSubmission(decision=ReviewDecision.REVISE, issues=()),
            now=now,
        )
        assert PostgresIndependentReviewRepository(database).get(review.artifact_id) == review
        assert review.report.draft_version == 1
        assert review.report.decision is ReviewDecision.REVISE
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
