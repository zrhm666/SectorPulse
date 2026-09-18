"""专用资源门禁，在不接服务器的情况下逐条验证。

门禁存在的意义是拦住一次写向生产的运行，所以它真正要紧的分支是**拒绝**那一条：一个从不
拒绝的门禁比没有门禁更糟，套件照样报绿。除了"服务器答了话"之外，其余分支离线都能走到，
这里把它们全部断言一遍。

`connect` 是一个记录调用的假工厂。它是这个文件里唯一的替身，也是唯一能证明"拒绝发生在
连接之前"的东西——顺序写在代码里读得出来，但只有"工厂一次没被调用"是证据。
"""

from collections.abc import Callable

import pytest

from backend.tests.dedicated_resources import (
    BusinessResourceRefused,
    connect_to_dedicated_resource,
    require_test_name,
)
from backend.tests.postgres_isolation import (
    BusinessDatabaseRefused,
    isolate_configured_postgres_url,
)

BUCKET_VARIABLE = "SECTOR_PULSE_RAG_MINIO_BUCKET"
COLLECTION_VARIABLE = "SECTOR_PULSE_RAG_MILVUS_COLLECTION"
DATABASE_VARIABLE = "SECTOR_PULSE_DATABASE_URL"

BUSINESS_URL = "postgresql+asyncpg://sectorpulse_app:secret@localhost:5432/sectorpulse_runtime"
TEST_URL = "postgresql+asyncpg://sectorpulse_app:secret@localhost:5432/sectorpulse_runtime_test"


def a_factory(opened: list[str]) -> Callable[[str], str]:
    def connect(name: str) -> str:
        opened.append(name)
        return "client"

    return connect


def test_a_test_resource_reaches_the_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BUCKET_VARIABLE, "sectorpulse-research-test")
    opened: list[str] = []

    result = connect_to_dedicated_resource(
        kind="bucket",
        variable=BUCKET_VARIABLE,
        connect=a_factory(opened),
        suffixes=("-test",),
    )

    assert result == "client"
    assert opened == ["sectorpulse-research-test"]


def test_an_unconfigured_resource_skips_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(BUCKET_VARIABLE, raising=False)
    opened: list[str] = []

    # 缺配置是前提缺失，属于 skip；而配置了一个不是测试资源的东西是错误，属于 fail。
    with pytest.raises(pytest.skip.Exception):
        connect_to_dedicated_resource(
            kind="bucket",
            variable=BUCKET_VARIABLE,
            connect=a_factory(opened),
            suffixes=("-test",),
        )

    assert opened == []


def test_a_production_bucket_is_refused_before_the_factory_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BUCKET_VARIABLE, "sectorpulse-research")
    opened: list[str] = []

    with pytest.raises(BusinessResourceRefused, match="sectorpulse-research"):
        connect_to_dedicated_resource(
            kind="bucket",
            variable=BUCKET_VARIABLE,
            connect=a_factory(opened),
            suffixes=("-test",),
        )

    assert opened == []


def test_the_refusal_names_the_variable_that_has_to_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BUCKET_VARIABLE, "production-assets")

    with pytest.raises(BusinessResourceRefused) as refusal:
        require_test_name(kind="bucket", value="production-assets", variable=BUCKET_VARIABLE)

    # 一句"拒绝了"没有用：要么说清改哪个变量，要么运维只能去读源码。
    assert BUCKET_VARIABLE in str(refusal.value)
    assert "production-assets" in str(refusal.value)


def test_each_resource_keeps_its_own_suffix_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    # Milvus 的 collection 用下划线，MinIO 的 bucket 用连字符，PostgreSQL 的库名用下划线；
    # 把三者的后缀合成一条更宽松的规则，等于给其中两个开了一个不该有的口子。
    monkeypatch.setenv(COLLECTION_VARIABLE, "internal_research_chunks_test")
    opened: list[str] = []
    connect_to_dedicated_resource(
        kind="collection",
        variable=COLLECTION_VARIABLE,
        connect=a_factory(opened),
        suffixes=("_test", "-test"),
    )
    assert opened == ["internal_research_chunks_test"]

    with pytest.raises(BusinessResourceRefused):
        require_test_name(
            kind="database",
            value="sectorpulse-research-test",
            variable=DATABASE_VARIABLE,
            suffixes=("_test",),
        )


def test_the_database_guard_refuses_with_the_shared_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_VARIABLE, BUSINESS_URL)

    # 与 bucket/collection 同一类拒绝：三条门禁说的是同一条规则，调用方也就该只 `except` 一次。
    with pytest.raises(BusinessResourceRefused, match="sectorpulse_runtime"):
        isolate_configured_postgres_url()


def test_a_test_database_still_passes_the_shared_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATABASE_VARIABLE, TEST_URL)

    isolate_configured_postgres_url()

    assert BusinessDatabaseRefused is BusinessResourceRefused
