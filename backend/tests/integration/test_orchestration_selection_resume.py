from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest


def _proposal(run_id):
    from sector_pulse.domain.market.candidate_proposal import (
        CandidateProposal,
        CandidateProposalItem,
    )
    from sector_pulse.domain.market.market import SectorKind

    proposal_id = uuid4()
    return CandidateProposal(
        proposal_id=proposal_id,
        run_id=run_id,
        candidate_batch_id=uuid4(),
        input_fingerprint="a" * 64,
        created_at=datetime.now(UTC),
        items=tuple(
            CandidateProposalItem(
                provider_sector_id=f"sector-{index}",
                kind=SectorKind.INDUSTRY,
                name=f"Sector {index}",
                rank=index,
                score=Decimal(10 - index),
                explanation="candidate",
            )
            for index in range(1, 5)
        ),
    )


def _setup(tmp_path):
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "selection-resume.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    run_id, root_id = uuid4(), uuid4()
    proposal = _proposal(run_id)
    root = TaskRecord(
        task_id=root_id,
        role="A0",
        scope="full analysis",
        status=TaskStatus.WAITING_USER_SELECTION,
    )
    proposal_ref = ArtifactRef(
        artifact_id=proposal.proposal_id,
        task_id=root_id,
        attempt=1,
        kind="candidate_proposal",
        reference=f"candidate-proposal:{proposal.proposal_id}",
    )
    snapshot = RunSnapshot(
        run_id=run_id,
        deadline=datetime.now(UTC) + timedelta(minutes=10),
        tasks=(root,),
        artifacts=(proposal_ref,),
    )
    repository.save(snapshot, -1, "test.waiting_selection")

    class Proposals:
        def get(self, proposal_id):
            return proposal if proposal_id == proposal.proposal_id else None

    return database, repository, snapshot, root, proposal, Proposals()


def test_confirm_selection_atomically_resumes_same_root_with_new_attempt(tmp_path):
    from sector_pulse.application.orchestration.budget import SharedBudget
    from sector_pulse.application.orchestration.selection_resume import SelectionResumeService
    from sector_pulse.application.orchestration.tasks import TaskOwnershipError
    from sector_pulse.domain.orchestration.models import TaskStatus
    from sector_pulse.storage.sqlite.market.orchestration_selection_repository import (
        SQLiteOrchestrationSelectionRepository,
    )

    database, repository, snapshot, root, proposal, proposals = _setup(tmp_path)
    service = SelectionResumeService(
        orchestration=repository,
        proposals=proposals,
    )
    now = datetime.now(UTC)
    claimed = service.confirm_and_claim(
        run_id=snapshot.run_id,
        proposal_id=proposal.proposal_id,
        sector_ids=("sector-3", "sector-1", "sector-2"),
        expected_selection_version=0,
        expected_attempt=1,
        worker_id="root-worker-2",
        lease_expires_at=now + timedelta(minutes=2),
        now=now,
    )

    state = repository.load(snapshot.run_id)
    assert claimed.task_id == root.task_id
    assert claimed.attempt == 2
    assert claimed.status is TaskStatus.RUNNING
    assert claimed.selection_version == 1
    assert claimed.worker_id == "root-worker-2"
    assert state.tasks[0] == claimed
    selection_ref = next(item for item in state.artifacts if item.kind == "candidate_selection")
    assert selection_ref.task_id == root.task_id
    assert selection_ref.attempt == 2
    assert selection_ref.reference == "candidate-selection:1"
    assert claimed.input_artifact_ids == (proposal.proposal_id, selection_ref.artifact_id)
    selection = SQLiteOrchestrationSelectionRepository(database).latest(snapshot.run_id)
    assert selection is not None
    assert selection.selected_sector_ids == ("sector-1", "sector-2", "sector-3")
    assert selection.version == 1
    with pytest.raises(TaskOwnershipError, match="stale task attempt"):
        SharedBudget(
            repository,
            snapshot.run_id,
            task_id=root.task_id,
            attempt=1,
            role="A0",
        ).reserve("late-model", 1, 1)


