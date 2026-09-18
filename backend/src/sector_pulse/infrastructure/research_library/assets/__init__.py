"""原始资料存储的适配器与它们共用的完整性规则。

`integrity` 不是可选的实现细节而是共用的：键文法、声明核对、上限截断必须由两个
适配器走同一份代码，否则它们在离线测试里会悄悄分叉。
"""

from sector_pulse.infrastructure.research_library.assets.integrity import (
    SpooledAsset,
    read_bounded,
    sha256_of,
    spool_to_disk,
    verify_declaration,
)
from sector_pulse.infrastructure.research_library.assets.memory import (
    InMemoryResearchAssetStore,
)
from sector_pulse.infrastructure.research_library.assets.minio import (
    MinioResearchAssetStore,
)
from sector_pulse.infrastructure.research_library.assets.scanner import (
    ContentMarkerScanner,
    NullScanner,
    build_scanner,
)

__all__ = [
    "ContentMarkerScanner",
    "InMemoryResearchAssetStore",
    "MinioResearchAssetStore",
    "NullScanner",
    "SpooledAsset",
    "build_scanner",
    "read_bounded",
    "sha256_of",
    "spool_to_disk",
    "verify_declaration",
]
