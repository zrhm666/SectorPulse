from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot

FIELD = {
    "name": "板块名称",
    "code": "板块代码",
    "pct": "涨跌幅",
    "cap": "总市值",
    "turnover": "换手率",
    "up": "上涨家数",
    "down": "下跌家数",
    "leader": "领涨股票",
    "leader_pct": "领涨股票-涨跌幅",
}


def _get(row: Mapping[str, Any], key: str) -> Any:
    # 仅在 Adapter 边界识别中文供应商列名，领域层不泄露 AKShare/DataFrame 细节。
    if FIELD[key] in row:
        return row[FIELD[key]]
    aliases = {
        "name": ("名称",),
        "code": ("代码",),
        "pct": ("涨跌幅",),
        "turnover": ("换手率",),
        "up": ("上涨家数",),
        "down": ("下跌家数",),
        "leader": ("领涨股票",),
        "leader_pct": ("领涨股票-涨跌幅",),
    }
    for alias in aliases.get(key, ()):
        if alias in row:
            return row[alias]
    return None


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "" or str(value).lower() in {"nan", "none"}:
        return None
    return Decimal(str(value).replace("%", ""))


def map_sector_rows(
    rows: Sequence[Mapping[str, Any]],
    kind: SectorKind,
    observed_at: datetime,
    collected_at: datetime,
    source_version: str,
) -> SectorUniverseSnapshot:
    # 将原始行转换为不可变领域快照；缺失的可选指标保留为 None，而非编造数值。
    sectors = tuple(
        SectorSnapshot(
            provider_sector_id=str(_get(row, "code") or _get(row, "name")),
            name=str(_get(row, "name") or ""),
            kind=kind,
            pct_change=decimal_or_none(_get(row, "pct")) or Decimal("0"),
            turnover_rate=decimal_or_none(_get(row, "turnover")),
            total_market_cap=decimal_or_none(_get(row, "cap")),
            advancers=int(_get(row, "up") or 0),
            decliners=int(_get(row, "down") or 0),
            leader_name=str(_get(row, "leader")) if _get(row, "leader") else None,
            leader_pct_change=decimal_or_none(_get(row, "leader_pct")),
        )
        for row in rows
    )
    return SectorUniverseSnapshot(
        provider_id="akshare-eastmoney",
        classification_version=f"eastmoney-{kind.value.lower()}",
        source_version=source_version,
        kind=kind,
        observed_at=observed_at,
        collected_at=collected_at,
        sectors=sectors,
    )
