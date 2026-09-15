import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from aidynamic_agent.tools.base import Tool, ToolResult

from sector_pulse.application.orchestration.proposal_tools import (
    ProposalExplanation,
    ProposeCandidatesService,
)
from sector_pulse.domain.market.candidate_proposal import CandidateProposal
from sector_pulse.storage.ports.market import CandidateProposalRepositoryPort


class ProposeCandidatesTool(Tool):
    name = "propose_candidates"
    description = "Propose ranked candidates without confirming the user's selection."
    tags = ["A1", "deterministic_guarded", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "candidate_artifact_ref": {"type": "string", "format": "uuid"},
            "proposals": {
                "type": "array",
                "minItems": 3,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "sector_id": {"type": "string"},
                        "explanation": {"type": "string", "minLength": 1},
                    },
                    "required": ["sector_id", "explanation"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["candidate_artifact_ref", "proposals"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: ProposeCandidatesService,
        *,
        proposals: CandidateProposalRepositoryPort,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._proposals = proposals
        self._task_id = task_id
        self._attempt = attempt
        self._worker_id = worker_id
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"candidate_artifact_ref", "proposals"}:
            raise ValueError("scores, rank, selection and task identity are server controlled")
        artifact_ref = kwargs["candidate_artifact_ref"]
        raw_items = kwargs["proposals"]
        if not isinstance(artifact_ref, str) or not isinstance(raw_items, list):
            raise ValueError("candidate artifact and proposal list are required")
        explanations = tuple(ProposalExplanation.model_validate(item) for item in raw_items)
        proposal = self._service.propose(
            task_id=self._task_id,
            attempt=self._attempt,
            worker_id=self._worker_id,
            candidate_artifact_id=UUID(artifact_ref),
            explanations=explanations,
            now=self._clock(),
        )
        return ToolResult(
            content=self._content(proposal),
            metadata={"result_reference": f"candidate-proposal:{proposal.proposal_id}"},
        )

    def replay(self, reference: str) -> ToolResult:
        prefix = "candidate-proposal:"
        if not reference.startswith(prefix):
            raise ValueError("invalid candidate proposal reference")
        proposal = self._proposals.get(UUID(reference[len(prefix) :]))
        if proposal is None:
            raise KeyError("persisted candidate proposal is unavailable")
        return ToolResult(content=self._content(proposal))

    @staticmethod
    def _content(proposal: CandidateProposal) -> str:
        return json.dumps(
            {
                "status": "awaiting_user_selection",
                "artifact_refs": [str(proposal.proposal_id)],
                "summary": {
                    "candidate_count": len(proposal.items),
                    "candidates": [
                        {
                            "sector_id": item.provider_sector_id,
                            "rank": item.rank,
                            "score": str(item.score),
                            "explanation": item.explanation,
                        }
                        for item in proposal.items
                    ],
                },
                "safe_error_code": None,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
