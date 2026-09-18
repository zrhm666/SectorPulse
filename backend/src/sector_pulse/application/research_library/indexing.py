"""派生索引的兑现者，以及用权威状态复核召回结果的最后一道闸门。

规格 10 的分工在这两个东西上体现得最直接：

- `IndexOutboxWorker` 兑现落库的意图。它只做 Milvus 那边的事，且不判断"该不该发布"——
  那个判断在意图被写下的那一刻就已经做完了。这样安排的原因只有一个：进程可能死在
  "写完了状态"和"改完了索引"之间的任何地方，而待办留在库里，重启后还能被捡起来。
- `filter_active_hits` 在每次检索的最后一步用 PostgreSQL 复核。Milvus 里的
  `index_state` 只是让候选少一点，它**不是**可见性本身：一个被取代的版本、一次失败的
  发布，在 Milvus 里看起来和一次成功的发布没有区别。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sector_pulse.domain.research_library.models import (
    DocumentVersionStatus,
    IndexOutboxEvent,
    OutboxOperation,
)
from sector_pulse.ports.vector_index import VectorHit, VectorIndex, VectorIndexError
from sector_pulse.storage.ports.research_library import ResearchLibraryRepositoryPort


class IndexOutboxWorker:
    """把 `research_index_outbox` 里的意图兑现成向量索引上的动作。"""

    def __init__(
        self, *, repository: ResearchLibraryRepositoryPort, vector_index: VectorIndex
    ) -> None:
        self._repository = repository
        self._vector_index = vector_index

    def run_once(
        self, *, worker_id: str, now: datetime, limit: int = 10
    ) -> tuple[IndexOutboxEvent, ...]:
        """认领并兑现一批事件，返回它们结束后的样子。

        认领是原子的（`FOR UPDATE SKIP LOCKED`），因此两个 worker 同时跑不会重复兑现。
        每一个事件的结果都单独写回：一个失败的事件不该让同一批里其它事件也停在半路。
        """
        claimed = self._repository.claim_outbox_events(worker_id=worker_id, now=now, limit=limit)
        return tuple(self._perform(event, worker_id=worker_id, now=now) for event in claimed)

    def _perform(
        self, event: IndexOutboxEvent, *, worker_id: str, now: datetime
    ) -> IndexOutboxEvent:
        """兑现一个事件，并把失败记在它自己身上。

        只接 `VectorIndexError`：那是索引端口声明的失败方式（连不上、这一代不认识）。
        其它异常一律往上抛——那是本进程里的缺陷，把它写成 `last_error` 只会让一个 bug
        看起来像一次网络抖动。
        """
        try:
            if event.operation is OutboxOperation.PUBLISH_GENERATION:
                self._vector_index.publish(generation=event.index_generation)
            else:
                self._vector_index.delete_generation(generation=event.index_generation)
        except VectorIndexError as error:
            return self._repository.finish_outbox_event(
                event.event_id, worker_id=worker_id, now=now, error=str(error)
            )
        return self._repository.finish_outbox_event(event.event_id, worker_id=worker_id, now=now)


def filter_active_hits(
    hits: Sequence[VectorHit], *, repository: ResearchLibraryRepositoryPort
) -> tuple[VectorHit, ...]:
    """丢掉所有不属于当前 ACTIVE 版本的召回结果。

    **查不到状态的同样丢掉。** 一个 Milvus 里还留着的、权威库里已经查不到的版本，说明它
    正在被清理；把"查不到"当成"没问题"会让最该被丢弃的那一条穿过去。

    状态一次批量取回：这一步在每次检索的末尾都要跑，逐条查询会把它变成瓶颈。
    """
    if not hits:
        return ()
    statuses = repository.load_version_statuses([hit.document_version_id for hit in hits])
    return tuple(
        hit for hit in hits if statuses.get(hit.document_version_id) is DocumentVersionStatus.ACTIVE
    )
