from decimal import Decimal

import pytest
from sector_pulse.application.run_comparison_diff import (
    candidate_keys,
    document_membership,
    metric_difference,
    rank_delta,
)
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.real_data_run import RealDataCandidate


def test_percentage_difference_preserves_decimal_zero() -> None:
    result = metric_difference(Decimal("0"), Decimal("0.10"), unit="percentage_points")
    assert result.base == Decimal("0")
    assert result.delta == Decimal("0.10")
    assert result.model_dump(mode="json")["delta"] == "0.10"
    assert result.base_reason is None


@pytest.mark.parametrize(
    "base,compare,expected", [(5, 2, 3), (2, 5, -3), (2, 2, 0), (None, 2, None), (2, None, None)]
)
def test_rank_direction_and_missing_candidates(base, compare, expected) -> None:
    assert rank_delta(base, compare) == expected


def test_missing_value_does_not_become_zero() -> None:
    result = metric_difference(None, Decimal("0"), unit="count")
    assert result.base is None
    assert result.delta is None
    assert result.base_reason == "VALUE_MISSING"
    assert result.compare_reason is None


def test_undeclared_default_value_is_not_an_observation() -> None:
    result = metric_difference(
        Decimal("0"), Decimal("3"), unit="count", base_reason="FIELD_UNDECLARED"
    )
    assert result.base is None
    assert result.delta is None
    assert result.base_reason == "FIELD_UNDECLARED"


def test_negative_decimal_changes_are_exact() -> None:
    result = metric_difference(Decimal("1.10"), Decimal("-0.20"), unit="percentage_points")
    assert result.delta == Decimal("-1.30")


def test_candidate_identity_includes_kind() -> None:
    items = [
        RealDataCandidate(
            sector_id="001", sector_kind=kind, rank=rank, score=Decimal("0.5"), reasons=()
        )
        for rank, kind in enumerate(SectorKind, 1)
    ]
    assert candidate_keys(items) == {(SectorKind.INDUSTRY, "001"), (SectorKind.CONCEPT, "001")}


def test_document_membership_uses_distinct_ids_and_stable_order() -> None:
    result = document_membership({"a", "shared"}, {"b", "shared"})
    assert result == {"a": "ONLY_BASE", "b": "ONLY_COMPARE", "shared": "BOTH"}
    assert list(result) == ["a", "b", "shared"]
    assert document_membership(set(), set()) == {}
