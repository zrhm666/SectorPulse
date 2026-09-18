"""A0→A4 一次真实链路（Task 20 Step 6）。

这是整条 RAG 的验收门，排在最后是因为它同时要握着四样东西：真实对话模型（A0–A4 的每一次
发言）、真实 RAG Provider（检索、重排、冲突裁决）、专用 PostgreSQL（权威库与编排状态）、
专用 MinIO 与 Milvus（原件与派生索引）。四样缺一不可，缺哪一样就跳过——**跳过不是通过**，
这是计划 Step 6 的原话。

它跑的是应用真正的入口：`create_app` 加上一份注入的资料库装配，然后从 HTTP 上开一次运行。
这样做是因为要验的那几件事全都落在"运行停下来时的状态"上——A2 有没有接纳内部证据、判不了的
冲突有没有被记成 UNRESOLVED、A3 有没有谨慎地表达它、A4 有没有评校、最终状态是不是停在
`WAITING_USER_REVIEW`。从命令层驱动一遍得不到最后那一条。

语料是三份自编的文档，装着**一个可裁决的冲突与一个不可裁决的冲突**：

* 可裁决：同一主体与谓词、同一时间窗，两份来源权重不同（0.90 对 0.50）→ 权重规则选出赢家；
* 不可裁决：同一主体与谓词、同一时间窗，两份来源互相独立且权重相同 → 没有规则能分出高下。

第二个才是这个用例的重点。把不可裁决记成一条已经查清的事实，是这套系统最坏的失败方式：
它看起来像一条有出处的结论。因此断言落在证据表里那些 UNRESOLVED 行上，而不只落在措辞上。

**状态：本机从未跑通过。** 这台机器没有 PostgreSQL、MinIO、Milvus，也没有配置真实 Provider，
所以这份文件目前只会被收集然后跳过。它是先写好的验收脚本：任何一次"通过"都必须来自一台真的
接上了这四样东西的机器。这段状态写在文件里而不是只写在报告里，因为读代码的人有权知道，
自己看到的这份绿色到底是不是跑出来的。
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from sector_pulse.application.research_library.commands import UploadTarget
from sector_pulse.domain.research_library.models import DocumentType
from sector_pulse.infrastructure.research_library.assets.integrity import spool_to_disk
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.orchestration.repository import (
    PostgresOrchestrationRepository,
)

from backend.tests.research_library_live_support import (
    BUCKET_VARIABLE,
    COLLECTION_VARIABLE,
    POSTGRES_VARIABLE,
    build_live_library,
    dedicated_names,
    require_live_rag_settings,
    require_module,
)

pytestmark = [pytest.mark.live_llm, pytest.mark.live_rag]

GOAL = "只用内部研究资料库的证据，说明二线厂商产能利用率与电解液价格季度涨幅的最新情况。"

#: 不可裁决那一对的主体。草稿里出现它时必须带着不确信的措辞。
UNRESOLVED_SUBJECT = "电解液价格"

#: 表达"这件事还没定"的词。A3 用哪个词不重要，重要的是它不能把两方相反的结论写成一边的。
HEDGES = (
    "分歧",
    "不一致",
    "冲突",
    "未定",
    "尚不能",
    "无法确认",
    "待核实",
    "存疑",
    "不确定",
)

#: A4 留下的评校 Artifact 的 kind。两种写法都在用，断言要认全。
REVIEW_KINDS = frozenset({"review", "independent_review"})

ACTOR = "验收"
WORKER = "acceptance-worker"
PUBLISHED_AT = "2026-09-18T04:00:00+00:00"
DEADLINE_SECONDS = 3600.0
POLL_SECONDS = 5.0

#: 三份文档：一份高权重的产能结论、一份低权重的相反结论（并带一句电解液价格）、
#: 一份与第二份权重相同的相反结论。第二个冲突的两侧各说各的季度涨幅，谁都不比谁更有分量。
DOCUMENTS: tuple[dict[str, str], ...] = (
    {
        "key": "weight_high",
        "title": "二线厂商产能跟踪（高权重）",
        "institution": "华源研究所",
        "source_weight": "0.90",
        "body": "二线厂商产能跟踪\n\n调研结论：二线厂商的产能利用率在过去一个季度上升。",
    },
    {
        "key": "weight_low",
        "title": "二线厂商与电解液调研纪要（低权重）",
        "institution": "独立调研机构乙",
        "source_weight": "0.50",
        "body": (
            "二线厂商与电解液调研纪要\n\n"
            "调研结论：二线厂商的产能利用率在过去一个季度下降。\n\n"
            "电解液价格跟踪：二季度电解液价格环比上涨百分之六。"
        ),
    },
    {
        "key": "peer_low",
        "title": "电解液价格季度跟踪（同权重）",
        "institution": "独立调研机构丙",
        "source_weight": "0.50",
        "body": "电解液价格季度跟踪\n\n二季度电解液价格环比下降百分之三。",
    },
)


def test_one_real_rag_chain_stops_at_user_review(monkeypatch: pytest.MonkeyPatch) -> None:
    require_module("psycopg")
    require_module("minio")
    require_module("pymilvus")

    # 三个专用资源名逐个判定：缺配置是 skip，名字不以 `_test` 结尾是拒绝；判定发生在任何
    # 客户端存在之前，而下面这几行正是拿判定结果去设环境变量的地方。
    database_url, bucket, collection = dedicated_names()
    monkeypatch.setenv(POSTGRES_VARIABLE, database_url)
    monkeypatch.setenv(BUCKET_VARIABLE, bucket)
    monkeypatch.setenv(COLLECTION_VARIABLE, collection)
    monkeypatch.setenv("SECTOR_PULSE_RAG_ENABLED", "true")

    # 真实对话模型是另一样必需项：A0–A4 的每一次发言都花它的钱。
    if os.environ.get("SECTOR_PULSE_LLM_PROVIDER", "") != "live":
        pytest.skip("SECTOR_PULSE_LLM_PROVIDER must be 'live' for a real chain")
    for variable in ("SECTOR_PULSE_LLM_BASE_URL", "SECTOR_PULSE_LLM_MODEL"):
        if not os.environ.get(variable):
            pytest.skip(f"a real agent chain needs {variable}")

    settings = require_live_rag_settings()
    database = PostgresDatabase(database_url)
    database.initialize()
    library = build_live_library(settings, database=database)
    ingested: list[str] = []
    try:
        ingested = _ingest(library)
        client = _app(library)
        run_id = _start_run(client)
        detail = _await_terminal(client, run_id)

        assert detail["status"] == "WAITING_USER_REVIEW", detail

        evidence = _evidence(database, run_id)
        assert evidence, "A2 accepted no internal evidence at all"

        unresolved = [row for row in evidence if row["conflict_status"] == "UNRESOLVED"]
        assert unresolved, (
            "the unresolvable pair never came back as UNRESOLVED; the run accepted "
            f"{[row['conflict_status'] for row in evidence]}"
        )
        for row in unresolved:
            # 判不了就要带着双方一起说：只引一边的 UNRESOLVED 是一句没有出处的结论。
            assert row["source_count"] >= 2, row

        draft = client.get(f"/api/runs/{run_id}/draft.md")
        assert draft.status_code == 200, draft.text
        assert UNRESOLVED_SUBJECT in draft.text, (
            "A3's draft never mentions the unresolved subject"
        )
        assert any(hedge in draft.text for hedge in HEDGES), (
            f"A3 stated the unresolved conflict without hedging; the draft says: {draft.text}"
        )

        state = PostgresOrchestrationRepository(database).load(_uuid(run_id))
        assert state is not None
        kinds = {item.kind for item in state.artifacts}
        assert kinds & REVIEW_KINDS, f"A4 left no review artifact: {sorted(kinds)}"
    finally:
        _cleanup(library, ingested)
        database.close()


def _ingest(library: Any) -> list[str]:
    """把三份文档真的摄取进权威库。走的是命令层，与 API 是同一条路。"""
    document_ids: list[str] = []
    for spec in DOCUMENTS:
        with spool_to_disk(
            BytesIO(spec["body"].encode("utf-8")), max_bytes=library.max_upload_bytes
        ) as spooled:
            result = library.commands.upload(
                spooled=spooled,
                media_type="text/plain",
                filename=f"{spec['key']}.txt",
                target=UploadTarget.NEW_DOCUMENT,
                actor=ACTOR,
                title=spec["title"],
                document_type=DocumentType.REPORT,
                institution=spec["institution"],
                published_at=PUBLISHED_AT,
            )
        job = library.commands.run_ingestion(result.job.job_id, worker_id=WORKER)
        assert job.status.value == "PUBLISHED", (spec["key"], job.status, job.failure_reason)
        # 权重不是装饰：可裁决的那一对全靠它分出高下。
        library.commands.set_source_weight(
            result.document.document_id,
            source_weight=Decimal(spec["source_weight"]),
            actor=ACTOR,
        )
        document_ids.append(result.document.document_id)
    return document_ids


def _app(library: Any) -> Any:
    """应用真正的入口：注入资料库，其余全部按环境配置自己装配。"""
    from fastapi.testclient import TestClient
    from sector_pulse.web.app import create_app

    return TestClient(create_app(overrides={"research_library": library}))


def _start_run(client: Any) -> str:
    response = client.post(
        "/api/runs",
        json={
            "input_json": {"goal": GOAL},
            "provider": "live",
            # 人工挑选不在这个用例的范围里：要走的是 A2→A4 那一段，因此选项由服务端给。
            "selection_policy": "server_default",
        },
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    assert isinstance(run_id, str) and run_id, run_id
    return run_id


def _await_terminal(client: Any, run_id: str) -> dict[str, Any]:
    """等这一次运行自己停下来。

    上限是墙钟而不是轮询次数：一次真实运行的长短由模型决定，一次卡住的调用应当以超时结束，
    而不是以"轮询到第几次"结束。
    """
    started = time.monotonic()
    while time.monotonic() - started < DEADLINE_SECONDS:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        payload: dict[str, Any] = response.json()
        if payload["status"] != "RUNNING":
            return payload
        time.sleep(POLL_SECONDS)
    raise AssertionError(f"the run did not stop within {DEADLINE_SECONDS:.0f}s")


def _uuid(run_id: str) -> Any:
    from uuid import UUID

    return UUID(run_id)


def _evidence(database: PostgresDatabase, run_id: str) -> list[dict[str, Any]]:
    """这一次运行接纳下来的内部证据，每一行带上它的来源条数。"""
    with database.connection() as connection:
        rows = connection.execute(
            """
            SELECT e.conflict_status, e.grade, e.statement, e.requires_verification,
                   (SELECT COUNT(*) FROM internal_research_evidence_sources s
                     WHERE s.evidence_id = e.evidence_id) AS source_count
            FROM internal_research_evidence e
            WHERE e.run_id = :run_id
            ORDER BY e.created_at
            """,
            {"run_id": run_id},
        ).fetchall()
    return [dict(row._mapping) for row in rows]


def _cleanup(library: Any, document_ids: list[str]) -> None:
    """把这一次自己造出来的东西收拾掉。

    专用测试库是共享的：留下的文档会继续参与下一次运行的检索，于是下一次的"不可裁决冲突"
    里会多出来历不明的一份来源。清理由测试自己做，不指望运维记得。软删除就够了——检索看不见
    被删的文档，而彻底清理交给维护流程的 purge。
    """
    for document_id in document_ids:
        library.commands.soft_delete(
            document_id, actor=ACTOR, now=datetime.now(UTC)
        )
