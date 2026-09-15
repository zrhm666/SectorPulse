"""Per-sector tool context. Observations are data, never model instructions."""

import asyncio
from datetime import timedelta

from sector_pulse.domain.news.news import NewsDocument, NewsUse
from sector_pulse.domain.writing.agent_execution import (
    InspectMarket,
    ReadNewsDetail,
    SearchNews,
    ToolObservation,
)
from sector_pulse.domain.writing.attribution import AttributionContext
from sector_pulse.ports.news_detail import NewsDetailPort
from sector_pulse.ports.news_sources import KeywordNewsSearchPort


class AttributionTools:
    def __init__(
        self,
        context: AttributionContext,
        search: KeywordNewsSearchPort,
        detail: NewsDetailPort,
        documents: tuple[NewsDocument, ...] = (),
    ) -> None:
        self.context = context
        self.search = search
        self.detail = detail
        self.documents = {document.document_id: document for document in documents}
        self._cache: dict[str, ToolObservation] = {}

    async def execute(self, action: SearchNews | ReadNewsDetail | InspectMarket) -> ToolObservation:
        key = action.model_dump_json()
        if key in self._cache:
            return self._cache[key]
        try:
            async with asyncio.timeout(30):
                observation = await self._execute(action)
        except TimeoutError:
            observation = ToolObservation(
                action=action.action, status="error", error_code="TOOL_TIMEOUT"
            )
        except Exception:
            # Provider exceptions may contain credentials/URLs; persist a stable public code.
            observation = ToolObservation(
                action=action.action, status="error", error_code="TOOL_FAILED"
            )
        self._cache[key] = observation
        return observation

    async def _execute(
        self, action: SearchNews | ReadNewsDetail | InspectMarket
    ) -> ToolObservation:
        if isinstance(action, InspectMarket):
            return ToolObservation(
                action=action.action,
                status="success",
                data={
                    "sector_id": self.context.sector_id,
                    "sector_kind": self.context.sector_kind.value,
                    "sector_name": self.context.sector_name,
                    "cutoff_at": self.context.cutoff_at.isoformat(),
                    "facts": self.context.model_dump(mode="json")["market_facts"],
                },
            )
        if isinstance(action, ReadNewsDetail):
            document = self.documents.get(action.document_id)
            if document is None:
                return ToolObservation(
                    action=action.action, status="error", error_code="UNKNOWN_DOCUMENT_ID"
                )
            if document.use_at(self.context.cutoff_at) is NewsUse.EXCLUDED:
                return ToolObservation(
                    action=action.action, status="unavailable", error_code="DOCUMENT_AFTER_CUTOFF"
                )
            detail = await self.detail.read(document)
            return ToolObservation(
                action=action.action,
                status="success" if detail.availability == "full_text" else "partial",
                data=detail.model_dump(mode="json"),
                error_code=detail.error_code,
            )
        query = " ".join(action.query.split())
        if not query:
            return ToolObservation(action=action.action, status="error", error_code="EMPTY_QUERY")
        # Bind the query to this sector even when the model chooses a company/event keyword.
        subject = self.context.sector_name or self.context.sector_id
        query = f"{subject} {query}" if subject not in query else query
        start_at = self.context.cutoff_at - timedelta(days=7)
        result = await self.search.search(query, start_at, self.context.cutoff_at)
        accepted = [
            document
            for document in (result.data or ())
            if document.use_at(self.context.cutoff_at) is not NewsUse.EXCLUDED
            and (document.published_at is None or document.published_at >= start_at)
        ][:10]
        for document in accepted:
            self.documents.setdefault(document.document_id, document)
        return ToolObservation(
            action=action.action,
            status="success" if accepted else "unavailable",
            data={"query": query, "documents": [d.model_dump(mode="json") for d in accepted]},
            error_code=result.error.code if result.error else None,
        )
