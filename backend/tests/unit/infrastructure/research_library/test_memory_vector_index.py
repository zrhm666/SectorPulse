"""The reference adapter for the vector index: every contract property, plus its own rules.

The contract bodies live in `backend/tests/contracts/test_vector_index.py` and are run here
one per test, so a failure names the property that broke rather than "the index is wrong".
The Milvus adapter runs the same list.

The tests below the contract loop are the ones only this adapter can answer: that a rebuild
reproduces the index (the index is derived state, so this must be true), and what happens
when a vector arrives from a different embedding model than the one the query was encoded
with.
"""

import pytest
from sector_pulse.infrastructure.research_library.vector import memory
from sector_pulse.ports.vector_index import VectorIndex

from backend.tests.contracts.test_vector_index import (
    CONTRACT_BODIES,
    GENERATION,
    OTHER_GENERATION,
    TOKEN,
    query,
    record,
)


@pytest.mark.parametrize(
    "body", [body for _, body in CONTRACT_BODIES], ids=[name for name, _ in CONTRACT_BODIES]
)
def test_the_memory_index_satisfies_the_contract(body) -> None:
    body(memory.InMemoryVectorIndex())


def test_the_memory_index_declares_the_port_it_implements() -> None:
    assert isinstance(memory.InMemoryVectorIndex(), VectorIndex)


def test_a_rebuild_reproduces_the_same_hits() -> None:
    """规格 9.4：索引是派生的，因此"删掉重建"必须回到同一处。

    如果重建之后检索结果变了，索引就在事实上变成了一个权威状态源——只是没人能说清它存
    的是什么——而权威状态源按规格必须是 PostgreSQL。
    """
    index = memory.InMemoryVectorIndex()
    records = [
        record("chunk_a", content=f"{TOKEN} 中标公告"),
        record("chunk_b", content="欧洲市场库存下降"),
    ]
    index.stage(generation=GENERATION, records=records)
    index.publish(generation=GENERATION)
    before = [hit.chunk_id for hit in index.hybrid_search(query=query(TOKEN))]

    index.delete_generation(generation=GENERATION)
    assert index.hybrid_search(query=query(TOKEN)) == ()

    index.stage(generation=OTHER_GENERATION, records=records)
    index.publish(generation=OTHER_GENERATION)
    assert [hit.chunk_id for hit in index.hybrid_search(query=query(TOKEN))] == before


def test_a_vector_from_another_embedding_model_is_never_scored_by_cosine() -> None:
    """换嵌入模型期间，旧维度的向量和查询向量不可比。

    两个不同维度的向量算余弦，要么抛错、要么按共同前缀算出一个看起来合理的分数——后者更
    糟，因为检索会安静地返回按错误依据排序的结果。旧记录因此退出稠密那一侧；它这里也和
    查询没有共同词，所以干脆不出现，这正是"没有被错误分数捞回来"的观测形式。
    """
    index = memory.InMemoryVectorIndex()
    index.stage(
        generation=GENERATION,
        records=[
            record("chunk_old", content="旧模型切出来的片段", dense_vector=(1.0, 0.1)),
            record("chunk_new", content="欧洲市场库存下降"),
        ],
    )
    index.publish(generation=GENERATION)

    hits = index.hybrid_search(query=query(TOKEN))
    assert [hit.chunk_id for hit in hits] == ["chunk_new"]


def test_an_index_with_nothing_published_returns_nothing() -> None:
    index = memory.InMemoryVectorIndex()
    assert index.hybrid_search(query=query(TOKEN)) == ()
    index.stage(generation=GENERATION, records=[record("chunk_a", content="任意内容")])
    assert index.hybrid_search(query=query(TOKEN)) == ()


def test_the_reported_dimension_is_the_one_the_records_carry() -> None:
    index = memory.InMemoryVectorIndex()
    index.stage(
        generation=GENERATION,
        records=[record("chunk_a", content="第一段", dense_vector=(1.0, 0.0, 0.0))],
    )
    assert index.verify(generation=GENERATION, expected_ids={"chunk_a"}).dimension == 3


def test_a_generation_mixing_two_dimensions_reports_no_dimension() -> None:
    """混着两种维度时"那个维度"不存在，报出一个具体数字就是在编。

    这正是换嵌入模型换到一半的样子，而校验报告是唯一会看到它的地方。
    """
    index = memory.InMemoryVectorIndex()
    index.stage(
        generation=GENERATION,
        records=[
            record("chunk_a", content="第一段"),
            record("chunk_b", content="第二段", dense_vector=(1.0, 0.0, 0.0)),
        ],
    )
    report = index.verify(generation=GENERATION, expected_ids={"chunk_a", "chunk_b"})
    assert report.dimension is None
    assert report.is_complete
