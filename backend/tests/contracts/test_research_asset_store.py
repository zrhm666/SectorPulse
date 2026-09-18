"""One contract, two adapters.

Spec 4 makes asset storage pluggable: MinIO is the default adapter, but every rule that
keeps a document store safe has to hold for any adapter that claims to be one. So the
shared assertions live in `assert_asset_store_contract` and both the in-memory adapter
(the offline gate) and the MinIO adapter (the `minio` marker) run exactly the same body.

The rules under test are the ones a caller cannot be trusted to enforce: object keys are
a server-owned namespace, a caller-declared hash and size are claims to be verified
rather than values to be stored, and a scan that never happened must be recorded as
`NOT_SCANNED` instead of being rounded up to clean.
"""

from hashlib import sha256
from io import BytesIO

import pytest
from sector_pulse.infrastructure.research_library.assets.memory import (
    InMemoryResearchAssetStore,
)
from sector_pulse.infrastructure.research_library.assets.scanner import (
    ContentMarkerScanner,
    NullScanner,
)
from sector_pulse.ports.research_assets import (
    AssetConflict,
    AssetIntegrityError,
    AssetMetadata,
    AssetNotFound,
    AssetRole,
    ScanStatus,
    UnsafeAssetKey,
    validate_asset_key,
)

PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
PDF_SHA = sha256(PDF).hexdigest()
KEY = "original/doc_1/docv_1/source.pdf"
META = AssetMetadata(
    content_type="application/pdf",
    asset_role=AssetRole.ORIGINAL,
    filename="2026 年储能行业中期策略.pdf",
    document_id="doc_1",
    document_version_id="docv_1",
    sha256=PDF_SHA,
    byte_size=len(PDF),
)


def open_must_fail(store, key: str, error: type[Exception]) -> None:
    """Assert that opening `key` fails.

    `open` returns a context manager, so the lookup only happens on `__enter__`: calling it
    without entering would assert nothing at all, whichever adapter is under test.
    """
    with pytest.raises(error), store.open(key):
        pytest.fail(f"opening {key!r} should have raised {error.__name__}")


def assert_asset_store_contract(store) -> None:
    """Every adapter must satisfy this, byte for byte."""
    ref = store.put(key=KEY, content=BytesIO(PDF), metadata=META)
    assert ref.key == KEY
    assert ref.sha256 == PDF_SHA
    assert ref.byte_size == len(PDF)

    with store.open(ref.key) as stream:
        assert stream.read() == PDF

    assert store.stat(ref.key).sha256 == PDF_SHA

    store.delete(ref.key)
    open_must_fail(store, ref.key, AssetNotFound)


def assert_stat_matches_what_was_stored(store) -> None:
    ref = store.put(key=KEY, content=BytesIO(PDF), metadata=META)
    stored = store.stat(ref.key)
    assert stored == ref
    assert stored.metadata.content_type == "application/pdf"
    assert stored.metadata.asset_role is AssetRole.ORIGINAL
    assert stored.metadata.filename == META.filename


def assert_put_is_idempotent_for_identical_content(store) -> None:
    first = store.put(key=KEY, content=BytesIO(PDF), metadata=META)
    again = store.put(key=KEY, content=BytesIO(PDF), metadata=META)
    assert again == first
    with store.open(KEY) as stream:
        assert stream.read() == PDF


def assert_put_refuses_to_replace_different_content(store) -> None:
    store.put(key=KEY, content=BytesIO(PDF), metadata=META)
    other = b"%PDF-1.7\ntampered\n%%EOF\n"
    with pytest.raises(AssetConflict):
        store.put(
            key=KEY,
            content=BytesIO(other),
            metadata=AssetMetadata(
                content_type="application/pdf",
                asset_role=AssetRole.ORIGINAL,
                sha256=sha256(other).hexdigest(),
                byte_size=len(other),
            ),
        )
    with store.open(KEY) as stream:
        assert stream.read() == PDF


def assert_put_verifies_a_declared_hash(store) -> None:
    with pytest.raises(AssetIntegrityError):
        store.put(
            key=KEY,
            content=BytesIO(PDF),
            metadata=AssetMetadata(
                content_type="application/pdf",
                asset_role=AssetRole.ORIGINAL,
                sha256=sha256(b"something else").hexdigest(),
            ),
        )
    with pytest.raises(AssetIntegrityError):
        store.put(
            key=KEY,
            content=BytesIO(PDF),
            metadata=AssetMetadata(
                content_type="application/pdf",
                asset_role=AssetRole.ORIGINAL,
                byte_size=len(PDF) + 1,
            ),
        )


def assert_delete_is_idempotent(store) -> None:
    store.put(key=KEY, content=BytesIO(PDF), metadata=META)
    store.delete(KEY)
    store.delete(KEY)
    with pytest.raises(AssetNotFound):
        store.stat(KEY)
    open_must_fail(store, KEY, AssetNotFound)


def assert_grants_are_bounded_and_refuse_missing_assets(store) -> None:
    store.put(key=KEY, content=BytesIO(PDF), metadata=META)
    grant = store.create_download_grant(KEY, expires_in_seconds=120)
    assert KEY in grant.url
    assert 0 < grant.expires_in_seconds <= 300

    with pytest.raises(AssetNotFound):
        store.create_download_grant("original/doc_1/docv_1/missing.pdf")
    with pytest.raises(ValueError):
        store.create_download_grant(KEY, expires_in_seconds=86400)


def assert_an_unconfigured_scanner_says_so(store) -> None:
    """A file nobody scanned is not a file that is clean."""
    ref = store.put(key=KEY, content=BytesIO(PDF), metadata=META)
    assert ref.scan_status is ScanStatus.NOT_SCANNED


