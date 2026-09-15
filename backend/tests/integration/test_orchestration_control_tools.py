import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest


def setup_control_state(tmp_path):
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.domain.orchestration.models import ArtifactRef, RunSnapshot, TaskRecord
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "control-tools.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    root = TaskRecord(task_id=uuid4(), role="A0", scope="run")
    research_one = TaskRecord(
        task_id=uuid4(), parent_id=root.task_id, role="A2", scope="industry:1"
    )
    research_two = TaskRecord(
        task_id=uuid4(), parent_id=root.task_id, role="A2", scope="industry:2"
    )
    writer = TaskRecord(task_id=uuid4(), parent_id=root.task_id, role="A3", scope="article")
    artifacts = (
        ArtifactRef(
            artifact_id=uuid4(),
            task_id=root.task_id,
            kind="candidate_selection",
            reference="selection:1",
        ),
        ArtifactRef(
            artifact_id=uuid4(),
            task_id=research_one.task_id,
            kind="sector_analysis",
            reference="analysis:1",
        ),
        ArtifactRef(
            artifact_id=uuid4(),
            task_id=research_two.task_id,
            kind="sector_analysis",
            reference="analysis:2",
        ),
        ArtifactRef(
            artifact_id=uuid4(),
            task_id=writer.task_id,
            kind="draft",
            reference="draft:1",
        ),
    )
    snapshot = RunSnapshot(
        run_id=uuid4(),
        deadline=datetime.now(UTC) + timedelta(minutes=10),
        tasks=(root, research_one, research_two, writer),
        artifacts=artifacts,
    )
    repository.save(snapshot, -1, "created")
    coordinator = TaskCoordinator(repository, snapshot.run_id)
    lease = datetime.now(UTC) + timedelta(minutes=5)
    coordinator.start(root.task_id, attempt=1, worker_id="parent", lease_expires_at=lease)
    coordinator.start(
        research_one.task_id,
        attempt=1,
        worker_id="research-1",
        lease_expires_at=lease,
    )
    coordinator.start(
        research_two.task_id,
        attempt=1,
        worker_id="research-2",
        lease_expires_at=lease,
    )
    coordinator.start(writer.task_id, attempt=1, worker_id="writer", lease_expires_at=lease)
    return repository, snapshot, root, research_one, research_two, writer, artifacts


class StubArtifactReader:
    def read(self, artifact, *, max_chars):
        from sector_pulse.application.orchestration.controls import ArtifactContent

        return ArtifactContent(
            summary=(f"summary for {artifact.reference} " * 20),
            data={"safe_reference": artifact.reference},
        ).bounded(max_chars)


def test_t15_artifact_inspection_is_bounded_and_blocks_other_a2_scope(tmp_path):
    from sector_pulse.application.orchestration.controls import (
        ArtifactAccessDenied,
        ArtifactInspector,
    )

    repository, snapshot, _, research_one, _, _, artifacts = setup_control_state(tmp_path)
    inspector = ArtifactInspector(repository, snapshot.run_id, StubArtifactReader())

    visible = inspector.inspect(
        research_one.task_id,
        attempt=1,
        artifact_ids=(artifacts[0].artifact_id, artifacts[1].artifact_id),
        max_chars=60,
    )
    assert [item.artifact_id for item in visible] == [
        artifacts[0].artifact_id,
        artifacts[1].artifact_id,
    ]
    assert all(len(item.summary) <= 60 for item in visible)
    assert visible[0].data == {"safe_reference": "selection:1"}

    own_scope = inspector.inspect(
        research_one.task_id,
        attempt=1,
        kinds=("sector_analysis",),
    )
    assert [item.artifact_id for item in own_scope] == [artifacts[1].artifact_id]

    with pytest.raises(ArtifactAccessDenied, match="scope"):
        inspector.inspect(
            research_one.task_id,
            attempt=1,
            artifact_ids=(artifacts[2].artifact_id,),
        )


