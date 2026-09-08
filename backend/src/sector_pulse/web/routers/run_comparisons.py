from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from sector_pulse.application.comparison.run_comparison_models import (
    EvidenceComparisonPage,
    MembershipFilter,
    NewsComparisonPage,
    Provider,
    RunComparisonView,
    RunMode,
    RunOptionPage,
)
from sector_pulse.application.comparison.run_comparison_queries import (
    ComparisonConflictError,
    ComparisonInputError,
    ComparisonNotFoundError,
    RunComparisonQueries,
)
from sector_pulse.domain.market import SectorKind


def _query[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ComparisonNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ComparisonConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ComparisonInputError as exc:
        raise HTTPException(422, str(exc)) from exc


def build_run_comparisons_router(queries: RunComparisonQueries) -> APIRouter:
    router = APIRouter(prefix="/api/run-comparisons", tags=["run-comparisons"])

    @router.get("/runs", response_model=RunOptionPage)
    def runs(
        provider: Provider | None = None,
        mode: RunMode | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ) -> RunOptionPage:
        return _query(
            lambda: queries.list_runs(provider=provider, mode=mode, offset=offset, limit=limit)
        )

    @router.get("", response_model=RunComparisonView)
    def compare(base_run_id: UUID, compare_run_id: UUID) -> RunComparisonView:
        return _query(lambda: queries.compare(base_run_id, compare_run_id))

    @router.get("/news", response_model=NewsComparisonPage)
    def news(
        base_run_id: UUID,
        compare_run_id: UUID,
        membership: MembershipFilter = "ALL",
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ) -> NewsComparisonPage:
        return _query(
            lambda: queries.news(
                base_run_id, compare_run_id, membership=membership, offset=offset, limit=limit
            )
        )

    @router.get("/evidence", response_model=EvidenceComparisonPage)
    def evidence(
        base_run_id: UUID,
        compare_run_id: UUID,
        kind: SectorKind | None = None,
        sector_id: str | None = Query(None, min_length=1),
        offset: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
    ) -> EvidenceComparisonPage:
        return _query(
            lambda: queries.evidence(
                base_run_id,
                compare_run_id,
                kind=kind,
                sector_id=sector_id,
                offset=offset,
                limit=limit,
            )
        )

    return router
