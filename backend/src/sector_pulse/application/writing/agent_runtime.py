"""Connect per-sector loops to trusted news, persistent traces and pipeline artifacts."""

import asyncio
from dataclasses import dataclass
from typing import Any

from sector_pulse.application.news.news_ingestion import deduplicate_documents
from sector_pulse.application.writing.agent_runner import run_agent_loop
from sector_pulse.application.writing.agent_tools import AttributionTools
from sector_pulse.application.writing.attribution_agents import AttributionAgentResult
from sector_pulse.application.writing.invocations import InvocationSink
from sector_pulse.application.writing.progress import ProgressSink
from sector_pulse.domain.news.news import NewsUse
from sector_pulse.domain.writing.agent_execution import AgentLimits
from sector_pulse.domain.writing.article import ArticleSource
from sector_pulse.domain.writing.attribution import AttributionContext, AttributionGateResult
from sector_pulse.infrastructure.llm.prompt_registry import PromptDefinition
from sector_pulse.ports.llm import LLMPort
from sector_pulse.ports.news_detail import NewsDetailPort
from sector_pulse.ports.news_sources import KeywordNewsSearchPort
from sector_pulse.storage.ports.news import NewsRepositoryPort
from sector_pulse.storage.ports.writing import AgentTracePort


@dataclass
class AgentRuntime:
    news: NewsRepositoryPort
    trace: AgentTracePort
    search: KeywordNewsSearchPort
    detail: NewsDetailPort
    limits: AgentLimits
    prompt: PromptDefinition | None = None

    async def run(
        self,
        contexts: tuple[AttributionContext, ...],
        gates: dict[str, AttributionGateResult],
        llm: LLMPort,
        model: str,
        invocation_sink: InvocationSink,
        progress: ProgressSink,
        sources: dict[str, tuple[ArticleSource, ...]],
    ) -> tuple[tuple[AttributionAgentResult, ...], tuple[AttributionContext, ...]]:
        semaphore = asyncio.Semaphore(2)
        updated = dict((context.sector_id, context) for context in contexts)

        async def one(initial: AttributionContext) -> AttributionAgentResult:
            async with semaphore:
                original_events = self.news.get_events(initial.event_ids)
                original_docs = self.news.get_documents(
                    tuple(doc_id for event in original_events for doc_id in event.document_ids)
                )
                tools = AttributionTools(
                    initial, self.search, self.detail, tuple(original_docs.values())
                )
                seen_documents = set(original_docs)

                def refresh() -> tuple[AttributionContext, AttributionGateResult]:
                    context = updated[initial.sector_id]
                    new_docs = [
                        doc for key, doc in tools.documents.items() if key not in seen_documents
                    ]
                    # The search keyword alone is not proof that an article is about the sector.
                    subject = initial.sector_name or initial.sector_id
                    linked = [
                        doc
                        for doc in new_docs
                        if subject in (doc.title + (doc.summary or ""))
                        and doc.use_at(initial.cutoff_at) is not NewsUse.EXCLUDED
                    ]
                    if not linked:
                        return context, gates[initial.sector_id]
                    events = deduplicate_documents(linked)
                    self.news.save(linked, events)
                    seen_documents.update(doc.document_id for doc in linked)
                    # This provider searches current pages, not verified historical snapshots.
                    # Newly observed documents are background; never invent a stronger causal gate.
                    context = context.model_copy(
                        update={
                            "event_ids": tuple(
                                dict.fromkeys((*context.event_ids, *(e.event_id for e in events)))
                            ),
                            "background_event_ids": tuple(
                                dict.fromkeys(
                                    (*context.background_event_ids, *(e.event_id for e in events))
                                )
                            ),
                            "source_grades": {
                                **context.source_grades,
                                **{d.document_id: d.source_grade for d in linked},
                            },
                        }
                    )
                    updated[initial.sector_id] = context
                    tools.context = context
                    additions = tuple(
                        ArticleSource(
                            source_id=event.event_id,
                            title=event.canonical_title,
                            citation_url=tools.documents[event.document_ids[0]].citation_url,
                            publisher=tools.documents[event.document_ids[0]].publisher,
                            published_at=event.first_published_at.isoformat()
                            if event.first_published_at
                            else None,
                        )
                        for event in events
                    )
                    sources[initial.sector_id] = tuple(
                        {
                            s.source_id: s
                            for s in (*sources.get(initial.sector_id, ()), *additions)
                        }.values()
                    )
                    return context, gates[initial.sector_id]

                async def admit(_request: Any) -> bool:
                    return not getattr(llm, "exhausted", False)

                def step(index: int, event: dict[str, Any]) -> None:
                    self.trace.save(initial, index, event)
                    progress.emit(
                        "agent.step",
                        {
                            "sector_id": initial.sector_id,
                            "sector_kind": initial.sector_kind.value,
                            "step": index,
                            "type": event["type"],
                        },
                    )

                step(
                    0,
                    {
                        "type": "started",
                        "limits": self.limits.model_dump(),
                        "sector_name": initial.sector_name,
                        "prompt_version": self.prompt.version if self.prompt else "1",
                        "prompt_hash": self.prompt.content_sha256 if self.prompt else None,
                    },
                )
                result = await run_agent_loop(
                    initial,
                    gates[initial.sector_id],
                    llm,
                    tools,
                    model=model,
                    limits=self.limits,
                    admit=admit,
                    record_invocation=invocation_sink,
                    record_step=step,
                    refresh_state=refresh,
                    prompt=self.prompt,
                )
                return AttributionAgentResult(
                    result.card, None if result.stop_reason == "finished" else result.stop_reason
                )

        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(one(context)) for context in contexts]
        return tuple(task.result() for task in tasks), tuple(updated[c.sector_id] for c in contexts)
