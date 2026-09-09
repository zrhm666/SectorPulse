import asyncio
from datetime import UTC, datetime
from typing import Any

import akshare as ak  # type: ignore[import-untyped]

from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderError,
    ProviderManifest,
    ProviderResult,
)


class AkShareSectorConstituentAdapter:
    """仅为有限预候选获取成分股，不把 DataFrame 暴露给应用层。"""

    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="akshare-eastmoney-constituents",
            version="1.0.0",
            capabilities=frozenset({"sector_constituents.industry", "sector_constituents.concept"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="AKShare / 东方财富板块成分股",
            retention_note="Codes and names only",
        )

    @staticmethod
    def map_rows(
        rows: list[dict[str, Any]], kind: SectorKind, collected_at: datetime
    ) -> ProviderResult[tuple[tuple[str, str], ...]]:
        del kind
        members = tuple(
            (
                str(row.get("代码") or row.get("股票代码") or ""),
                str(row.get("名称") or row.get("股票简称") or ""),
            )
            for row in rows
        )
        members = tuple(item for item in members if item[0] and item[1])
        if not members:
            return ProviderResult(
                provider_id="akshare-eastmoney-constituents",
                capability="sector_constituents",
                status=DataStatus.EMPTY,
                collected_at=collected_at,
            )
        return ProviderResult(
            provider_id="akshare-eastmoney-constituents",
            capability="sector_constituents",
            status=DataStatus.SUCCESS,
            data=members,
            collected_at=collected_at,
        )

    async def fetch_constituents(
        self, sector_name: str, kind: SectorKind
    ) -> ProviderResult[tuple[tuple[str, str], ...]]:
        function = (
            ak.stock_board_industry_cons_em
            if kind is SectorKind.INDUSTRY
            else ak.stock_board_concept_cons_em
        )
        collected_at = datetime.now(UTC)
        try:
            frame = await asyncio.to_thread(function, symbol=sector_name)
            return self.map_rows(frame.to_dict(orient="records"), kind, collected_at)
        except Exception as exc:
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability="sector_constituents",
                status=DataStatus.FAILED,
                collected_at=collected_at,
                error=ProviderError(
                    code="AKSHARE_CONSTITUENTS_FAILED", message=str(exc), retriable=True
                ),
            )
