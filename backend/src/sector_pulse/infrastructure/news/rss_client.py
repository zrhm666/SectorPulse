import ipaddress
from urllib.parse import urlsplit

import requests


class UnsafeNewsUrlError(ValueError):
    """新闻 URL 不满足协议或公网地址约束。"""


def validate_public_url(url: str) -> None:
    """拒绝非 HTTP(S)、本机、内网和保留 IP，避免新闻抓取成为 SSRF 入口。"""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeNewsUrlError("news URL must use http or https")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise UnsafeNewsUrlError("local hostnames are not allowed")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise UnsafeNewsUrlError("private or reserved addresses are not allowed")


def validate_response_size(content: bytes, max_bytes: int) -> None:
    if len(content) > max_bytes:
        raise ValueError("news response exceeds configured size limit")


class RssHttpClient:
    """同步 HTTP 客户端；由 Adapter 在线程中调用，默认不跟随重定向。"""

    def __init__(self, timeout_seconds: float = 10.0, max_bytes: int = 2_000_000) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    def fetch(self, url: str) -> bytes:
        validate_public_url(url)
        response = requests.get(
            url,
            timeout=self._timeout_seconds,
            allow_redirects=False,
            headers={"User-Agent": "SectorPulse/0.1 (+local research)"},
        )
        if 300 <= response.status_code < 400:
            raise UnsafeNewsUrlError("news redirects require explicit provider review")
        response.raise_for_status()
        validate_response_size(response.content, self._max_bytes)
        return response.content
