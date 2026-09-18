"""Milvus 向量索引适配器。

规格 9.3 的一张全局 collection，规格 10 的"先构建、校验、再发布"。四处实现层面的取舍，
每一处都是被 Milvus 的实际能力逼出来的，写在这里以免下次有人重新推一遍：

1. **主键是派生的 `chunk_id + ":" + index_generation`。** Milvus 的主键只能是单个字段，
   而规格 19 要求写入以 `chunk_id + index_generation` 幂等、规格 16.2 要求重建期间新旧
   generation 并存。拿 `chunk_id` 当主键，重建会就地覆盖正在服务的那一份。
2. **`published_at` 与生效区间存 epoch 秒（`INT64`）。** Milvus 没有日期类型，过滤只有
   数值比较。转换只发生在这一个文件里；端口和其它地方一律用 `date` / `datetime`。
3. **发布用部分更新（`partial_update=True`）改 `index_state`。** Milvus 2.x 没有
   `UPDATE ... WHERE`，而 `content` 的稀疏向量由 BM25 Function 在写入时生成、不能由调用
   方提供——所以"读回来再整条 upsert"这条路会把 Function 的输出字段一起写坏。因此这里只
   动标量字段。
4. **不使用 Milvus Lite。** 官方文档说明 BM25 全文检索需要服务端部署；Lite 上能建出
   collection、检索却不走全文索引，那会让验收在一个不成立的假设上通过。

pymilvus 来自可选的 `rag` extra，因此在这里延迟导入（理由与 `assets/minio.py` 相同）。
"""

import importlib
from collections.abc import Sequence, Set
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sector_pulse.domain.research_library.models import (
    ChunkType,
    DocumentType,
    ExtractionMethod,
    IndexState,
)
from sector_pulse.ports.vector_index import (
    HybridQuery,
    IndexGenerationUnknown,
    IndexRecordConflict,
    IndexVerification,
    SearchFilters,
    VectorHit,
    VectorIndexError,
    VectorRecord,
)

PRIMARY_KEY_FIELD = "pk"
CHUNK_ID_FIELD = "chunk_id"
GENERATION_FIELD = "index_generation"
STATE_FIELD = "index_state"
DOCUMENT_ID_FIELD = "document_id"
DOCUMENT_VERSION_FIELD = "document_version_id"
PARENT_CHUNK_FIELD = "parent_chunk_id"
CHUNK_TYPE_FIELD = "chunk_type"
DOCUMENT_TYPE_FIELD = "document_type"
INSTITUTION_FIELD = "institution"
PUBLISHED_AT_FIELD = "published_at"
EFFECTIVE_FROM_FIELD = "effective_from"
EFFECTIVE_TO_FIELD = "effective_to"
SOURCE_WEIGHT_FIELD = "source_weight"
CONTENT_ORIGIN_FIELD = "content_origin"
CONFIDENCE_FIELD = "confidence"
VERIFICATION_FIELD = "requires_verification"
CONTENT_FIELD = "content"
SPARSE_FIELD = "sparse_vector"
DENSE_FIELD = "dense_vector"

#: Milvus 的 VARCHAR 上限是 65535；正文按字符数计，超过这个长度的切片在切片阶段就该被
#: 拆开，因此这里取上限而不是留一个会静默截断的余量。
MAX_CONTENT_LENGTH = 65535
MAX_ID_LENGTH = 512
MAX_NAME_LENGTH = 256
MAX_LABEL_LENGTH = 64
QUERY_LIMIT = 16384

#: 一次删除表达式里最多列几个主键。Milvus 对表达式长度有上限，而"孤立向量"可能很多，
#: 因此分批而不是把几千个键拼进一条表达式里。
DELETE_BATCH = 200


def _sdk() -> Any:
    """按需加载 SDK（理由见 `assets/minio.py` 的同名函数）。"""
    try:
        return importlib.import_module("pymilvus")
    except ModuleNotFoundError as error:  # pragma: no cover - optional extra
        raise VectorIndexError(
            "the pymilvus SDK is not installed; install the 'rag' extra to use this adapter"
        ) from error


def primary_key(chunk_id: str, generation: str) -> str:
    """Milvus 主键：`chunk_id + ":" + index_generation`（规格 19）。"""
    return f"{chunk_id}:{generation}"


def _seconds(value: datetime | None) -> int | None:
    return None if value is None else int(value.timestamp())


def _day_start(value: date) -> int:
    return int(datetime.combine(value, time.min, tzinfo=UTC).timestamp())


def _day_end(value: date) -> int:
    """窗口右端包含当天，因此取当天最后一秒而不是次日零点。

    存量值是整秒，所以截断到秒不会漏掉任何一条。
    """
    return int(datetime.combine(value + timedelta(days=1), time.min, tzinfo=UTC).timestamp()) - 1


