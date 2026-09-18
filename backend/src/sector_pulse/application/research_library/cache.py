"""规格 17 的缓存键，以及"语料是哪一代"这件事（规格 17、20.2）。

缓存键有七项，其中五项是**观察到的**版本（语料世代、嵌入模型、重排模型、NLI 模型、
冲突策略）。这不是为了把键凑长：少一项，两代模型的结果就会落进同一条缓存，而它看上去
与一条正确的缓存没有区别。

语料世代（`CorpusGeneration`）是这里唯一需要读权威库的一项，也是唯一一个"忘掉就等于
悄悄喂出过期答案"的地方。它的做法是**对语料现状求指纹**，而不是维护一个递增计数器：
计数器会被忘掉加，而忘记加的那一次，缓存会把一批已经被删除或改过权重的文档继续交给
Agent。指纹覆盖文档的软删除状态、来源权重，以及每个版本的编号、状态、索引世代、嵌入
模型与切片口径——发布、删除、恢复、改权重各改变其中一项。

它不是索引世代（`gen_…`，见 `ingestion.generation_for`）。索引是派生的（规格 9.4），
重建索引不改变语料；把两者混为一谈，每次重建都会把整个缓存作废，而真正改过的语料反倒
可能因为 `gen_` 没变而命中。

扫描是**有界**的：`list_documents` 只有一页、没有偏移量，因此取回满页时这里拒绝计算，
而不是按半份语料算出一个看起来完整的世代。那半份语料里的文档会永远命中不到，而错误是
安静的那种。

策略版本同理：它不是配置里的一个字段，而是**由策略本身算出来**的。手写的版本号会与
策略脱节，而脱节的那一天，同一个键会指向两套裁决规则。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Generic, Protocol, TypeVar

from pydantic import Field
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.research_library.models import (
    Record,
    ResearchDocument,
    ResearchDocumentVersion,
)
from sector_pulse.storage.ports.research_library import ResearchLibraryRepositoryPort

__all__ = [
    "CACHE_KEY_COMPONENTS",
    "NO_NLI_MODEL",
    "CacheKey",
    "CorpusGeneration",
    "InMemoryRetrievalCache",
    "IncompleteCorpusScan",
    "MissingKeyComponent",
    "RetrievalCache",
    "cache_key",
    "conflict_policy_version",
]

#: 规格 17 列出的七项，顺序即文档里的顺序。`CacheKey` 的字段与它逐个对上，
#: 由 `tests/integration/test_research_retrieval_audit.py` 盯着。
CACHE_KEY_COMPONENTS: tuple[str, ...] = (
    "query_fingerprint",
    "corpus_generation",
    "filters",
    "embedding_model_version",
    "reranker_model_version",
    "nli_model_version",
    "conflict_policy_version",
)

#: 一次只做检索、没有走冲突判断的结果用它标明"这条缓存不依赖任何 NLI 模型"。
#: 留空等于少一项，填一个配置值等于声称它参与过——两种都比明说更糟。
NO_NLI_MODEL = "not-used"

#: 语料指纹覆盖的版本字段。改动其中任何一个，语料的**可检索结果**就可能不同。
_VERSION_FIELDS = (
    "document_version_id",
    "version_number",
    "status",
    "index_generation",
    "embedding_model_version",
    "chunking_policy_version",
    "parser_version",
    "ocr_model_version",
    "expected_chunk_count",
)

#: 冲突策略版本覆盖的配置项：冲突层读的那一个阈值，加上决定"有哪些事实可比"的那一个。
#: 少算一项会让改了阈值之后的裁决复用旧结果；多算一项只是多失效几次。
_POLICY_FIELDS = ("min_nli_confidence", "min_claim_confidence")


class IncompleteCorpusScan(RuntimeError):
    """取回的一页是满的，因此无法断定还有没有下一页。

    拒绝而不是猜：按半份语料算出的世代会让没读到的那一半永远命中不到，而它看上去和
    一个正确的世代没有区别。
    """


class MissingKeyComponent(ValueError):
    """键里少了一项。

    缺的那一项会静默地把两批结果混进同一格缓存——比如一次没有 NLI 的检索与一次有 NLI
    的检索，它们的答案本来不该互相复用。
    """


class CacheKey(Record):
    """规格 17 的一次检索缓存键。"""

    query_fingerprint: str = Field(min_length=1)
    corpus_generation: str = Field(min_length=1)
    filters: Mapping[str, object] = Field(default_factory=dict)
    embedding_model_version: str = Field(min_length=1)
    reranker_model_version: str = Field(min_length=1)
    nli_model_version: str = Field(min_length=1)
    conflict_policy_version: str = Field(min_length=1)

    @property
    def digest(self) -> str:
        """七项的规范 JSON 摘要。存储用摘要，排查用 `components`。"""
        payload = json.dumps(
            {name: getattr(self, name) for name in CACHE_KEY_COMPONENTS},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        return f"rk_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"

    def components(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in CACHE_KEY_COMPONENTS}


def conflict_policy_version(settings: RagSettings) -> str:
    """由冲突策略本身算出的版本号。"""
    payload = "|".join(f"{name}={getattr(settings, name)}" for name in _POLICY_FIELDS)
    return f"cp_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def cache_key(
    *,
    query_fingerprint: str,
    corpus_generation: str,
    filters: Mapping[str, object],
    provider_versions: Mapping[str, str],
    settings: RagSettings,
) -> CacheKey:
    """从一次检索**观察到**的东西拼出键。

    三个模型版本从 `provider_versions` 里取。取的是结果自报的版本，不是配置里写的那个：
    审计记的是实际服务的那一代（见 `openai_compatible._model_version`），键要与审计对上，
    否则"缓存里的答案来自哪个模型"事后答不出来。
    """
    versions = {
        name: provider_versions.get(name)
        for name in ("embedding_model_version", "reranker_model_version", "nli_model_version")
    }
    missing = [name for name, value in versions.items() if not value]
    if missing:
        raise MissingKeyComponent(
            f"the cache key is missing {', '.join(missing)}; a key that drops a component "
            "silently mixes the results of two different models"
        )
    return CacheKey(
        query_fingerprint=query_fingerprint,
        corpus_generation=corpus_generation,
        filters=dict(filters),
        embedding_model_version=versions["embedding_model_version"] or "",
        reranker_model_version=versions["reranker_model_version"] or "",
        nli_model_version=versions["nli_model_version"] or "",
        conflict_policy_version=conflict_policy_version(settings),
    )


class CorpusGeneration:
    """规格 17 的 `corpus_generation`：语料只要有一个字节不同，世代就必须不同。"""

    def __init__(self, repository: ResearchLibraryRepositoryPort, *, scan_limit: int = 100) -> None:
        if scan_limit < 1:
            raise ValueError("a corpus scan needs a positive page size")
        self.repository = repository
        #: 与 `list_documents` 的那一页对齐。小于它就会把多出来的文档漏掉，
        #: 因此调用方（部署配置）给的值必须大于语料里文档数的上界。
        self.scan_limit = scan_limit

    def __call__(self) -> str:
        documents = self.repository.list_documents(include_deleted=True, limit=self.scan_limit)
        if len(documents) == self.scan_limit:
            raise IncompleteCorpusScan(
                f"the repository returned a full page of {self.scan_limit} documents; "
                "a generation computed from a partial corpus is silently wrong"
            )
        entries = [self._document_entry(document) for document in documents]
        entries.sort(key=lambda entry: str(entry["document_id"]))
        payload = json.dumps(entries, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return f"corpus_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"

    def _document_entry(self, document: ResearchDocument) -> dict[str, object]:
        """一份文档的现状。

        `deleted_at` 只取"有没有"而不取时刻：软删除的时间戳改变的是它自己，而删掉又恢复
        的文档与从未被删过的文档，在检索这件事上是同一份语料——世代回到原来那一个，缓存
        里那条旧结果现在又是对的。
        """
        versions = self.repository.list_versions(document.document_id)
        return {
            "document_id": document.document_id,
            "deleted": document.deleted_at is not None,
            "source_weight": str(document.source_weight),
            "current_version_id": document.current_version_id,
            "versions": [
                {field: self._version_value(version, field) for field in _VERSION_FIELDS}
                for version in versions
            ],
        }

    @staticmethod
    def _version_value(version: ResearchDocumentVersion, field: str) -> object:
        value = getattr(version, field)
        return value.value if hasattr(value, "value") else value


T = TypeVar("T")


class RetrievalCache(Protocol[T]):
    """一次检索结果的缓存。

    没有 `invalidate`：失效由键里的 `corpus_generation` 决定，因此不存在"忘了调某个失效
    方法"这种失败方式。键变了就查不到，这是缓存最不容易被写错的一种形状。
    """

    def get(self, key: CacheKey) -> T | None: ...

    def put(self, key: CacheKey, value: T) -> None: ...


class InMemoryRetrievalCache(Generic[T]):
    """进程内缓存，按键的摘要存。

    刻意不设 TTL、不设容量、不做淘汰：这里要证明的是"键变了就查不到"，而过期与淘汰是
    部署参数（规格 17 只要求失效，没有要求保留多久）。把它们做进这一层，测试与生产就会
    跑在两套不同的语义上。
    """

    def __init__(self) -> None:
        self._entries: dict[str, T] = {}

    def get(self, key: CacheKey) -> T | None:
        return self._entries.get(key.digest)

    def put(self, key: CacheKey, value: T) -> None:
        self._entries[key.digest] = value

    def __len__(self) -> int:
        return len(self._entries)