def test_t15_rejects_stale_attempt_and_unlisted_artifact_kind(tmp_path):
    from sector_pulse.application.orchestration.controls import (
        ArtifactAccessDenied,
        ArtifactInspector,
    )
    from sector_pulse.application.orchestration.tasks import TaskOwnershipError

    repository, snapshot, _, research_one, _, _, artifacts = setup_control_state(tmp_path)
    inspector = ArtifactInspector(repository, snapshot.run_id, StubArtifactReader())
    with pytest.raises(TaskOwnershipError, match="stale"):
        inspector.inspect(research_one.task_id, attempt=2)
    with pytest.raises(ArtifactAccessDenied, match="kind"):
        inspector.inspect(
            research_one.task_id,
            attempt=1,
            artifact_ids=(artifacts[3].artifact_id,),
        )


def test_t15_a2_reads_own_research_artifacts_but_not_another_a2_private_artifact(tmp_path):
    from sector_pulse.application.orchestration.controls import (
        ArtifactAccessDenied,
        ArtifactInspector,
    )
    from sector_pulse.domain.orchestration.models import ArtifactRef

    repository, snapshot, _, research_one, research_two, _, _ = setup_control_state(tmp_path)
    private_kinds = (
        "research_search",
        "news_detail",
        "evidence_inspection",
        "sector_analysis",
    )
    own = tuple(
        ArtifactRef(
            artifact_id=uuid4(),
            task_id=research_one.task_id,
            kind=kind,
            reference=f"{kind}:own",
        )
        for kind in private_kinds
    )
    other = ArtifactRef(
        artifact_id=uuid4(),
        task_id=research_two.task_id,
        kind="research_search",
        reference="research_search:other",
    )
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "artifacts": (*current.artifacts, *own, other),
            }
        ),
        current.revision,
        "research.private-artifacts",
    )
    inspector = ArtifactInspector(repository, snapshot.run_id, StubArtifactReader())

    visible = inspector.inspect(
        research_one.task_id,
        attempt=1,
        artifact_ids=tuple(item.artifact_id for item in own),
    )
    assert {item.kind for item in visible} == set(private_kinds)
    with pytest.raises(ArtifactAccessDenied, match="scope"):
        inspector.inspect(
            research_one.task_id,
            attempt=1,
            artifact_ids=(other.artifact_id,),
        )


def test_t15_a3_a4_private_artifacts_require_ownership_or_explicit_input(tmp_path):
    from sector_pulse.application.orchestration.controls import (
        ArtifactAccessDenied,
        ArtifactInspector,
    )
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.domain.orchestration.models import ArtifactRef, TaskRecord

    repository, snapshot, root, _, _, writer, _ = setup_control_state(tmp_path)
    own_draft = ArtifactRef(
        artifact_id=uuid4(),
        task_id=writer.task_id,
        kind="article_draft",
        reference="article-draft:own",
    )
    other_writer = TaskRecord(
        task_id=uuid4(), parent_id=root.task_id, role="A3", scope="article:other"
    )
    other_draft = ArtifactRef(
        artifact_id=uuid4(),
        task_id=other_writer.task_id,
        kind="article_draft",
        reference="article-draft:other",
    )
    reviewer = TaskRecord(
        task_id=uuid4(),
        parent_id=root.task_id,
        role="A4",
        scope="review:own:1",
        input_artifact_ids=(own_draft.artifact_id,),
    )
    review = ArtifactRef(
        artifact_id=uuid4(),
        task_id=reviewer.task_id,
        kind="independent_review",
        reference="independent-review:own",
    )
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "tasks": (*current.tasks, other_writer, reviewer),
                "artifacts": (*current.artifacts, own_draft, other_draft, review),
            }
        ),
        current.revision,
        "editorial.private-artifacts",
    )
    coordinator = TaskCoordinator(repository, snapshot.run_id)
    lease = datetime.now(UTC) + timedelta(minutes=2)
    coordinator.start(
        other_writer.task_id,
        attempt=1,
        worker_id="other-writer",
        lease_expires_at=lease,
    )
    coordinator.start(
        reviewer.task_id,
        attempt=1,
        worker_id="reviewer",
        lease_expires_at=lease,
    )
    inspector = ArtifactInspector(repository, snapshot.run_id, StubArtifactReader())

    assert inspector.inspect(
        writer.task_id, attempt=1, artifact_ids=(own_draft.artifact_id,)
    )[0].artifact_id == own_draft.artifact_id
    with pytest.raises(ArtifactAccessDenied, match="private"):
        inspector.inspect(
            writer.task_id, attempt=1, artifact_ids=(other_draft.artifact_id,)
        )
    assert inspector.inspect(
        reviewer.task_id, attempt=1, artifact_ids=(own_draft.artifact_id,)
    )[0].artifact_id == own_draft.artifact_id
    assert inspector.inspect(
        reviewer.task_id, attempt=1, artifact_ids=(review.artifact_id,)
    )[0].artifact_id == review.artifact_id
    with pytest.raises(ArtifactAccessDenied, match="private"):
        inspector.inspect(
            reviewer.task_id, attempt=1, artifact_ids=(other_draft.artifact_id,)
        )


