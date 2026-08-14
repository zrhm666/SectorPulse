from datetime import UTC, datetime, timedelta

import pytest
from sector_pulse.domain.provider import DataStatus
from sector_pulse.infrastructure.news.akshare_adapters import (
    AkShareClsAdapter,
    AkShareCninfoAdapter,
    AkShareEastmoneyNewsAdapter,
)

pytestmark = pytest.mark.live


async def test_cls_live_returns_explicit_status() -> None:
    result = await AkShareClsAdapter().fetch_global(datetime.now(UTC))
    assert result.status in {DataStatus.SUCCESS, DataStatus.EMPTY, DataStatus.PARTIAL}
    assert result.status is not DataStatus.FAILED


async def test_eastmoney_live_has_auditable_metadata() -> None:
    now = datetime.now(UTC)
    result = await AkShareEastmoneyNewsAdapter().search(
        "人工智能", now - timedelta(days=7), now
    )
    assert result.status in {DataStatus.SUCCESS, DataStatus.EMPTY, DataStatus.PARTIAL}
    for document in result.data or ():
        assert document.source_id
        assert document.published_at is None or document.published_at <= now
        assert document.source_observed_at is None or document.source_observed_at <= now


async def test_cninfo_live_has_primary_documents_or_empty() -> None:
    now = datetime.now(UTC)
    result = await AkShareCninfoAdapter().search_disclosures(
        ("000001",), now - timedelta(days=7), now
    )
    assert result.status in {DataStatus.SUCCESS, DataStatus.EMPTY, DataStatus.PARTIAL}
