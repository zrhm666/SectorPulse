"""两个适配器共用的完整性检查。

放在单独模块里而不是各写一份：键文法、声明核对、上限截断是同一套规则，分头实现迟早
会分头漂移，而漂移的那一半恰好就是离线测试跑不到的那一半（MinIO）。
"""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO

from sector_pulse.ports.research_assets import (
    AssetIntegrityError,
    AssetMetadata,
)

SPOOL_CHUNK_BYTES = 64 * 1024


def sha256_of(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def verify_declaration(metadata: AssetMetadata, *, digest: str, size: int) -> None:
    """核对调用方声明的散列与长度。

    两者都可选：只给了其中一个时只核对那一个。声明与实际不符意味着上传在中途被截断、
    被替换或被打包错，此时必须失败，而不是把对不上号的散列写进权威库。
    """
    if metadata.sha256 is not None and metadata.sha256 != digest:
        raise AssetIntegrityError("the declared sha256 does not match the bytes that arrived")
    if metadata.byte_size is not None and metadata.byte_size != size:
        raise AssetIntegrityError(
            f"the declared byte_size {metadata.byte_size} does not match the "
            f"{size} bytes that arrived"
        )


def read_bounded(content: BinaryIO, *, max_bytes: int) -> bytes:
    """按块读取，超限立刻失败。"""
    chunks: list[bytes] = []
    total = 0
    while chunk := content.read(SPOOL_CHUNK_BYTES):
        total += len(chunk)
        if total > max_bytes:
            raise AssetIntegrityError(
                f"an asset must not exceed {max_bytes} bytes; the upload was truncated"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class SpooledAsset:
    path: Path
    sha256: str
    byte_size: int


class AssetSpool:
    """上传落盘器：边收边算散列，超限立刻失败。

    之所以不是只有 `spool_to_disk` 一个函数，是因为上传有两条入口。摄取侧拿到的是一个
    同步文件对象，而 HTTP 上传拿到的是**异步**请求体流——往异步处理器里塞一个"读同步
    文件对象"的函数，要么把整份上传读进内存，要么在事件循环里开线程，而两个异步流之间
    靠线程拼起来的东西拼错一次就是死锁。

    于是"分块、计长、算散列、超限失败"抽成这一份规则，谁都能往里推块：
    `spool_to_disk` 是它的同步包装，上传路由直接按块调用它。

    刻意不用 `with` 包住写入：Windows 上被打开的文件无法第二次打开，而调用方恰恰要按
    路径再读一遍（扫描、上传到对象存储）。因此 `finish` 先关闭句柄再交出路径，删除留给
    `__exit__`。
    """

    def __init__(self, *, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = max_bytes
        self._digest = sha256()
        self._total = 0
        self._handle = tempfile.NamedTemporaryFile(delete=False)  # noqa: SIM115 - 见类文档
        self._path = Path(self._handle.name)
        self._finished: SpooledAsset | None = None

    def write(self, chunk: bytes) -> None:
        """收下一块。累计超过上限时立刻失败，而不是先写满磁盘再报错。"""
        if self._finished is not None:
            raise AssetIntegrityError("this spool is already finished")
        if not chunk:
            return
        self._total += len(chunk)
        if self._total > self._max_bytes:
            raise AssetIntegrityError(
                f"an asset must not exceed {self._max_bytes} bytes; the upload was truncated"
            )
        self._digest.update(chunk)
        self._handle.write(chunk)

    def finish(self) -> SpooledAsset:
        """关闭句柄并交出路径、散列与长度。空文件返回长度为 0 的结果，由调用方决定。"""
        if self._finished is not None:
            return self._finished
        self._handle.close()
        self._finished = SpooledAsset(
            path=self._path, sha256=self._digest.hexdigest(), byte_size=self._total
        )
        return self._finished

    def discard(self) -> None:
        """删掉落盘内容。上传被拒绝时调用，别把一份被拒的文件留在临时目录里。"""
        if self._finished is None:
            self._handle.close()
        self._path.unlink(missing_ok=True)

    def __enter__(self) -> "AssetSpool":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.discard()


@contextmanager
def spool_to_disk(content: BinaryIO, *, max_bytes: int) -> Iterator[SpooledAsset]:
    """把上传流落到临时文件，同时算出散列与长度。

    不把整份文件读进内存：上传体积由调用方决定，内存占用不该由它决定。
    """
    with AssetSpool(max_bytes=max_bytes) as spool:
        while chunk := content.read(SPOOL_CHUNK_BYTES):
            spool.write(chunk)
        yield spool.finish()
