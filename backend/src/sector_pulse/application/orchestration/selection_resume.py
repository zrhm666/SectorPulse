"""Human-owned candidate confirmation and atomic A0 resume claim."""

import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sector_pulse.domain.market.candidate_proposal import CandidateProposal
from sector_pulse.domain.market.candidate_selection import (
    CandidateSelection,
    CandidateSelectionMethod,
    CandidateSelectionVersionConflict,
)
from sector_pulse.domain.orchestration.models import ArtifactRef, TaskRecord, TaskStatus
from sector_pulse.ports.orchestration import SnapshotRepository, TransactionSession
from sector_pulse.storage.ports.market import CandidateProposalRepositoryPort


class SelectionResumeService:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        proposals: CandidateProposalRepositoryPort,
    ) -> None:
        self._orchestration = orchestration
        self._proposals = proposals

    def confirm_and_claim(
        self,
        *,
        run_id: UUID,
        proposal_id: UUID,
        sector_ids: tuple[str, ...],
        expected_selection_version: int,
        expected_attempt: int,
        worker_id: str,
        lease_expires_at: datetime,
        now: datetime | None = None,
    ) -> TaskRecord:
        observed_at = now or datetime.now(UTC)
        if not worker_id.strip():
            raise ValueError("worker ID is required")
        if lease_expires_at.tzinfo is None or lease_expires_at <= observed_at:
            raise ValueError("lease must expire in the future")
        state = self._orchestration.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        if lease_expires_at > state.deadline:
            raise ValueError("lease cannot exceed the run deadline")
        root = next(task for task in state.tasks if task.parent_id is None)
        if root.role != "A0" or root.status is not TaskStatus.WAITING_USER_SELECTION:
            raise ValueError("run is not waiting for candidate selection")
        if root.attempt != expected_attempt:
            raise ValueError("candidate selection uses a stale task attempt")
        proposal_ref = next(
            (
                item
                for item in state.artifacts
                if item.kind == "candidate_proposal"
                and item.reference == f"candidate-proposal:{proposal_id}"
            ),
            None,
        )
        proposal = self._proposals.get(proposal_id)
        if proposal_ref is None or proposal is None or proposal.run_id != run_id:
            raise ValueError("candidate proposal is not part of this run")
        ordered = self._validate_selection(proposal, sector_ids)
        version = expected_selection_version + 1
        method = (
            CandidateSelectionMethod.DEFAULT
            if ordered == tuple(item.provider_sector_id for item in proposal.items)
            else CandidateSelectionMethod.MANUAL
        )
        selection = CandidateSelection(
            run_id=run_id,
            version=version,
            selected_sector_ids=ordered,
            method=method,
            confirmed_at=observed_at,
            data_version=proposal.input_fingerprint,
            edit_count=1 if method is CandidateSelectionMethod.MANUAL else 0,
        )
        selection_ref = ArtifactRef(
            artifact_id=uuid5(
                NAMESPACE_URL,
                f"candidate-selection:{run_id}:{version}:{proposal_id}:{','.join(ordered)}",
            ),
            task_id=root.task_id,
            attempt=root.attempt + 1,
            kind="candidate_selection",
            reference=f"candidate-selection:{version}",
        )
        claimed = root.model_copy(
            update={
                "attempt": root.attempt + 1,
                "status": TaskStatus.RUNNING,
                "worker_id": worker_id,
                "lease_expires_at": lease_expires_at,
                "input_artifact_ids": (proposal_ref.artifact_id, selection_ref.artifact_id),
                "selection_version": version,
            }
        )
        changed = state.model_copy(
            update={
                "revision": state.revision + 1,
                "tasks": tuple(
                    claimed if task.task_id == root.task_id else task for task in state.tasks
                ),
                "artifacts": (*state.artifacts, selection_ref),
            }
        )

        def persist(session: TransactionSession) -> None:
            rows = session.rows(
                "SELECT MAX(version) FROM orchestration_candidate_selections "
                "WHERE run_id=:run",
                {"run": str(run_id)},
            )
            actual = int(rows[0][0]) if rows and rows[0][0] is not None else 0
            if actual != expected_selection_version:
                raise CandidateSelectionVersionConflict(
                    f"candidate selection version conflict: expected={expected_selection_version} "
                    f"actual={actual}"
                )
            inserted = session.execute(
                "INSERT INTO orchestration_candidate_selections "
                "(run_id,version,proposal_id,selected_sector_ids_json,method,confirmed_at,"
                "data_version,edit_count) VALUES "
                "(:run,:version,:proposal,:sectors,:method,:confirmed,:data_version,:edits) "
                "ON CONFLICT (run_id,version) DO NOTHING",
                {
                    "run": str(run_id),
                    "version": version,
                    "proposal": str(proposal_id),
                    "sectors": json.dumps(ordered, ensure_ascii=False),
                    "method": method.value,
                    "confirmed": observed_at.isoformat(),
                    "data_version": selection.data_version,
                    "edits": selection.edit_count,
                },
            )
            if inserted != 1:
                raise CandidateSelectionVersionConflict(
                    f"candidate selection version conflict: expected={expected_selection_version}"
                )

        self._orchestration.save_atomic(
            changed,
            state.revision,
            f"selection.confirmed:{version}",
            persist,
        )
        return claimed

    @staticmethod
    def _validate_selection(
        proposal: CandidateProposal, sector_ids: tuple[str, ...]
    ) -> tuple[str, ...]:
        if not 3 <= len(sector_ids) <= 12 or len(set(sector_ids)) != len(sector_ids):
            raise ValueError("candidate selection must contain 3 to 12 unique sectors")
        selected = set(sector_ids)
        available = {item.provider_sector_id for item in proposal.items}
        if not selected.issubset(available):
            raise ValueError("candidate selection contains a sector outside the proposal")
        return tuple(
            item.provider_sector_id
            for item in proposal.items
            if item.provider_sector_id in selected
        )
