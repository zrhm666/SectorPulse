from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sector_pulse.application.writing.agent_tools import AttributionTools
from sector_pulse.domain.news.news import NewsDocument, SourceGrade
from sector_pulse.domain.writing.agent_execution import (
    ACTION_ADAPTER,
    InspectMarket,
    ReadNewsDetail,
    SearchNews,
)
from sector_pulse.infrastructure.news.news_detail_reader import (
    ArticleTextParser,
    PublicNewsDetailReader,
    allowed_article_url,
)

from backend.tests.integration.test_phase1b_pipeline import contexts


def document(**updates):
    values = dict(
        document_id="doc-1",
        source_id="test",
        canonical_locator="test:1",
        title="文化传媒新闻",
        summary="摘要",
        published_at=contexts()[0].cutoff_at,
        collected_at=datetime.now(UTC),
        content_hash="abc",
        source_grade=SourceGrade.DISCOVERY_ONLY,
    )
    return NewsDocument(**{**values, **updates})


@pytest.mark.parametrize(
    "action",
    [
        {"action": "shell", "command": "test"},
        {"action": "inspect_market", "sector_id": "other"},
        {"action": "read_news_detail", "url": "http://localhost"},
    ],
)
def test_model_cannot_choose_unregistered_tools_or_extra_parameters(action):
    with pytest.raises(ValidationError):
        ACTION_ADAPTER.validate_python(action)


@pytest.mark.parametrize(
    "url",
    [
        "http://finance.eastmoney.com/a/1.html",
        "https://localhost/",
        "https://finance.eastmoney.com.evil.test/a",
        "https://finance.eastmoney.com:8080/a",
        "https://user:password@finance.eastmoney.com/a",
    ],
)
def test_detail_url_boundary(url):
    assert not allowed_article_url(url)


def test_parser_reads_only_article_container_without_script():
    parser = ArticleTextParser()
    parser.feed(
        '<p>导航</p><div id="ContentBody"><p>正文一</p><script>脚本</script>'
        "<p>正文二<br/>续文</p></div><footer>推荐内容</footer>"
    )
    text = parser.article_text()
    assert "正文一" in text and "正文二" in text and "续文" in text
    assert all(word not in text for word in ["导航", "脚本", "推荐内容"])


async def test_unsupported_article_honestly_returns_summary_without_network():
    result = await PublicNewsDetailReader().read(document())
    assert result.availability == "summary_only"
    assert result.content == "摘要"
    assert not result.historical_snapshot_verified


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (200, '<div id="ContentBody">' + "新闻正文。" * 30 + "</div>", "full_text"),
        (200, "<html><p>登录后查看</p></html>", "summary_only"),
        (302, "", "summary_only"),
    ],
)
async def test_article_reader_classifies_real_http_shapes(monkeypatch, status, body, expected):
    import asyncio
    import socket

    import httpx
    from sector_pulse.infrastructure.news import news_detail_reader

    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    factory = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status,
            headers={"content-type": "text/html; charset=utf-8"},
            text=body,
        )
    )
    monkeypatch.setattr(
        news_detail_reader.httpx,
        "AsyncClient",
        lambda **kwargs: factory(transport=transport, **kwargs),
    )
    result = await PublicNewsDetailReader().read(
        document(citation_url="https://finance.eastmoney.com/a/example.html")
    )
    assert result.availability == expected
    assert not result.historical_snapshot_verified


async def test_tools_filter_future_news_cache_requests_and_reject_unknown_ids():
    calls = []
    context = contexts()[0]

    class Search:
        async def search(self, query, start_at, cutoff):
            calls.append((query, cutoff))
            return SimpleNamespace(
                data=(
                    document(),
                    document(document_id="future", published_at=cutoff + timedelta(days=1)),
                ),
                error=None,
            )

    tools = AttributionTools(context, Search(), PublicNewsDetailReader())
    action = SearchNews(action="search_news", query="最新事件")
    result = await tools.execute(action)
    assert [d["document_id"] for d in result.data["documents"]] == ["doc-1"]
    assert await tools.execute(action) == result
    assert len(calls) == 1 and calls[0][1] == context.cutoff_at
    assert context.sector_id in calls[0][0]
    missing = await tools.execute(ReadNewsDetail(action="read_news_detail", document_id="unknown"))
    assert missing.error_code == "UNKNOWN_DOCUMENT_ID"
    market = await tools.execute(InspectMarket(action="inspect_market"))
    assert market.data["sector_id"] == context.sector_id
    assert market.data["facts"]["pct_change"] == "3.2"
