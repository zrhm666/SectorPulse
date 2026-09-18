"""可插拔原始资料存储的端口。

规格 4：MinIO 只是默认适配器，不是依赖。因此这里描述的是“任何适配器都必须做到的事”，
而不是 MinIO 的做法：

- 对象键是服务端的命名空间，调用方只能按既定文法构造键，不能提供路径；
- 调用方声明的散列与长度是**待核对的声明**，不是待落库的取值；
- 没跑过扫描的文件必须如实记为 `NOT_SCANNED`，不能四舍五入成“干净”；
- 同一对象键下的内容不可被悄悄替换（幂等重放除外）。

把键的文法检查放在端口模块里，是因为它是契约本身而不是某个适配器的实现细节：两个
适配器必须拒绝完全相同的键，否则“可插拔”只是名义上的。
"""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from enum import StrEnum
from typing import BinaryIO, Protocol, Self, runtime_checkable

from pydantic import AwareDatetime, Field, model_validator

from sector_pulse.domain.research_library.models import Record

#: 对象键的规范形态：`<角色>/<文档>/<版本>/<文件名>`。至少两段，让“角色”总是显式存在。
ASSET_KEY_MAX_LENGTH = 255
ASSET_KEY_SEGMENTS_MIN = 2
ASSET_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: 预签名下载链接的最长有效期。链接会绕过鉴权，只能短时存在。
MAX_DOWNLOAD_GRANT_SECONDS = 300
DEFAULT_DOWNLOAD_GRANT_SECONDS = 120

#: 单个资产的默认上限。无上限的落盘等于给上传接口一个可选的磁盘耗尽。
DEFAULT_MAX_ASSET_BYTES = 256 * 1024 * 1024

SHA256_LENGTH = 64


class AssetRole(StrEnum):
    """资产在文档中的角色；取值与 `research_document_assets.asset_role` 一致。"""

    ORIGINAL = "original"
    PAGE_IMAGE = "page_image"
    EXTRACTED_TABLE = "extracted_table"
    CHART_IMAGE = "chart_image"


class ScanStatus(StrEnum):
    """取值与 `research_document_assets.scan_status` 一致。"""

    NOT_SCANNED = "NOT_SCANNED"
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"
    FAILED = "FAILED"


class AssetError(RuntimeError):
    """资料存储层的基准错误。"""


class AssetNotFound(AssetError):
    """对象不存在。"""


class AssetConflict(AssetError):
    """同一对象键下已经存在不同的内容；替换需要显式的删除动作。"""


class UnsafeAssetKey(AssetError, ValueError):
    """对象键越出了服务端允许的键空间。"""


class AssetIntegrityError(AssetError, ValueError):
    """调用方声明的长度或散列与实际内容不符。"""


def validate_asset_key(key: str) -> str:
    """校验对象键并原样返回。

    拒绝绝对路径、盘符、反斜杠、空段、`.`/`..` 段与控制字符：这些是键空间逃逸的
    全部常见形式，任何一条通过都意味着适配器在按调用方给的路径写文件。
    """
    if not key:
        raise UnsafeAssetKey("an asset key must not be empty")
    if len(key) > ASSET_KEY_MAX_LENGTH:
        raise UnsafeAssetKey(f"an asset key must not exceed {ASSET_KEY_MAX_LENGTH} characters")
    if not key.isascii() or any(character < " " or character == "\x7f" for character in key):
        raise UnsafeAssetKey("an asset key must be printable ASCII")
    if key != key.strip():
        raise UnsafeAssetKey("an asset key must not carry surrounding whitespace")
    if "\\" in key:
        raise UnsafeAssetKey("an asset key must not contain a backslash")
    if ":" in key:
        raise UnsafeAssetKey("an asset key must not contain a colon or drive letter")
    segments = key.split("/")
    if len(segments) < ASSET_KEY_SEGMENTS_MIN:
        raise UnsafeAssetKey(
            f"an asset key must have at least {ASSET_KEY_SEGMENTS_MIN} segments"
        )
    for segment in segments:
        if not ASSET_KEY_SEGMENT.match(segment):
            raise UnsafeAssetKey(f"unsafe asset key segment: {segment!r}")
    return key


