from datetime import UTC, datetime, timedelta
from uuid import uuid4


def test_multi_agent_query_adapter_projects_root_task_status():
    from sector_pulse.application.orchestration.query_adapter import MultiAgentRunQueryAdapter
    from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord, TaskStatus

    run_id = uuid4()
    requested_at = datetime(2026, 9, 15, 1, 2, tzinfo=UTC)
    root = TaskRecord(task_id=uuid4(), role="A0", scope="prepare", status=TaskStatus.WAITING)
    snapshot = RunSnapshot(
        run_id=run_id,
        requested_at=requested_at,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        tasks=(root,),
    )

    class Repository:
        def load(self, requested):
            return snapshot if requested == run_id else None

        def list_snapshots(self, limit=50):
            return [snapshot][:limit]

    detail = MultiAgentRunQueryAdapter(Repository()).get_run(run_id)

    assert detail is not None
    assert detail.status == "WAITING"
    assert detail.provider == "fixture"
    assert detail.execution_engine == "multi_agent"
    assert detail.requested_at == requested_at
    assert [item.run_id for item in MultiAgentRunQueryAdapter(Repository()).list_runs()] == [
        run_id
    ]


def test_multi_agent_query_adapter_is_refresh_stable_and_children_do_not_finish_the_run():
    from sector_pulse.application.orchestration.query_adapter import MultiAgentRunQueryAdapter
    from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord, TaskStatus

    run_id = uuid4()
    root_id = uuid4()
    child_id = uuid4()
    requested_at = datetime(2026, 9, 15, 1, 2, tzinfo=UTC)
    snapshot = RunSnapshot(
        run_id=run_id,
        requested_at=requested_at,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        tasks=(
            TaskRecord(
                task_id=root_id,
                role="A0",
                scope="prepare",
                status=TaskStatus.RUNNING,
                worker_id="worker-1",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
            ),
            TaskRecord(
                task_id=child_id,
                parent_id=root_id,
                role="A2",
                scope="sector-1",
                status=TaskStatus.COMPLETED,
            ),
        ),
    )

    class Repository:
        def load(self, requested):
            return snapshot if requested == run_id else None

    adapter = MultiAgentRunQueryAdapter(Repository())
    first = adapter.get_run(run_id)
    second = adapter.get_run(run_id)

    assert first == second
    assert first.requested_at == requested_at
    assert first.status == "RUNNING"

    trace = adapter.get_agent_trace(run_id)
    record = {task["task_id"]: task for task in trace["tasks"]}
    assert record[str(root_id)]["status"] == "running"
    assert record[str(child_id)]["status"] == "completed"
    assert record[str(child_id)]["parent_id"] == str(root_id)
    assert record[str(root_id)]["parent_id"] is None


def test_multi_agent_query_adapter_keeps_legacy_runs_readable_without_duplicates():
    from types import SimpleNamespace

    from sector_pulse.application.orchestration.query_adapter import MultiAgentRunQueryAdapter
    from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord

    current_id = uuid4()
    historical_id = uuid4()
    snapshot = RunSnapshot(
        run_id=current_id,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        tasks=(TaskRecord(task_id=uuid4(), role="A0", scope="prepare"),),
    )

    class Repository:
        def load(self, requested):
            return snapshot if requested == current_id else None

        def list_snapshots(self, limit=50):
            return [snapshot][:limit]

    historical = SimpleNamespace(run_id=historical_id, execution_engine="legacy")
    duplicate = SimpleNamespace(run_id=current_id, execution_engine="legacy")
    legacy = SimpleNamespace(
        list_runs=lambda limit=50: [historical, duplicate][:limit],
        get_run=lambda requested: historical if requested == historical_id else None,
    )
    adapter = MultiAgentRunQueryAdapter(Repository(), legacy=legacy)

    assert [item.run_id for item in adapter.list_runs()] == [current_id, historical_id]
    assert adapter.get_run(historical_id) is historical


