import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sector_pulse.application.candidate_selection import select_market_precandidates
from sector_pulse.application.news_retrieval import build_news_query_plan, execute_news_query_plan
from sector_pulse.domain.candidate import SectorCandidate
from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.news_retrieval import (
    NewsQueryPlan,
    QueryType,
    SectorEntityConfig,
)
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderError,
    ProviderManifest,
    ProviderResult,
)

START = datetime(2026, 8, 13, 2, 0, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 14, 2, 0, tzinfo=UTC)
ENTITY_CONFIG = SectorEntityConfig(
    version="2026-08-14.1",
    aliases={"industry-1": ("行业别名",)},
    industry_terms={"industry-1": ("产业链",)},
    ambiguous_terms=(),
)


def make_candidates(count: int) -> tuple[SectorCandidate, ...]:
    return tuple(
        SectorCandidate(
            rank=index,
            provider_sector_id=f"industry-{index}",
            name=f"行业{index}",
            kind=SectorKind.INDUSTRY,
            score=Decimal("0.9"),
            reasons=("movement",),
        )
        for index in range(1, count + 1)
    )


class FakeNewsProvider:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0
        self.active = 0
        self.peak_active = 0

    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="fake",
            version="1",
            capabilities=frozenset({"news.keyword.search", "news.global.discovery"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="fixture",
            retention_note="test",
        )

    async def fetch_global(self, cutoff: datetime):
        return ProviderResult(
            provider_id="fake",
            capability="news.global.discovery",
            status=DataStatus.EMPTY,
            collected_at=cutoff,
        )

    async def search(self, query: str, start_at: datetime, cutoff: datetime):
        del query, start_at
        self.calls += 1
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        if self.failures:
            self.failures -= 1
            return ProviderResult(
                provider_id="fake",
                capability="news.keyword.search",
                status=DataStatus.FAILED,
                collected_at=cutoff,
                error=ProviderError(code="TEMPORARY", message="retry", retriable=True),
            )
        return ProviderResult(
            provider_id="fake",
            capability="news.keyword.search",
            status=DataStatus.EMPTY,
            collected_at=cutoff,
        )

    async def search_disclosures(self, stock_codes, start_at, cutoff):
        del stock_codes, start_at
        return ProviderResult(
            provider_id="fake",
            capability="news.disclosure.search",
            status=DataStatus.EMPTY,
            collected_at=cutoff,
        )


def test_plan_obeys_keyword_and_disclosure_budgets() -> None:
    candidates = make_candidates(30)
    constituents = {candidate.provider_sector_id: (("600001", "龙头"),) for candidate in candidates}
    plan = build_news_query_plan(
        candidates,
        ENTITY_CONFIG,
        constituents,
        START,
        CUTOFF,
        keyword_budget=24,
        disclosure_code_budget=12,
    )
    assert sum(query.query_type is QueryType.GLOBAL for query in plan.queries) == 1
    assert sum(query.query_type is QueryType.KEYWORD for query in plan.queries) <= 24
    disclosure_codes = {
        query.value for query in plan.queries if query.query_type is QueryType.DISCLOSURE
    }
    assert len(disclosure_codes) <= 12
    assert plan == build_news_query_plan(
        candidates,
        ENTITY_CONFIG,
        constituents,
        START,
        CUTOFF,
        keyword_budget=24,
        disclosure_code_budget=12,
    )


def test_market_precandidates_do_not_depend_on_news() -> None:
    observed = datetime(2026, 8, 14, 2, 0, tzinfo=UTC)
    snapshot = SectorUniverseSnapshot(
        provider_id="fixture",
        classification_version="v1",
        source_version="v1",
        kind=SectorKind.INDUSTRY,
        observed_at=observed,
        collected_at=observed,
        sectors=tuple(
            SectorSnapshot(
                provider_sector_id=f"industry-{index}",
                name=f"行业{index}",
                kind=SectorKind.INDUSTRY,
                pct_change=Decimal(str(index)),
                turnover_rate=Decimal("1"),
                advancers=2,
                decliners=1,
            )
            for index in range(1, 4)
        ),
    )
    result = select_market_precandidates(snapshot, snapshot, limit=2)
    assert len(result) == 2


def test_query_executor_retries_and_preserves_plan_order() -> None:
    provider = FakeNewsProvider(failures=1)
    plan = NewsQueryPlan(
        rule_version="1",
        queries=tuple(
            build_news_query_plan(
                make_candidates(1),
                ENTITY_CONFIG,
                {"industry-1": (("600001", "龙头"),)},
                START,
                CUTOFF,
                1,
                1,
            ).queries[1:2]
        ),
        keyword_budget=1,
        disclosure_code_budget=1,
        concurrency_per_provider=4,
    )
    results = asyncio.run(
        execute_news_query_plan(
            plan,
            provider,
            provider,
            provider,
            max_retries=2,
            retry_backoff=lambda _: 0,
        )
    )
    assert len(results) == 1
    assert results[0].attempts == 2
    assert provider.calls == 2
