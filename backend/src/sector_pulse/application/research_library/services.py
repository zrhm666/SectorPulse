"""一次运行里接上的内部资料库：权威库、对象存储、派生索引，以及围着它们的三件服务。

这个对象存在的理由是**边界**，不是省参数。规格 15.2 只允许 A2 碰到资料库的三件东西
（检索、回库、上限），而治理动作——上传、删除、恢复、归档、改来源权重、清理——是用户
与 API 层的事。把两者装进同一个对象、再靠"记得别调用那几个方法"来维持边界，正是那种
在第一次赶工时就失效的约束。因此：

- `ResearchLibraryServices` 是**接线层**拿到的东西，带 `commands` / `maintenance`；
- `agent_services()` 交出去的是窄接口，只有检索、只读仓库与上限。

`RuntimeStorageBundle` 与 `web/dependencies.py` 只碰前者，Agent 组合只碰后者。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sector_pulse.application.research_library.indexing import IndexOutboxWorker
from sector_pulse.application.research_library.ingestion import ResearchIngestionCoordinator
from sector_pulse.application.research_library.observability import MetricsRegistry
from sector_pulse.application.research_library.parsing import ResearchParsePipeline
from sector_pulse.application.research_library.retrieval import ResearchRetrievalService
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.ports.research_assets import (
    DEFAULT_MAX_ASSET_BYTES,
    ResearchAssetStore,
)
from sector_pulse.ports.research_models import EmbeddingProvider
from sector_pulse.ports.vector_index import VectorIndex
from sector_pulse.storage.ports.research_library import ResearchLibraryRepositoryPort

if TYPE_CHECKING:  # pragma: no cover - 只为类型
    from sector_pulse.application.research_library.commands import (
        ResearchLibraryCommands,
        ResearchLibraryQueries,
    )
    from sector_pulse.application.research_library.maintenance import (
        ResearchLibraryMaintenance,
    )
    from sector_pulse.infrastructure.agents.composition import A2ResearchLibraryServices


@dataclass(frozen=True)
class ResearchLibraryServices:
    """资料库的装配结果。

    `max_upload_bytes` 的缺省与对象存储端口的上限**同一个数**：上传门禁与存储适配器
    各自持有一个上限时，两者不一致的那一天会表现为"门禁放行的文件在存储层被截断"。
    """

    repository: ResearchLibraryRepositoryPort
    assets: ResearchAssetStore
    vector_index: VectorIndex
    settings: RagSettings
    parse_pipeline: ResearchParsePipeline
    ingestion: ResearchIngestionCoordinator
    outbox: IndexOutboxWorker
    embedding: EmbeddingProvider
    retrieval: ResearchRetrievalService
    corpus_generation: Callable[[], str]
    clock: Callable[[], datetime]
    metrics: MetricsRegistry
    max_upload_bytes: int = DEFAULT_MAX_ASSET_BYTES

    def __post_init__(self) -> None:
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")

    @property
    def commands(self) -> ResearchLibraryCommands:
        from sector_pulse.application.research_library.commands import ResearchLibraryCommands

        return ResearchLibraryCommands(self)

    @property
    def queries(self) -> ResearchLibraryQueries:
        from sector_pulse.application.research_library.commands import ResearchLibraryQueries

        return ResearchLibraryQueries(self)

    @property
    def maintenance(self) -> ResearchLibraryMaintenance:
        from sector_pulse.application.research_library.maintenance import (
            ResearchLibraryMaintenance,
        )

        return ResearchLibraryMaintenance(self)

    def agent_services(self) -> A2ResearchLibraryServices:
        """交给 A2 的窄接口（规格 15.2）。

        延迟导入 `infrastructure.agents`：搬库时 Agent 组合一定会导入应用层，而应用层
        在模块顶层反过来导入它，就会把这条依赖变成一个循环。
        """
        from sector_pulse.infrastructure.agents.composition import A2ResearchLibraryServices

        return A2ResearchLibraryServices(
            retrieval=self.retrieval,
            repository=self.repository,
            settings=self.settings,
        )


__all__ = ["ResearchLibraryServices"]
