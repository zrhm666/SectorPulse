import asyncio
import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sector_pulse.domain.market.candidate import SectorCandidate
from sector_pulse.domain.news.news import NewsDocument
from sector_pulse.domain.news.news_retrieval import (
    NewsQuery,
    NewsQueryPlan,
    QueryType,
    SectorEntityConfig,
)
from sector_pulse.domain.provider import DataStatus, ProviderError, ProviderResult
from sector_pulse.ports.news_sources import (
    DisclosureSearchPort,
    GlobalNewsDiscoveryPort,
    KeywordNewsSearchPort,
)


def _query_id(query_type: QueryType, source_id: str, value: str, cutoff: datetime) -> str:
    raw = f"{query_type.value}|{source_id}|{value.strip().lower()}|{cutoff.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def build_news_query_plan(
    candidates: Sequence[SectorCandidate],
    entity_config: SectorEntityConfig,
    constituents: Mapping[str, Sequence[tuple[str, str]]],
    start_at: datetime,
    cutoff: datetime,
    keyword_budget: int = 24,
    disclosure_code_budget: int = 12,
) -> NewsQueryPlan:
    queries: list[NewsQuery] = [
        NewsQuery(
            query_id=_query_id(QueryType.GLOBAL, "cls", "全部", cutoff),
            query_type=QueryType.GLOBAL,
            source_id="cls",
            value="全部",
            priority=100,
            start_at=start_at,
            cutoff_at=cutoff,
        )
    ]
    keyword_values: list[tuple[int, str, tuple[str, ...]]] = []
    code_values: list[tuple[int, str, tuple[str, ...]]] = []
    for candidate in sorted(candidates, key=lambda item: (item.rank, item.provider_sector_id)):
        sector_ids: tuple[str, ...] = (candidate.provider_sector_id,)
        keyword_values.append((90, candidate.name, sector_ids))
        for alias in entity_config.aliases.get(candidate.provider_sector_id, ()):
            keyword_values.append((80, alias, sector_ids))
        if candidate.name != candidate.provider_sector_id:
            keyword_values.append((70, candidate.provider_sector_id, sector_ids))
        for code, _name in constituents.get(candidate.provider_sector_id, ()):
            code_values.append((60, code, sector_ids))

    seen_keyword: set[str] = set()
    for priority, value, sector_ids in sorted(keyword_values, key=lambda item: (-item[0], item[1])):
        normalized = value.strip().lower()
        if not normalized or normalized in seen_keyword or len(seen_keyword) >= keyword_budget:
            continue
        seen_keyword.add(normalized)
        queries.append(
            NewsQuery(
                query_id=_query_id(QueryType.KEYWORD, "eastmoney", value, cutoff),
                query_type=QueryType.KEYWORD,
                source_id="eastmoney",
                value=value,
                sector_ids=sector_ids,
                priority=priority,
                start_at=start_at,
                cutoff_at=cutoff,
            )
        )

    seen_codes: set[str] = set()
    for priority, value, sector_ids in sorted(code_values, key=lambda item: (-item[0], item[1])):
        if value in seen_codes or len(seen_codes) >= disclosure_code_budget:
            continue
        seen_codes.add(value)
        queries.append(
            NewsQuery(
                query_id=_query_id(QueryType.DISCLOSURE, "cninfo", value, cutoff),
                query_type=QueryType.DISCLOSURE,
                source_id="cninfo",
                value=value,
                sector_ids=sector_ids,
                priority=priority,
                start_at=start_at,
                cutoff_at=cutoff,
            )
        )
    return NewsQueryPlan(
        rule_version=entity_config.version,
        queries=tuple(queries),
        keyword_budget=keyword_budget,
        disclosure_code_budget=disclosure_code_budget,
    )


@dataclass(frozen=True)
class QueryExecutionResult:
    query: NewsQuery
    status: DataStatus
    documents: tuple[NewsDocument, ...]
    attempts: int
    duration_ms: int
    started_at: datetime
    completed_at: datetime
    error_code: str | None = None


class _RetryableProvider(Protocol):
    async def __call__(self, query: NewsQuery) -> ProviderResult[tuple[NewsDocument, ...]]: ...


async def _execute_one(
    query: NewsQuery,
    provider_call: _RetryableProvider,
    semaphore: asyncio.Semaphore,
    max_retries: int,
    retry_backoff: Callable[[int], float],
) -> QueryExecutionResult:
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    attempts = 0
    async with semaphore:
        while True:
            attempts += 1
            try:
                result = await provider_call(query)
            except Exception as exc:  # 单个查询异常必须被隔离，不能取消同批其他查询。
                result = ProviderResult(
                    provider_id=query.source_id,
                    capability=f"news.{query.query_type.value}.search",
                    status=DataStatus.FAILED,
                    collected_at=datetime.now(UTC),
                    error=ProviderError(
                        code="QUERY_EXECUTION_FAILED",
                        message=str(exc),
                        retriable=False,
                    ),
                )
            if (
                result.status is not DataStatus.FAILED
                or result.error is None
                or not result.error.retriable
            ):
                break
            if attempts > max_retries:
                break
            await asyncio.sleep(retry_backoff(attempts))
    completed_at = datetime.now(UTC)
    return QueryExecutionResult(
        query=query,
        status=result.status,
        documents=result.data or (),
        attempts=attempts,
        duration_ms=int((time.perf_counter() - started) * 1000),
        started_at=started_at,
        completed_at=completed_at,
        error_code=result.error.code if result.error else None,
    )


async def execute_news_query_plan(
    plan: NewsQueryPlan,
    global_provider: GlobalNewsDiscoveryPort,
    keyword_provider: KeywordNewsSearchPort,
    disclosure_provider: DisclosureSearchPort,
    max_retries: int = 2,
    retry_backoff: Callable[[int], float] | None = None,
) -> tuple[QueryExecutionResult, ...]:
    """按来源独立限并发执行查询；单个失败不会取消其他查询。"""
    backoff = retry_backoff or (lambda attempt: 0.5 * attempt)
    semaphores = {
        source_id: asyncio.Semaphore(plan.concurrency_per_provider)
        for source_id in ("cls", "eastmoney", "cninfo")
    }

    async def call(query: NewsQuery) -> ProviderResult[tuple[NewsDocument, ...]]:
        if query.query_type is QueryType.GLOBAL:
            return await global_provider.fetch_global(query.cutoff_at)
        if query.query_type is QueryType.KEYWORD:
            return await keyword_provider.search(query.value, query.start_at, query.cutoff_at)
        return await disclosure_provider.search_disclosures(
            (query.value,), query.start_at, query.cutoff_at
        )

    async def run(query: NewsQuery) -> QueryExecutionResult:
        source = "cls" if query.query_type is QueryType.GLOBAL else query.source_id
        return await _execute_one(query, call, semaphores[source], max_retries, backoff)

    results = await asyncio.gather(*(run(query) for query in plan.queries), return_exceptions=False)
    return tuple(results)
