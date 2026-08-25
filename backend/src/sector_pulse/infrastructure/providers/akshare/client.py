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


def _normalized_board_name(value: object) -> str:
    return str(value).strip()


def _merge_ths_industry_rows(
    name_frame: Any, summary_frame: Any
) -> list[dict[str, Any]]:
    names = name_frame.to_dict(orient="records")
    summaries = summary_frame.to_dict(orient="records")
    by_name = {
        _normalized_board_name(row.get("板块")): row
        for row in summaries
    }
    expected = {_normalized_board_name(row.get("name")) for row in names}
    if (
        not expected
        or expected != set(by_name)
        or len(names) != len(summaries)
        or len(by_name) != len(summaries)
    ):
        raise ValueError("THS industry field contract mismatch")
    return [
        {**row, **by_name[_normalized_board_name(row.get("name"))]}
        for row in names
    ]


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
        started = datetime.now(UTC)
        if kind is SectorKind.INDUSTRY:
            # Both THS functions initialize py_mini_racer/V8. Running them concurrently
            # can crash the Windows process before Python can surface an exception.
            name_frame = await asyncio.to_thread(ak.stock_board_industry_name_ths)
            summary_frame = await asyncio.to_thread(
                ak.stock_board_industry_summary_ths
            )
            rows = _merge_ths_industry_rows(name_frame, summary_frame)
        else:
            frame = await asyncio.to_thread(ak.stock_board_concept_name_ths)
            rows = frame.to_dict(orient="records")
        completed = datetime.now(UTC)
        digest = hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        return RawSectorBatch(rows, started, completed, version("akshare"), digest)