@pytest.mark.parametrize(
    "sector_ids",
    [
        ("sector-1", "sector-2"),
        ("sector-1", "sector-2", "unknown"),
        ("sector-1", "sector-1", "sector-2"),
    ],
)
def test_invalid_selection_does_not_resume_or_persist(tmp_path, sector_ids):
    from sector_pulse.application.orchestration.selection_resume import SelectionResumeService
    from sector_pulse.storage.sqlite.market.orchestration_selection_repository import (
        SQLiteOrchestrationSelectionRepository,
    )

    database, repository, snapshot, root, proposal, proposals = _setup(tmp_path)
    service = SelectionResumeService(orchestration=repository, proposals=proposals)
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="candidate selection"):
        service.confirm_and_claim(
            run_id=snapshot.run_id,
            proposal_id=proposal.proposal_id,
            sector_ids=sector_ids,
            expected_selection_version=0,
            expected_attempt=1,
            worker_id="root-worker-2",
            lease_expires_at=now + timedelta(minutes=1),
            now=now,
        )
    assert repository.load(snapshot.run_id).tasks[0] == root
    assert SQLiteOrchestrationSelectionRepository(database).latest(snapshot.run_id) is None


def test_two_confirmation_workers_allow_only_one_version_and_claim(tmp_path):
    from sector_pulse.application.orchestration.selection_resume import SelectionResumeService

    _, repository, snapshot, _, proposal, proposals = _setup(tmp_path)
    now = datetime.now(UTC)

    def confirm(worker):
        service = SelectionResumeService(orchestration=repository, proposals=proposals)
        try:
            service.confirm_and_claim(
                run_id=snapshot.run_id,
                proposal_id=proposal.proposal_id,
                sector_ids=("sector-1", "sector-2", "sector-3"),
                expected_selection_version=0,
                expected_attempt=1,
                worker_id=worker,
                lease_expires_at=now + timedelta(minutes=1),
                now=now,
            )
            return True
        except (ValueError, RuntimeError):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm, ("worker-a", "worker-b"))) == [False, True]
    state = repository.load(snapshot.run_id)
    assert state.tasks[0].attempt == 2
    assert len([item for item in state.artifacts if item.kind == "candidate_selection"]) == 1


@pytest.mark.asyncio
async def test_multi_agent_service_continues_same_root_after_human_confirmation(tmp_path):
    from pathlib import Path

    from sector_pulse.application.orchestration.multi_agent_run_service import MultiAgentRunService
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.orchestration.models import TaskStatus
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry

    _, repository, snapshot, root, proposal, proposals = _setup(tmp_path)
    short_deadline = datetime.now(UTC) + timedelta(seconds=1)
    repository.save(
        snapshot.model_copy(
            update={"revision": snapshot.revision + 1, "deadline": short_deadline}
        ),
        snapshot.revision,
        "test.selection_wait_consumed_deadline",
    )
    service = MultiAgentRunService(
        repository=repository,
        config=load_llm_config(Path("config/llm.yaml")),
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_factory=AgentProviderFactory(
            fixture_turns={
                AgentRole.A0: (FixtureAgentTurn(text="selection accepted; continue later"),)
            }
        ),
        candidate_proposals=proposals,
    )

    result = await service.confirm_selection(
        run_id=snapshot.run_id,
        proposal_id=proposal.proposal_id,
        sector_ids=("sector-1", "sector-2", "sector-3"),
        expected_selection_version=0,
        expected_attempt=1,
    )

    assert result == snapshot.run_id
    state = repository.load(snapshot.run_id)
    assert len([task for task in state.tasks if task.parent_id is None]) == 1
    assert state.tasks[0].task_id == root.task_id
    assert state.tasks[0].attempt == 2
    assert state.tasks[0].selection_version == 1
    assert state.tasks[0].status is TaskStatus.WAITING
    assert state.deadline > short_deadline
    assert [(call.role, call.attempt) for call in state.ledger.reservations] == [("A0", 2)]


