import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Any

import akshare as ak  # type: ignore[import-untyped]

from sector_pulse.domain.market import SectorKind


@dataclass(frozen=True)
class RawSectorBatch:
    rows: list[dict[str, Any]]
    observed_at: datetime
    collected_at: datetime
    source_version: str
    raw_artifact_sha256: str


class PandasAkShareClient:
    async def fetch(self, kind: SectorKind) -> RawSectorBatch:
        # AKShare 是同步 DataFrame API，放到线程中执行以免阻塞后续并行采集。
        function = (
            ak.stock_board_industry_name_em
            if kind is SectorKind.INDUSTRY
            else ak.stock_board_concept_name_em
        )
        started = datetime.now(UTC)
        frame = await asyncio.to_thread(function)
        completed = datetime.now(UTC)
        rows = frame.to_dict(orient="records")
        digest = hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        return RawSectorBatch(rows, started, completed, version("akshare"), digest)


class PandasThsAkShareClient(PandasAkShareClient):
    async def fetch(self, kind: SectorKind) -> RawSectorBatch:
        function = (
            ak.stock_board_industry_name_ths
            if kind is SectorKind.INDUSTRY
            else ak.stock_board_concept_name_ths
        )
        started = datetime.now(UTC)
        frame = await asyncio.to_thread(function)
        completed = datetime.now(UTC)
        rows = frame.to_dict(orient="records")
        digest = hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        return RawSectorBatch(rows, started, completed, version("akshare"), digest)
