"""The MinIO adapter against a real server, using the shared contract.

This test only runs when a dedicated test bucket is configured. The bucket name must end
in `-test`, the same rule the PostgreSQL guard applies to database names: a bucket that
is not named as a test bucket can only mean production data, so the test refuses to run
rather than finding out by deleting someone's uploads.

The store is built inside the guard's `connect` callback, never around it: the refusal has
to land before an endpoint is dialled, otherwise it is a comment rather than a gate.
"""

from io import BytesIO
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from sector_pulse.config.rag_settings import load_rag_settings
from sector_pulse.infrastructure.research_library.assets.minio import MinioResearchAssetStore
from sector_pulse.infrastructure.research_library.assets.scanner import NullScanner

from backend.tests.contracts.test_research_asset_store import (
    KEY,
    META,
    PDF,
    assert_an_unconfigured_scanner_says_so,
    assert_asset_store_contract,
    assert_delete_is_idempotent,
    assert_grants_are_bounded_and_refuse_missing_assets,
    assert_put_is_idempotent_for_identical_content,
    assert_put_refuses_to_replace_different_content,
    assert_put_verifies_a_declared_hash,
    assert_stat_matches_what_was_stored,
    assert_unsafe_keys_are_refused_everywhere,
)
from backend.tests.dedicated_resources import connect_to_dedicated_resource

pytestmark = pytest.mark.minio


@pytest.fixture(scope="module")
def store() -> MinioResearchAssetStore:
    settings = load_rag_settings()

    def build(bucket: str) -> MinioResearchAssetStore:
        return MinioResearchAssetStore(
            endpoint=settings.minio_endpoint or "",
            access_key=(
                settings.minio_access_key.get_secret_value()
                if settings.minio_access_key
                else ""
            ),
            secret_key=(
                settings.minio_secret_key.get_secret_value()
                if settings.minio_secret_key
                else ""
            ),
            bucket=bucket,
            secure=settings.minio_secure,
            scanner=NullScanner(),
        )

    instance = connect_to_dedicated_resource(
        kind="MinIO test bucket",
        variable="SECTOR_PULSE_RAG_MINIO_BUCKET",
        connect=build,
        suffixes=("-test",),
    )
    instance.ensure_bucket()
    try:
        yield instance
    finally:
        instance.delete(KEY)
        instance.close()


def test_minio_store_satisfies_the_contract(store) -> None:
    assert_asset_store_contract(store)


def test_minio_store_stats_what_it_stored(store) -> None:
    assert_stat_matches_what_was_stored(store)


def test_minio_store_is_idempotent_for_identical_content(store) -> None:
    assert_put_is_idempotent_for_identical_content(store)


def test_minio_store_refuses_to_replace_different_content(store) -> None:
    assert_put_refuses_to_replace_different_content(store)


def test_minio_store_verifies_a_declared_hash(store) -> None:
    assert_put_verifies_a_declared_hash(store)


def test_minio_store_delete_is_idempotent(store) -> None:
    assert_delete_is_idempotent(store)


def test_minio_store_grants_are_bounded(store) -> None:
    assert_grants_are_bounded_and_refuse_missing_assets(store)


def test_minio_store_reports_an_unscanned_file_as_unscanned(store) -> None:
    assert_an_unconfigured_scanner_says_so(store)


def test_minio_store_refuses_unsafe_keys(store) -> None:
    assert_unsafe_keys_are_refused_everywhere(store)


def test_the_bucket_is_not_world_readable(store) -> None:
    """A private bucket is the difference between an internal library and a leak."""
    store.put(key=KEY, content=BytesIO(PDF), metadata=META)
    anonymous = f"{store.public_base_url}/{KEY}"
    with pytest.raises((HTTPError, OSError)), urlopen(anonymous, timeout=5) as response:  # noqa: S310
        assert response.status != 200
