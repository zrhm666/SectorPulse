"""A multi-agent run must be reviewable in the existing workbench, unchanged.

The legacy workbench reads `article_drafts` through the human CAS repository. A
multi-agent run never writes there: its draft is an `editorial_draft_artifacts`
row admitted under the orchestration revision. The compatibility layer has to
project that artifact into the workbench on first read, so an operator reviews,
edits, approves and exports an agent draft exactly as they did a legacy one —
without the run's history being rewritten to make that possible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sector_pulse.domain.orchestration.models import ArtifactRef, RunSnapshot, TaskRecord

pytest.importorskip("aidynamic_agent")


def _seed_agent_only_run(tmp_path):
    """One multi-agent run whose only draft lives in the editorial artifact store."""
    from sector_pulse.domain.writing.article import (
        ArticleDraft,
        ArticleSection,
        ArticleSource,
        DraftStatus,
    )
    from sector_pulse.domain.writing.editorial import EditorialDraftArtifact
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import (
        SQLiteOrchestrationRepository,
    )

    path = tmp_path / "agent-draft.db"
    database = SQLiteDatabase(path)
    database.initialize()
    now = datetime.now(UTC)
    run_id, root_id, writer_id, reviewer_id = uuid4(), uuid4(), uuid4(), uuid4()
    outline_id, draft_id, artifact_id = uuid4(), uuid4(), uuid4()
    draft = ArticleDraft(
        draft_id=draft_id,
        run_id=run_id,
        version=1,
        status=DraftStatus.UNREVIEWED,
        titles=("板块观察",),
        introduction="今日市场出现结构性变化。",
        sections=(
            ArticleSection(
                section_id="section-1",
                sector_id="sector-1",
                heading="半导体",
                body="半导体板块出现异动。",
                claims=(),
                source_ids=("source-1",),
                character_count=10,
            ),
        ),
        conclusion="以上仅为公开信息梳理。",
        risk_notice="市场有风险，信息仅供研究参考。",
        sources=(
            ArticleSource(
                source_id="source-1",
                title="来源",
                citation_url="https://example.test/source",
            ),
        ),
        character_count=60,
    )
    artifact = EditorialDraftArtifact(
        artifact_id=artifact_id,
        run_id=run_id,
        task_id=writer_id,
        attempt=1,
        outline_id=outline_id,
        input_fingerprint="a" * 64,
        draft_hash="b" * 64,
        draft=draft,
        created_at=now,
    )
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO analysis_runs (run_id, mode, requested_at) VALUES (?, ?, ?)",
            (str(run_id), "LIVE", now.isoformat()),
        )
        connection.execute(
            "INSERT INTO editorial_outline_artifacts "
            "(outline_id, run_id, task_id, attempt, selection_version, input_fingerprint, "
            "outline_hash, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(outline_id), str(run_id), str(writer_id), 1, 1,
                "c" * 64, "d" * 64, "{}", now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO editorial_draft_artifacts "
            "(artifact_id, draft_id, run_id, task_id, attempt, version, outline_id, "
            "input_fingerprint, draft_hash, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(artifact_id), str(draft_id), str(run_id), str(writer_id), 1, 1,
                str(outline_id), "a" * 64, "b" * 64, artifact.model_dump_json(),
                now.isoformat(),
            ),
        )
    rules = _rules_artifact(run_id, writer_id, artifact_id, draft_id, now)
    review = _review_artifact(run_id, reviewer_id, artifact_id, rules.artifact_id, draft_id, now)
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO draft_rules_artifacts "
            "(artifact_id, run_id, task_id, attempt, draft_artifact_id, draft_id, "
            "draft_version, input_fingerprint, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(rules.artifact_id), str(run_id), str(reviewer_id), 1,
                str(artifact_id), str(draft_id), 1, "e" * 64,
                rules.model_dump_json(), now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO independent_review_artifacts "
            "(artifact_id, run_id, task_id, attempt, draft_artifact_id, rules_artifact_id, "
            "draft_id, draft_version, decision, input_fingerprint, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(review.artifact_id), str(run_id), str(reviewer_id), 1,
                str(artifact_id), str(rules.artifact_id), str(draft_id), 1,
                review.report.decision.value, "f" * 64, review.model_dump_json(),
                now.isoformat(),
            ),
        )
    repository = SQLiteOrchestrationRepository(database)
    repository.save(
        RunSnapshot(
            run_id=run_id,
            requested_at=now,
            deadline=now + timedelta(minutes=30),
            tasks=(
                TaskRecord(task_id=root_id, role="A0", scope="分析半导体板块"),
                TaskRecord(
                    task_id=writer_id,
                    parent_id=root_id,
                    role="A3",
                    scope=f"article:{run_id}",
                ),
                TaskRecord(
                    task_id=reviewer_id,
                    parent_id=root_id,
                    role="A4",
                    scope=f"review:{draft_id}:1",
                    input_artifact_ids=(artifact_id,),
                ),
            ),
            artifacts=(
                ArtifactRef(
                    artifact_id=artifact_id,
                    task_id=writer_id,
                    kind="article_draft",
                    reference=f"article-draft:{artifact_id}",
                ),
                ArtifactRef(
                    artifact_id=review.artifact_id,
                    task_id=reviewer_id,
                    kind="independent_review",
                    reference=f"independent-review:{review.artifact_id}",
                ),
            ),
        ),
        -1,
        "run.created",
    )
    return TestClient(create_app_under_test(path)), draft, database


def _rules_artifact(run_id, task_id, draft_artifact_id, draft_id, now):
    from uuid import uuid4

    from sector_pulse.application.review.governance_service import GovernanceReport
    from sector_pulse.domain.writing.editorial import DraftRulesArtifact, DraftRulesReport

    return DraftRulesArtifact(
        artifact_id=uuid4(),
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        draft_artifact_id=draft_artifact_id,
        input_fingerprint="e" * 64,
        report=DraftRulesReport(
            draft_id=draft_id,
            draft_version=1,
            quality_issues=(),
            governance=GovernanceReport(status="PASS", issues=()),
        ),
        created_at=now,
    )


def _review_artifact(run_id, task_id, draft_artifact_id, rules_artifact_id, draft_id, now):
    from uuid import uuid4

    from sector_pulse.domain.review.review import ReviewDecision, ReviewReport
    from sector_pulse.domain.writing.editorial import IndependentReviewArtifact

    return IndependentReviewArtifact(
        artifact_id=uuid4(),
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        draft_artifact_id=draft_artifact_id,
        rules_artifact_id=rules_artifact_id,
        input_fingerprint="f" * 64,
        report=ReviewReport(
            review_id=str(uuid4()),
            draft_id=str(draft_id),
            draft_version=1,
            decision=ReviewDecision.PASS,
            issues=(),
            revision_round=1,
        ),
        created_at=now,
    )


def create_app_under_test(database_path):
    from sector_pulse.web.app import create_app

    return create_app(database_path=database_path, static_dir=None)


def test_the_run_reads_as_multi_agent_and_points_at_the_agent_draft(tmp_path) -> None:
    client, draft, _ = _seed_agent_only_run(tmp_path)

    detail = client.get(f"/api/runs/{draft.run_id}")

    assert detail.status_code == 200
    assert detail.json()["execution_engine"] == "multi_agent"
    assert detail.json()["draft_id"] == str(draft.draft_id)


def test_the_workbench_serves_the_agent_draft_without_a_human_row(tmp_path) -> None:
    client, draft, _ = _seed_agent_only_run(tmp_path)
    base = f"/api/runs/{draft.run_id}"

    versions = client.get(f"{base}/draft")
    governance = client.get(f"{base}/governance")
    audit = client.get(f"{base}/drafts/{draft.draft_id}/audit")

    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()["versions"]] == [1]
    assert governance.status_code == 200
    assert governance.json()["status"] == "PASS"
    # No human action yet, so the trail is empty rather than missing.
    assert audit.status_code == 200
    assert audit.json() == []


def test_an_operator_can_approve_and_export_the_reviewed_agent_draft(tmp_path) -> None:
    """The A4 review travels through the workbench with the draft it reviewed."""
    client, draft, _ = _seed_agent_only_run(tmp_path)
    base = f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}"
    headers = {"X-Actor": "editor-on-duty"}

    review = client.get(f"/api/runs/{draft.run_id}/review")
    assert review.status_code == 200
    assert review.json()["decision"] == "PASS"
    assert review.json()["draft_version"] == 1

    approved = client.post(f"{base}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["version"] == 1

    exported = client.get(f"{base}/export.json", headers=headers)
    assert exported.status_code == 200, exported.text
    assert exported.json()["introduction"] == draft.introduction
    assert exported.json()["version"] == 1


def test_an_operator_edit_requires_a_fresh_review_before_release(tmp_path) -> None:
    """Editing an agent draft is allowed; releasing unreviewed text is not."""
    client, draft, _ = _seed_agent_only_run(tmp_path)
    base = f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}"
    headers = {"X-Actor": "editor-on-duty"}

    patched = client.post(
        f"{base}/patches",
        headers=headers,
        json={
            "base_version": 1,
            "operations": [
                {
                    "path": "introduction",
                    "old_value_hash": sha256(draft.introduction.encode()).hexdigest(),
                    "value": "人工改写后的导语",
                }
            ],
        },
    )
    assert patched.status_code == 201, patched.text
    assert patched.json()["version"] == 2

    refused = client.post(f"{base}/approve", headers=headers)
    assert refused.status_code == 409
    assert "review" in refused.json()["error"]["message"]


def test_the_projection_does_not_rewrite_the_agent_artifact(tmp_path) -> None:
    """Reading is a projection; the agent's own row stays exactly as it was."""
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.writing.editorial_repository import (
        SQLiteEditorialDraftRepository,
    )

    client, draft, database = _seed_agent_only_run(tmp_path)
    before = SQLiteEditorialDraftRepository(database).latest_version(draft.draft_id)

    # The audit read is the workbench's entry point into human ownership.
    assert client.get(f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}/audit").status_code == 200

    after = SQLiteEditorialDraftRepository(database).latest_version(draft.draft_id)
    assert after == before
    # The legacy store now serves it, so the workbench is not read-through on
    # every request and its own CAS still owns the human edit that follows.
    with SQLiteDatabase(tmp_path / "agent-draft.db").connection() as connection:
        rows = connection.execute(
            "SELECT version FROM article_drafts WHERE draft_id = ?",
            (str(draft.draft_id),),
        ).fetchall()
    assert [row[0] for row in rows] == [1]


