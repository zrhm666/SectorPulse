"""Framework adapter for deterministic A1 candidate ranking."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from aidynamic_agent.tools.base import Tool, ToolResult

from sector_pulse.application.orchestration.candidate_tools import (
    RankSectorCandidatesService,
)
from sector_pulse.domain.market.candidate_batch import CandidateBatch
from sector_pulse.storage.ports.market import CandidateBatchRepositoryPort


class RankSectorCandidatesTool(Tool):
    name = "rank_sector_candidates"
    description = "Run the fixed server-side sector scoring algorithm on current snapshots."
    tags = ["A1", "deterministic", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "market_artifact_refs": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "minItems": 2,
                "maxItems": 2,
                "uniqueItems": True,
            },
            "news_artifact_ref": {"type": "string", "format": "uuid"},
        },
        "required": ["market_artifact_refs"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: RankSectorCandidatesService,
        *,
        batches: CandidateBatchRepositoryPort,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        candidate_limit: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        if not 1 <= candidate_limit <= 50:
            raise ValueError("candidate limit is invalid")
        self._service = service
        self._batches = batches
        self._task_id = task_id
        self._attempt = attempt
        self._worker_id = worker_id
        self._candidate_limit = candidate_limit
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) not in (
            {"market_artifact_refs"},
            {"market_artifact_refs", "news_artifact_ref"},
        ):
            raise ValueError("scores, limits and task identity are server controlled")
        raw_refs = kwargs["market_artifact_refs"]
        if (
            not isinstance(raw_refs, list)
            or len(raw_refs) != 2
            or not all(isinstance(item, str) for item in raw_refs)
        ):
            raise ValueError("two market artifact UUIDs are required")
        market_refs = tuple(UUID(item) for item in raw_refs)
        news_ref = kwargs.get("news_artifact_ref")
        if news_ref is None:
            batch = self._service.rank_market(
                task_id=self._task_id,
                attempt=self._attempt,
                worker_id=self._worker_id,
                market_artifact_ids=market_refs,
                limit=self._candidate_limit,
                now=self._clock(),
            )
        else:
            if not isinstance(news_ref, str):
                raise ValueError("news artifact UUID must be a string")
            batch = self._service.rank_news_enriched(
                task_id=self._task_id,
                attempt=self._attempt,
                worker_id=self._worker_id,
                market_artifact_ids=market_refs,
                news_artifact_id=UUID(news_ref),
                limit=self._candidate_limit,
                now=self._clock(),
            )
        return ToolResult(
            content=self._content(batch),
            metadata={"result_reference": f"candidate-batch:{batch.batch_id}"},
        )

    def replay(self, reference: str) -> ToolResult:
        prefix = "candidate-batch:"
        if not reference.startswith(prefix):
            raise ValueError("invalid candidate batch reference")
        batch = self._batches.get(UUID(reference[len(prefix) :]))
        if batch is None:
            raise KeyError("persisted candidate batch is unavailable")
        return ToolResult(content=self._content(batch))

    @staticmethod
    def _content(batch: CandidateBatch) -> str:
        return json.dumps(
            {
                "status": "success",
                "artifact_refs": [str(batch.batch_id)],
                "summary": {
                    "candidate_count": len(batch.candidates),
                    "ranking_stage": batch.ranking_stage.value,
                    "candidates": [
                        {
                            "sector_id": item.provider_sector_id,
                            "sector_kind": item.kind.value,
                            "name": item.name,
                            "rank": item.rank,
                            "score": str(item.score),
                            "reasons": item.reasons,
                        }
                        for item in batch.candidates
                    ],
                },
                "safe_error_code": None,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
