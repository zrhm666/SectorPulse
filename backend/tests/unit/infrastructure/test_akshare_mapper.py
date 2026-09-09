import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sector_pulse.domain.market.market import SectorKind
from sector_pulse.infrastructure.providers.akshare.mapper import map_sector_rows


def test_mapper_records_only_fields_present_in_provider_rows() -> None:
    now = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
    snapshot = map_sector_rows(
        ({"code": "881121", "name": "Semiconductor"},),
        SectorKind.INDUSTRY,
        now,
        now,
        "test",
        provider_id="akshare-ths",
        classification_prefix="ths",
        raw_artifact_sha256="abc123",
    )

    assert snapshot.available_fields == frozenset({"provider_sector_id", "name"})
    assert snapshot.raw_artifact_sha256 == "abc123"
    assert snapshot.sectors[0].pct_change == Decimal("0")


def test_mapper_marks_explicit_zero_as_available() -> None:
    now = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
    snapshot = map_sector_rows(
        ({"code": "BK1", "name": "Test", "pct_change": 0},),
        SectorKind.INDUSTRY,
        now,
        now,
        "test",
    )

    assert "pct_change" in snapshot.available_fields


def test_mapper_supports_ths_industry_summary_fields() -> None:
    now = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
    snapshot = map_sector_rows(
        (
            {
                "code": "881121",
                "name": "半导体",
                "涨跌幅": 2.3,
                "上涨家数": 20,
                "下跌家数": 4,
                "领涨股": "测试股份",
                "领涨股-涨跌幅": 9.8,
            },
        ),
        SectorKind.INDUSTRY,
        now,
        now,
        "test",
        provider_id="akshare-ths",
        classification_prefix="ths",
    )

    assert snapshot.available_fields == frozenset(
        {
            "provider_sector_id",
            "name",
            "pct_change",
            "advancers",
            "decliners",
            "leader_name",
            "leader_pct_change",
        }
    )
    assert snapshot.sectors[0].leader_name == "测试股份"
    assert snapshot.sectors[0].leader_pct_change == Decimal("9.8")


def test_mapper_hides_chinese_supplier_columns() -> None:
    rows = json.loads(Path("backend/tests/fixtures/akshare_sector_rows.json").read_text("utf-8"))
    now = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)
    universe = map_sector_rows(rows, SectorKind.CONCEPT, now, now, "fixture-v1")
    assert universe.sector_count == 2
    assert universe.sectors[0].provider_sector_id == "BK0001"
    assert str(universe.sectors[0].pct_change) == "2.5"
    assert universe.sectors[0].name == "示例板块甲"
