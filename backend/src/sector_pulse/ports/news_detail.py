from typing import Protocol

from sector_pulse.domain.news.news import NewsDocument
from sector_pulse.domain.news.news_detail import NewsDetail


class NewsDetailPort(Protocol):
    async def read(self, document: NewsDocument) -> NewsDetail: ...
