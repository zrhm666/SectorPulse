import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from aidynamic_agent.tools.base import Tool, ToolResult

from sector_pulse.application.orchestration.research_context import BoundSectorResearchContext
from sector_pulse.application.orchestration.research_news_tools import (
    NewsDetailAccessError,
    ReadBoundNewsDetailService,
    SearchSectorNewsService,
    news_detail_artifact_id,
    research_search_artifact_id,
)
from sector_pulse.domain.news.research import (
    NewsDetailSnapshot,
    ResearchSearchBatch,
    ResearchSearchStatus,
)
from sector_pulse.storage.ports.news import (
    NewsDetailSnapshotRepositoryPort,
    ResearchSearchRepositoryPort,
)


class SearchNewsTool(Tool):
    name = "search_news"
    description = "Search a bounded time window for the current server-bound sector."
    tags = ["A2", "external_bounded", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string", "minLength": 2, "maxLength": 120}},
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: SearchSectorNewsService,
        *,
        searches: ResearchSearchRepositoryPort,
        context: BoundSectorResearchContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._searches = searches
        self._context = context
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"query"}:
            raise ValueError("sector, time window and task identity are server controlled")
        query = kwargs["query"]
        if not isinstance(query, str):
            raise ValueError("query must be text")
        batch = await self._service.search(
            context=self._context,
            query=query,
            now=self._clock(),
        )
        failed = batch.status is ResearchSearchStatus.FAILED
        return ToolResult(
            content=self._content(batch),
            success=not failed,
            error=batch.error_code if failed else None,
            metadata={"result_reference": f"research-search:{batch.batch_id}"},
        )

    def replay(self, reference: str) -> ToolResult:
        prefix = "research-search:"
        if not reference.startswith(prefix):
            raise ValueError("invalid research search reference")
        batch = self._searches.get(UUID(reference[len(prefix) :]))
        if batch is None:
            raise KeyError("persisted research search is unavailable")
        failed = batch.status is ResearchSearchStatus.FAILED
        return ToolResult(
            content=self._content(batch),
            success=not failed,
            error=batch.error_code if failed else None,
        )

    @staticmethod
    def _content(batch: ResearchSearchBatch) -> str:
        return json.dumps(
            {
                "status": batch.status.value.lower(),
                "artifact_refs": [str(research_search_artifact_id(batch))],
                "summary": {
                    "document_ids": batch.document_ids,
                    "event_ids": batch.event_ids,
                },
                "safe_error_code": batch.error_code,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


class ReadNewsDetailTool(Tool):
    name = "read_news_detail"
    description = "Read one news document already known to the current sector task."
    tags = ["A2", "external_bounded", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {"document_id": {"type": "string", "minLength": 1}},
        "required": ["document_id"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: ReadBoundNewsDetailService,
        *,
        details: NewsDetailSnapshotRepositoryPort,
        context: BoundSectorResearchContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._details = details
        self._context = context
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"document_id"}:
            raise ValueError("URL, source, task identity and request options are server controlled")
        document_id = kwargs["document_id"]
        if not isinstance(document_id, str) or not document_id:
            raise ValueError("document_id must be non-empty text")
        try:
            snapshot = await self._service.read(
                context=self._context,
                document_id=document_id,
                now=self._clock(),
            )
        except NewsDetailAccessError as exc:
            return ToolResult(content="", success=False, error=str(exc))
        return self._result(snapshot)

    def replay(self, reference: str) -> ToolResult:
        prefix = "news-detail:"
        if not reference.startswith(prefix):
            raise ValueError("invalid news detail reference")
        snapshot = self._details.get(UUID(reference[len(prefix) :]))
        if snapshot is None:
            raise KeyError("persisted news detail is unavailable")
        return self._result(snapshot)

    @staticmethod
    def _result(snapshot: NewsDetailSnapshot) -> ToolResult:
        failed = snapshot.error_code == "TOOL_FAILED"
        return ToolResult(
            content=json.dumps(
                {
                    "availability": snapshot.availability,
                    "artifact_refs": [str(news_detail_artifact_id(snapshot))],
                    "document_id": snapshot.document_id,
                    "content": snapshot.content,
                    "content_hash": snapshot.content_hash,
                    "truncated": snapshot.truncated,
                    "historical_snapshot_verified": snapshot.historical_snapshot_verified,
                    "safe_error_code": snapshot.error_code,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            success=not failed,
            error=snapshot.error_code if failed else None,
            metadata={"result_reference": f"news-detail:{snapshot.detail_id}"},
        )


__all__ = ["ReadNewsDetailTool", "SearchNewsTool"]
