"""资料库 API 的治理面（规格 18.1～18.3），全部离线运行。

这一层要证明的是**端点与命令之间的翻译**：状态码与错误码稳定、上传的四类门禁都在权威库
留下痕迹之前生效、原件是私人读取而不是公开链接、每一个改动资料库的动作都点得出名字。
它不重复验证命令内部的性质——那些在 `test_research_ingestion_pipeline.py` 与
`test_research_index_publication.py` 里。

装配的是真实的路由，只有存储是内存实现（见 `backend/tests/research_library_stack.py`）。
一个只测真实路由、不测真实存储的选择，出自这套系统的形状：三个存储里有两个是可以重建的
派生物，而权威库的那部分语义（条件更新、并发认领）本来就要真 PostgreSQL 才能验。
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sector_pulse.application.research_library.commands import GovernanceRefused
from sector_pulse.application.research_library.services import ResearchLibraryServices
from sector_pulse.domain.research_library.audit import DocumentAuditAction
from sector_pulse.domain.research_library.models import (
    DocumentVersionStatus,
    IngestionStatus,
)
from sector_pulse.infrastructure.agents.composition import (
    RAG_BUSINESS_TOOL_NAMES,
    RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES,
    REQUIRED_BUSINESS_TOOL_NAMES,
)
from sector_pulse.ports.research_assets import ScanStatus
from sector_pulse.ports.vector_index import VectorIndexError
from sector_pulse.web.app import create_app
from sector_pulse.web.errors import register_error_handlers
from sector_pulse.web.routers.research_library import build_research_library_router
from sector_pulse.web.schemas.research_library import (
    AssetDiscrepancyResponse,
    MaintenanceResponse,
)

from backend.tests.research_library_stack import (
    BODY,
    SMALL_UPLOAD_LIMIT,
    ResearchLibraryStack,
    build_research_library_stack,
    null_scanner_stack,
)

MALWARE_MARKER = b"@@MALWARE@@"
ACTOR = "hanyu"
WORKER = "worker-api"

#: 与路由里注册的一模一样。测试自己拼一遍路径，是为了让"端点被改名"这件事在客户端这一侧
#: 立刻变成 404，而不是被一个共享常量悄悄跟上。
DOCUMENTS = "/api/research-library/documents"
UPLOADS = "/api/research-library/uploads"
MAINTENANCE = "/api/research-library/maintenance"


def build_client(services: ResearchLibraryServices | None) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(build_research_library_router(services))
    return TestClient(app)


def stack_client(**kwargs) -> tuple[TestClient, ResearchLibraryStack]:
    stack = build_research_library_stack(**kwargs)
    return build_client(stack.services), stack


def upload(
    client: TestClient,
    body: bytes = BODY.encode("utf-8"),
    *,
    filename: str = "report.txt",
    media_type: str = "text/plain",
    target: str = "new_document",
    actor: str = ACTOR,
    **params: object,
):
    return client.post(
        UPLOADS,
        content=body,
        params={"target": target, "actor": actor, **params},
        headers={"content-type": media_type, "x-research-filename": filename},
    )


def publish(client: TestClient, uploaded) -> str:
    """把刚上传的版本推到底，返回它的 ID。"""
    job_id = uploaded.json()["job"]["job_id"]
    response = client.post(
        f"/api/research-library/ingestion-jobs/{job_id}/run",
        json={"worker_id": WORKER},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == IngestionStatus.PUBLISHED.value
    return uploaded.json()["version"]["document_version_id"]


# --- 没有资料库的部署 ---


def test_a_deployment_without_the_library_answers_404_not_500():
    """关掉 RAG 是正常状态，不是故障：前端据此显示空态。"""
    client = build_client(None)
    for method, path in (
        ("get", DOCUMENTS),
        ("get", MAINTENANCE),
        ("post", UPLOADS),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESEARCH_LIBRARY_DISABLED"


# --- 真应用里的接线 ---


def test_the_application_mounts_the_library_it_was_given(tmp_path):
    """`create_app` 真的把这一组路由挂上去了，而且用的就是注入的那一份装配。

    路由本身在别处已经测过，这一条测的是"接上了没有"：只被测试直接调用的构建函数，
    很容易在一个挂错位置的 app 里一直看着是绿的。注入的那一份也是**唯一**来源——
    治理路由与 A2 拿到的必须是同一次运行里的同一个权威库。
    """
    stack = build_research_library_stack()
    app = create_app(
        database_path=tmp_path / "app.sqlite3",
        static_dir=None,
        overrides={"research_library": stack.services},
    )
    with TestClient(app) as client:
        response = client.get(DOCUMENTS)

    assert response.status_code == 200
    assert response.json()["documents"] == []
    assert response.json()["corpus_generation"]


def test_the_application_answers_404_when_no_library_was_injected(tmp_path):
    app = create_app(
        database_path=tmp_path / "app.sqlite3", static_dir=None, overrides={}
    )
    with TestClient(app) as client:
        response = client.get(DOCUMENTS)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESEARCH_LIBRARY_DISABLED"


# --- 上传 ---


def test_upload_creates_a_document_version_and_job():
    client, stack = stack_client()
    response = upload(
        client,
        title="储能行业 2026 年中期策略",
        document_type="report",
        institution="测试研究院",
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True
    assert body["scan_status"] == ScanStatus.CLEAN.value
    assert body["document"]["title"] == "储能行业 2026 年中期策略"
    assert body["version"]["version_number"] == 1
    assert body["version"]["has_source"] is True
    assert body["job"]["status"] == IngestionStatus.RECEIVED.value

    listed = client.get(DOCUMENTS).json()
    assert [item["document"]["document_id"] for item in listed["documents"]] == [
        body["document"]["document_id"]
    ]
    # 同一次请求里的两行共享一个时间戳，因此只断言它们都在——同刻之内的先后是审计表不保证
    # 的东西（PostgreSQL 那边没有可依赖的插入顺序），拿它做断言等于在测一个巧合。
    audit = {
        entry.action
        for entry in stack.repository.list_document_audit(body["document"]["document_id"])
    }
    assert audit == {
        DocumentAuditAction.REGISTER_DOCUMENT,
        DocumentAuditAction.REGISTER_VERSION,
    }


def test_upload_of_a_new_version_requires_the_document():
    client, _ = stack_client()
    response = upload(client, target="new_version")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UPLOAD_TARGET_REQUIRED"


def test_upload_of_a_new_version_attaches_to_the_named_document():
    client, stack = stack_client()
    first = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    document_id = first["document"]["document_id"]

    response = upload(client, target="new_version", document_id=document_id, upload_key="second")
    assert response.status_code == 201, response.text
    assert response.json()["version"]["version_number"] == 2
    assert response.json()["document"]["document_id"] == document_id


def test_upload_of_a_new_document_refuses_an_existing_document_id():
    client, _ = stack_client()
    first = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    response = upload(
        client,
        title="另一份",
        document_type="report",
        document_id=first["document"]["document_id"],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UPLOAD_TARGET_CONFLICT"


def test_upload_requires_the_filename_header():
    client, _ = stack_client()
    response = client.post(
        UPLOADS,
        content=BODY.encode("utf-8"),
        params={"target": "new_document", "actor": ACTOR},
        headers={"content-type": "text/plain"},
    )
    assert response.status_code == 422


def test_a_percent_encoded_filename_comes_back_as_the_name_the_user_uploaded():
    """请求头只能放 latin-1，因此中文文件名只能在客户端转义。

    两个方向的转义必须互逆：上传时按 RFC 3986 转义，下载时按同一套规则再转义回来。只做
    一半的后果是具体的——权威库里存着的原件名变成一串 `%E5%82%A8…`，而用户在"原件"那一栏
    看到的就是这串码。这里断言的是端到端的那条路：转义送进来，人名读回去。
    """
    client, _ = stack_client()
    uploaded = upload(
        client,
        filename=quote("储能报告.txt", safe=""),
        title="储能报告",
        document_type="report",
    )
    assert uploaded.status_code == 201, uploaded.text
    version_id = publish(client, uploaded)
    document_id = uploaded.json()["document"]["document_id"]

    response = client.get(f"{DOCUMENTS}/{document_id}/versions/{version_id}/source")

    assert response.status_code == 200, response.text
    assert unquote(response.headers["x-research-filename"]) == "储能报告.txt"


def test_upload_of_an_empty_body_is_rejected_and_registers_nothing():
    client, stack = stack_client()
    response = upload(client, b"", title="空文件", document_type="report")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UPLOAD_EMPTY"
    assert stack.repository.list_documents() == ()


def test_upload_of_an_unknown_media_type_is_rejected_with_415():
    client, stack = stack_client()
    response = upload(
        client,
        b"a,b\n1,2\n",
        filename="table.csv",
        media_type="text/csv",
        title="表格",
        document_type="report",
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UPLOAD_UNSUPPORTED_TYPE"
    assert stack.repository.list_documents() == ()


def test_upload_of_a_pdf_that_is_not_a_pdf_is_rejected():
    """门禁看的是内容，不是名字：`.pdf` 里没有 `%PDF-` 就不是 PDF。"""
    client, _ = stack_client()
    response = upload(
        client,
        BODY.encode("utf-8"),
        filename="report.pdf",
        media_type="application/pdf",
        title="其实是文本",
        document_type="report",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UPLOAD_TYPE_MISMATCH"


def test_upload_over_the_limit_is_refused_before_anything_is_stored():
    client, stack = stack_client(max_upload_bytes=SMALL_UPLOAD_LIMIT)
    response = upload(
        client,
        b"x" * (SMALL_UPLOAD_LIMIT * 4),
        title="太大了",
        document_type="report",
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "UPLOAD_TOO_LARGE"
    assert stack.repository.list_documents() == ()


def test_a_flagged_file_is_quarantined_rather_than_silently_dropped():
    """被判定为恶意的上传：文件留在存储里作为隔离证据，但没有摄取任务。

    删掉它会让这件事变成"没有发生过"：谁在什么时候试过传什么，事后无从回答。
    """
    client, stack = stack_client()
    response = upload(
        client,
        BODY.encode("utf-8") + MALWARE_MARKER,
        title="可疑文件",
        document_type="report",
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UPLOAD_SCAN_FAILED"

    document_id = stack.repository.list_documents()[0].document_id
    version = stack.repository.list_versions(document_id)[0]
    assert version.status is DocumentVersionStatus.PROCESSING
    job_count = len(stack.repository.list_ingestion_jobs(document_id=document_id))
    assert job_count == 0, "a refused upload must not get an ingestion job"
    key = stack.repository.get_original_asset_key(version.document_version_id)
    assert key is not None and stack.assets.stat(key).scan_status is ScanStatus.INFECTED
    audit = {entry.action for entry in stack.repository.list_document_audit(document_id)}
    assert audit == {DocumentAuditAction.REGISTER_DOCUMENT, DocumentAuditAction.REFUSE_UPLOAD}


def test_replaying_an_upload_key_does_not_create_a_second_version():
    client, stack = stack_client()
    first = upload(
        client, title="储能行业 2026 年中期策略", document_type="report", upload_key="k1"
    )
    second = upload(
        client, title="储能行业 2026 年中期策略", document_type="report", upload_key="k1"
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert (
        second.json()["version"]["document_version_id"]
        == (first.json()["version"]["document_version_id"])
    )
    assert second.json()["scan_status"] is None, (
        "a replay has no new scan verdict; reporting NOT_SCANNED would claim it was never scanned"
    )
    document_id = first.json()["document"]["document_id"]
    assert len(stack.repository.list_ingestion_jobs(document_id=document_id)) == 1


def test_reusing_an_upload_key_for_other_content_is_a_conflict():
    client, _ = stack_client()
    upload(client, title="储能行业 2026 年中期策略", document_type="report", upload_key="k1")
    second = upload(
        client,
        BODY.encode("utf-8") + "补充说明\n".encode(),
        title="储能行业 2026 年中期策略",
        document_type="report",
        upload_key="k1",
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "UPLOAD_KEY_CONFLICT"


# --- 读取 ---


def test_document_detail_never_exposes_implementation_identifiers():
    client, _ = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    response = client.get(f"{DOCUMENTS}/{uploaded['document']['document_id']}")
    assert response.status_code == 200

    dump = response.text
    for leaked in ("index_generation", "original_file_hash", "embedding_model", "chunking_policy"):
        assert leaked not in dump, f"{leaked} describes how we did it, not what the document is"


def test_unknown_document_is_404():
    client, _ = stack_client()
    response = client.get(f"{DOCUMENTS}/doc_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_source_download_streams_the_original_with_its_hash():
    client, _ = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    version_id = uploaded["version"]["document_version_id"]
    document_id = uploaded["document"]["document_id"]

    response = client.get(f"{DOCUMENTS}/{document_id}/versions/{version_id}/source")
    assert response.status_code == 200
    assert response.content == BODY.encode("utf-8")
    assert response.headers["x-research-sha256"]
    assert unquote(response.headers["x-research-filename"]) == "report.txt"


def test_source_of_a_version_of_another_document_is_404():
    """版本 ID 不是跨文档的访问凭据。"""
    client, _ = stack_client()
    first = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    second = upload(client, title="另一份报告", document_type="report").json()

    response = client.get(
        f"{DOCUMENTS}/{first['document']['document_id']}/versions/"
        f"{second['version']['document_version_id']}/source"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VERSION_NOT_FOUND"


# --- 治理 ---


def test_source_weight_edit_lands_and_is_audited():
    client, stack = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    document_id = uploaded["document"]["document_id"]
    # 让这一刻与上传那一刻分开：审计的顺序保证只到时间戳为止，所以"最后一条"要先有时间差。
    stack.clock.advance(seconds=60)

    response = client.patch(
        f"{DOCUMENTS}/{document_id}/source-weight",
        json={"source_weight": "0.9", "actor": ACTOR},
    )
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["source_weight"]) == Decimal("0.9")
    assert stack.repository.get_document(document_id).source_weight == Decimal("0.9")
    audit = stack.repository.list_document_audit(document_id)[-1]
    assert audit.action is DocumentAuditAction.SET_SOURCE_WEIGHT
    assert audit.actor == ACTOR


def test_archive_takes_a_published_version_out_of_the_serving_set():
    client, stack = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report")
    version_id = publish(client, uploaded)
    document_id = uploaded.json()["document"]["document_id"]

    response = client.post(
        f"{DOCUMENTS}/{document_id}/versions/{version_id}/archive",
        json={"actor": ACTOR},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == DocumentVersionStatus.ARCHIVED.value
    assert stack.repository.get_document(document_id).current_version_id is None


def test_archiving_a_version_that_is_still_processing_is_a_conflict():
    """还没发布的版本不在服务集里，归档它不是"取消"，是一次说不清的请求。"""
    client, _ = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    response = client.post(
        f"{DOCUMENTS}/{uploaded['document']['document_id']}/versions/"
        f"{uploaded['version']['document_version_id']}/archive",
        json={"actor": ACTOR},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GOVERNANCE_REFUSED"


def test_soft_delete_hides_the_document_until_it_is_restored():
    client, stack = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    document_id = uploaded["document"]["document_id"]

    deleted = client.delete(f"{DOCUMENTS}/{document_id}", params={"actor": ACTOR})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["document"]["deleted_at"] is not None
    assert client.get(DOCUMENTS).json()["documents"] == []
    assert len(client.get(DOCUMENTS, params={"include_deleted": True}).json()["documents"]) == 1
    assert (
        stack.repository.load_version_statuses([uploaded["version"]["document_version_id"]]) == {}
    ), "a soft-deleted document's versions must stop being retrievable immediately"

    restored = client.post(f"{DOCUMENTS}/{document_id}/restore", json={"actor": ACTOR})
    assert restored.status_code == 200, restored.text
    assert restored.json()["deleted_at"] is None
    assert len(client.get(DOCUMENTS).json()["documents"]) == 1


def test_restoring_a_document_that_is_not_deleted_is_a_conflict():
    client, _ = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    response = client.post(
        f"{DOCUMENTS}/{uploaded['document']['document_id']}/restore", json={"actor": ACTOR}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GOVERNANCE_REFUSED"


def test_retry_requeues_a_failed_job_and_is_audited():
    client, stack = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    job_id = uploaded["job"]["job_id"]
    # 走上传路径是为了让文档、版本、任务三行都真实存在；失败态本身用一个"第二个 worker 已经
    # 把它判死"的快照摆出来，因为要测的是重试，不是失败。
    job = stack.repository.get_ingestion_job(job_id)
    assert job is not None
    stack.repository.save_ingestion_job(
        job.model_copy(
            update={
                "status": IngestionStatus.PERMANENT_FAILED,
                "failure_reason": "the parser rejected the file",
            }
        ),
        expected_status=job.status,
        expected_attempt=job.attempt_id,
    )
    stack.clock.advance(seconds=120)

    response = client.post(
        f"/api/research-library/ingestion-jobs/{job_id}/retry", json={"actor": ACTOR}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == IngestionStatus.RECEIVED.value
    assert response.json()["failure_reason"] is None
    audit = stack.repository.list_document_audit(uploaded["document"]["document_id"])[-1]
    assert audit.action is DocumentAuditAction.RETRY_INGESTION


def test_unknown_ingestion_job_is_404():
    client, _ = stack_client()
    response = client.post(
        "/api/research-library/ingestion-jobs/job_missing/run", json={"worker_id": WORKER}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INGESTION_JOB_NOT_FOUND"


def test_rebuild_reports_the_vectors_the_index_is_missing():
    client, stack = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report")
    version_id = publish(client, uploaded)
    document_id = uploaded.json()["document"]["document_id"]

    version = stack.repository.get_version(version_id)
    assert version.index_generation is not None
    indexed = [
        chunk.chunk_id
        for chunk in stack.repository.list_chunks(version_id)
        if chunk.parent_chunk_id is not None
    ]
    assert len(indexed) >= 2, "the fixture body must cut into more than one child chunk"
    stack.vector_index.delete_records(generation=version.index_generation, chunk_ids=indexed[:1])
    stack.clock.advance(seconds=180)

    response = client.post(
        f"{DOCUMENTS}/{document_id}/versions/{version_id}/rebuild",
        json={"actor": ACTOR},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["index_generation"] == version.index_generation
    assert body["present_count"] == body["expected_count"]
    assert body["missing_ids"] == []
    audit = stack.repository.list_document_audit(document_id)
    assert audit[-1].action is DocumentAuditAction.REBUILD_INDEX


def test_rebuilding_a_version_that_is_not_published_is_a_conflict():
    client, _ = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    response = client.post(
        f"{DOCUMENTS}/{uploaded['document']['document_id']}/versions/"
        f"{uploaded['version']['document_version_id']}/rebuild",
        json={"actor": ACTOR},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GOVERNANCE_REFUSED"


def test_a_deployment_without_a_scanner_reports_not_scanned():
    """没扫过就是没扫过：NOT_SCANNED 不会被伪装成干净。"""
    stack = null_scanner_stack()
    client = build_client(stack.services)
    response = upload(client, title="储能行业 2026 年中期策略", document_type="report")
    assert response.status_code == 201, response.text
    assert response.json()["scan_status"] == ScanStatus.NOT_SCANNED.value


# --- 治理端点不可由 Agent 触达 ---

#: 治理动词。任何一个出现在 Agent 能调用的工具名里，就意味着 A2 可以自己改语料。
GOVERNANCE_VERBS = (
    "upload",
    "archive",
    "delete",
    "restore",
    "purge",
    "reconcile",
    "rebuild",
    "source_weight",
)

AGENTS_PACKAGE = Path("backend/src/sector_pulse/infrastructure/agents")

#: Agent 侧不许导入的应用层模块。检索、冲突判定、证据接纳是它可以用的；命令与维护不是。
FORBIDDEN_AGENT_IMPORTS = (
    "sector_pulse.application.research_library.commands",
    "sector_pulse.application.research_library.maintenance",
    "sector_pulse.application.research_library.services",
)


#: 接上资料库之后 A2 多出来的那三件工具。**写死在这里**，不从生产常量反推：这份常量正是
#: 它要钉住的东西，`<=` 一类的关系式（`X ⊆ X ∪ Y`）对 `X` 取任何值都成立，包括空集。
RAG_TOOL_NAMES = frozenset(
    {
        "search_internal_research",
        "inspect_research_source",
        "accept_internal_evidence",
    }
)


def test_no_agent_tool_performs_a_governance_action():
    for name in RAG_BUSINESS_TOOL_NAMES:
        assert not any(verb in name for verb in GOVERNANCE_VERBS), (
            f"the agent-facing tool {name!r} reads like a governance action"
        )
    # 右边的三个名字是写死的，左边的常量是生产的那一份：少一件工具、多一件工具都会失败。
    # 用 `RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES == RAG_BUSINESS_TOOL_NAMES | …` 则不会
    # ——那个常量本身就是这么定义的，等式两边是同一个式子。
    assert RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES == (
        REQUIRED_BUSINESS_TOOL_NAMES | RAG_TOOL_NAMES
    )


def test_agent_modules_never_import_the_governance_layer():
    """静态的导入图检查：A2 的包里根本没有治理层可调。

    这是"没有 Agent 可触达的治理端点"在代码层面的那一半；另一半是每个治理端点都要一个
    执行者名字（下一条测试），而 Agent 没有人名可填。
    """
    offenders: list[str] = []
    for path in sorted(AGENTS_PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_AGENT_IMPORTS:
                offenders.append(f"{path.name} imports {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_AGENT_IMPORTS:
                        offenders.append(f"{path.name} imports {alias.name}")
    assert offenders == [], (
        "the agent package must not be able to reach the research library's governance layer: "
        + ", ".join(offenders)
    )


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", DOCUMENTS, {"title": "x", "document_type": "report"}),
        ("patch", f"{DOCUMENTS}/doc_1/source-weight", {"source_weight": "0.5"}),
        ("post", f"{DOCUMENTS}/doc_1/versions/docv_1/archive", {}),
        ("post", f"{DOCUMENTS}/doc_1/restore", {}),
        ("post", f"{DOCUMENTS}/doc_1/versions/docv_1/rebuild", {}),
        ("post", "/api/research-library/ingestion-jobs/job_1/retry", {}),
        ("post", f"{MAINTENANCE}/purge", {"limit": 10}),
    ],
)
def test_every_governance_action_names_who_performed_it(method: str, path: str, payload: dict):
    client, _ = stack_client()
    response = getattr(client, method)(path, json=payload)
    assert response.status_code == 422, (
        f"{method.upper()} {path} accepted a governance action without naming its actor"
    )


def test_delete_requires_a_named_actor_in_the_query():
    client, _ = stack_client()
    assert client.delete(f"{DOCUMENTS}/doc_1").status_code == 422


def test_upload_without_an_actor_is_rejected():
    client, _ = stack_client()
    response = client.post(
        UPLOADS,
        content=BODY.encode("utf-8"),
        params={"target": "new_document", "title": "x", "document_type": "report"},
        headers={"content-type": "text/plain", "x-research-filename": "report.txt"},
    )
    assert response.status_code == 422


def test_repairing_the_index_without_an_actor_is_rejected():
    client, _ = stack_client()
    response = client.post(f"{MAINTENANCE}/reconcile", json={"repair": True})
    assert response.status_code == 422
    assert client.post(f"{MAINTENANCE}/reconcile", json={}).status_code == 200


# --- 维护视图 ---


def test_the_maintenance_report_is_read_only():
    """GET 不带 repair：它报告不一致，但一个不一致都不动手修。"""
    client, stack = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report")
    version_id = publish(client, uploaded)
    version = stack.repository.get_version(version_id)
    assert version.index_generation is not None
    indexed = {
        chunk.chunk_id
        for chunk in stack.repository.list_chunks(version_id)
        if chunk.parent_chunk_id is not None
    }
    dropped = sorted(indexed)[0]
    stack.vector_index.delete_records(generation=version.index_generation, chunk_ids=[dropped])

    response = client.get(MAINTENANCE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["consistent"] is False
    assert body["repaired"] is False
    assert body["orphans_removed"] == 0
    assert body["index_gaps"][0]["document_version_id"] == version_id
    assert body["index_gaps"][0]["missing_ids"] == [dropped]
    # 报告是只读的：那个缺口还在原处。
    assert set(
        stack.vector_index.verify(
            generation=version.index_generation, expected_ids=frozenset(indexed)
        ).missing_ids
    ) == {dropped}


def test_purging_before_the_retention_window_is_empty_and_names_the_actor():
    client, _ = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report").json()
    document_id = uploaded["document"]["document_id"]
    client.delete(f"{DOCUMENTS}/{document_id}", params={"actor": ACTOR})

    response = client.post(f"{MAINTENANCE}/purge", json={"actor": ACTOR, "limit": 10})
    assert response.status_code == 200, response.text
    assert response.json()["purged"] == []


def test_a_blank_actor_on_purge_is_refused_instead_of_becoming_a_server_error():
    """空名字要被拒绝，而且是以 4xx 的形式。

    同一条规则在 `commands._require_actor` 里报的是 `GovernanceRefused`（→409），维护这一侧
    却抛裸 `ValueError`，于是同一个错误在两处是两种状态码。客户端看到 500 会以为"服务端坏了，
    重试也许有用"（`retryable=true`），而它其实只是没有把名字给对。
    """
    client, _ = stack_client()

    response = client.post(f"{MAINTENANCE}/purge", json={"actor": "   ", "limit": 10})

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "GOVERNANCE_REFUSED"
    assert response.json()["error"]["retryable"] is False


def test_the_repair_guard_refuses_a_blank_actor_at_the_service_layer_too():
    """请求模型已经拦了一次，服务层不能只剩下裸 `ValueError`。

    直接调服务的调用方（脚本、定时任务）不经过 pydantic，拿到的必须是同一个治理拒绝，
    否则同一个规则会分裂成"HTTP 入口守得住、别的入口守不住"。
    """
    _, stack = stack_client()

    with pytest.raises(GovernanceRefused):
        stack.maintenance.reconcile(repair=True, actor="   ")


def test_maintenance_reports_an_unreachable_index_as_unavailable_not_as_a_crash(monkeypatch):
    """派生索引连不上要报 503，而不是 500。

    `_STATUS_BY_ERROR` 一直写着 `(VectorIndexError, 503)`，但它从来没有生效过：`_governed`
    接的是 `ResearchLibraryCommandError`，而 `VectorIndexError` 是 `RuntimeError` 的另一支。
    于是每一个端点上的"索引连不上"都绕过那张表，落到通用处理器变成 500——运维看到的是
    "服务端代码出错"，而正确处置是"等索引恢复"。
    """

    def refuse(**_: object) -> None:
        raise VectorIndexError("milvus is not reachable")

    client, stack = stack_client()
    # 先让核对真的走到索引：没有发布过的版本时 `reconcile` 一个 generation 都不会查，
    # 那样这条断言测的是"空的核对也是 200"。
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report")
    publish(client, uploaded)
    monkeypatch.setattr(stack.vector_index, "verify", refuse)

    response = client.get(MAINTENANCE)

    assert response.status_code == 503, response.text
    assert response.json()["error"]["retryable"] is True


def test_the_maintenance_report_never_hands_the_browser_a_storage_key():
    """维护报告要说清"哪一项对不上"，但不必说出它在对象存储里的键。

    `object_key` 是服务端派生的存储标识：`commands.source` 一路都在避免把它交给调用方，
    下载走的是按文档/版本查出来的键，而不是调用方递进来的键。维护接口曾经把每一条对账差异
    的键原样返回，于是这条规则在唯一一个"只读的运维接口"上开了口子。
    """
    assert "object_key" not in AssetDiscrepancyResponse.model_fields
    assert "object_key" not in MaintenanceResponse.model_fields


def test_the_maintenance_payload_carries_no_storage_addresses_or_credentials():
    """把整份响应的键名扫一遍：字段是后面加的，规则要能挡住后面加的那个。"""
    client, _ = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report")
    publish(client, uploaded)

    payload = client.get(MAINTENANCE).json()

    forbidden = ("object_key", "bucket", "endpoint", "secret", "access_key", "s3://")
    keys: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                keys.append(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    assert keys, "the maintenance payload must have been scanned, not assumed empty"
    assert not [key for key in keys if any(word in key.lower() for word in forbidden)]


def test_the_outbox_route_reports_the_events_it_settled():
    client, _ = stack_client()
    # 先发布：一个从未进过索引的版本没有"要删的那一代"，软删除时也就没有意图可登记。
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report")
    publish(client, uploaded)
    document_id = uploaded.json()["document"]["document_id"]
    client.delete(f"{DOCUMENTS}/{document_id}", params={"actor": ACTOR})

    response = client.post(f"{MAINTENANCE}/outbox", json={"worker_id": WORKER, "limit": 10})
    assert response.status_code == 200, response.text
    assert response.json()["events"], "a soft delete queues a delete intent for the derived index"


def test_purge_after_the_retention_window_removes_the_chunks_and_the_audit_survives():
    client, stack = stack_client()
    uploaded = upload(client, title="储能行业 2026 年中期策略", document_type="report")
    version_id = publish(client, uploaded)
    document_id = uploaded.json()["document"]["document_id"]
    assert stack.repository.list_chunks(version_id)

    client.delete(f"{DOCUMENTS}/{document_id}", params={"actor": ACTOR})
    stack.clock.now = datetime(2030, 1, 1, tzinfo=UTC)

    response = client.post(f"{MAINTENANCE}/purge", json={"actor": ACTOR, "limit": 10})
    assert response.status_code == 200, response.text
    assert response.json()["purged"] == [document_id]
    assert stack.repository.list_chunks(version_id) == ()
    assert stack.repository.get_version(version_id).status is DocumentVersionStatus.PURGED
    assert [entry.action for entry in stack.repository.list_document_audit(document_id)][-1] is (
        DocumentAuditAction.PURGE
    )