@pytest.mark.asyncio
async def test_default_selection_requires_creation_time_server_policy(tmp_path):
    from pathlib import Path

    from sector_pulse.application.orchestration.multi_agent_run_service import MultiAgentRunService
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.market.candidate_selection import CandidateSelectionMethod
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.market.orchestration_selection_repository import (
        SQLiteOrchestrationSelectionRepository,
    )

    database, repository, snapshot, _, proposal, proposals = _setup(tmp_path)

    def service():
        return MultiAgentRunService(
            repository=repository,
            config=load_llm_config(Path("config/llm.yaml")),
            prompt_registry=PromptRegistry(Path("config/prompts")),
            provider_factory=AgentProviderFactory(
                fixture_turns={AgentRole.A0: (FixtureAgentTurn(text="default accepted"),)}
            ),
            candidate_proposals=proposals,
        )

    with pytest.raises(ValueError, match="server default"):
        await service().confirm_default_selection(
            run_id=snapshot.run_id,
            proposal_id=proposal.proposal_id,
            expected_selection_version=0,
            expected_attempt=1,
        )
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(
            update={"revision": current.revision + 1, "selection_policy": "server_default"}
        ),
        current.revision,
        "test.server_default_policy",
    )
    await service().confirm_default_selection(
        run_id=snapshot.run_id,
        proposal_id=proposal.proposal_id,
        expected_selection_version=0,
        expected_attempt=1,
    )
    selection = SQLiteOrchestrationSelectionRepository(database).latest(snapshot.run_id)
    assert selection is not None
    assert selection.method is CandidateSelectionMethod.DEFAULT
    assert selection.selected_sector_ids == tuple(
        item.provider_sector_id for item in proposal.items
    )


@pytest.mark.postgres
def test_postgres_selection_and_root_claim_share_one_cas_transaction():
    import os

    from sector_pulse.application.orchestration.selection_resume import SelectionResumeService
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.storage.postgres.database import PostgresDatabase
    from sector_pulse.storage.postgres.market.orchestration_selection_repository import (
        PostgresOrchestrationSelectionRepository,
    )
    from sector_pulse.storage.postgres.orchestration.repository import (
        PostgresOrchestrationRepository,
    )
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    url = os.getenv("SECTOR_PULSE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires dedicated SECTOR_PULSE_TEST_DATABASE_URL")
    assert (make_url(url).database or "").endswith("_test"), "business database refused"
    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresOrchestrationRepository(database)
    run_id, root_id = uuid4(), uuid4()
    proposal = _proposal(run_id)
    root = TaskRecord(
        task_id=root_id,
        role="A0",
        scope="full analysis",
        status=TaskStatus.WAITING_USER_SELECTION,
    )
    proposal_ref = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root_id,
        kind="candidate_proposal",
        reference=f"candidate-proposal:{proposal.proposal_id}",
    )
    snapshot = RunSnapshot(
        run_id=run_id,
        deadline=datetime.now(UTC) + timedelta(minutes=5),
        tasks=(root,),
        artifacts=(proposal_ref,),
    )

    class Proposals:
        def get(self, proposal_id):
            return proposal if proposal_id == proposal.proposal_id else None

    repository.save(snapshot, -1, "test.waiting_selection")
    now = datetime.now(UTC)

    def confirm(worker):
        try:
            SelectionResumeService(
                orchestration=PostgresOrchestrationRepository(database),
                proposals=Proposals(),
            ).confirm_and_claim(
                run_id=run_id,
                proposal_id=proposal.proposal_id,
                sector_ids=("sector-1", "sector-2", "sector-3"),
                expected_selection_version=0,
                expected_attempt=1,
                worker_id=worker,
                lease_expires_at=now + timedelta(minutes=1),
                now=now,
            )
            return True
        except (ValueError, RuntimeError):
            return False

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(confirm, ("pg-worker-a", "pg-worker-b"))) == [False, True]
        state = repository.load(run_id)
        selection = PostgresOrchestrationSelectionRepository(database).latest(run_id)
        assert state.tasks[0].task_id == root_id
        assert state.tasks[0].attempt == 2
        assert state.tasks[0].selection_version == 1
        assert selection is not None
        assert selection.selected_sector_ids == ("sector-1", "sector-2", "sector-3")
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM orchestration_candidate_selections WHERE run_id=:run"),
                {"run": str(run_id)},
            )
            connection.execute(
                text("DELETE FROM orchestration_events WHERE run_id=:run"),
                {"run": str(run_id)},
            )
            connection.execute(
                text("DELETE FROM orchestration_snapshots WHERE run_id=:run"),
                {"run": str(run_id)},
            )
        database.close()
