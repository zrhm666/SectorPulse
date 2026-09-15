from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest


def build_context_fixture(tmp_path):
    from sector_pulse.domain.market.candidate import SectorCandidate
    from sector_pulse.domain.market.candidate_batch import (
        CandidateBatch,
        CandidateRankingStage,
    )
    from sector_pulse.domain.market.candidate_selection import (
        CandidateSelection,
        CandidateSelectionMethod,
    )
    from sector_pulse.domain.market.market import SectorKind
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.domain.runs.time import AnalysisRun
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import (
        SQLiteOrchestrationRepository,
    )

    now = datetime(2026, 9, 14, 2, 0, tzinfo=UTC)
    run_id, root_id, task_id, batch_id = uuid4(), uuid4(), uuid4(), uuid4()
    artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root_id,
        kind="candidate_batch",
        reference=f"candidate-batch:{batch_id}",
    )
    root = TaskRecord(task_id=root_id, role="A0", scope="run")
    task = TaskRecord(
        task_id=task_id,
        parent_id=root_id,
        role="A2",
        scope="sector:INDUSTRY:sector-1",
        status=TaskStatus.RUNNING,
        worker_id="research-worker",
        lease_expires_at=now + timedelta(minutes=5),
        input_artifact_ids=(artifact.artifact_id,),
        selection_version=1,
    )
    database = SQLiteDatabase(tmp_path / "research-context.db")
    database.initialize()
    orchestration = SQLiteOrchestrationRepository(database)
    orchestration.save(
        RunSnapshot(
            run_id=run_id,
            deadline=now + timedelta(minutes=10),
            tasks=(root, task),
            artifacts=(artifact,),
        ),
        -1,
        "research.created",
    )
    batch = CandidateBatch(
        batch_id=batch_id,
        run_id=run_id,
        input_fingerprint="a" * 64,
        ranking_stage=CandidateRankingStage.NEWS_ENRICHED,
        candidate_limit=12,
        created_at=now,
        candidates=(
            SectorCandidate(
                provider_sector_id="sector-1",
                kind=SectorKind.INDUSTRY,
                name="文化传媒",
                rank=1,
                score=Decimal("0.91"),
                reasons=("market",),
            ),
        ),
    )
    selection = CandidateSelection(
        run_id=run_id,
        version=1,
        selected_sector_ids=("sector-1", "sector-2", "sector-3"),
        method=CandidateSelectionMethod.MANUAL,
        confirmed_at=now,
        data_version="b" * 64,
    )
    analysis_run = AnalysisRun.create_live(now, run_id).lock_live_cutoff(now, now)

    class Batches:
        def get(self, requested_id):
            return batch if requested_id == batch_id else None

    class Selections:
        def list_versions(self, requested_run_id):
            return [selection] if requested_run_id == run_id else []

    class Markets:
        def get_run(self, requested_run_id):
            return analysis_run if requested_run_id == run_id else None

    return now, orchestration, run_id, task, artifact, Batches(), Selections(), Markets()


def test_a2_context_uses_only_pinned_selection_scope_and_artifacts(tmp_path):
    from sector_pulse.application.orchestration.research_context import (
        BoundSectorResearchContextReader,
    )
    from sector_pulse.domain.market.market import SectorKind

    now, orchestration, run_id, task, artifact, batches, selections, markets = (
        build_context_fixture(tmp_path)
    )
    context = BoundSectorResearchContextReader(
        orchestration=orchestration,
        selections=selections,
        candidate_batches=batches,
        market_snapshots=markets,
        run_id=run_id,
    ).read(
        task_id=task.task_id,
        attempt=1,
        worker_id="research-worker",
        now=now,
    )
    assert context.sector_id == "sector-1"
    assert context.sector_kind is SectorKind.INDUSTRY
    assert context.sector_name == "文化传媒"
    assert context.selection_version == 1
    assert context.cutoff_at == now
    assert [item.artifact_id for item in context.input_artifacts] == [artifact.artifact_id]


def test_a2_context_rejects_stale_owner_and_unselected_scope(tmp_path):
    from sector_pulse.application.orchestration.research_context import (
        BoundSectorResearchContextReader,
    )
    from sector_pulse.application.orchestration.tasks import TaskOwnershipError

    now, orchestration, run_id, task, _, batches, selections, markets = build_context_fixture(
        tmp_path
    )
    reader = BoundSectorResearchContextReader(
        orchestration=orchestration,
        selections=selections,
        candidate_batches=batches,
        market_snapshots=markets,
        run_id=run_id,
    )
    with pytest.raises(TaskOwnershipError, match="stale"):
        reader.read(
            task_id=task.task_id,
            attempt=2,
            worker_id="research-worker",
            now=now,
        )
    with pytest.raises(TaskOwnershipError, match="own"):
        reader.read(
            task_id=task.task_id,
            attempt=1,
            worker_id="other-worker",
            now=now,
        )

    state = orchestration.load(run_id)
    changed_task = task.model_copy(update={"scope": "sector:INDUSTRY:not-selected"})
    orchestration.save(
        state.model_copy(
            update={
                "revision": state.revision + 1,
                "tasks": tuple(
                    changed_task if item.task_id == task.task_id else item
                    for item in state.tasks
                ),
            }
        ),
        state.revision,
        "scope.changed",
    )
    with pytest.raises(ValueError, match="confirmed selection"):
        reader.read(
            task_id=task.task_id,
            attempt=1,
            worker_id="research-worker",
            now=now,
        )


def test_a2_context_does_not_substitute_latest_selection(tmp_path):
    from sector_pulse.application.orchestration.research_context import (
        BoundSectorResearchContextReader,
    )

    now, orchestration, run_id, task, _, batches, selections, markets = build_context_fixture(
        tmp_path
    )
    pinned = selections.list_versions(run_id)[0]
    latest = pinned.model_copy(
        update={
            "version": 2,
            "selected_sector_ids": ("other-1", "other-2", "other-3"),
        }
    )

    class VersionedSelections:
        def list_versions(self, requested_run_id):
            return [pinned, latest] if requested_run_id == run_id else []

    context = BoundSectorResearchContextReader(
        orchestration=orchestration,
        selections=VersionedSelections(),
        candidate_batches=batches,
        market_snapshots=markets,
        run_id=run_id,
    ).read(
        task_id=task.task_id,
        attempt=1,
        worker_id="research-worker",
        now=now,
    )
    assert context.selection_version == 1
    assert context.sector_id == "sector-1"
