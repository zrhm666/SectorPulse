"""The Milvus adapter against a real server, using the shared contract.

This test only runs when a dedicated test collection is configured, and the collection name
must be marked as a test collection (`_test` or `-test`) — the same rule the PostgreSQL and
MinIO guards apply to database and bucket names. A collection that is not named as a test
collection can only mean production vectors, so the test refuses to run rather than finding
out by deleting someone's index.

It is skipped, not failed, when the SDK is absent or nothing is configured. What it must
never do is pass while having verified nothing, which is why the collection guard is a
refusal and the environment guards are skips: "nobody configured a test collection" is a
missing precondition, while "the configured collection is not a test collection" is a
mistake that must stop the run.

The index is built inside the guard's `connect` callback, never around it: a collection is
dialled only after the name has passed.
"""

import importlib.util

import pytest
from sector_pulse.config.rag_settings import load_rag_settings
from sector_pulse.infrastructure.research_library.vector.milvus import MilvusVectorIndex

from backend.tests.contracts.test_vector_index import (
    CONTRACT_BODIES,
    GENERATION,
    OTHER_GENERATION,
    TOKEN,
    query,
    record,
)
from backend.tests.dedicated_resources import connect_to_dedicated_resource

pytestmark = pytest.mark.milvus

#: 契约里的向量是 8 维的，测试 collection 必须按同一维度建；与内存实现无关，这是契约
#: 自身的约定。
DIMENSION = 8


@pytest.fixture
def index() -> "MilvusVectorIndex":
    """每条契约一个干净的起点。

    契约体用的是固定的 generation 名字，因此上一条留下的 staged 记录会让下一条拿到
    "同一个 ID、不同内容"——那是一个由测试顺序造出来的冲突，不是实现的问题。
    """
    if importlib.util.find_spec("pymilvus") is None:
        pytest.skip("the pymilvus SDK is not installed; install the 'rag' extra")
    settings = load_rag_settings()
    if not settings.milvus_uri:
        pytest.skip("no Milvus URI is configured")

    def build(collection: str) -> MilvusVectorIndex:
        return MilvusVectorIndex(
            uri=settings.milvus_uri,
            token=settings.milvus_token.get_secret_value()
            if settings.milvus_token
            else None,
            collection=collection,
            dimension=DIMENSION,
        )

    instance = connect_to_dedicated_resource(
        kind="Milvus test collection",
        variable="SECTOR_PULSE_RAG_MILVUS_COLLECTION",
        connect=build,
        suffixes=("_test", "-test"),
    )
    instance.ensure_collection()
    for generation in (GENERATION, OTHER_GENERATION):
        instance.delete_generation(generation=generation)
    return instance


@pytest.mark.parametrize(
    "body", [body for _, body in CONTRACT_BODIES], ids=[name for name, _ in CONTRACT_BODIES]
)
def test_the_milvus_index_satisfies_the_contract(index, body) -> None:
    body(index)


def test_the_same_chunk_in_two_generations_is_two_rows(index) -> None:
    """派生主键的直接后果，也是它存在的理由（规格 16.2、19）。

    把主键简化成 `chunk_id` 之后这一条会失败，而失败的方式是"重建覆盖了正在服务的那一
    份"——在真实环境里这意味着切换 generation 之前检索就已经指向了新数据。
    """
    records = [record("chunk_a", content=f"{TOKEN} 中标公告")]
    index.stage(generation=GENERATION, records=records)
    index.publish(generation=GENERATION)
    index.stage(generation=OTHER_GENERATION, records=records)
    index.publish(generation=OTHER_GENERATION)

    assert index.verify(generation=GENERATION, expected_ids={"chunk_a"}).present_count == 1
    assert index.verify(generation=OTHER_GENERATION, expected_ids={"chunk_a"}).present_count == 1

    # 两行都在，但检索只回一条：重建期间同一段文本不该占掉两个 Top-K 名额，也不该在
    # 证据里出现两次。
    assert [hit.chunk_id for hit in index.hybrid_search(query=query(TOKEN))] == ["chunk_a"]