def test_t17_only_a0_can_inspect_exact_task_states_and_safe_artifact_refs(tmp_path):
    from sector_pulse.application.orchestration.controls import TaskInspector
    from sector_pulse.application.orchestration.tasks import TaskCoordinator, TaskOwnershipError
    from sector_pulse.domain.orchestration.models import TaskStatus

    repository, snapshot, root, research_one, research_two, _, artifacts = setup_control_state(
        tmp_path
    )
    TaskCoordinator(repository, snapshot.run_id).fail(
        research_one.task_id,
        attempt=1,
        worker_id="research-1",
        public_error_code="EVIDENCE_INSUFFICIENT",
    )
    task_inspector = TaskInspector(repository, snapshot.run_id)
    tasks = task_inspector.inspect(root.task_id, attempt=1)
    research = next(item for item in tasks if item.task_id == research_one.task_id)
    assert research.status is TaskStatus.FAILED
    assert research.artifact_ids == (artifacts[1].artifact_id,)
    assert research.public_error_code == "EVIDENCE_INSUFFICIENT"
    with pytest.raises(TaskOwnershipError, match="A0"):
        task_inspector.inspect(research_two.task_id, attempt=1)


def test_t18_selection_request_waits_without_creating_user_confirmation(tmp_path):
    from sector_pulse.application.orchestration.controls import SelectionController
    from sector_pulse.domain.orchestration.models import ArtifactRef, TaskStatus

    repository, snapshot, root, _, _, _, _ = setup_control_state(tmp_path)
    proposal = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root.task_id,
        kind="candidate_proposal",
        reference="proposal:1",
    )
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "artifacts": (*current.artifacts, proposal),
            }
        ),
        current.revision,
        "proposal.created",
    )
    result = SelectionController(repository, snapshot.run_id).request(
        root.task_id,
        attempt=1,
        worker_id="parent",
        proposal_id=proposal.artifact_id,
    )
    assert result.status is TaskStatus.WAITING_USER_SELECTION
    state = repository.load(snapshot.run_id)
    assert not any(
        item.kind == "candidate_selection" and item.reference == "proposal:1"
        for item in state.artifacts
    )


