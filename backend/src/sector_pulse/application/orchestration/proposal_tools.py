import hashlib
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.data_tools import require_live_task_owner
from sector_pulse.domain.market.candidate_proposal import (
    CandidateProposal,
    CandidateProposalItem,
)
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.ports.orchestration import SnapshotRepository, TransactionSession
from sector_pulse.storage.ports.market import (
    CandidateBatchRepositoryPort,
    CandidateProposalRepositoryPort,
)


class ProposalExplanation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sector_id: str
    explanation: str = Field(min_length=1, max_length=1000)


class CandidateProposalPersistence:
    def __init__(self, proposal: CandidateProposal) -> None:
        self._proposal = proposal

    def write(self, session: TransactionSession, artifact: ArtifactRef) -> None:
        del artifact
        proposal = self._proposal
        session.execute(
            "INSERT INTO candidate_proposals (proposal_id, run_id, candidate_batch_id, "
            "input_fingerprint, created_at) VALUES (:proposal_id, :run_id, "
            ":candidate_batch_id, :input_fingerprint, :created_at)",
            {
                "proposal_id": str(proposal.proposal_id),
                "run_id": str(proposal.run_id),
                "candidate_batch_id": str(proposal.candidate_batch_id),
                "input_fingerprint": proposal.input_fingerprint,
                "created_at": proposal.created_at.isoformat(),
            },
        )
        for item in proposal.items:
            session.execute(
                "INSERT INTO candidate_proposal_items (proposal_id, provider_sector_id, "
                "sector_kind, sector_name, rank, score, explanation) VALUES "
                "(:proposal_id, :sector_id, :kind, :name, :rank, :score, :explanation)",
                {
                    "proposal_id": str(proposal.proposal_id),
                    "sector_id": item.provider_sector_id,
                    "kind": item.kind.value,
                    "name": item.name,
                    "rank": item.rank,
                    "score": str(item.score),
                    "explanation": item.explanation,
                },
            )

    def exists(self, session: TransactionSession, artifact: ArtifactRef) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM candidate_proposals WHERE proposal_id=:proposal_id",
                {"proposal_id": str(self._proposal.proposal_id)},
            )
        )


class ProposeCandidatesService:
    def __init__(
        self,
        *,
        candidate_batches: CandidateBatchRepositoryPort,
        proposals: CandidateProposalRepositoryPort,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
    ) -> None:
        self._candidate_batches = candidate_batches
        self._proposals = proposals
        self._orchestration = orchestration
        self._committer = committer

    def propose(
        self,
        *,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        candidate_artifact_id: UUID,
        explanations: tuple[ProposalExplanation, ...],
        now: datetime | None = None,
    ) -> CandidateProposal:
        observed_at = now or datetime.now(UTC)
        run_id = self._committer.run_id
        require_live_task_owner(
            self._orchestration,
            run_id,
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            now=observed_at,
        )
        if not 3 <= len(explanations) <= 12:
            raise ValueError("candidate proposal must contain between 3 and 12 sectors")
        sector_ids = tuple(item.sector_id for item in explanations)
        if len(set(sector_ids)) != len(sector_ids):
            raise ValueError("candidate proposal sector IDs must be unique")
        state = self._orchestration.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        artifact = next(
            (item for item in state.artifacts if item.artifact_id == candidate_artifact_id),
            None,
        )
        if (
            artifact is None
            or artifact.kind != "candidate_batch"
            or artifact.task_id != task_id
            or artifact.attempt != attempt
        ):
            raise ValueError("candidate artifact is outside current task")
        prefix = "candidate-batch:"
        if not artifact.reference.startswith(prefix):
            raise ValueError("candidate artifact reference is invalid")
        batch = self._candidate_batches.get(UUID(artifact.reference[len(prefix) :]))
        if batch is None or batch.run_id != run_id:
            raise KeyError("candidate batch is unavailable")
        by_id = {item.provider_sector_id: item for item in batch.candidates}
        if not set(sector_ids).issubset(by_id):
            raise ValueError("candidate proposal contains an unknown sector ID")
        explanations_by_id = {
            item.sector_id: item.explanation.strip() for item in explanations
        }
        if any(not value for value in explanations_by_id.values()):
            raise ValueError("candidate proposal explanation is required")
        selected = tuple(item for item in batch.candidates if item.provider_sector_id in sector_ids)
        items = tuple(
            CandidateProposalItem(
                provider_sector_id=item.provider_sector_id,
                kind=item.kind,
                name=item.name,
                rank=item.rank,
                score=item.score,
                explanation=explanations_by_id[item.provider_sector_id],
            )
            for item in selected
        )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "candidate_artifact_id": str(candidate_artifact_id),
                    "items": [
                        {
                            "sector_id": item.provider_sector_id,
                            "explanation": item.explanation,
                        }
                        for item in items
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        proposal = CandidateProposal(
            proposal_id=uuid5(NAMESPACE_URL, f"candidate-proposal:{run_id}:{fingerprint}"),
            run_id=run_id,
            candidate_batch_id=batch.batch_id,
            input_fingerprint=fingerprint,
            created_at=observed_at,
            items=items,
        )
        proposal_artifact = ArtifactRef(
            artifact_id=uuid5(
                NAMESPACE_URL,
                f"candidate-proposal-artifact:{proposal.proposal_id}:{task_id}:{attempt}",
            ),
            task_id=task_id,
            attempt=attempt,
            kind="candidate_proposal",
            reference=f"candidate-proposal:{proposal.proposal_id}",
        )
        self._committer.commit(
            proposal_artifact,
            worker_id=worker_id,
            persistence=CandidateProposalPersistence(proposal),
            now=observed_at,
        )
        return proposal


__all__ = ["ProposalExplanation", "ProposeCandidatesService"]