def test_a_legacy_run_without_a_snapshot_still_reads_unchanged(tmp_path) -> None:
    """The compatibility layer must not make a legacy draft depend on a snapshot."""
    from sector_pulse.domain.writing.article import (
        ArticleDraft,
        ArticleSection,
        ArticleSource,
        DraftStatus,
    )
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.runs.phase1b_runs_repository import (
        Phase1BRunRow,
        SQLitePhase1BRunsRepository,
    )
    from sector_pulse.storage.sqlite.writing.phase1b_repository import (
        SQLitePhase1BRepository,
    )

    path = tmp_path / "legacy.db"
    database = SQLiteDatabase(path)
    draft = ArticleDraft(
        draft_id=uuid4(),
        run_id=uuid4(),
        version=1,
        status=DraftStatus.INCOMPLETE,
        titles=("标题",),
        introduction="导语",
        sections=(
            ArticleSection(
                section_id="section-1",
                sector_id="sector-1",
                heading="板块",
                body="正文",
                claims=(),
                source_ids=("source-1",),
                character_count=2,
            ),
        ),
        conclusion="结论",
        risk_notice="风险",
        sources=(
            ArticleSource(
                source_id="source-1",
                title="来源",
                citation_url="https://example.test/source",
            ),
        ),
        character_count=8,
    )
    SQLitePhase1BRepository(database).save_draft(draft)
    SQLitePhase1BRunsRepository(database).insert(
        Phase1BRunRow(
            run_id=draft.run_id,
            requested_at=datetime(2026, 8, 20, 9, tzinfo=UTC),
            provider="fixture",
            status="READY_FOR_HUMAN_REVIEW",
            draft_id=draft.draft_id,
        )
    )
    client = TestClient(create_app_under_test(path))

    detail = client.get(f"/api/runs/{draft.run_id}")

    assert detail.status_code == 200
    assert detail.json()["execution_engine"] == "legacy"
    assert detail.json()["draft_id"] == str(draft.draft_id)