class MilvusVectorIndex:
    """规格 9.3 的 collection。"""

    def __init__(
        self,
        *,
        uri: str,
        collection: str,
        dimension: int,
        token: str | None = None,
    ) -> None:
        if not uri:
            raise ValueError("a Milvus URI is required")
        if not collection:
            raise ValueError("a Milvus collection name is required")
        if dimension <= 0:
            raise ValueError("a positive dense vector dimension is required")
        client = _sdk().MilvusClient(uri=uri, token=token or "")
        self._client = client
        self._collection = collection
        self._dimension = dimension

    # --- collection ---

    def ensure_collection(self) -> None:
        """建表。已存在就不动：重建走 generation，不靠删表。"""
        if self._client.has_collection(self._collection):
            return
        sdk = _sdk()
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            field_name=PRIMARY_KEY_FIELD,
            datatype=sdk.DataType.VARCHAR,
            max_length=MAX_ID_LENGTH,
            is_primary=True,
        )
        for name in (
            CHUNK_ID_FIELD,
            GENERATION_FIELD,
            DOCUMENT_ID_FIELD,
            DOCUMENT_VERSION_FIELD,
            PARENT_CHUNK_FIELD,
            INSTITUTION_FIELD,
        ):
            schema.add_field(
                field_name=name,
                datatype=sdk.DataType.VARCHAR,
                max_length=MAX_NAME_LENGTH,
                nullable=name in {PARENT_CHUNK_FIELD, INSTITUTION_FIELD},
            )
        for name in (STATE_FIELD, CHUNK_TYPE_FIELD, DOCUMENT_TYPE_FIELD, CONTENT_ORIGIN_FIELD):
            schema.add_field(
                field_name=name, datatype=sdk.DataType.VARCHAR, max_length=MAX_LABEL_LENGTH
            )
        schema.add_field(
            field_name=CONTENT_FIELD,
            datatype=sdk.DataType.VARCHAR,
            max_length=MAX_CONTENT_LENGTH,
            # 这一项就是全文检索的开关：没有它，`content` 只是一个普通字符串字段，
            # BM25 那一半会安静地永远召回不到东西。
            enable_analyzer=True,
        )
        schema.add_field(field_name=SPARSE_FIELD, datatype=sdk.DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field(
            field_name=DENSE_FIELD,
            datatype=sdk.DataType.FLOAT_VECTOR,
            dim=self._dimension,
        )
        for name in (PUBLISHED_AT_FIELD, EFFECTIVE_FROM_FIELD, EFFECTIVE_TO_FIELD):
            schema.add_field(field_name=name, datatype=sdk.DataType.INT64, nullable=True)
        schema.add_field(field_name=SOURCE_WEIGHT_FIELD, datatype=sdk.DataType.FLOAT)
        schema.add_field(field_name=CONFIDENCE_FIELD, datatype=sdk.DataType.FLOAT)
        schema.add_field(field_name=VERIFICATION_FIELD, datatype=sdk.DataType.BOOL)
        schema.add_function(
            sdk.Function(
                name="bm25",
                function_type=sdk.FunctionType.BM25,
                input_field_names=[CONTENT_FIELD],
                output_field_names=[SPARSE_FIELD],
            )
        )

        indexes = self._client.prepare_index_params()
        indexes.add_index(field_name=DENSE_FIELD, index_type="AUTOINDEX", metric_type="COSINE")
        indexes.add_index(
            field_name=SPARSE_FIELD, index_type="SPARSE_INVERTED_INDEX", metric_type="BM25"
        )
        self._client.create_collection(
            collection_name=self._collection, schema=schema, index_params=indexes
        )

    # --- 写入 ---

    def stage(self, *, generation: str, records: Sequence[VectorRecord]) -> None:
        batch: dict[str, VectorRecord] = {}
        for record in records:
            duplicate = batch.get(record.chunk_id)
            if duplicate is not None and duplicate.content != record.content:
                raise IndexRecordConflict(
                    f"chunk {record.chunk_id!r} appears twice in one batch with different "
                    f"content; the id is derived from the content, so this means the id "
                    f"generation upstream is broken"
                )
            batch[record.chunk_id] = record

        # 整批验完再写：一半成功的批次会把"哪些进了"变成一个需要额外记录才能回答的问题，
        # 而调用方拿到的只有一个异常。
        already_staged = self._content_by_chunk_id(generation)
        for chunk_id, record in batch.items():
            if chunk_id in already_staged and already_staged[chunk_id] != record.content:
                raise IndexRecordConflict(
                    f"chunk {chunk_id!r} is already staged in generation {generation!r} with "
                    f"different content"
                )

        self._client.upsert(
            collection_name=self._collection,
            data=[self._row(record, generation) for record in batch.values()],
        )

    def publish(self, *, generation: str) -> None:
        held = self._staged_keys(generation)
        if not held:
            raise IndexGenerationUnknown(
                f"generation {generation!r} has no staged records to publish; if the staging "
                f"happened in another process, stage them again here"
            )
        # 部分更新：只改标量字段。整条 upsert 需要提供稀疏向量，而它是 BM25 Function 的
        # 输出，调用方提供不了——那样写回去的会是一条没有全文索引的记录。
        self._client.upsert(
            collection_name=self._collection,
            data=[
                {PRIMARY_KEY_FIELD: key, STATE_FIELD: IndexState.PUBLISHED.value} for key in held
            ],
            partial_update=True,
        )

    def delete_generation(self, *, generation: str) -> None:
        self._client.delete(
            collection_name=self._collection, filter=self._generation_filter(generation)
        )

    def delete_records(self, *, generation: str, chunk_ids: Sequence[str]) -> int:
        """删掉一代里指定的那几条（规格 16.4 的孤立向量）。

        主键由 `chunk_id + ":" + generation` 拼成，因此这里按**主键**删，不按 `chunk_id`
        删：同一批 chunk_id 会同时存在于新旧两代里，按 chunk_id 删会把正在服务的那一代也
        打出一个洞。一次删不完时分批：Milvus 的表达式长度有限，而"孤立向量"恰恰可能很多。
        """
        wanted = list(dict.fromkeys(chunk_ids))
        if not wanted:
            return 0
        removed = 0
        for start in range(0, len(wanted), DELETE_BATCH):
            batch = wanted[start : start + DELETE_BATCH]
            keys = ", ".join(f'"{primary_key(chunk_id, generation)}"' for chunk_id in batch)
            result = self._client.delete(
                collection_name=self._collection,
                filter=f"{PRIMARY_KEY_FIELD} in [{keys}]",
            )
            removed += int(getattr(result, "delete_count", len(batch)))
        return removed

    # --- 校验 ---

    def verify(self, *, generation: str, expected_ids: Set[str]) -> IndexVerification:
        rows = self._query(generation, output_fields=[CHUNK_ID_FIELD, STATE_FIELD])
        present = {row[CHUNK_ID_FIELD] for row in rows}
        return IndexVerification(
            generation=generation,
            expected_count=len(expected_ids),
            present_count=len(present),
            missing_ids=tuple(sorted(set(expected_ids) - present)),
            unexpected_ids=tuple(sorted(present - set(expected_ids))),
            # Milvus 的维度由 collection 的 schema 强制，不是从记录里推出来的，因此这里报
            # 的是索引真正会使用的那个数字。
            dimension=self._dimension if present else None,
            published=bool(rows)
            and all(row[STATE_FIELD] == IndexState.PUBLISHED.value for row in rows),
        )

    # --- 检索 ---

    def hybrid_search(self, query: HybridQuery) -> tuple[VectorHit, ...]:
        sdk = _sdk()
        expression = self._expression(query.filters)
        dense = sdk.AnnSearchRequest(
            data=[list(query.dense_vector)],
            anns_field=DENSE_FIELD,
            param={"metric_type": "COSINE"},
            limit=query.dense_top_k,
            expr=expression,
        )
        sparse = sdk.AnnSearchRequest(
            data=[query.query_text],
            anns_field=SPARSE_FIELD,
            param={"metric_type": "BM25"},
            limit=query.bm25_top_k,
            expr=expression,
        )
        # 两条独立请求 + RRF 融合：融合发生在服务端，因此回来的分数只有融合分，这正是
        # `VectorHit` 不暴露分路得分的原因。
        results = self._client.hybrid_search(
            collection_name=self._collection,
            reqs=[dense, sparse],
            ranker=sdk.RRFRanker(k=query.rrf_k),
            limit=query.fusion_top_k,
            output_fields=list(_HIT_FIELDS),
        )
        return self._hits(results)

    def _hits(self, results: Sequence[Sequence[Any]]) -> tuple[VectorHit, ...]:
        hits: list[VectorHit] = []
        seen: set[str] = set()
        for hit in results[0] if results else []:
            entity = hit["entity"]
            chunk_id = entity[CHUNK_ID_FIELD]
            # 重建期间同一个 chunk 会同时存在于新旧两个 generation。两行内容相同，都返回
            # 只会占掉一个 Top-K 名额，并让同一段文本在证据里出现两次。
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            hits.append(
                VectorHit(
                    chunk_id=chunk_id,
                    document_id=entity[DOCUMENT_ID_FIELD],
                    document_version_id=entity[DOCUMENT_VERSION_FIELD],
                    parent_chunk_id=entity.get(PARENT_CHUNK_FIELD),
                    chunk_type=ChunkType(entity[CHUNK_TYPE_FIELD]),
                    document_type=DocumentType(entity[DOCUMENT_TYPE_FIELD]),
                    content=entity[CONTENT_FIELD],
                    content_origin=ExtractionMethod(entity[CONTENT_ORIGIN_FIELD]),
                    requires_verification=bool(entity[VERIFICATION_FIELD]),
                    fused_score=hit["distance"],
                )
            )
        return tuple(hits)

    # --- 内部 ---

    def _row(self, record: VectorRecord, generation: str) -> dict[str, Any]:
        return {
            PRIMARY_KEY_FIELD: primary_key(record.chunk_id, generation),
            CHUNK_ID_FIELD: record.chunk_id,
            GENERATION_FIELD: generation,
            STATE_FIELD: IndexState.STAGED.value,
            DOCUMENT_ID_FIELD: record.document_id,
            DOCUMENT_VERSION_FIELD: record.document_version_id,
            PARENT_CHUNK_FIELD: record.parent_chunk_id,
            CHUNK_TYPE_FIELD: record.chunk_type.value,
            DOCUMENT_TYPE_FIELD: record.document_type.value,
            INSTITUTION_FIELD: record.institution,
            PUBLISHED_AT_FIELD: _seconds(record.published_at),
            EFFECTIVE_FROM_FIELD: _seconds(
                None
                if record.effective_from is None
                else datetime.combine(record.effective_from, time.min, tzinfo=UTC)
            ),
            EFFECTIVE_TO_FIELD: _seconds(
                None
                if record.effective_to is None
                else datetime.combine(record.effective_to, time.max, tzinfo=UTC)
            ),
            SOURCE_WEIGHT_FIELD: record.source_weight,
            CONTENT_ORIGIN_FIELD: record.content_origin.value,
            CONFIDENCE_FIELD: record.confidence,
            VERIFICATION_FIELD: record.requires_verification,
            CONTENT_FIELD: record.content,
            DENSE_FIELD: list(record.dense_vector),
        }

    def _expression(self, filters: SearchFilters) -> str:
        """过滤由 Milvus 执行，不是召回之后再筛（规格 11.1）。

        先召回再筛会得到同样的结果，直到窗口被无关候选占满——那时"为什么这个问题召回不到"
        就无从解释了。
        """
        clauses = [f'{STATE_FIELD} == "{IndexState.PUBLISHED.value}"']
        if filters.document_types:
            values = ", ".join(f'"{entry.value}"' for entry in filters.document_types)
            clauses.append(f"{DOCUMENT_TYPE_FIELD} in [{values}]")
        if not filters.include_unverified_leads:
            clauses.append(f"{VERIFICATION_FIELD} == false")
        if filters.published_from is not None:
            clauses.append(f"{PUBLISHED_AT_FIELD} >= {_day_start(filters.published_from)}")
        if filters.published_to is not None:
            clauses.append(f"{PUBLISHED_AT_FIELD} <= {_day_end(filters.published_to)}")
        # 没有发布日期的记录因为 `null` 的比较结果为假而被排除，与内存实现一致。
        return " and ".join(clauses)

    def _generation_filter(self, generation: str) -> str:
        return f'{GENERATION_FIELD} == "{generation}"'

    def _query(self, generation: str, *, output_fields: Sequence[str]) -> list[dict[str, Any]]:
        # 经由一个标注过的局部变量回来：SDK 没有类型信息，直接 return 会把 Any 当成契约
        # 的一部分传下去。
        rows: list[dict[str, Any]] = self._client.query(
            collection_name=self._collection,
            filter=self._generation_filter(generation),
            output_fields=list(output_fields),
            limit=QUERY_LIMIT,
        )
        return rows

    def _content_by_chunk_id(self, generation: str) -> dict[str, str]:
        rows = self._query(generation, output_fields=[CHUNK_ID_FIELD, CONTENT_FIELD])
        return {row[CHUNK_ID_FIELD]: row[CONTENT_FIELD] for row in rows}

    def _staged_keys(self, generation: str) -> list[str]:
        rows = self._query(generation, output_fields=[PRIMARY_KEY_FIELD])
        return [row[PRIMARY_KEY_FIELD] for row in rows]


_HIT_FIELDS = (
    CHUNK_ID_FIELD,
    DOCUMENT_ID_FIELD,
    DOCUMENT_VERSION_FIELD,
    PARENT_CHUNK_FIELD,
    CHUNK_TYPE_FIELD,
    DOCUMENT_TYPE_FIELD,
    CONTENT_FIELD,
    CONTENT_ORIGIN_FIELD,
    VERIFICATION_FIELD,
)
