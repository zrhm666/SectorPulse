from datetime import UTC, datetime

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.provider import DataStatus
from sector_pulse.infrastructure.providers.akshare.constituents import (
    AkShareSectorConstituentAdapter,
)


def test_constituent_rows_are_normalized() -> None:
    result = AkShareSectorConstituentAdapter().map_rows(
        [{"代码": "600001", "名称": "示例股"}], SectorKind.INDUSTRY, datetime.now(UTC)
    )
    assert result.status is DataStatus.SUCCESS
    assert result.data == (("600001", "示例股"),)