def assert_unsafe_keys_are_refused_everywhere(store) -> None:
    for key in (
        "/etc/passwd",
        "C:/windows/system32/config/sam",
        "original/../../secrets.pdf",
        "original\\doc_1\\source.pdf",
        "",
        "original/doc_1/",
        "original/./source.pdf",
    ):
        with pytest.raises(UnsafeAssetKey):
            store.put(
                key=key,
                content=BytesIO(PDF),
                metadata=AssetMetadata(
                    content_type="application/pdf",
                    asset_role=AssetRole.ORIGINAL,
                ),
            )


# --- the offline adapter runs the whole contract ---


@pytest.fixture
def memory_store() -> InMemoryResearchAssetStore:
    return InMemoryResearchAssetStore(scanner=NullScanner())


def test_in_memory_store_satisfies_the_contract(memory_store) -> None:
    assert_asset_store_contract(memory_store)


def test_in_memory_store_stats_what_it_stored(memory_store) -> None:
    assert_stat_matches_what_was_stored(memory_store)


def test_in_memory_store_is_idempotent_for_identical_content(memory_store) -> None:
    assert_put_is_idempotent_for_identical_content(memory_store)


def test_in_memory_store_refuses_to_replace_different_content(memory_store) -> None:
    assert_put_refuses_to_replace_different_content(memory_store)


def test_in_memory_store_verifies_a_declared_hash(memory_store) -> None:
    assert_put_verifies_a_declared_hash(memory_store)


def test_in_memory_store_delete_is_idempotent(memory_store) -> None:
    assert_delete_is_idempotent(memory_store)


def test_in_memory_store_grants_are_bounded(memory_store) -> None:
    assert_grants_are_bounded_and_refuse_missing_assets(memory_store)


def test_in_memory_store_reports_an_unscanned_file_as_unscanned(memory_store) -> None:
    assert_an_unconfigured_scanner_says_so(memory_store)


def test_in_memory_store_refuses_unsafe_keys(memory_store) -> None:
    assert_unsafe_keys_are_refused_everywhere(memory_store)


# --- the behaviours that need more than one adapter instance ---


def test_two_stores_do_not_share_state() -> None:
    """A store instance owns its objects; nothing may leak through a module global."""
    first = InMemoryResearchAssetStore(scanner=NullScanner())
    first.put(key=KEY, content=BytesIO(PDF), metadata=META)

    second = InMemoryResearchAssetStore(scanner=NullScanner())
    with pytest.raises(AssetNotFound):
        second.stat(KEY)


def test_a_configured_scanner_decides_the_scan_status() -> None:
    store = InMemoryResearchAssetStore(
        scanner=ContentMarkerScanner(markers=(b"@@MALWARE@@",))
    )
    clean = store.put(key="original/doc_1/docv_1/clean.pdf", content=BytesIO(PDF), metadata=META)
    assert clean.scan_status is ScanStatus.CLEAN

    dirty = store.put(
        key="original/doc_1/docv_1/dirty.pdf",
        content=BytesIO(b"%PDF-1.7\n@@MALWARE@@\n%%EOF\n"),
        metadata=AssetMetadata(content_type="application/pdf", asset_role=AssetRole.ORIGINAL),
    )
    assert dirty.scan_status is ScanStatus.INFECTED
    assert "MALWARE" in (dirty.scan_detail or "")


def test_a_refused_upload_leaves_nothing_behind() -> None:
    """A rejected hash must not leave a half-written object under the key."""
    store = InMemoryResearchAssetStore(scanner=NullScanner())
    with pytest.raises(AssetIntegrityError):
        store.put(
            key=KEY,
            content=BytesIO(PDF),
            metadata=AssetMetadata(
                content_type="application/pdf",
                asset_role=AssetRole.ORIGINAL,
                sha256=sha256(b"other").hexdigest(),
            ),
        )
    with pytest.raises(AssetNotFound):
        store.stat(KEY)


def test_an_infected_file_is_still_stored_but_never_reported_as_clean() -> None:
    """Quarantine is a policy decision; the store's job is to not lie about it."""
    store = InMemoryResearchAssetStore(
        scanner=ContentMarkerScanner(markers=(b"@@MALWARE@@",))
    )
    pdf = b"%PDF-1.7\n@@MALWARE@@\n%%EOF\n"
    ref = store.put(
        key=KEY,
        content=BytesIO(pdf),
        metadata=AssetMetadata(
            content_type="application/pdf",
            asset_role=AssetRole.ORIGINAL,
            sha256=sha256(pdf).hexdigest(),
        ),
    )
    assert ref.scan_status is ScanStatus.INFECTED
    assert store.stat(KEY).scan_status is ScanStatus.INFECTED


# --- the key grammar itself ---


def test_key_grammar_accepts_the_documented_shape() -> None:
    assert validate_asset_key("original/doc_1/docv_1/source.pdf") == (
        "original/doc_1/docv_1/source.pdf"
    )
    assert validate_asset_key("page_images/doc_1/docv_1/p0007.png") == (
        "page_images/doc_1/docv_1/p0007.png"
    )


@pytest.mark.parametrize(
    "key",
    [
        "",
        " ",
        "/absolute/path.pdf",
        "C:/absolute/path.pdf",
        "../escape.pdf",
        "original/../escape.pdf",
        "original\\windows.pdf",
        "original/doc_1/",
        "original//source.pdf",
        "original/./source.pdf",
        "original/doc_1/source.pdf\x00",
        "original/doc_1/" + "a" * 400 + ".pdf",
    ],
)
def test_key_grammar_refuses_anything_a_caller_might_inject(key: str) -> None:
    with pytest.raises(UnsafeAssetKey):
        validate_asset_key(key)
