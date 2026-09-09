"""Read known public article pages, returning honest summary fallbacks."""

import asyncio
import hashlib
import ipaddress
import socket
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from sector_pulse.domain.news.news import NewsDocument
from sector_pulse.domain.news.news_detail import NewsDetail

ALLOWED_HOSTS = frozenset({"finance.eastmoney.com", "stock.eastmoney.com", "www.cls.cn"})
VOID_TAGS = frozenset({"br", "img", "hr", "input", "meta", "link", "source", "wbr"})


class ArticleTextParser(HTMLParser):
    """Extract only recognized article containers; never turn the whole page into evidence."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.ignored = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if not self.depth:
            if attributes.get("id") == "ContentBody" or "detail-content" in classes:
                self.depth = 1
            return
        if tag not in VOID_TAGS:
            self.depth += 1
        if tag in {"script", "style", "noscript"}:
            self.ignored += 1
        if tag in {"p", "br", "div"} and not self.ignored:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self.depth or tag in VOID_TAGS:
            return
        if tag in {"script", "style", "noscript"} and self.ignored:
            self.ignored -= 1
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth and not self.ignored:
            self.parts.append(data)

    def article_text(self) -> str:
        return "\n".join(part.strip() for part in "".join(self.parts).splitlines() if part.strip())


def allowed_article_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in ALLOWED_HOSTS
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


class PublicNewsDetailReader:
    async def read(self, document: NewsDocument) -> NewsDetail:
        def result(content: str, full: bool = False, error: str | None = None) -> NewsDetail:
            return NewsDetail(
                document_id=document.document_id,
                availability="full_text" if full else "summary_only" if content else "unavailable",
                content=content[:12000],
                fetched_at=datetime.now(UTC),
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                truncated=len(content) > 12000,
                error_code=error,
            )

        fallback = document.summary or ""
        url = document.citation_url
        if not url or not allowed_article_url(url):
            return result(fallback, error="UNSUPPORTED_ARTICLE_SOURCE")
        try:
            async with asyncio.timeout(15):
                hostname = urlsplit(url).hostname
                addresses = await asyncio.get_running_loop().getaddrinfo(
                    hostname, 443, type=socket.SOCK_STREAM
                )
                if not addresses or any(
                    not ipaddress.ip_address(address[4][0]).is_global for address in addresses
                ):
                    return result(fallback, error="NON_PUBLIC_ARTICLE_ADDRESS")
                # No redirects: the next host must never bypass the source allowlist.
                async with (
                    httpx.AsyncClient(
                        timeout=10, follow_redirects=False, trust_env=False
                    ) as client,
                    client.stream("GET", url) as response,
                ):
                    if response.status_code != 200:
                        return result(fallback, error="ARTICLE_HTTP_UNAVAILABLE")
                    if "text/html" not in response.headers.get("content-type", "").lower():
                        return result(fallback, error="ARTICLE_CONTENT_TYPE_UNSUPPORTED")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 1_000_000:
                            return result(fallback, error="ARTICLE_TOO_LARGE")
                    encoding = response.charset_encoding or "utf-8"
                    parser = ArticleTextParser()
                    parser.feed(bytes(body).decode(encoding, errors="replace"))
                    content = parser.article_text()
                    if len(content) < 80:
                        return result(fallback, error="ARTICLE_BODY_NOT_FOUND")
                    return result(content, full=True)
        except (TimeoutError, httpx.HTTPError, OSError, ValueError, LookupError):
            return result(fallback, error="ARTICLE_FETCH_FAILED")
