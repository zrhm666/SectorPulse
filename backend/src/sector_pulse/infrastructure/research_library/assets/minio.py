"""MinIO 资产适配器（默认实现）。

三条不可让步的约定：

1. 桶永远是私有的。对外下载只能走短时预签名 URL，而且只有面向用户的下载路由能拿到；
   Agent 工具既不该拿到 URL，也不该知道对象键。
2. 内容寻址。对象的散列写在用户元数据里，因此“同样的内容重复上传”可以判定为幂等，
   而“同一个键换一份内容”可以被拒绝——覆盖一份已被引用的原件必须是一次显式动作。
3. 读取流式。落盘用临时文件、上传用 `fput_object`，内存占用不随上传体积增长。

MinIO SDK 来自可选的 `rag` extra，因此在这里延迟导入：离线门禁必须能在没装 SDK 的
环境里收集并运行，而真的调用适配器时得到一句明确的错误，而不是 ImportError 回溯。
"""

import importlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO
from urllib.parse import quote, unquote

from sector_pulse.infrastructure.research_library.assets.integrity import (
    SpooledAsset,
    spool_to_disk,
    verify_declaration,
)
from sector_pulse.infrastructure.research_library.assets.scanner import NullScanner
from sector_pulse.ports.research_assets import (
    DEFAULT_DOWNLOAD_GRANT_SECONDS,
    DEFAULT_MAX_ASSET_BYTES,
    AssetConflict,
    AssetError,
    AssetMetadata,
    AssetNotFound,
    AssetRef,
    AssetRole,
    DownloadGrant,
    FileSafetyScanner,
    ScanStatus,
    ScanVerdict,
    validate_asset_key,
)

MISSING_OBJECT_CODES = frozenset({"NoSuchKey", "NoSuchObject", "NoSuchBucket", "NotFound"})

#: 用户元数据键。MinIO 会把它们以小写形式回读，且不同版本对 `x-amz-meta-` 前缀的
#: 处理不一致，因此读取时两种形式都试。
META_SHA256 = "sha256"
META_BYTE_SIZE = "byte-size"
META_ASSET_ROLE = "asset-role"
META_SCAN_STATUS = "scan-status"
META_SCAN_DETAIL = "scan-detail"
META_FILENAME = "filename"
META_DOCUMENT_ID = "document-id"
META_DOCUMENT_VERSION_ID = "document-version-id"
META_PAGE_NUMBER = "page-number"

DEFAULT_REGION = "us-east-1"


def _sdk() -> Any:
    """按需加载 SDK。

    用 `importlib` 而不是 `import`：静态导入会让 Mypy 在没装 `rag` extra 的环境里报
    `import-not-found`、在装了但缺类型信息的环境里报 `import-untyped`，而“忽略哪一个”
    取决于环境——那样本地能过、CI 未必能过。
    """
    try:
        return importlib.import_module("minio")
    except ModuleNotFoundError as error:  # pragma: no cover - optional extra
        raise AssetError(
            "the MinIO SDK is not installed; install the 'rag' extra to use this adapter"
        ) from error