class AssetMetadata(Record):
    """调用方提供的资产描述。

    `sha256` 与 `byte_size` 是可选的：给了就必须与实到的内容一致。上传接口读到多少
    写多少，因此这两个字段是唯一能在落库前发现截断或串包的证据。
    """

    content_type: str = Field(min_length=1)
    asset_role: AssetRole
    filename: str | None = None
    document_id: str | None = None
    document_version_id: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    sha256: str | None = None
    byte_size: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _declared_hash_is_well_formed(self) -> Self:
        if self.sha256 is None:
            return self
        if len(self.sha256) != SHA256_LENGTH or not self.sha256.islower():
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        int(self.sha256, 16)
        return self

    @model_validator(mode="after")
    def _identifiers_stay_header_safe(self) -> Self:
        """这些取值会成为对象存储的元数据头，因此必须保持 ASCII 可编码。"""
        for name in ("content_type", "document_id", "document_version_id"):
            value = getattr(self, name)
            if value is not None and not value.isascii():
                raise ValueError(f"{name} must be ASCII so it can travel as object metadata")
        return self


class ScanVerdict(Record):
    """一次文件安全扫描的结论。`NOT_SCANNED` 是结论，不是缺省。"""

    status: ScanStatus
    detail: str | None = None

    @model_validator(mode="after")
    def _a_bad_verdict_says_why(self) -> Self:
        if self.status in {ScanStatus.INFECTED, ScanStatus.FAILED} and not self.detail:
            raise ValueError(f"a {self.status} verdict must record what was found")
        return self


class AssetRef(Record):
    """已存储资产的可核对描述；`put` 与 `stat` 返回同一形状。"""

    key: str = Field(min_length=1)
    sha256: str = Field(min_length=SHA256_LENGTH, max_length=SHA256_LENGTH)
    byte_size: int = Field(ge=0)
    content_type: str = Field(min_length=1)
    asset_role: AssetRole
    scan_status: ScanStatus = ScanStatus.NOT_SCANNED
    scan_detail: str | None = None
    metadata: AssetMetadata


class ResearchDocumentAsset(Record):
    """`research_document_assets` 的一行：一份已经落到对象存储里的资产。

    与 `AssetRef` 的关系值得写清楚，因为两者看起来很像：`AssetRef` 是**存储层对一次
    `put`/`stat` 的回答**（键、散列、长度、扫描结论），它随适配器而变；这一行是**权威库里
    的记录**，是"这份文档的原件是什么"这个问题的答案，因此带着它属于谁、扮演什么角色、
    什么时候被登记的。上传命令把前者翻译成后者，别处都不该自己拼这一行。
    """

    asset_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version_id: str | None = None
    asset_role: AssetRole
    object_key: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    byte_size: int = Field(ge=0)
    sha256: str = Field(min_length=SHA256_LENGTH, max_length=SHA256_LENGTH)
    page_number: int | None = Field(default=None, ge=1)
    scan_status: ScanStatus = ScanStatus.NOT_SCANNED
    scan_detail: str | None = None
    created_at: AwareDatetime
    deleted_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _a_bad_verdict_says_why(self) -> Self:
        if self.scan_status in {ScanStatus.INFECTED, ScanStatus.FAILED} and not self.scan_detail:
            raise ValueError(f"a {self.scan_status} asset must record what was found")
        return self


class DownloadGrant(Record):
    """短时下载授权。只发给面向用户的下载路由，绝不进入 Agent 工具。"""

    key: str = Field(min_length=1)
    url: str = Field(min_length=1)
    expires_in_seconds: int = Field(gt=0, le=MAX_DOWNLOAD_GRANT_SECONDS)
    expires_at: AwareDatetime


@runtime_checkable
class FileSafetyScanner(Protocol):
    def scan(self, *, key: str, content: BinaryIO, metadata: AssetMetadata) -> ScanVerdict: ...


@runtime_checkable
class ResearchAssetStore(Protocol):
    def put(self, *, key: str, content: BinaryIO, metadata: AssetMetadata) -> AssetRef: ...

    def open(self, key: str) -> AbstractContextManager[BinaryIO]: ...

    def stat(self, key: str) -> AssetRef: ...

    def delete(self, key: str) -> None: ...

    def create_download_grant(
        self, key: str, *, expires_in_seconds: int = DEFAULT_DOWNLOAD_GRANT_SECONDS
    ) -> DownloadGrant: ...