def test_t19_full_analysis_requires_current_complete_artifacts_and_never_approves(tmp_path):
    from sector_pulse.application.orchestration.controls import (
        CompletionGoal,
        FinalizationController,
        FinalizationRejected,
        RequiredArtifactsFinalizationPolicy,
    )
    from sector_pulse.domain.orchestration.models import ArtifactRef, TaskStatus

    repository, snapshot, root, research_one, research_two, writer, artifacts = setup_control_state(
        tmp_path
    )
    review = ArtifactRef(
        artifact_id=uuid4(), task_id=writer.task_id, kind="review", reference="review:1"
    )
    governance = ArtifactRef(
        artifact_id=uuid4(),
        task_id=writer.task_id,
        kind="governance",
        reference="governance:1",
    )
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "artifacts": (*current.artifacts, review, governance),
            }
        ),
        current.revision,
        "reviewed",
    )
    current_refs = {item.reference for item in (*artifacts, review, governance)} - {"draft:1"}
    policy = RequiredArtifactsFinalizationPolicy(
        goal=CompletionGoal.FULL_ANALYSIS,
        required_analysis_scopes=("industry:1", "industry:2"),
        is_current=lambda artifact: artifact.reference in current_refs,
    )
    controller = FinalizationController(repository, snapshot.run_id, policy)
    all_ids = tuple(item.artifact_id for item in (*artifacts, review, governance))
    with pytest.raises(FinalizationRejected, match="current draft"):
        controller.request(
            root.task_id,
            attempt=1,
            worker_id="parent",
            artifact_ids=all_ids,
        )
    assert repository.load(snapshot.run_id).tasks[0].status is TaskStatus.RUNNING

    current_refs.add("draft:1")
    from sector_pulse.application.orchestration.tasks import TaskCoordinator

    coordinator = TaskCoordinator(repository, snapshot.run_id)
    coordinator.transition(
        research_one.task_id,
        attempt=1,
        worker_id="research-1",
        target=TaskStatus.COMPLETED,
    )
    coordinator.transition(
        research_two.task_id,
        attempt=1,
        worker_id="research-2",
        target=TaskStatus.COMPLETED,
    )
    coordinator.transition(
        writer.task_id,
        attempt=1,
        worker_id="writer",
        target=TaskStatus.COMPLETED,
    )
    result = controller.request(
        root.task_id,
        attempt=1,
        worker_id="parent",
        artifact_ids=all_ids,
    )
    assert result.status is TaskStatus.WAITING_USER_REVIEW
    assert result.status is not TaskStatus.COMPLETED


def test_t19_research_completion_requires_current_analysis_for_each_confirmed_scope(tmp_path):
    from sector_pulse.application.orchestration.controls import (
        CompletionGoal,
        FinalizationController,
        FinalizationRejected,
        RequiredArtifactsFinalizationPolicy,
    )
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.domain.orchestration.models import TaskStatus

    repository, snapshot, root, research_one, research_two, writer, artifacts = (
        setup_control_state(tmp_path)
    )
    current_refs = {"selection:1", "analysis:1"}
    policy = RequiredArtifactsFinalizationPolicy(
        goal=CompletionGoal.RESEARCH,
        required_analysis_scopes=("industry:1", "industry:2"),
        is_current=lambda artifact: artifact.reference in current_refs,
    )
    controller = FinalizationController(repository, snapshot.run_id, policy)
    artifact_ids = tuple(item.artifact_id for item in artifacts[:3])
    with pytest.raises(FinalizationRejected, match="industry:2"):
        controller.request(
            root.task_id,
            attempt=1,
            worker_id="parent",
            artifact_ids=artifact_ids,
        )

    current_refs.add("analysis:2")
    coordinator = TaskCoordinator(repository, snapshot.run_id)
    coordinator.transition(
        research_one.task_id,
        attempt=1,
        worker_id="research-1",
        target=TaskStatus.COMPLETED,
    )
    coordinator.transition(
        research_two.task_id,
        attempt=1,
        worker_id="research-2",
        target=TaskStatus.COMPLETED,
    )
    coordinator.transition(
        writer.task_id,
        attempt=1,
        worker_id="writer",
        target=TaskStatus.CANCELLED,
    )
    result = controller.request(
        root.task_id,
        attempt=1,
        worker_id="parent",
        artifact_ids=artifact_ids,
    )
    assert result.status is TaskStatus.WAITING
    assert result.status is not TaskStatus.WAITING_USER_REVIEW
    assert result.status is not TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_framework_control_tools_bind_identity_and_return_safe_json(tmp_path):
    from sector_pulse.application.orchestration.controls import ArtifactInspector, TaskInspector
    from sector_pulse.infrastructure.agents.control_tools import (
        InspectArtifactsTool,
        InspectTasksTool,
    )

    repository, snapshot, root, _, _, _, artifacts = setup_control_state(tmp_path)
    inspect_artifacts = InspectArtifactsTool(
        ArtifactInspector(repository, snapshot.run_id, StubArtifactReader()),
        task_id=root.task_id,
        attempt=1,
    )
    inspect_tasks = InspectTasksTool(
        TaskInspector(repository, snapshot.run_id),
        task_id=root.task_id,
        attempt=1,
    )
    artifact_result = await inspect_artifacts.run(artifact_refs=[str(artifacts[0].artifact_id)])
    task_result = await inspect_tasks.run()
    assert artifact_result.success and task_result.success
    assert json.loads(artifact_result.content)[0]["reference"] == "selection:1"
    assert json.loads(task_result.content)[0]["role"] == "A0"
    rejected = await inspect_tasks.run(run_id=str(uuid4()))
    assert not rejected.success
    assert "server controlled" in (rejected.error or "")


