"""Canonical payload builders for internal research library tests.

Deliberately dict-only and free of domain imports: a test that consumes these must
fail on the missing production model, never on a missing helper import.

The values encode the locator contract the spec demands — document, version, chunk,
page, section, block and character span all present at once — so a model that drops
any one of them cannot silently validate.
"""

from datetime import UTC, datetime

NOW = datetime(2026, 9, 18, 2, 0, 0, tzinfo=UTC)
UPLOADED_AT = datetime(2026, 9, 17, 9, 30, 0, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 9, 10, 0, 0, 0, tzinfo=UTC)

CHUNK_TEXT = "海外储能订单在 2026 年第二季度明显增长，二季度新增订单同比翻倍。"

CHUNK_PAYLOAD: dict[str, object] = {
    "chunk_id": "chunk_123",
    "document_id": "doc_12",
    "document_version_id": "docv_42",
    "parent_chunk_id": "chunk_parent_1",
    "chunk_type": "text",
    "content": CHUNK_TEXT,
    "content_hash": "blake3:8f14e45fceea167a5a36dedd4bea2543",
    "source": {
        "page_start": 18,
        "page_end": 18,
        "section_path": ["第三章 行业跟踪", "3.2 海外需求"],
        "block_ids": ["blk_9", "blk_10"],
        "spans": [{"start": 0, "end": 12}],
        "bounding_boxes": [[72.0, 96.0, 520.0, 238.0]],
    },
    "content_origin": "native",
    "confidence": 0.98,
    "requires_verification": False,
    "embedding_status": "pending",
    "created_at": NOW.isoformat(),
}


def chunk_payload(**overrides: object) -> dict[str, object]:
    source = CHUNK_PAYLOAD["source"]
    assert isinstance(source, dict)
    return {**CHUNK_PAYLOAD, "source": {**source}, **overrides}


DOCUMENT_PAYLOAD: dict[str, object] = {
    "document_id": "doc_12",
    "title": "2026 年储能行业中期策略",
    "document_type": "report",
    "author": "研究部",
    "institution": "SectorPulse Research",
    "source_weight": "0.8",
    "current_version_id": "docv_42",
    "visibility_scope": "GLOBAL",
    "owner_id": "user_1",
    "access_tags": ["energy-storage"],
    "created_at": UPLOADED_AT.isoformat(),
    "deleted_at": None,
    "purge_after": None,
}


def document_payload(**overrides: object) -> dict[str, object]:
    return {**DOCUMENT_PAYLOAD, **overrides}


VERSION_PAYLOAD: dict[str, object] = {
    "document_version_id": "docv_42",
    "document_id": "doc_12",
    "version_number": 1,
    "status": "ACTIVE",
    "published_at": PUBLISHED_AT.isoformat(),
    "effective_from": PUBLISHED_AT.isoformat(),
    "effective_to": None,
    "uploaded_at": UPLOADED_AT.isoformat(),
    "original_file_hash": "sha256:" + "0" * 64,
    "parser_version": "pdf-native-v1",
    "chunking_policy_version": "structural-v1",
    "ocr_provider": None,
    "ocr_model_version": None,
    "embedding_provider": "openai-compatible",
    "embedding_model_version": "text-embedding-fixture",
    "index_generation": "gen_1",
    "expected_chunk_count": 120,
    "indexed_at": NOW.isoformat(),
}


def version_payload(**overrides: object) -> dict[str, object]:
    return {**VERSION_PAYLOAD, **overrides}


JOB_PAYLOAD: dict[str, object] = {
    "job_id": "job_7",
    "document_id": "doc_12",
    "document_version_id": "docv_42",
    "status": "RECEIVED",
    "attempt_id": 0,
    "worker_id": None,
    "lease_expires_at": None,
    "max_attempts": 3,
    "failure_reason": None,
    "created_at": UPLOADED_AT.isoformat(),
    "updated_at": UPLOADED_AT.isoformat(),
}


def job_payload(**overrides: object) -> dict[str, object]:
    return {**JOB_PAYLOAD, **overrides}


BLOCK_PAYLOAD: dict[str, object] = {
    "block_id": "blk_9",
    "block_type": "paragraph",
    "text": CHUNK_TEXT,
    "heading_path": ["第三章 行业跟踪", "3.2 海外需求"],
    "page_number": 18,
    "block_order": 12,
    "bounding_box": [72.0, 96.0, 520.0, 238.0],
    "extraction_method": "native",
    "extraction_confidence": 0.99,
    "source_asset_ref": "pages/doc_12/docv_42/page-018.png",
}


def block_payload(**overrides: object) -> dict[str, object]:
    return {**BLOCK_PAYLOAD, **overrides}


CLAIM_PAYLOAD: dict[str, object] = {
    "claim_id": "claim_runtime_01",
    "statement": "海外储能订单在 2026 年第二季度明显增长",
    "subject": "海外储能订单",
    "predicate": "增长情况",
    "object": "明显增长",
    "valid_time": {"from": "2026-04-01", "to": "2026-06-30"},
    "qualifiers": ["第二季度"],
    "source_chunk_id": "chunk_123",
    "source_span": {"start": 0, "end": 12},
    "extraction_confidence": 0.91,
}


def claim_payload(**overrides: object) -> dict[str, object]:
    return {**CLAIM_PAYLOAD, **overrides}
