import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Any

import akshare as ak  # type: ignore[import-untyped]


@dataclass(frozen=True)
class RawNewsBatch:
    rows: list[dict[str, Any]]
    collected_at: datetime
    source_version: str
    raw_artifact_sha256: str


class PandasAkShareNewsClient:
    """隔离 AKShare 同步 DataFrame 调用；领域层只接收普通 dict。"""

    async def _call(self, function: Callable[..., Any], **kwargs: Any) -> RawNewsBatch:
        collected_at = datetime.now(UTC)
        frame = await asyncio.to_thread(function, **kwargs)
        rows = frame.to_dict(orient="records")
        digest = hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return RawNewsBatch(rows, collected_at, version("akshare"), digest)

    async def fetch_cls(self) -> RawNewsBatch:
        return await self._call(ak.stock_info_global_cls, symbol="全部")

    async def search_eastmoney(self, query: str) -> RawNewsBatch:
        return await self._call(ak.stock_news_em, symbol=query)

    async def search_cninfo(
        self, stock_code: str, start_date: str, end_date: str
    ) -> RawNewsBatch:
        return await self._call(
            ak.stock_zh_a_disclosure_report_cninfo,
            symbol=stock_code,
            market="沪深京",
            category="",
            start_date=start_date,
            end_date=end_date,
        )
