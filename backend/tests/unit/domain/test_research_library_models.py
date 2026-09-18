"""Domain contract for the internal research library value models.

Every assertion here maps to a spec rule: a claim or chunk without a resolvable
locator, a status invented by mixing enums, or a naive timestamp must not be
constructible at all.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError
from sector_pulse.domain.research_library.models import (
    ChunkEmbeddingStatus,
    DocumentBlock,
    DocumentVersionStatus,
    IndexState,
    ResearchChunk,
    ResearchDocument,
    ResearchDocumentVersion,
)
from sector_pulse.domain.research_library.retrieval import (
    ClaimStance,
    ConflictDecision,
    ConflictRule,
    ConflictStatus,
    ExtractedClaim,
    RetrievalQuery,
)

from backend.tests.research_library_support import (
    CHUNK_PAYLOAD,
    block_payload,
    chunk_payload,
    document_payload,
    version_payload,
)


def test_active_chunk_keeps_exact_source_locator():
    chunk = ResearchChunk.model_validate(CHUNK_PAYLOAD)
    assert chunk.source.page_start == 18
    assert chunk.source.bounding_boxes[0] == (72.0, 96.0, 520.0, 238.0)


def test_chunk_records_lineage_from_document_to_character_span():
    chunk = ResearchChunk.model_validate(CHUNK_PAYLOAD)
    assert chunk.document_id == "doc_12"
    assert chunk.document_version_id == "docv_42"
    assert chunk.parent_chunk_id == "chunk_parent_1"
    assert chunk.source.section_path == ("第三章 行业跟踪", "3.2 海外需求")
    assert chunk.source.block_ids == ("blk_9", "blk_10")
    assert chunk.source.spans[0].start == 0
    assert chunk.embedding_status is ChunkEmbeddingStatus.PENDING


def test_chunk_is_immutable():
    chunk = ResearchChunk.model_validate(CHUNK_PAYLOAD)
    with pytest.raises(ValidationError):
        chunk.content = "被改写的正文"


@pytest.mark.parametrize("content", ["", "   ", "\n\t "])
def test_chunk_rejects_blank_content(content):
    with pytest.raises(ValidationError, match="content"):
        ResearchChunk.model_validate(chunk_payload(content=content))


def test_chunk_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ResearchChunk.model_validate(chunk_payload(top_k=99))


def test_chunk_rejects_source_span_outside_content():
    source = {**CHUNK_PAYLOAD["source"], "spans": [{"start": 0, "end": 9999}]}
    with pytest.raises(ValidationError, match="span"):
        ResearchChunk.model_validate(chunk_payload(source=source))


def test_chunk_rejects_reversed_page_range():
    payload = chunk_payload(source={**CHUNK_PAYLOAD["source"], "page_start": 20, "page_end": 18})
    with pytest.raises(ValidationError, match="page"):
        ResearchChunk.model_validate(payload)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2])
def test_chunk_rejects_confidence_outside_unit_interval(confidence):
    with pytest.raises(ValidationError, match="confidence"):
        ResearchChunk.model_validate(chunk_payload(confidence=confidence))


def test_chunk_requires_some_source_lineage():
    """Page, section or block lineage is mandatory; a chunk with none is unusable."""
    payload = chunk_payload(
        source={
            "page_start": None,
            "page_end": None,
            "section_path": [],
            "block_ids": [],
            "spans": [],
            "bounding_boxes": [],
        }
    )
    with pytest.raises(ValidationError, match="lineage"):
        ResearchChunk.model_validate(payload)


def test_chunk_rejects_naive_created_at():
    with pytest.raises(ValidationError):
        ResearchChunk.model_validate(chunk_payload(created_at="2026-09-18T02:00:00"))


def test_chunk_rejects_unknown_content_origin():
    with pytest.raises(ValidationError):
        ResearchChunk.model_validate(chunk_payload(content_origin="guesswork"))


def test_ocr_derived_chunk_must_declare_its_extraction_confidence():
    chunk = ResearchChunk.model_validate(
        chunk_payload(content_origin="ocr", confidence=0.71, requires_verification=True)
    )
    assert chunk.content_origin == "ocr"
    assert chunk.requires_verification is True


def test_document_block_carries_layout_and_extraction_provenance():
    block = DocumentBlock.model_validate(block_payload())
    assert block.block_type == "paragraph"
    assert block.heading_path == ("第三章 行业跟踪", "3.2 海外需求")
    assert block.bounding_box == (72.0, 96.0, 520.0, 238.0)
    assert block.extraction_method == "native"


@pytest.mark.parametrize("block_type", ["heading", "paragraph", "table", "code"])
def test_textual_blocks_reject_blank_text(block_type):
    with pytest.raises(ValidationError, match="text"):
        DocumentBlock.model_validate(block_payload(block_type=block_type, text="  "))


@pytest.mark.parametrize("block_type", ["image", "chart"])
def test_picture_blocks_may_have_no_text_of_their_own(block_type):
    """An uncaptioned image is still a located block; it just is not indexable."""
    block = DocumentBlock.model_validate(block_payload(block_type=block_type, text=""))
    assert block.text == ""


def test_document_block_rejects_reversed_page_range():
    with pytest.raises(ValidationError, match="page"):
        DocumentBlock.model_validate(block_payload(page_number=18, page_end=17))


def test_document_defaults_to_global_visibility_with_no_deletion():
    document = ResearchDocument.model_validate(document_payload())
    assert document.visibility_scope == "GLOBAL"
    assert document.source_weight == Decimal("0.8")
    assert document.deleted_at is None
    assert document.purge_after is None


def test_document_rejects_purge_schedule_without_deletion():
    with pytest.raises(ValidationError, match="purge_after"):
        ResearchDocument.model_validate(
            document_payload(deleted_at=None, purge_after="2026-10-18T00:00:00+00:00")
        )


def test_document_rejects_offset_free_timestamps():
    with pytest.raises(ValidationError):
        ResearchDocument.model_validate(document_payload(created_at="2026-09-17T09:30:00"))


def test_published_is_not_a_document_version_status():
    """Spec 7.2: ingestion, version and index state are three separate enums."""
    assert "PUBLISHED" not in {status.value for status in DocumentVersionStatus}
    assert "PUBLISHED" in {state.value for state in IndexState}
    assert "ACTIVE" not in {state.value for state in IndexState}
    assert "STAGED" not in {status.value for status in DocumentVersionStatus}


def test_version_status_rejects_index_state_value():
    with pytest.raises(ValidationError):
        ResearchDocumentVersion.model_validate(version_payload(status="STAGED"))


def test_active_version_must_record_the_generation_it_was_published_from():
    with pytest.raises(ValidationError, match="index_generation"):
        ResearchDocumentVersion.model_validate(
            version_payload(index_generation=None, indexed_at=None)
        )


def test_processing_version_may_have_no_generation_yet():
    version = ResearchDocumentVersion.model_validate(
        version_payload(status="PROCESSING", index_generation=None, indexed_at=None)
    )
    assert version.status is DocumentVersionStatus.PROCESSING


def test_version_rejects_effective_window_inversion():
    with pytest.raises(ValidationError, match="effective"):
        ResearchDocumentVersion.model_validate(
            version_payload(
                effective_from="2026-09-10T00:00:00+00:00",
                effective_to="2026-08-10T00:00:00+00:00",
            )
        )


def test_claim_requires_an_exact_source_span_into_a_chunk():
    claim = ExtractedClaim.model_validate(
        {
            "claim_id": "claim_runtime_01",
            "statement": "海外储能订单在 2026 年第二季度明显增长",
            "subject": "海外储能订单",
            "predicate": "增长情况",
            "object": "明显增长",
            "qualifiers": ["第二季度"],
            "source_chunk_id": "chunk_123",
            "source_span": {"start": 0, "end": 12},
            "extraction_confidence": 0.91,
        }
    )
    assert claim.source_chunk_id == "chunk_123"
    assert claim.source_span.end == 12
    assert claim.stance is ClaimStance.SUPPORTING


def test_query_time_window_accepts_the_documented_from_to_keys():
    query = RetrievalQuery.model_validate(
        {
            "question": "储能板块近期上涨是否与海外需求改善有关？",
            "sector": "储能",
            "time_range": {"from": "2026-01-01", "to": "2026-09-17"},
            "document_types": ["report", "historical_article"],
        }
    )
    assert query.time_range is not None
    assert query.time_range.start.isoformat() == "2026-01-01"
    assert query.include_unverified_leads is False


def test_query_rejects_a_caller_supplied_top_k():
    """Spec 11.1: the Agent cannot widen recall; limits come from configuration."""
    with pytest.raises(ValidationError):
        RetrievalQuery.model_validate({"question": "储能趋势", "top_k": 500})


def test_query_rejects_reversed_time_window():
    with pytest.raises(ValidationError, match="time_range"):
        RetrievalQuery.model_validate(
            {
                "question": "储能趋势",
                "time_range": {"from": "2026-09-17", "to": "2026-01-01"},
            }
        )


def test_unresolved_conflict_must_keep_both_sources_and_select_nothing():
    decision = ConflictDecision.model_validate(
        {
            "status": "UNRESOLVED",
            "claim_ids": ("claim_a", "claim_b"),
            "rule": None,
            "selected_claim_id": None,
        }
    )
    assert decision.status is ConflictStatus.UNRESOLVED
    assert len(decision.claim_ids) == 2


def test_unresolved_conflict_cannot_silently_pick_a_winner():
    with pytest.raises(ValidationError, match="UNRESOLVED"):
        ConflictDecision.model_validate(
            {
                "status": "UNRESOLVED",
                "claim_ids": ("claim_a", "claim_b"),
                "selected_claim_id": "claim_a",
            }
        )


def test_resolved_conflict_must_name_the_rule_and_the_kept_claim():
    with pytest.raises(ValidationError, match="RESOLVED"):
        ConflictDecision.model_validate(
            {"status": "RESOLVED", "claim_ids": ("claim_a", "claim_b"), "rule": "STATUS"}
        )
    decision = ConflictDecision.model_validate(
        {
            "status": "RESOLVED",
            "claim_ids": ("claim_a", "claim_b"),
            "rule": "STATUS",
            "selected_claim_id": "claim_a",
        }
    )
    assert decision.rule is ConflictRule.STATUS


def test_resolved_conflict_cannot_select_outside_its_own_group():
    with pytest.raises(ValidationError, match="claim_ids"):
        ConflictDecision.model_validate(
            {
                "status": "RESOLVED",
                "claim_ids": ("claim_a", "claim_b"),
                "rule": "SOURCE_WEIGHT",
                "selected_claim_id": "claim_elsewhere",
            }
        )


def test_check_failed_records_that_no_conflict_verdict_was_reached():
    decision = ConflictDecision.model_validate(
        {"status": "CHECK_FAILED", "claim_ids": ("claim_a", "claim_b")}
    )
    assert decision.selected_claim_id is None