def test_the_workbench_hands_the_editor_the_revision_its_edit_must_state(tmp_path) -> None:
    """The draft payload carries the snapshot revision the editor read.

    Without it the workbench can only send `base_version`, which the agent's
    writes never touch, so the shared CAS guard would never fire from the
    product surface. The revision has to reach the editor for the guard to be
    real rather than merely implemented.
    """
    client, draft, database = _seed_agent_only_run(tmp_path)
    base = f"/api/runs/{draft.run_id}"

    revision = client.get(f"{base}/draft").json()["revision"]
    from sector_pulse.storage.sqlite.orchestration.repository import (
        SQLiteOrchestrationRepository,
    )

    assert revision == SQLiteOrchestrationRepository(database).load(draft.run_id).revision

    patched = client.post(
        f"{base}/drafts/{draft.draft_id}/patches",
        headers={"X-Actor": "editor-on-duty"},
        json={
            "base_version": 1,
            "base_revision": revision,
            "operations": [
                {
                    "path": "introduction",
                    "old_value_hash": sha256(draft.introduction.encode()).hexdigest(),
                    "value": "人工改写后的导语",
                }
            ],
        },
    )

    assert patched.status_code == 201, patched.text
    assert patched.json()["version"] == 2
    # The edit moved the shared counter, so the agent's next write loses.
    assert SQLiteOrchestrationRepository(database).load(draft.run_id).revision == revision + 1


