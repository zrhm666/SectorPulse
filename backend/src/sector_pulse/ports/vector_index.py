"""向量索引的端口：先构建、校验、再发布（规格 9.3、10）。

这个端口的语义只有一句话：**staged 的记录检索不到，published 的才检索得到**。规格 10
之所以这样安排，是因为 PostgreSQL 与 Milvus 之间没有分布式事务——半份文档可见是这里
唯一必须避免的结果，而"整体可见或整体不可见"由 PostgreSQL 的版本状态与检索期的批量
复核共同保证。

因此本模块里没有、也不该有任何 Milvus 词汇：内存实现与 Milvus 实现要跑同一段契约断言，
任何一方专有的概念都会立刻把那段断言撕成两半。索引也不持有权威状态——`index_state` 只
用来减少无效候选，某个文档版本是否有效仍以 PostgreSQL 为准（规格 9.4）。

`VectorRecord` 不带 `index_generation` 与 `index_state`：两者分别由 `stage` 的参数和
`publish` 这个动作决定。把它们放进记录里，就会出现"调用方写了 STAGED、参数说是
PUBLISHED"这种没有正确答案的状态，而写进 Milvus 的那个值看起来同样合理。
"""

from collections.abc import Sequence, Set
from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import AwareDatetime, Field, model_validator

from sector_pulse.domain.research_library.models import (
    ChunkType,
    DocumentType,
    ExtractionMethod,
    Record,
)


class VectorIndexError(RuntimeError):
    """向量索引的基准错误。"""


class IndexGenerationUnknown(VectorIndexError):
    """这个 generation 没有可发布的记录。

    单独成一类，是因为它最常见的成因不是"调用方写错了 generation"，而是**发布发生在
    另一个进程里**：staged 记录在写入方那里，发布方看不到它们。这时正确动作是重新
    staged 再发布，而不是把一次没有发生的发布记成成功。
    """


class IndexRecordConflict(VectorIndexError):
    """同一个 `chunk_id` 送来了不同的内容。

    块 ID 由文档版本、口径与内容共同决定，因此"同一个 ID、不同内容"只可能是两次不同的
    切片口径或两份不同的文档撞在了一起。覆盖其中一份会让已经引用它的证据指向另一段文本。
    """


class VectorRecord(Record):
    """一个进索引的切片，连同索引侧需要的全部标量字段。

    标量字段不是装饰：`document_type`、`published_at`、`requires_verification` 都会被
    检索期的过滤条件直接使用（规格 9.3）。缺了它们，过滤只能退化成"先全量召回再由上层
    筛掉"，代价是召回窗口被无关候选占满。
    """

    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    parent_chunk_id: str | None = None
    chunk_type: ChunkType = ChunkType.TEXT
    document_type: DocumentType
    institution: str | None = None
    published_at: AwareDatetime | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    source_weight: float = Field(default=0.5, ge=0, le=1)
    content_origin: ExtractionMethod
    confidence: float = Field(default=1.0, ge=0, le=1)
    requires_verification: bool = False
    #: BM25 的文本字段。规格 9.3 里它同时是可检索正文与全文索引的输入。
    content: str = Field(min_length=1)
    dense_vector: tuple[float, ...] = ()

    @model_validator(mode="after")
    def _the_record_can_be_searched(self) -> "VectorRecord":
        if not self.dense_vector:
            raise ValueError(
                "a vector record must carry a dense vector; a record without one would be "
                "reachable by keyword only, which is a retrieval decision, not a storage one"
            )
        if not self.content.strip():
            raise ValueError("a vector record must carry indexable content")
        return self

    @property
    def dimension(self) -> int:
        return len(self.dense_vector)


class SearchFilters(Record):
    """规格 11.1 允许 Agent 表达的那几个维度。

    刻意只是一组具名字段：Agent 不能传任意 filter 表达式、collection 名或 Top-K
    （规格 11.1），因此这里没有可以拼字符串的入口。

    `sector` 与 `companies` 不在这里：规格 9.3 的 schema 没有这两个标量字段，把过滤放在
    一个不存在的字段上只会静默地不过滤。它们由查询准备阶段展开进查询文本（Task 11）。
    """

    document_types: tuple[DocumentType, ...] = ()
    published_from: date | None = None
    published_to: date | None = None
    include_unverified_leads: bool = False

    @model_validator(mode="after")
    def _the_window_is_forward(self) -> "SearchFilters":
        if (
            self.published_from is not None
            and self.published_to is not None
            and self.published_to < self.published_from
        ):
            raise ValueError("published_to must not precede published_from")
        return self


