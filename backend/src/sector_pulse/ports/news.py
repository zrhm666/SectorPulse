from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from sector_pulse.domain.news import NewsDocument
from sector_pulse.domain.provider import ProviderResult


class NewsPort(Protocol):
    """新闻发现 Provider 的稳定接口。"""

    async def fetch_since(
        self, cutoff: datetime, source_ids: Sequence[str]
    ) -> ProviderResult[tuple[NewsDocument, ...]]: ...
