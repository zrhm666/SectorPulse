import json
from datetime import UTC, datetime
from pathlib import Path

from sector_pulse.domain.market import SectorKind
from sector_pulse.infrastructure.providers.akshare.mapper import map_sector_rows


def test_mapper_hides_chinese_supplier_columns() -> None:
    rows = json.loads(Path("backend/tests/fixtures/akshare_sector_rows.json").read_text("utf-8"))
    now = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)
    universe = map_sector_rows(rows, SectorKind.CONCEPT, now, now, "fixture-v1")
    assert universe.sector_count == 2
    assert universe.sectors[0].provider_sector_id == "BK0001"
    assert str(universe.sectors[0].pct_change) == "2.5"
    assert universe.sectors[0].name == "示例板块甲"