def test_an_edit_based_on_a_revision_the_agent_already_passed_is_refused(tmp_path) -> None:
    """The editor's stale revision must lose rather than overwrite the agent."""
    from sector_pulse.storage.sqlite.orchestration.repository import (
        SQLiteOrchestrationRepository,
    )

    client, draft, database = _seed_agent_only_run(tmp_path)
    base = f"/api/runs/{draft.run_id}"
    repository = SQLiteOrchestrationRepository(database)
    stale_revision = client.get(f"{base}/draft").json()["revision"]

    # The agent admits a revision while the editor is still reading the draft.
    current = repository.load(draft.run_id)
    repository.save(
        current.model_copy(update={"revision": current.revision + 1}),
        current.revision,
        "artifact.admitted",
    )

    refused = client.post(
        f"{base}/drafts/{draft.draft_id}/patches",
        headers={"X-Actor": "editor-on-duty"},
        json={
            "base_version": 1,
            "base_revision": stale_revision,
            "operations": [
                {
                    "path": "introduction",
                    "old_value_hash": sha256(draft.introduction.encode()).hexdigest(),
                    "value": "基于旧版本的改写",
                }
            ],
        },
    )

    assert refused.status_code == 409
    # The revision guard is what fired, not the draft-version one.
    assert "revision" in refused.json()["error"]["message"]
    # Nothing half-applied: the human edit never landed.
    assert client.get(f"{base}/draft").json()["versions"][0]["introduction"] == draft.introduction
