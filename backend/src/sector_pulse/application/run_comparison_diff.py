"""Pure differences over persisted observations, never scores recomputed from live data."""

from collections.abc import Sequence
from decimal import Decimal

from sector_pulse.application.run_comparison_models import (
    Membership,
    MetricDifference,
    MetricUnit,
    MissingReason,
)
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.real_data_run import RealDataCandidate


def metric_difference(
    base: Decimal | None,
    compare: Decimal | None,
    *,
    unit: MetricUnit,
    base_reason: MissingReason | None = None,
    compare_reason: MissingReason | None = None,
) -> MetricDifference:
    if base_reason is not None:
        base = None
    if compare_reason is not None:
        compare = None
    return MetricDifference(
        base=base,
        compare=compare,
        delta=None if base is None or compare is None else compare - base,
        unit=unit,
        base_reason=base_reason or ("VALUE_MISSING" if base is None else None),
        compare_reason=compare_reason or ("VALUE_MISSING" if compare is None else None),
    )


def rank_delta(base: int | None, compare: int | None) -> int | None:
    return None if base is None or compare is None else base - compare


def candidate_keys(candidates: Sequence[RealDataCandidate]) -> set[tuple[SectorKind, str]]:
    return {(item.sector_kind, item.sector_id) for item in candidates}


def document_membership(base_ids: set[str], compare_ids: set[str]) -> dict[str, Membership]:
    return {
        key: "BOTH"
        if key in base_ids and key in compare_ids
        else "ONLY_BASE"
        if key in base_ids
        else "ONLY_COMPARE"
        for key in sorted(base_ids | compare_ids)
    }
