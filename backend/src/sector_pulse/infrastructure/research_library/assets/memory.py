"""内存资产适配器：离线门禁与开发环境的实现。

它必须和 MinIO 适配器一样严格，否则契约测试会在开发环境放行一个在生产会被拒绝的键。
因此这里刻意不做“内存里反正无所谓”的简化：键文法、声明核对、覆盖保护、扫描结论
全部照做，共用同一份 `integrity` 规则。
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import BinaryIO

from sector_pulse.infrastructure.research_library.assets.integrity import (
    read_bounded,
    sha256_of,
    verify_declaration,
)
from sector_pulse.infrastructure.research_library.assets.scanner import NullScanner
from sector_pulse.ports.research_assets import (
    DEFAULT_DOWNLOAD_GRANT_SECONDS,
    DEFAULT_MAX_ASSET_BYTES,
    AssetConflict,
    AssetMetadata,
    AssetNotFound,
    AssetRef,
    DownloadGrant,
    FileSafetyScanner,
    ScanVerdict,
    validate_asset_key,
)


@dataclass(frozen=True)
class _StoredAsset:
    content: bytes
    metadata: AssetMetadata
    sha256: str
    verdict: ScanVerdict

    def ref(self, key: str) -> AssetRef:
        return AssetRef(
            key=key,
            sha256=self.sha256,
            byte_size=len(self.content),
            content_type=self.metadata.content_type,
            asset_role=self.metadata.asset_role,
            scan_status=self.verdict.status,
            scan_detail=self.verdict.detail,
            metadata=self.metadata,
        )


class InMemoryResearchAssetStore:
    def __init__(
        self,
        *,
        scanner: FileSafetyScanner | None = None,
        max_asset_bytes: int = DEFAULT_MAX_ASSET_BYTES,
    ) -> None:
        self._scanner = scanner or NullScanner()
        self._max_asset_bytes = max_asset_bytes
        self._objects: dict[str, _StoredAsset] = {}

    def put(self, *, key: str, content: BinaryIO, metadata: AssetMetadata) -> AssetRef:
        validate_asset_key(key)
        payload = read_bounded(content, max_bytes=self._max_asset_bytes)
        digest = sha256_of(payload)
        verify_declaration(metadata, digest=digest, size=len(payload))

        existing = self._objects.get(key)
        if existing is not None:
            if existing.sha256 != digest:
                raise AssetConflict(
                    f"asset {key!r} already holds different content; delete it first"
                )
            return existing.ref(key)

        verdict = self._scanner.scan(key=key, content=BytesIO(payload), metadata=metadata)
        stored = _StoredAsset(content=payload, metadata=metadata, sha256=digest, verdict=verdict)
        self._objects[key] = stored
        return stored.ref(key)

    @contextmanager
    def open(self, key: str) -> Iterator[BinaryIO]:
        stored = self._objects.get(validate_asset_key(key))
        if stored is None:
            raise AssetNotFound(f"asset {key!r} does not exist")
        yield BytesIO(stored.content)

    def stat(self, key: str) -> AssetRef:
        stored = self._objects.get(validate_asset_key(key))
        if stored is None:
            raise AssetNotFound(f"asset {key!r} does not exist")
        return stored.ref(key)

    def delete(self, key: str) -> None:
        validate_asset_key(key)
        self._objects.pop(key, None)

    def create_download_grant(
        self, key: str, *, expires_in_seconds: int = DEFAULT_DOWNLOAD_GRANT_SECONDS
    ) -> DownloadGrant:
        ref = self.stat(key)
        # 内存适配器没有可预签名的服务器，但仍然给出形状正确、会过期的授权对象：调用方
        # 不该为了跑通离线测试而走一条与生产不同的代码路径。
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
        return DownloadGrant(
            key=ref.key,
            url=f"memory://assets/{ref.key}?expires={int(expires_at.timestamp())}",
            expires_in_seconds=expires_in_seconds,
            expires_at=expires_at,
        )


__all__ = ["InMemoryResearchAssetStore"]
