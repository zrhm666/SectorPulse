"""规格 20.2 的指标：这套资料库在运行时的样子。

指标的名字按规格列，值是**上报的人算出来的**，这一层只负责把它们分开记。两个刻意的
选择：

**标签只接受标识符。** Provider 名、模型版本、角色、状态、规则名都是标识符；问题文本
与正文不是。允许它们进标签，等于让"日志里没有正文"这句话失效——标签会被写进时间序列
库、告警消息和工单标题里，活得比文档还长。拒绝时只报长度，不复述那一段。

**"没人报过"与"报上来就是 0"分开。** `samples()` 为空说明这条线断了，`total()` 为 0
说明跑出来的就是 0。混在一起，一条断掉的采集线与一次安静的正常运行看起来一模一样。

指标里没有、也不该有"从融合分反推 Dense/BM25 各召回了几条"这种算法。索引端口只回传
融合结果（见 `ports/vector_index.VectorHit` 的文档），反推出来的"贡献率"是猜的。真能
报告两侧候选的索引实现，用 `record_recall_contribution` 报进来。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field
from sector_pulse.domain.research_library.models import Record
from sector_pulse.domain.research_library.retrieval import (
    ConflictDecision,
    RetrievalAuditRecord,
)

if TYPE_CHECKING:  # pragma: no cover - 只为类型检查存在
    from sector_pulse.application.research_library.provider_calls import ProviderCallRecord

__all__ = [
    "MetricName",
    "MetricSample",
    "MetricsRegistry",
    "UnsafeMetricLabel",
]


class MetricName(StrEnum):
    """规格 20.2 的信号。名字就是约定，改名等于把历史数据切断。"""

    # 摄取
    INGESTION_DURATION_MS = "ingestion.duration_ms"
    INGESTION_OUTCOMES = "ingestion.outcomes"
    OCR_PAGE_RATIO = "ocr.page_ratio"
    OCR_LOW_CONFIDENCE_RATIO = "ocr.low_confidence_ratio"
    CHUNK_COUNT = "chunk.count"
    CHUNK_LENGTH_MEAN = "chunk.length_mean"
    # Provider
    PROVIDER_CALLS = "provider.calls"
    PROVIDER_LATENCY_MS = "provider.latency_ms"
    PROVIDER_ERRORS = "provider.errors"
    PROVIDER_COST_CNY = "provider.cost_cny"
    # 检索
    RETRIEVAL_COUNT = "retrieval.count"
    EMPTY_RETRIEVALS = "retrieval.empty"
    DUPLICATE_RATE = "retrieval.duplicate_rate"
    SOURCE_DIVERSITY = "retrieval.source_diversity"
    DENSE_CONTRIBUTION = "dense.candidate_contribution"
    LEXICAL_CONTRIBUTION = "bm25.candidate_contribution"
    STALE_DOCUMENT_RETURNS = "retrieval.stale_document_returns"
    # 冲突与存储
    CONFLICT_OUTCOMES = "conflict.outcomes"
    STORAGE_INCONSISTENCIES = "storage.inconsistencies"


#: 标签值必须是一个标识符。中文、空格、换行都不在其中。
_LABEL = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}\Z")

#: 角色缺省时的占位。留空会让"谁问的"变成空标签，而空标签在时间序列库里会与"没这个
#: 标签"混成一件事。
_UNATTRIBUTED = "unattributed"


class UnsafeMetricLabel(ValueError):
    """一个指标标签不是标识符。

    消息里只有长度，没有原文：异常会被日志与告警转抄，把正文放进去就前功尽弃。
    """


class MetricSample(Record):
    """一个 (名字, 标签集合) 上累计的样子。

    `value` 是累计值而不是最后一次观测：比率要除以 `observations` 才是均值（用 `mean`），
    计数就是它自己。两者都需要，因此两个都留着。
    """

    name: str = Field(min_length=1)
    labels: Mapping[str, str] = Field(default_factory=dict)
    value: float = 0.0
    observations: int = Field(default=1, ge=1)

    @property
    def mean(self) -> float:
        return self.value / self.observations


class MetricsRegistry:
    """内存里的指标表。进程内累计，导出由部署侧决定（规格 20.2 只要求这些信号存在）。"""

    def __init__(self) -> None:
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = {}

    # --- 记 ---

    def observe(self, name: MetricName, value: float, **labels: str) -> None:
        self._values.setdefault(self._key(name, labels), []).append(float(value))

    def increment(self, name: MetricName, **labels: str) -> None:
        self.observe(name, 1.0, **labels)

    # --- 读 ---

    def samples(self, name: MetricName) -> tuple[MetricSample, ...]:
        return tuple(
            self._sample(key, values)
            for key, values in sorted(self._values.items())
            if key[0] == name.value
        )

    def snapshot(self) -> tuple[MetricSample, ...]:
        return tuple(self._sample(key, values) for key, values in sorted(self._values.items()))

    def total(self, name: MetricName, **labels: str) -> float:
        return sum(
            sum(values)
            for key, values in self._values.items()
            if key[0] == name.value and self._labels_of(key).items() >= labels.items()
        )

    def mean(self, name: MetricName, **labels: str) -> float:
        everything = [
            value
            for key, values in self._values.items()
            if key[0] == name.value and self._labels_of(key).items() >= labels.items()
            for value in values
        ]
        return sum(everything) / len(everything) if everything else 0.0

    # --- 从真实事件上报（规格 20.2 的每一行都有一条上报路径） ---

    def record_retrieval(self, audit: RetrievalAuditRecord, *, stale_returns: int = 0) -> None:
        """一次检索。比率与多样性都从审计自己的名单里算，不问调用方要数字。"""
        role = audit.role or _UNATTRIBUTED
        returned = len(audit.returned_evidence)
        reranked = len(audit.reranked_candidates)
        self.increment(MetricName.RETRIEVAL_COUNT, role=role)
        if returned == 0:
            self.increment(MetricName.EMPTY_RETRIEVALS, role=role)
        self.observe(
            MetricName.DUPLICATE_RATE,
            (reranked - returned) / reranked if reranked else 0.0,
            role=role,
        )
        self.observe(
            MetricName.SOURCE_DIVERSITY,
            len({str(entry.get("document_id")) for entry in audit.returned_evidence}) / returned
            if returned
            else 0.0,
            role=role,
        )
        if audit.provider_calls is not None:
            self.observe(MetricName.PROVIDER_CALLS, audit.provider_calls, role=role)
        for _ in range(stale_returns):
            self.record_stale_document_return()

    def record_recall_contribution(self, *, dense_only: int, lexical_only: int, both: int) -> None:
        """两侧召回各自的贡献，由**能分开报告两侧**的索引实现上报。

        一个切片被两侧都召回到时算它两次：这一项要回答的是"稠密那一半有没有在工作"，
        不是"最终有几条"。
        """
        self.observe(MetricName.DENSE_CONTRIBUTION, dense_only + both)
        self.observe(MetricName.LEXICAL_CONTRIBUTION, lexical_only + both)

    def record_conflicts(self, decisions: Sequence[ConflictDecision]) -> None:
        for decision in decisions:
            self.increment(
                MetricName.CONFLICT_OUTCOMES,
                status=decision.status.value,
                rule=decision.rule.value if decision.rule is not None else "none",
            )

    def record_provider_call(self, record: ProviderCallRecord) -> None:
        labels = {"provider": record.provider, "kind": record.kind}
        self.observe(MetricName.PROVIDER_LATENCY_MS, record.latency_ms, **labels)
        self.increment(MetricName.PROVIDER_CALLS, **labels)
        if record.error_kind is not None:
            self.increment(
                MetricName.PROVIDER_ERRORS, kind=record.error_kind, provider=record.provider
            )
        if record.actual_cny is not None:
            self.observe(MetricName.PROVIDER_COST_CNY, float(record.actual_cny), **labels)

    def record_ingestion(
        self,
        *,
        stage: str,
        duration_ms: int,
        succeeded: bool,
        pages: int,
        ocr_pages: int,
        low_confidence_pages: int,
        chunk_lengths: Sequence[int],
    ) -> None:
        """一个摄取阶段。

        零页的解析报 0.0 而不是不报：它是"这一份文档一页都没读出内容"，一个真实的比例。
        `CHUNK_COUNT` 只在真的产出切片时报——计数指标的和要等于总共切出多少块，把一次
        空产出也记成一次观测会把均值拉低。
        """
        self.observe(MetricName.INGESTION_DURATION_MS, duration_ms, stage=stage)
        self.increment(
            MetricName.INGESTION_OUTCOMES,
            stage=stage,
            status="succeeded" if succeeded else "failed",
        )
        self.observe(MetricName.OCR_PAGE_RATIO, ocr_pages / pages if pages else 0.0)
        self.observe(
            MetricName.OCR_LOW_CONFIDENCE_RATIO, low_confidence_pages / pages if pages else 0.0
        )
        if chunk_lengths:
            self.observe(MetricName.CHUNK_COUNT, len(chunk_lengths))
            self.observe(MetricName.CHUNK_LENGTH_MEAN, sum(chunk_lengths) / len(chunk_lengths))

    def record_stale_document_return(self) -> None:
        """规格 20.2 的"失效文档误返回次数"。正常运行时它应该一直是 0。"""
        self.increment(MetricName.STALE_DOCUMENT_RETURNS)

    def record_storage_inconsistency(self, *, store: str, table: str, count: int) -> None:
        """PostgreSQL、MinIO、Milvus 之间的一处对不上（规格 20.2 的最后一行）。"""
        self.observe(MetricName.STORAGE_INCONSISTENCIES, count, store=store, table=table)

    # --- 内部 ---

    @staticmethod
    def _labels_of(key: tuple[str, tuple[tuple[str, str], ...]]) -> dict[str, str]:
        return dict(key[1])

    def _key(
        self, name: MetricName, labels: Mapping[str, str]
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        checked = {label: self._checked(label, value) for label, value in labels.items()}
        return name.value, tuple(sorted(checked.items()))

    @staticmethod
    def _checked(label: str, value: str) -> str:
        if not isinstance(value, str) or not _LABEL.match(value):
            raise UnsafeMetricLabel(
                f"metric label {label!r} must be a plain identifier; "
                f"got {len(value) if isinstance(value, str) else type(value).__name__}"
            )
        return value

    def _sample(
        self, key: tuple[str, tuple[tuple[str, str], ...]], values: list[float]
    ) -> MetricSample:
        return MetricSample(
            name=key[0], labels=dict(key[1]), value=sum(values), observations=len(values)
        )
