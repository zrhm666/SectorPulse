"""文件安全扫描器的契约实现。

配置为 `none` 时不能假装文件是干净的：`NullScanner` 明确回答 `NOT_SCANNED`，并把它
写进资产记录，让上传质量门禁自己决定要不要放行。把“没扫过”当成“干净”是这类系统里
最容易发生、也最难被发现的一次退化。
"""

from typing import BinaryIO

from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.ports.research_assets import (
    AssetMetadata,
    FileSafetyScanner,
    ScanStatus,
    ScanVerdict,
)

#: 未接入真实杀毒引擎时用于演练 `fixture` 扫描器的合成标记。它不对应任何真实恶意软件，
#: 因此可以安全地出现在测试与开发环境里。
FIXTURE_MARKERS: tuple[bytes, ...] = (b"@@MALWARE@@",)

READ_CHUNK_BYTES = 64 * 1024


class NullScanner:
    """未配置扫描器时的显式选择。"""

    def scan(self, *, key: str, content: BinaryIO, metadata: AssetMetadata) -> ScanVerdict:
        return ScanVerdict(
            status=ScanStatus.NOT_SCANNED,
            detail="no file safety scanner is configured",
        )


class ContentMarkerScanner:
    """按固定字节标记判定。

    结论只取决于内容与构造参数，因此可复现：同一份文件在任何机器上得到同一个结论。
    读取按块进行并保留跨越块边界的尾部，避免标记正好落在块缝上时漏判。
    """

    def __init__(self, markers: tuple[bytes, ...] = FIXTURE_MARKERS) -> None:
        if not markers:
            raise ValueError("a marker scanner needs at least one marker")
        self._markers = markers
        self._overlap = max(len(marker) for marker in markers) - 1

    def scan(self, *, key: str, content: BinaryIO, metadata: AssetMetadata) -> ScanVerdict:
        content.seek(0)
        carry = b""
        while chunk := content.read(READ_CHUNK_BYTES):
            window = carry + chunk
            for marker in self._markers:
                if marker in window:
                    return ScanVerdict(
                        status=ScanStatus.INFECTED,
                        detail=f"matched content marker {marker!r}",
                    )
            carry = window[-self._overlap :] if self._overlap else b""
        return ScanVerdict(status=ScanStatus.CLEAN)


def build_scanner(settings: RagSettings) -> FileSafetyScanner:
    """按配置构造扫描器；`fixture` 只用于离线与开发环境。"""
    if settings.asset_scanner == "fixture":
        return ContentMarkerScanner()
    return NullScanner()
