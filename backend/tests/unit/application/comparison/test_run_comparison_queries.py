from decimal import Decimal

import pytest
from sector_pulse.application.comparison.run_comparison_queries import RunComparisonQueries
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.runs.real_data_run import RealDataCandidate, RealDataRunStatus
from sector_pulse.storage.runtime_bundle import build_sqlite_storage
from sector_pulse.storage.sqlite.database import SQLiteDatabase

from backend.tests.comparison_fixtures import save_snapshot, seed_news, seed_pair


@pytest.fixture
def comparison(tmp_path):
    storage = build_sqlite_storage(SQLiteDatabase(tmp_path / "queries.sqlite"))
    base, other = seed_pair(storage)
    return storage, RunComparisonQueries(storage), base.run_id, other.run_id


def test_rank_candidate_union_and_kind_groups(comparison) -> None:
    _, queries, base, other = comparison
    result = queries.compare(base, other)
    assert result.candidates.model_dump() == {
        "both": 2,
        "only_base": 1,
        "only_compare": 1,
        "unavailable_kinds": 0,
    }
    industry = next(group for group in result.kinds if group.kind == SectorKind.INDUSTRY)
    concept = next(group for group in result.kinds if group.kind == SectorKind.CONCEPT)
    assert [row.sector_id for row in industry.rows] == ["003", "001", "002"]
    common = industry.rows[1]
    assert common.rank_delta == 3
    assert common.pct_change.delta == Decimal("0.10")
    assert common.advancers.base == Decimal("0")
    assert common.turnover_rate.delta is None
    assert common.turnover_rate.base_reason == "VALUE_MISSING"
    assert "score_delta" not in common.model_dump()
    assert concept.rows[0].rank_delta == -3
    assert industry.rows[0].base_rank is None
    assert industry.rows[0].pct_change.base == Decimal("0")
    reversed_result = queries.compare(other, base)
    assert "REVERSED_TIME" in {warning.code for warning in reversed_result.warnings}


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("classification_version", "other", "INCOMPATIBLE"),
        ("provider_id", "other-source", "INCOMPATIBLE"),
        ("classification_version", "", "INCOMPATIBLE"),
        ("source_version", "next", "COMPARABLE"),
    ],
)
def test_snapshot_compatibility(comparison, field, value, status) -> None:
    storage, queries, base, other = comparison
    snapshot = storage.market_snapshots.get(other, SectorKind.INDUSTRY)
    save_snapshot(storage, other, snapshot.model_copy(update={field: value}))
    result = queries.compare(base, other)
    group = next(item for item in result.kinds if item.kind == SectorKind.INDUSTRY)
    assert group.status == status
    if status == "INCOMPATIBLE":
        assert group.rows == []
        assert result.candidates.only_base == result.candidates.only_compare == 0
        assert result.candidates.unavailable_kinds == 1
    else:
        assert "SOURCE_VERSION_DIFF" in {item.code for item in result.warnings}


def test_undeclared_defaults_and_failed_run_remain_explainable(comparison) -> None:
    storage, queries, base, other = comparison
    snapshot = storage.market_snapshots.get(base, SectorKind.INDUSTRY)
    save_snapshot(storage, base, snapshot.model_copy(update={"available_fields": frozenset()}))
    storage.real_data_runs.update_status(base, RealDataRunStatus.FAILED)
    result = queries.compare(base, other)
    row = next(group for group in result.kinds if group.kind == SectorKind.INDUSTRY).rows[1]
    assert row.pct_change.base is None
    assert row.advancers.base is None
    assert row.advancers.base_reason == "FIELD_UNDECLARED"
    assert {"RUN_PARTIAL", "CUTOFF_MISSING", "FIELD_SCHEMA_UNKNOWN"} <= {
        item.code for item in result.warnings
    }


def test_current_metadata_updates_do_not_change_saved_membership(comparison) -> None:
    storage, queries, base, other = comparison
    ids, _ = seed_news(storage, base, other)
    doc = storage.news.get_documents([ids[1]])[ids[1]]
    storage.news.save([doc.model_copy(update={"title": "后来更新的标题"})], ())
    result = queries.news(base, other)
    assert result.counts.model_dump() == {"both": 1, "only_base": 1, "only_compare": 1}
    assert [item.membership for item in result.items] == ["ONLY_BASE", "BOTH", "ONLY_COMPARE"]
    assert result.items[0].metadata.citation_url is None
    assert result.items[1].metadata.title == "后来更新的标题"
    assert result.items[1].metadata.metadata_scope == "CURRENT_STORED"


def test_missing_lineage_never_uses_current_event_documents(comparison) -> None:
    storage, queries, base, other = comparison
    seed_news(storage, base, other, lineage=False)
    result = queries.news(base, other)
    assert not result.available
    assert result.total is None and result.counts is None and result.items == []
    assert result.base_news.lineage == "UNVERIFIABLE"
    assert queries.compare(base, other).news_counts is None
    assert len(queries.evidence(base, other).items) == 2


def test_pagination_counts_members_before_loading_metadata(comparison, monkeypatch) -> None:
    storage, queries, base, other = comparison
    ids, _ = seed_news(storage, base, other, count=202)
    original = storage.news.get_documents
    requested = []

    def missing_first(keys):
        requested.extend(keys)
        result = original(keys)
        result.pop(ids[0], None)
        return result

    monkeypatch.setattr(storage.news, "get_documents", missing_first)
    page = queries.news(base, other, limit=20)
    assert page.total == 202
    assert page.counts.both == 200
    assert requested == ids[:20]
    assert page.items[0].document_id == ids[0]
    assert page.items[0].metadata is None
    assert queries.news(base, other, membership="ONLY_COMPARE").items[0].document_id == ids[-1]


def test_evidence_preserves_saved_kind_and_mapping(comparison) -> None:
    storage, queries, base, other = comparison
    _, event = seed_news(storage, base, other)
    page = queries.evidence(base, other)
    assert page.total == 2
    assert page.items[0].kind == SectorKind.CONCEPT
    assert page.items[0].membership == "ONLY_BASE"
    assert page.items[0].compare is None
    row = page.items[1]
    assert row.event_id == event
    assert row.base.mapping_reason == "saved-0-INDUSTRY"
    assert row.compare.mapping_reason == "saved-1-INDUSTRY"
    assert queries.evidence(base, other, kind=SectorKind.INDUSTRY, sector_id="001").total == 1
    assert (
        queries.evidence(base, other, kind=SectorKind.INDUSTRY, sector_id="not-candidate").total
        == 0
    )


def test_same_code_in_different_run_kinds_is_not_a_shared_candidate(comparison) -> None:
    storage, queries, base, other = comparison
    storage.real_data_runs.save_candidates(
        base,
        (
            RealDataCandidate(
                sector_id="001",
                sector_kind=SectorKind.INDUSTRY,
                rank=1,
                score=Decimal("0.50"),
                reasons=(),
            ),
        ),
    )
    storage.real_data_runs.save_candidates(
        other,
        (
            RealDataCandidate(
                sector_id="001",
                sector_kind=SectorKind.CONCEPT,
                rank=1,
                score=Decimal("0.70"),
                reasons=(),
            ),
        ),
    )
    result = queries.compare(base, other)
    assert result.candidates.both == 0
    assert result.candidates.only_base == result.candidates.only_compare == 1
    assert all(row.rank_delta is None for group in result.kinds for row in group.rows)