def test_multi_agent_query_adapter_projects_task_tree_and_audit_ledger():
    from sector_pulse.application.orchestration.query_adapter import MultiAgentRunQueryAdapter
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        BudgetLedger,
        BudgetReservation,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
        ToolInvocation,
    )

    run_id = uuid4()
    root_id = uuid4()
    child_id = uuid4()
    snapshot = RunSnapshot(
        run_id=run_id,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        tasks=(
            TaskRecord(
                task_id=root_id,
                role="A0",
                scope="prepare",
                status=TaskStatus.RUNNING,
                worker_id="worker-1",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
            ),
            TaskRecord(
                task_id=child_id,
                parent_id=root_id,
                role="A1",
                scope="collect",
                status=TaskStatus.COMPLETED,
            ),
        ),
        artifacts=(
            ArtifactRef(
                artifact_id=uuid4(),
                task_id=child_id,
                kind="market_snapshot",
                reference="market:1",
            ),
        ),
        ledger=BudgetLedger(
            reservations=(BudgetReservation(call_id="m1", reserved_tokens=10),),
            tool_invocations=(
                ToolInvocation(
                    call_id="t1",
                    task_id=child_id,
                    attempt=1,
                    role="A1",
                    tool_name="collect_market",
                    input_fingerprint="0" * 64,
                ),
            ),
        ),
    )

    class Repository:
        def load(self, requested):
            return snapshot if requested == run_id else None

    trace = MultiAgentRunQueryAdapter(Repository()).get_agent_trace(run_id)

    assert [task["role"] for task in trace["tasks"]] == ["A0", "A1"]
    assert trace["tasks"][1]["parent_id"] == str(root_id)
    assert trace["model_calls"][0]["call_id"] == "m1"
    assert trace["tool_invocations"][0]["tool_name"] == "collect_market"
    assert trace["artifacts"] == [
        {
            "artifact_id": str(snapshot.artifacts[0].artifact_id),
            "task_id": str(child_id),
            "attempt": 1,
            "kind": "market_snapshot",
            "reference": "market:1",
        }
    ]


def test_multi_agent_query_adapter_renders_latest_ready_draft():
    from types import SimpleNamespace

    from sector_pulse.application.orchestration.query_adapter import MultiAgentRunQueryAdapter
    from sector_pulse.domain.orchestration.models import ArtifactRef, RunSnapshot, TaskRecord
    from sector_pulse.domain.writing.article import (
        ArticleDraft,
        ArticleSection,
        ArticleSource,
        DraftStatus,
    )

    run_id = uuid4()
    task_id = uuid4()
    artifact_id = uuid4()
    draft = ArticleDraft(
        draft_id=uuid4(),
        run_id=run_id,
        version=2,
        status=DraftStatus.READY_FOR_HUMAN_REVIEW,
        titles=("标题",),
        introduction="导语",
        sections=tuple(
            ArticleSection(
                section_id=f"s{index}",
                sector_id=f"sector-{index}",
                heading=f"板块 {index}",
                body="正文" * 100,
                claims=(),
                source_ids=("source-1",),
                character_count=200,
            )
            for index in range(3)
        ),
        conclusion="结论",
        risk_notice="风险提示",
        sources=(ArticleSource(source_id="source-1", title="来源", citation_url="https://example"),),
        character_count=1200,
    )
    snapshot = RunSnapshot(
        run_id=run_id,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        tasks=(TaskRecord(task_id=task_id, role="A3", scope="draft"),),
        artifacts=(
            ArtifactRef(
                artifact_id=artifact_id,
                task_id=task_id,
                kind="article_draft",
                reference=str(draft.draft_id),
            ),
        ),
    )

    class Repository:
        def load(self, requested):
            return snapshot if requested == run_id else None

    storage = SimpleNamespace(
        editorial_drafts=SimpleNamespace(
            get=lambda requested: SimpleNamespace(draft=draft) if requested == artifact_id else None
        )
    )
    adapter = MultiAgentRunQueryAdapter(Repository(), storage)

    markdown = adapter.render_draft_markdown(run_id)
    text = adapter.render_draft_text(run_id)
    detail = adapter.get_run(run_id)

    assert adapter.latest_draft(run_id) == draft
    assert detail is not None
    assert detail.draft_id == draft.draft_id
    assert detail.sector_count == 3
    assert markdown is not None and "# 标题" in markdown and "## 板块 0" in markdown
    assert text is not None and "## " not in text