class HybridQuery(Record):
    """一次混合召回：稠密与稀疏各取一段，再由 RRF 融合。

    两个 Top-K 分开配置（规格 11.3 默认各 40），是因为两种召回方式的失效方式不同：稠密
    召回在专有名词上失手，BM25 在换个说法的同义表达上失手。共用一个数字会掩盖其中一边
    的退化。

    `rrf_k` 是融合公式里的常数：`1 / (k + rank)`。它压平高名次的优势，让"两个列表都
    上榜"比"一个列表里排第一"更值钱——这正是融合要的效果。
    """

    query_text: str = Field(min_length=1)
    dense_vector: tuple[float, ...] = ()
    dense_top_k: int = Field(default=40, ge=1, le=1000)
    bm25_top_k: int = Field(default=40, ge=1, le=1000)
    fusion_top_k: int = Field(default=50, ge=1, le=1000)
    rrf_k: int = Field(default=60, gt=0)
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @model_validator(mode="after")
    def _the_query_can_be_answered(self) -> "HybridQuery":
        if not self.query_text.strip():
            raise ValueError("a hybrid query must carry query text for the lexical half")
        if not self.dense_vector:
            raise ValueError("a hybrid query must carry a dense vector for the semantic half")
        return self


class VectorHit(Record):
    """一条召回结果。

    只有索引里真实存在的字段：页码、章节路径与块内区间都不在 Milvus 的 schema 里，它们
    随 PostgreSQL 的批量复核一起回来（规格 10）。在这里补上它们，就等于在说索引是权威
    来源，而它不是。

    也没有分路得分（稠密分、BM25 分）：融合发生在索引内部（Milvus 侧的 `RRFRanker`），
    除了融合分之外的分数根本不回传。留一个恒为 `None` 的字段会诱使调用方在上面写逻辑，
    而那个逻辑只在内存实现上成立。要看某一侧为什么召回不到，用 `verify` 与检索审计
    （Task 14）回答，不是靠猜分数。
    """

    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    parent_chunk_id: str | None = None
    chunk_type: ChunkType = ChunkType.TEXT
    document_type: DocumentType
    content: str = Field(min_length=1)
    content_origin: ExtractionMethod
    requires_verification: bool = False
    fused_score: float | None = None


class IndexVerification(Record):
    """一次发布前校验的结果（规格 10 第 3、5 步）。

    期望与实到都要留下：只说"少了 3 条"的校验结果，在排查时无法回答少的是哪 3 条，而那
    正是唯一要修的东西。
    """

    generation: str = Field(min_length=1)
    expected_count: int = Field(ge=0)
    present_count: int = Field(ge=0)
    missing_ids: tuple[str, ...] = ()
    unexpected_ids: tuple[str, ...] = ()
    dimension: int | None = Field(default=None, gt=0)
    published: bool = False

    @property
    def is_complete(self) -> bool:
        """可以发布了吗。

        数量对得上还不够：`missing_ids` 与 `unexpected_ids` 一起为空才说明这一批正好是
        期望的那一批。两者同时非空时数量也可能相等——换个 ID 记成"完整"会让一份文档带着
        另一份的块被发布出去。
        """
        return (
            not self.missing_ids
            and not self.unexpected_ids
            and self.present_count == self.expected_count
        )


@runtime_checkable
class VectorIndex(Protocol):
    """可重建的派生索引（规格 9.4）。"""

    def stage(self, *, generation: str, records: Sequence[VectorRecord]) -> None: ...

    def verify(self, *, generation: str, expected_ids: Set[str]) -> IndexVerification: ...

    def publish(self, *, generation: str) -> None: ...

    def hybrid_search(self, query: HybridQuery) -> tuple[VectorHit, ...]: ...

    def delete_generation(self, *, generation: str) -> None: ...

    def delete_records(self, *, generation: str, chunk_ids: Sequence[str]) -> int:
        """从这一代里删掉指定的记录，返回实际删掉的条数。

        这是**维护动作**，不是摄取动作。写入是 upsert，没有删除语义（见 `stage`），因此
        一代里多出来的记录只能靠这一条清出去——而"多出来的记录"意味着有东西写错了，那是
        要有人看过才动手的事（规格 16.4 的"删除失效、替代或孤立向量"）。摄取路径永远不该
        调用它：把复核不过的索引自动清理干净，等于让"索引里出现了不该有的东西"这件事不再
        被任何人看见。

        返回条数而不是 `None`，是因为调用方要把它写进报告：删了 0 条和删了 37 条是两件
        不同的事，而"我以为它清了"正是这里最容易发生的错误。
        """
        ...