class MinioResearchAssetStore:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = True,
        region: str | None = None,
        scanner: FileSafetyScanner | None = None,
        max_asset_bytes: int = DEFAULT_MAX_ASSET_BYTES,
    ) -> None:
        if not endpoint:
            raise ValueError("a MinIO endpoint is required")
        if not bucket:
            raise ValueError("a MinIO bucket is required")
        sdk = _sdk()
        self._client = sdk.Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region or DEFAULT_REGION,
        )
        self._missing_error = sdk.error.S3Error
        self._bucket = bucket
        self._secure = secure
        self._endpoint = endpoint
        self._scanner = scanner or NullScanner()
        self._max_asset_bytes = max_asset_bytes

    # --- 运维接口 ---

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def public_base_url(self) -> str:
        scheme = "https" if self._secure else "http"
        return f"{scheme}://{self._endpoint}/{self._bucket}"

    def ensure_bucket(self) -> None:
        """建立私有桶；已存在则不动它。"""
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket, object_lock=False)

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):  # pragma: no cover - depends on SDK version
            close()

    # --- 端口实现 ---

    def put(self, *, key: str, content: BinaryIO, metadata: AssetMetadata) -> AssetRef:
        validate_asset_key(key)
        with spool_to_disk(content, max_bytes=self._max_asset_bytes) as spooled:
            verify_declaration(metadata, digest=spooled.sha256, size=spooled.byte_size)

            existing = self._stat_or_none(key)
            if existing is not None:
                if _user_metadata(existing.metadata, META_SHA256) != spooled.sha256:
                    raise AssetConflict(
                        f"asset {key!r} already holds different content; delete it first"
                    )
                return self._ref_of(key, existing)

            verdict = self._scan(key=key, spooled=spooled, metadata=metadata)
            self._client.fput_object(
                self._bucket,
                key,
                str(spooled.path),
                content_type=metadata.content_type,
                metadata=_user_metadata_payload(
                    metadata=metadata,
                    spooled=spooled,
                    scan_status=verdict.status,
                    scan_detail=verdict.detail,
                ),
            )
            stored = self._stat_or_none(key)
        assert stored is not None  # 刚写进去的对象必须读得回来
        return self._ref_of(key, stored)

    @contextmanager
    def open(self, key: str) -> Iterator[BinaryIO]:
        validate_asset_key(key)
        response = self._get_object(key)
        try:
            yield response
        finally:
            response.close()
            response.release_conn()

    def stat(self, key: str) -> AssetRef:
        validate_asset_key(key)
        stored = self._stat_or_none(key)
        if stored is None:
            raise AssetNotFound(f"asset {key!r} does not exist")
        return self._ref_of(key, stored)

    def delete(self, key: str) -> None:
        """幂等删除：对象不存在也算成功。"""
        validate_asset_key(key)
        self._client.remove_object(self._bucket, key)

    def create_download_grant(
        self, key: str, *, expires_in_seconds: int = DEFAULT_DOWNLOAD_GRANT_SECONDS
    ) -> DownloadGrant:
        ref = self.stat(key)
        url = self._client.presigned_get_object(
            self._bucket, ref.key, expires=timedelta(seconds=expires_in_seconds)
        )
        return DownloadGrant(
            key=ref.key,
            url=url,
            expires_in_seconds=expires_in_seconds,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
        )

    # --- 内部 ---

    def _stat_or_none(self, key: str) -> Any:
        try:
            return self._client.stat_object(self._bucket, key)
        except self._missing_error as error:
            if getattr(error, "code", None) in MISSING_OBJECT_CODES:
                return None
            raise

    def _get_object(self, key: str) -> Any:
        try:
            return self._client.get_object(self._bucket, key)
        except self._missing_error as error:
            if getattr(error, "code", None) in MISSING_OBJECT_CODES:
                raise AssetNotFound(f"asset {key!r} does not exist") from error
            raise

    def _scan(self, *, key: str, spooled: SpooledAsset, metadata: AssetMetadata) -> ScanVerdict:
        with spooled.path.open("rb") as handle:
            return self._scanner.scan(key=key, content=handle, metadata=metadata)

    def _ref_of(self, key: str, stored: Any) -> AssetRef:
        headers = stored.metadata
        digest = _user_metadata(headers, META_SHA256)
        if not digest:
            raise AssetError(
                f"asset {key!r} carries no sha256 metadata; refusing to guess its content"
            )
        content_type = stored.content_type or "application/octet-stream"
        asset_role = AssetRole(_user_metadata(headers, META_ASSET_ROLE) or AssetRole.ORIGINAL)
        filename = _user_metadata(headers, META_FILENAME)
        declared_size = _user_metadata(headers, META_BYTE_SIZE)
        page_number = _user_metadata(headers, META_PAGE_NUMBER)
        metadata = AssetMetadata(
            content_type=content_type,
            asset_role=asset_role,
            filename=unquote(filename) if filename else None,
            document_id=_user_metadata(headers, META_DOCUMENT_ID),
            document_version_id=_user_metadata(headers, META_DOCUMENT_VERSION_ID),
            page_number=int(page_number) if page_number else None,
            sha256=digest,
            byte_size=int(declared_size) if declared_size else None,
        )
        return AssetRef(
            key=key,
            sha256=digest,
            byte_size=int(stored.size),
            content_type=content_type,
            asset_role=asset_role,
            scan_status=ScanStatus(
                _user_metadata(headers, META_SCAN_STATUS) or ScanStatus.NOT_SCANNED
            ),
            scan_detail=_user_metadata(headers, META_SCAN_DETAIL),
            metadata=metadata,
        )


def _user_metadata_payload(
    *,
    metadata: AssetMetadata,
    spooled: SpooledAsset,
    scan_status: ScanStatus,
    scan_detail: str | None,
) -> dict[str, str]:
    """对象元数据只接受 ASCII 字符串，因此文件名按 URL 编码存放。"""
    payload = {
        META_SHA256: spooled.sha256,
        META_BYTE_SIZE: str(spooled.byte_size),
        META_ASSET_ROLE: metadata.asset_role.value,
        META_SCAN_STATUS: scan_status.value,
    }
    optional = {
        META_SCAN_DETAIL: scan_detail,
        META_FILENAME: quote(metadata.filename) if metadata.filename else None,
        META_DOCUMENT_ID: metadata.document_id,
        META_DOCUMENT_VERSION_ID: metadata.document_version_id,
        META_PAGE_NUMBER: str(metadata.page_number) if metadata.page_number else None,
    }
    payload.update({name: value for name, value in optional.items() if value is not None})
    return payload


def _user_metadata(headers: Any, name: str) -> str | None:
    if not headers:
        return None
    wanted = {name.lower(), f"x-amz-meta-{name}".lower()}
    for key in headers:
        if str(key).lower() in wanted:
            return str(headers[key])
    return None


__all__ = ["MinioResearchAssetStore"]
