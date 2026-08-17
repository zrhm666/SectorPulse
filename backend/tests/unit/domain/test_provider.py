from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sector_pulse.domain.provider import DataStatus, ProviderError, ProviderResult


def test_failed_result_requires_error_and_forbids_data() -> None:
    now = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        ProviderResult[list[str]](
            provider_id="example",
            capability="sector_universe",
            status=DataStatus.FAILED,
            data=["bad"],
            collected_at=now,
            error=ProviderError(code="NETWORK", message="timeout", retriable=True),
        )


def test_empty_is_not_failed() -> None:
    result = ProviderResult[list[str]](
        provider_id="example",
        capability="sector_universe",
        status=DataStatus.EMPTY,
        data=None,
        collected_at=datetime(2026, 8, 13, 6, 0, tzinfo=UTC),
    )
    assert result.error is None


def test_success_result_requires_data() -> None:
    with pytest.raises(ValidationError):
        ProviderResult[list[str]](
            provider_id="example",
            capability="sector_universe",
            status=DataStatus.SUCCESS,
            data=None,
            collected_at=datetime(2026, 8, 13, 6, 0, tzinfo=UTC),
        )


def test_partial_result_requires_data_and_error() -> None:
    now = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)
    result = ProviderResult[list[str]](
        provider_id="example",
        capability="news.keyword.search",
        status=DataStatus.PARTIAL,
        data=["one"],
        collected_at=now,
        error=ProviderError(code="ROW_MAPPING", message="one row skipped", retriable=False),
    )
    assert result.data == ["one"]
    with pytest.raises(ValidationError):
        ProviderResult[list[str]](
            provider_id="example",
            capability="news.keyword.search",
            status=DataStatus.PARTIAL,
            data=["one"],
            collected_at=now,
        )
