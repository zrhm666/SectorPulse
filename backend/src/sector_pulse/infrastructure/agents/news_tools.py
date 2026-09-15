"""Framework adapter for bounded A1 initial-news collection."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from aidynamic_agent.tools.base import Tool, ToolResult

from sector_pulse.application.orchestration.news_tools import CollectInitialNewsService
from sector_pulse.domain.news.news_batch import NewsBatch, NewsCollectionReason
from sector_pulse.storage.ports.news import NewsBatchRepositoryPort


class CollectInitialNewsTool(Tool):
    name = "collect_initial_news"
    description = "Collect a server-bounded news batch for a persisted candidate batch."
    tags = ["A1", "external_data", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "candidate_artifact_ref": {"type": "string", "format": "uuid"},
            "reason": {
                "type": "string",
                "enum": [item.value for item in NewsCollectionReason],
            },
        },
        "required": ["candidate_artifact_ref", "reason"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: CollectInitialNewsService,
        *,
        batches: NewsBatchRepositoryPort,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        clock: Callable[[], datetime] | None = None,
        retry_backoff: Callable[[int], float] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._batches = batches
        self._task_id = task_id
        self._attempt = attempt
        self._worker_id = worker_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._retry_backoff = retry_backoff

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"candidate_artifact_ref", "reason"}:
            raise ValueError("query limits, sources and task identity are server controlled")
        artifact_ref = kwargs["candidate_artifact_ref"]
        reason = kwargs["reason"]
        if not isinstance(artifact_ref, str) or not isinstance(reason, str):
            raise ValueError("candidate_artifact_ref and reason must be strings")
        try:
            typed_reason = NewsCollectionReason(reason)
        except ValueError as exc:
            raise ValueError("NEWS_COLLECTION_REASON_INVALID") from exc
        batch = await self._service.collect(
            task_id=self._task_id,
            attempt=self._attempt,
            worker_id=self._worker_id,
            candidate_artifact_id=UUID(artifact_ref),
            reason=typed_reason,
            now=self._clock(),
            retry_backoff=self._retry_backoff,
        )
        return ToolResult(
            content=self._content(batch),
            metadata={"result_reference": f"news-batch:{batch.batch_id}"},
        )

    def replay(self, reference: str) -> ToolResult:
        prefix = "news-batch:"
        if not reference.startswith(prefix):
            raise ValueError("invalid news batch reference")
        batch = self._batches.get(UUID(reference[len(prefix) :]))
        if batch is None:
            raise KeyError("persisted news batch is unavailable")
        return ToolResult(content=self._content(batch))

    @staticmethod
    def _content(batch: NewsBatch) -> str:
        return json.dumps(
            {
                "status": batch.quality.status.value,
                "artifact_refs": [str(batch.batch_id)],
                "summary": {
                    "document_count": batch.document_count,
                    "event_count": batch.event_count,
                    "link_count": batch.link_count,
                    "excluded_after_cutoff_count": (
                        batch.quality.excluded_after_cutoff_count
                    ),
                    "sources": {
                        item.source_id: {
                            "status": item.status.value,
                            "call_count": item.call_count,
                            "retry_count": item.retry_count,
                            "result_count": item.result_count,
                            "error_code": item.error_code,
                        }
                        for item in batch.source_metrics
                    },
                },
                "safe_error_code": (
                    batch.quality.blocking_reasons[0]
                    if batch.quality.blocking_reasons
                    else None
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
