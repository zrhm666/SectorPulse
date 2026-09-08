import hashlib

import pytest
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.runs.real_data_run import RealDataRunStatus
from sector_pulse.storage.runtime_bundle import build_postgres_storage
from sqlalchemy import inspect

from backend.tests.comparison_fixtures import save_snapshot, seed_news, seed_pair
from backend.tests.comparison_support import (
    comparison_postgres as comparison_postgres_fixture,  # noqa: F401
)
from backend.tests.integration.test_run_comparison_api import comparison_client

pytestmark = pytest.mark.postgres


def database_fingerprint(database) -> str:
    engine = database.start()
    quote = engine.dialect.identifier_preparer.quote
    records = []
    with engine.connect() as connection:
        for table in sorted(inspect(connection).get_table_names(schema="public")):
            rows = (
                connection.exec_driver_sql(
                    f"SELECT row_to_json(t)::text FROM public.{quote(table)} t "
                    "ORDER BY row_to_json(t)::text"
                )
                .scalars()
                .all()
            )
            records.append((table, rows))
    return hashlib.sha256(repr(records).encode()).hexdigest()


def test_postgres_comparison_http_is_read_only_and_preserves_decimals(comparison_postgres) -> None:
    storage = build_postgres_storage(comparison_postgres)
    base, other = seed_pair(storage)
    ids, _ = seed_news(storage, base.run_id, other.run_id)
    doc = storage.news.get_documents([ids[1]])[ids[1]]
    storage.news.save([doc.model_copy(update={"title": "更新后的当前标题"})], ())
    client = comparison_client(storage)
    before = database_fingerprint(comparison_postgres)
    params = {"base_run_id": str(base.run_id), "compare_run_id": str(other.run_id)}
    result = client.get("/api/run-comparisons", params=params)
    assert result.status_code == 200
    body = result.json()
    assert body["candidates"] == {
        "both": 2,
        "only_base": 1,
        "only_compare": 1,
        "unavailable_kinds": 0,
    }
    row = body["kinds"][0]["rows"][1]
    assert row["pct_change"]["base"] == "0"
    assert row["pct_change"]["delta"] == "0.10"
    assert row["rank_delta"] == 3
    news = client.get("/api/run-comparisons/news", params={**params, "limit": 1, "offset": 1})
    assert news.status_code == 200
    assert news.json()["total"] == 3
    assert news.json()["counts"] == {"both": 1, "only_base": 1, "only_compare": 1}
    assert news.json()["items"][0]["metadata"]["title"] == "更新后的当前标题"
    evidence = client.get("/api/run-comparisons/evidence", params=params)
    assert evidence.status_code == 200 and evidence.json()["total"] == 2
    listing = client.get("/api/run-comparisons/runs", params={"provider": "fixture", "limit": 100})
    assert listing.status_code == 200
    assert database_fingerprint(comparison_postgres) == before


def test_postgres_partial_run_missing_lineage_and_incompatible_snapshot(
    comparison_postgres,
) -> None:
    storage = build_postgres_storage(comparison_postgres)
    base, other = seed_pair(storage)
    storage.real_data_runs.update_status(base.run_id, RealDataRunStatus.FAILED)
    snapshot = storage.market_snapshots.get(other.run_id, SectorKind.INDUSTRY)
    save_snapshot(
        storage, other.run_id, snapshot.model_copy(update={"classification_version": "other"})
    )
    client = comparison_client(storage)
    before = database_fingerprint(comparison_postgres)
    params = {"base_run_id": str(base.run_id), "compare_run_id": str(other.run_id)}
    response = client.get("/api/run-comparisons", params=params)
    assert response.status_code == 200
    body = response.json()
    industry = next(group for group in body["kinds"] if group["kind"] == "INDUSTRY")
    assert industry["status"] == "INCOMPATIBLE" and industry["rows"] == []
    assert {"RUN_PARTIAL", "NEWS_LINEAGE_UNVERIFIABLE"} <= {
        item["code"] for item in body["warnings"]
    }
    assert body["news_counts"] is None
    news = client.get("/api/run-comparisons/news", params=params).json()
    assert news["available"] is False and news["total"] is None
    evidence = client.get("/api/run-comparisons/evidence", params=params).json()
    assert evidence["unavailable_kinds"] == ["INDUSTRY"]
    assert database_fingerprint(comparison_postgres) == before


def test_postgres_missing_metadata_retains_member_id(comparison_postgres, monkeypatch) -> None:
    storage = build_postgres_storage(comparison_postgres)
    base, other = seed_pair(storage)
    ids, _ = seed_news(storage, base.run_id, other.run_id)
    original = storage.news.get_documents

    def missing_metadata(document_ids):
        documents = original(document_ids)
        documents.pop(ids[0], None)
        return documents

    monkeypatch.setattr(storage.news, "get_documents", missing_metadata)
    before = database_fingerprint(comparison_postgres)
    client = comparison_client(storage)
    response = client.get(
        "/api/run-comparisons/news",
        params={
            "base_run_id": str(base.run_id),
            "compare_run_id": str(other.run_id),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["items"][0]["document_id"] == ids[0]
    assert body["items"][0]["metadata"] is None
    assert body["items"][0]["membership"] == "ONLY_BASE"
    assert database_fingerprint(comparison_postgres) == before
