"""The upload rules the shared contract does not reach.

The contract test drives a store through its documented behaviour. These are the rules that
only show up when something goes wrong — an upload over the size cap, a declared size that
lies, a temp file that has to be cleaned up on the failure path, a marker split across a
read boundary, a scanner that was never configured — plus the one property that keeps the
offline gate runnable at all: importing the MinIO adapter must not require the SDK.
"""

import tempfile
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.infrastructure.research_library.assets.integrity import (
    read_bounded,
    sha256_of,
    spool_to_disk,
    verify_declaration,
)
from sector_pulse.infrastructure.research_library.assets.memory import (
    InMemoryResearchAssetStore,
)
from sector_pulse.infrastructure.research_library.assets.scanner import (
    READ_CHUNK_BYTES,
    ContentMarkerScanner,
    NullScanner,
    build_scanner,
)
from sector_pulse.ports.research_assets import (
    AssetError,
    AssetIntegrityError,
    AssetMetadata,
    AssetNotFound,
    AssetRole,
    ScanStatus,
)

PDF = b"%PDF-1.7\n%%EOF\n"
META = AssetMetadata(content_type="application/pdf", asset_role=AssetRole.ORIGINAL)
KEY = "original/doc_1/docv_1/source.pdf"


# --- declared values are claims, not facts ---


def test_a_matching_declaration_is_accepted() -> None:
    verify_declaration(
        META.model_copy(update={"sha256": sha256_of(PDF), "byte_size": len(PDF)}),
        digest=sha256_of(PDF),
        size=len(PDF),
    )


def test_an_absent_declaration_is_not_checked() -> None:
    """Nothing declared means nothing to contradict; the store computes the real values."""
    verify_declaration(META, digest=sha256_of(PDF), size=len(PDF))


@pytest.mark.parametrize(
    "declared",
    [
        {"sha256": sha256(b"something else").hexdigest()},
        {"byte_size": len(PDF) + 1},
        {"byte_size": len(PDF) - 1},
    ],
)
def test_a_declaration_that_contradicts_the_bytes_fails(declared: dict) -> None:
    with pytest.raises(AssetIntegrityError):
        verify_declaration(
            META.model_copy(update=declared), digest=sha256_of(PDF), size=len(PDF)
        )


# --- the size cap ---


def test_read_bounded_refuses_more_than_the_cap() -> None:
    with pytest.raises(AssetIntegrityError):
        read_bounded(BytesIO(b"x" * 11), max_bytes=10)


def test_read_bounded_accepts_exactly_the_cap() -> None:
    assert read_bounded(BytesIO(b"x" * 10), max_bytes=10) == b"x" * 10


@pytest.fixture
def spool_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point `NamedTemporaryFile` at a directory this test owns, so leaks are visible."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


def test_spool_to_disk_deletes_its_temporary_file_on_success(
    spool_directory: Path,
) -> None:
    with spool_to_disk(BytesIO(PDF), max_bytes=1024) as spooled:
        assert spooled.path.read_bytes() == PDF
        assert spooled.sha256 == sha256_of(PDF)
        assert spooled.byte_size == len(PDF)
        assert list(spool_directory.iterdir()) == [spooled.path]
    assert list(spool_directory.iterdir()) == []


def test_spool_to_disk_deletes_its_temporary_file_when_the_cap_is_exceeded(
    spool_directory: Path,
) -> None:
    """An over-limit upload is exactly when a leaked temp file would pile up."""
    with pytest.raises(AssetIntegrityError), spool_to_disk(BytesIO(b"x" * 5000), max_bytes=100):
        pytest.fail("an over-limit upload must not reach the caller")
    assert list(spool_directory.iterdir()) == []


def test_an_oversized_upload_leaves_nothing_in_the_store() -> None:
    store = InMemoryResearchAssetStore(scanner=NullScanner(), max_asset_bytes=8)
    with pytest.raises(AssetIntegrityError):
        store.put(key=KEY, content=BytesIO(PDF), metadata=META)
    with pytest.raises(AssetNotFound):
        store.stat(KEY)


# --- scan verdicts ---


def test_an_unconfigured_scanner_explains_itself() -> None:
    verdict = NullScanner().scan(key=KEY, content=BytesIO(PDF), metadata=META)
    assert verdict.status is ScanStatus.NOT_SCANNED
    assert verdict.detail


def test_a_marker_split_across_a_read_boundary_is_still_found() -> None:
    """Chunked reading without carrying a tail would miss exactly this case."""
    marker = b"@@MALWARE@@"
    padded = b"a" * (READ_CHUNK_BYTES - 3) + marker
    verdict = ContentMarkerScanner((marker,)).scan(
        key=KEY, content=BytesIO(padded), metadata=META
    )
    assert verdict.status is ScanStatus.INFECTED


def test_a_scanner_that_finds_nothing_reports_clean() -> None:
    verdict = ContentMarkerScanner((b"@@MALWARE@@",)).scan(
        key=KEY, content=BytesIO(PDF), metadata=META
    )
    assert verdict.status is ScanStatus.CLEAN


def test_a_marker_scanner_needs_markers() -> None:
    with pytest.raises(ValueError):
        ContentMarkerScanner(())


def test_a_configured_scanner_is_built_from_settings() -> None:
    assert isinstance(
        build_scanner(RagSettings(asset_scanner="fixture")), ContentMarkerScanner
    )
    assert isinstance(build_scanner(RagSettings(asset_scanner="none")), NullScanner)


# --- the adapter stays importable without the optional SDK ---


def test_the_minio_adapter_explains_a_missing_sdk() -> None:
    """The offline gate has no `rag` extra installed; a bare ImportError would be a mystery."""
    from sector_pulse.infrastructure.research_library.assets.minio import (
        MinioResearchAssetStore,
    )

    try:
        import minio  # noqa: F401
    except ModuleNotFoundError:
        pass
    else:
        pytest.skip("the MinIO SDK is installed, so this failure mode cannot be exercised")

    with pytest.raises(AssetError, match="rag"):
        MinioResearchAssetStore(
            endpoint="127.0.0.1:9000",
            access_key="key",
            secret_key="secret",
            bucket="research-test",
        )


def test_the_minio_adapter_refuses_a_configuration_that_cannot_work() -> None:
    """Checked before the SDK is touched, so a typo in `.env` never looks like a bug in MinIO."""
    from sector_pulse.infrastructure.research_library.assets.minio import (
        MinioResearchAssetStore,
    )

    with pytest.raises(ValueError, match="endpoint"):
        MinioResearchAssetStore(
            endpoint="", access_key="key", secret_key="secret", bucket="research-test"
        )
    with pytest.raises(ValueError, match="bucket"):
        MinioResearchAssetStore(
            endpoint="127.0.0.1:9000", access_key="key", secret_key="secret", bucket=""
        )