@pytest.mark.asyncio
async def test_framework_interaction_tools_cannot_approve_or_override_server_goal(tmp_path):
    from sector_pulse.application.orchestration.controls import (
        CompletionGoal,
        FinalizationController,
        RequiredArtifactsFinalizationPolicy,
        SelectionController,
    )
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.domain.orchestration.models import ArtifactRef, TaskStatus
    from sector_pulse.infrastructure.agents.control_tools import (
        RequestFinishTool,
        RequestSelectionTool,
    )

    repository, snapshot, root, research_one, research_two, writer, _ = setup_control_state(
        tmp_path
    )
    proposal = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root.task_id,
        kind="candidate_proposal",
        reference="proposal:controlled",
    )
    market = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root.task_id,
        kind="market_snapshot",
        reference="market:controlled",
    )
    quality = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root.task_id,
        kind="data_quality",
        reference="quality:controlled",
    )
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "artifacts": (*current.artifacts, proposal, market, quality),
            }
        ),
        current.revision,
        "data.ready",
    )
    selection_tool = RequestSelectionTool(
        SelectionController(repository, snapshot.run_id),
        task_id=root.task_id,
        attempt=1,
        worker_id="parent",
    )
    denied = await selection_tool.run(
        proposal_ref=str(proposal.artifact_id),
        approved=True,
    )
    assert not denied.success
    assert "server controlled" in (denied.error or "")

    coordinator = TaskCoordinator(repository, snapshot.run_id)
    for task, worker in (
        (research_one, "research-1"),
        (research_two, "research-2"),
        (writer, "writer"),
    ):
        coordinator.transition(
            task.task_id,
            attempt=1,
            worker_id=worker,
            target=TaskStatus.COMPLETED,
        )
    finish_tool = RequestFinishTool(
        FinalizationController(
            repository,
            snapshot.run_id,
            RequiredArtifactsFinalizationPolicy(
                goal=CompletionGoal.DATA_PREPARATION,
                is_current=lambda artifact: True,
            ),
        ),
        task_id=root.task_id,
        attempt=1,
        worker_id="parent",
    )
    result = await finish_tool.run(
        artifact_refs=[
            str(proposal.artifact_id),
            str(market.artifact_id),
            str(quality.artifact_id),
        ]
    )
    assert result.success
    assert json.loads(result.content) == {"status": "completed"}
    assert "goal" not in RequestFinishTool.parameters["properties"]
    assert "approved" not in RequestFinishTool.parameters["properties"]
