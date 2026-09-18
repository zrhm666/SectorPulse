# Internal Research RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents for this repository unless the owner later explicitly authorizes it.

**Goal:** Build a global, evidence-first internal research library that ingests PDF/Markdown/TXT into PostgreSQL + pluggable object storage + Milvus, performs Dense/BM25/Rerank/query-time claim extraction/NLI conflict handling, and exposes the results only through bounded A2 tools and referenced artifacts.

**Architecture:** PostgreSQL owns document/version/task/audit state; `ResearchAssetStore` owns original and derived binary assets with MinIO as the default adapter; `VectorIndex` owns a rebuildable Milvus index. A2 can search and inspect bounded results, while A3/A4 consume only accepted ArtifactRefs. New index generations are staged, verified, published in Milvus, then made visible by the final PostgreSQL `ACTIVE` transition and query-time PostgreSQL recheck.

**Tech Stack:** Python 3.12, Pydantic 2, FastAPI, SQLAlchemy/PostgreSQL, PyMuPDF, markdown-it-py, MinIO Python SDK, Milvus/PyMilvus 2.6-compatible API, React/TypeScript, pytest, Ruff, Mypy, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-17-internal-research-rag-design.md`

## Global Constraints

- Read the spec and this complete plan before modifying code.
- Preserve all existing uncommitted changes. Do not run pull, reset, checkout, clean, stash, or destructive repository commands.
- Do not commit, merge, or push unless the owner explicitly authorizes it.
- Use test-driven development: add the exact failing test first, run it and record the expected failure, then add the minimum implementation.
- RAG is disabled by default. When disabled, existing SQLite and PostgreSQL workflows must behave exactly as before.
- RAG production persistence requires PostgreSQL. If `SECTOR_PULSE_RAG_ENABLED=true` while the main database is SQLite, startup must fail with a clear configuration error.
- PostgreSQL integration tests require a dedicated database whose name ends in `_test`; MinIO and Milvus tests require dedicated test bucket/collection names. Never use production resources.
- Offline regression must use fixture providers and in-memory adapters. Do not call real OCR, Embedding, Reranker, NLI, Vision, MinIO, Milvus, or LLM endpoints unless the specific live/contract test is explicitly enabled.
- The uploaded document is the primary source. Do not build a graph of citations found inside that document.
- The upload API accepts an explicit new document or an explicit new version. Do not infer version relationships from similarity.
- PostgreSQL is authoritative; MinIO and Milvus are derived/external stores and cannot decide document validity.
- A2 alone receives RAG search/inspection tools. A3/A4 never receive open-ended RAG search.
- Do not store model hidden reasoning, credentials, complete prompts, arbitrary document bodies in logs, or MinIO internal object keys in Agent output.
- All provider calls bind `run_id`, `task_id`, `attempt_id`, `role`, deadline, call budget, cost budget, provider, model, and input fingerprint.
- Old-attempt late OCR/Embedding/Rerank/NLI/index/artifact results must be rejected.
- Required quality commands after every task: targeted pytest; after each phase: Ruff, Mypy, and the complete offline regression.
- Use official Milvus server + PyMilvus compatibility. The first tested pair is Milvus 2.6.x with `pymilvus==2.6.17`; changing either side requires rerunning all vector-index contracts.

## File Map

Create focused packages instead of adding RAG concerns to existing large orchestration files:

```text
backend/src/sector_pulse/domain/research_library/
  models.py                 immutable document/version/chunk/value models
  ingestion.py              ingestion state machine and transition rules
  retrieval.py              query, hit, claim, NLI and conflict result models

backend/src/sector_pulse/ports/
  research_assets.py        ResearchAssetStore protocol
  research_models.py        Embedding/Reranker/NLI/OCR/Vision protocols
  vector_index.py           VectorIndex protocol

backend/src/sector_pulse/storage/ports/
  research_library.py       PostgreSQL repository protocol

backend/src/sector_pulse/storage/postgres/research_library/
  repository.py             document/chunk/job/outbox/audit repository

backend/src/sector_pulse/application/research_library/
  commands.py               upload/version/delete/restore commands
  ingestion.py              leased ingestion coordinator
  parsing.py                normalization pipeline facade
  chunking.py               parent/child structural chunking
  indexing.py               outbox and staged/published index generation
  retrieval.py              hybrid retrieval and bounded inspection
  claims.py                 query-scoped claim extraction
  conflicts.py              NLI grouping and deterministic resolver
  artifacts.py              accepted internal evidence persistence
  maintenance.py            purge, reconcile and rebuild commands
  observability.py          metrics derived from safe audit/state records

backend/src/sector_pulse/infrastructure/research_library/
  assets/minio.py            MinIO ResearchAssetStore
  assets/memory.py           deterministic test adapter
  assets/scanner.py          pluggable file-safety scanner adapters
  parsing/pdf.py             PyMuPDF native extraction
  parsing/markdown.py        Markdown block extraction
  parsing/text.py            TXT normalization
  parsing/layout.py          layout normalization and OCR fallback
  vector/milvus.py           Milvus VectorIndex
  vector/memory.py           deterministic hybrid-index test adapter
  providers/fixture.py       fixture model providers
  providers/openai_compatible.py  HTTP adapters for configured APIs

backend/src/sector_pulse/infrastructure/agents/
  research_library_tools.py  A2 Tool wrappers

backend/src/sector_pulse/web/
  routers/research_library.py
  schemas/research_library.py

web/src/
  researchLibraryApi.ts
  pages/ResearchLibraryPage.tsx
  pages/research-library/*

config/agent-skills/
  internal-research-retrieval/SKILL.md
  internal-evidence-writing/SKILL.md
```

## Phase 1 — Domain, Configuration, PostgreSQL, and Asset Storage

### Task 1: Add optional RAG dependencies and strict configuration

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Modify: `backend/src/sector_pulse/config/settings.py`
- Create: `backend/tests/unit/config/test_rag_settings.py`
- Modify: `backend/tests/unit/test_package_layout.py`

**Interfaces:**
- Produces: `RagSettings` and `ApplicationSettings.rag`.
- Consumes later: every RAG dependency builder.

- [x] **Step 1: Write failing configuration tests**

```python
def test_rag_is_disabled_by_default(yaml_config, monkeypatch):
    monkeypatch.delenv("SECTOR_PULSE_RAG_ENABLED", raising=False)
    settings = ApplicationSettings.from_environment(yaml_config)
    assert settings.rag.enabled is False

def test_enabled_rag_requires_postgres_milvus_and_asset_configuration(yaml_config, monkeypatch):
    monkeypatch.setenv("SECTOR_PULSE_RAG_ENABLED", "true")
    monkeypatch.setenv("SECTOR_PULSE_DATABASE_PATH", "data/test.db")
    with pytest.raises(ValueError, match="RAG requires PostgreSQL"):
        ApplicationSettings.from_environment(yaml_config)
```

- [x] **Step 2: Run the tests and verify failure**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/config/test_rag_settings.py -q`

Expected: FAIL because `RagSettings` and `ApplicationSettings.rag` do not exist.

- [x] **Step 3: Add the optional dependency group and immutable settings**

Add to `pyproject.toml`:

```toml
rag = [
  "markdown-it-py>=4,<5",
  "minio>=7.2,<8",
  "PyMuPDF>=1.26,<2",
  "pymilvus==2.6.17",
]
```

Add a frozen `RagSettings` with explicit fields for enabled, MinIO, Milvus, collection alias, all provider names/models, timeouts, concurrency, batch sizes, retention days, retrieval K values, provider budgets, and confidence thresholds. `from_environment` must reject missing secrets/endpoints only when enabled and must reject enabled RAG without `database_url` using a PostgreSQL scheme.

- [x] **Step 4: Document every environment key in `.env.example` without real credentials**

Use the exact `SECTOR_PULSE_RAG_*` names from spec section 21 and add `SECTOR_PULSE_RAG_RETENTION_DAYS=30`, `...DENSE_TOP_K=40`, `...BM25_TOP_K=40`, `...RERANK_TOP_K=12`.

- [x] **Step 5: Run tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/config/test_rag_settings.py backend/tests/unit/config/test_settings.py backend/tests/unit/test_package_layout.py -q`

Expected: PASS.

**Observed: 37 passed.** `test_package_layout.py` needed no change; Task 1 adds no
package under `domain|application|storage|web`. Two facts recorded in
"Implementation Evidence" below: the PostgreSQL check must reuse
`resolve_database_config`, and `ApplicationSettings.database_url` stays plaintext.

### Task 2: Define immutable domain models and state transitions

**Files:**
- Create: `backend/src/sector_pulse/domain/research_library/__init__.py`
- Create: `backend/src/sector_pulse/domain/research_library/models.py`
- Create: `backend/src/sector_pulse/domain/research_library/ingestion.py`
- Create: `backend/src/sector_pulse/domain/research_library/retrieval.py`
- Create: `backend/tests/unit/domain/test_research_library_models.py`
- Create: `backend/tests/unit/domain/test_research_ingestion_state.py`

**Interfaces:**
- Produces: `ResearchDocument`, `ResearchDocumentVersion`, `DocumentBlock`, `ResearchChunk`, `IngestionJob`, `RetrievalQuery`, `RetrievedEvidence`, `ExtractedClaim`, `ConflictDecision`.
- Produces: `transition_ingestion(job, target, now, worker_id, attempt)`.

- [x] **Step 1: Write failing model and transition tests**

```python
def test_active_chunk_keeps_exact_source_locator():
    chunk = ResearchChunk.model_validate(CHUNK_PAYLOAD)
    assert chunk.source.page_start == 18
    assert chunk.source.bounding_boxes[0] == (72.0, 96.0, 520.0, 238.0)

def test_ingestion_cannot_publish_before_verification(job):
    with pytest.raises(InvalidIngestionTransition):
        transition_ingestion(job, IngestionStatus.PUBLISHED, NOW, "worker-1", 1)
```

- [x] **Step 2: Verify red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_research_library_models.py backend/tests/unit/domain/test_research_ingestion_state.py -q`

Expected: import failure for the new package.

- [x] **Step 3: Implement strict Pydantic models and enums**

Use frozen models and separate enums:

```python
class DocumentVersionStatus(StrEnum):
    PROCESSING = "PROCESSING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"
    DELETED = "DELETED"
    PURGED = "PURGED"

class IndexState(StrEnum):
    STAGED = "STAGED"
    PUBLISHED = "PUBLISHED"

class ConflictStatus(StrEnum):
    RESOLVED = "RESOLVED"
    NOT_CONFLICT = "NOT_CONFLICT"
    UNRESOLVED = "UNRESOLVED"
    CHECK_FAILED = "CHECK_FAILED"
```

Reject empty content, invalid page ranges, source spans outside content, confidence outside `[0,1]`, naive datetimes, and missing source lineage.

- [x] **Step 4: Implement explicit transition maps and ownership checks**

Only allow the spec state path plus retry/cancel edges. Require the current attempt and lease owner for every nonterminal transition.

- [x] **Step 5: Run tests**

Run the Task 2 test command. Expected: PASS.

**Observed: 72 passed** (83 with `test_package_layout.py`). Red state was
`ModuleNotFoundError: No module named 'sector_pulse.domain.research_library'`.

### Task 3: Add migration 035 and PostgreSQL repository contracts

**Files:**
- Create: `backend/src/sector_pulse/storage/migrations/035_research_library.sql`
- Create: `backend/src/sector_pulse/storage/migrations/postgres/035_research_library.sql`
- Create: `backend/src/sector_pulse/storage/ports/research_library.py`
- Create: `backend/src/sector_pulse/storage/postgres/research_library/__init__.py`
- Create: `backend/src/sector_pulse/storage/postgres/research_library/repository.py`
- Create: `backend/tests/integration/test_research_library_postgres_repository.py`
- Modify: `backend/tests/unit/storage/test_packaged_migrations.py`
- Modify: `backend/tests/integration/test_incremental_migration_from_an_old_database.py`

**Interfaces:**
- Produces: `ResearchLibraryRepositoryPort` with document/version/chunk/job/outbox/audit methods.
- Consumes: Task 2 domain types.

- [x] **Step 1: Write PostgreSQL contract tests**

Test exact cases: create new document/version; reject duplicate SHA within the same upload idempotency key; atomically activate new version and supersede old; lease acquisition competition; expired-only takeover with incremented attempt; append/read chunks; enqueue/claim/finish outbox; soft delete/restore; retrieval audit persistence.

```python
@pytest.mark.postgres
def test_activate_version_atomically_supersedes_previous(repo):
    old, new = seeded_versions(repo)
    repo.activate_version(new.version_id, expected_status=DocumentVersionStatus.PROCESSING)
    assert repo.get_version(old.version_id).status is DocumentVersionStatus.SUPERSEDED
    assert repo.get_version(new.version_id).status is DocumentVersionStatus.ACTIVE
```

- [x] **Step 2: Verify red only against a dedicated `_test` database**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/integration/test_research_library_postgres_repository.py -q -m postgres`

Expected: FAIL because migration/repository is absent, or SKIP if no dedicated URL exists. A skip is not a pass.

- [x] **Step 3: Create the migration**

Keep the common migration as the version anchor and create the PostgreSQL tables from spec section 9, plus `internal_research_evidence` and `internal_research_evidence_sources` required by Task 15. Add foreign keys, unique `(document_id, version_number)`, unique chunk IDs, job lease indexes, outbox availability indexes, status checks, `purge_after` index, and retrieval audit indexes. Use JSONB only in the PostgreSQL supplement. Migration 035 is immutable after this task passes.

- [x] **Step 4: Implement repository methods with SQLAlchemy transactions and conditional updates**

Every ownership or status change must include expected status/attempt/worker predicates and raise a typed conflict when `rowcount != 1`.

- [x] **Step 5: Run contracts and migration regression**

Run the Task 3 contract command and:

`.venv\Scripts\python.exe -m pytest backend/tests/unit/storage/test_packaged_migrations.py backend/tests/integration/test_incremental_migration_from_an_old_database.py -q`

Expected: PASS or the PostgreSQL cases explicitly SKIP for missing `_test` connection.

### Task 4: Implement pluggable asset storage with MinIO default

**Files:**
- Create: `backend/src/sector_pulse/ports/research_assets.py`
- Create: `backend/src/sector_pulse/infrastructure/research_library/assets/__init__.py`
- Create: `backend/src/sector_pulse/infrastructure/research_library/assets/memory.py`
- Create: `backend/src/sector_pulse/infrastructure/research_library/assets/minio.py`
- Create: `backend/src/sector_pulse/infrastructure/research_library/assets/scanner.py`
- Create: `backend/tests/contracts/test_research_asset_store.py`
- Create: `backend/tests/integration/test_minio_research_asset_store.py`

**Interfaces:**
- Produces: `ResearchAssetStore.put/open/stat/delete/create_download_grant` and `FileSafetyScanner.scan`.

- [x] **Step 1: Write one reusable contract suite**

```python
def assert_asset_store_contract(store: ResearchAssetStore):
    ref = store.put(key="original/doc/ver/source.pdf", content=BytesIO(b"%PDF"), metadata=META)
    with store.open(ref.key) as stream:
        assert stream.read() == b"%PDF"
    assert store.stat(ref.key).sha256 == sha256(b"%PDF").hexdigest()
    store.delete(ref.key)
    with pytest.raises(AssetNotFound):
        store.open(ref.key)
```

- [x] **Step 2: Verify red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_research_asset_store.py -q`

- [x] **Step 3: Implement the in-memory adapter first**

Reject unsafe keys, caller-provided absolute paths, mismatched hash/size, overwrites with different content, and download grants for missing assets.

- [x] **Step 4: Implement MinIO adapter**

Use private buckets, metadata SHA256, idempotent same-content writes, bounded stream reads, server-side delete, and short-lived presigned GET only for user-facing routes. Agent tools never receive grants or internal object keys. Define a scanner protocol and deterministic test scanner; when scanner configuration is `none`, persist `scan_status=NOT_SCANNED` and expose it to the upload quality gate instead of silently claiming the file is clean.

- [x] **Step 5: Run contracts**

Offline: `.venv\Scripts\python.exe -m pytest backend/tests/contracts/test_research_asset_store.py -q`

Real MinIO: `.venv\Scripts\python.exe -m pytest backend/tests/integration/test_minio_research_asset_store.py -q -m minio`

Expected: offline PASS; real test PASS only with a dedicated bucket ending `-test`, otherwise SKIP.

## Phase 2 — Parsing, OCR, Layout, and Structural Chunking

### Task 5: Normalize PDF, Markdown, and TXT into DocumentBlock

**Files:**
- Create: `backend/src/sector_pulse/ports/research_models.py`
- Create: `backend/src/sector_pulse/application/research_library/parsing.py`
- Create: `backend/src/sector_pulse/infrastructure/research_library/parsing/pdf.py`
- Create: `backend/src/sector_pulse/infrastructure/research_library/parsing/markdown.py`
- Create: `backend/src/sector_pulse/infrastructure/research_library/parsing/text.py`
- Create: `backend/src/sector_pulse/infrastructure/research_library/parsing/layout.py`
- Create: `backend/tests/fixtures/research_library/`
- Create: `backend/tests/unit/application/research_library/test_parsing.py`
- Create: `backend/tests/unit/infrastructure/research_library/test_pdf_parser.py`

**Interfaces:**
- Produces: `DocumentParser.parse(asset) -> ParsedDocument`, `OcrProvider.recognize_page`, and the shared `EmbeddingProvider`, `RerankerProvider`, `ClaimExtractorProvider`, `NliProvider`, and `VisionDocumentProvider` protocols used by later tasks.
- Consumes: Task 2 `DocumentBlock` and Task 4 asset bytes.

- [x] **Step 1: Add tiny licensed/generated fixtures and failing tests**

Cover native PDF text with page/bbox, one scanned page requiring OCR, Markdown headings/table/code, TXT encoding, repeated header/footer removal, encrypted PDF rejection, and max page/size limits.

```python
def test_pdf_uses_ocr_only_for_low_quality_page(parser, fake_ocr):
    parsed = parser.parse(PARTIAL_SCAN_PDF)
    assert fake_ocr.pages == [2]
    assert parsed.blocks_for_page(1)[0].extraction_method == "native"
    assert parsed.blocks_for_page(2)[0].extraction_method == "ocr"
```

- [x] **Step 2: Verify red**

Run the two Task 5 test files. Expected: missing parser modules.

- [x] **Step 3: Implement native extractors**

Import `pymupdf`, not legacy `fitz`. Return text spans, font metadata, bbox, page dimensions and initial reading order. Use `markdown-it-py` tokens for Markdown and deterministic encoding/paragraph normalization for TXT.

- [x] **Step 4: Implement quality scoring, OCR fallback, layout normalization**

OCR only low-quality pages. Merge OCR words into lines/blocks, remove repeated headers/footers, preserve extraction method/provider/model/confidence, and never execute PDF scripts, attachments, or links.

- [x] **Step 5: Run tests**

Expected: PASS with fixture OCR only.

### Task 6: Handle tables, charts, images, and formulas

**Files:**
- Create: `backend/src/sector_pulse/application/research_library/non_text_blocks.py`
- Create: `backend/tests/unit/application/research_library/test_non_text_blocks.py`
- Modify: `backend/src/sector_pulse/application/research_library/parsing.py`
- Modify: `backend/src/sector_pulse/ports/research_models.py`

**Interfaces:**
- Produces: normalized `table`, `chart`, `image`, and `formula` blocks and indexable text.

- [x] **Step 1: Write failing evidence-grade tests**

```python
def test_low_confidence_chart_is_searchable_only_as_unverified_lead():
    block = normalize_chart(VISION_RESULT_LOW_CONFIDENCE)
    assert block.content_origin == "vision_derived"
    assert block.requires_verification is True

def test_image_without_caption_or_description_is_not_indexable():
    assert normalize_image(UNLABELED_IMAGE).indexable_text is None
```

- [x] **Step 2: Verify red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/application/research_library/test_non_text_blocks.py -q`

- [x] **Step 3: Implement exact normalization rules**

Tables preserve headers/rows/units/notes and produce sentence-form text. Charts index caption/legend/axis/nearby text plus validated Vision output. Images index only original captions or clearly marked derived descriptions. Formulas index reliable Unicode/MathML/LaTeX with name, variables and context. Save region assets through `ResearchAssetStore`; do not send original images to Agent context.

- [x] **Step 4: Run tests**

Expected: PASS.

### Task 7: Implement deterministic parent/child structural chunking

**Files:**
- Create: `backend/src/sector_pulse/application/research_library/chunking.py`
- Create: `backend/tests/unit/application/research_library/test_chunking.py`

**Interfaces:**
- Produces: `StructuralChunker.chunk(parsed, policy) -> tuple[ResearchChunk, ...]`.

- [x] **Step 1: Write failing boundary tests**

Cover 300–500 token target, 700 soft cap, 50–80 overlap, heading propagation, table-header repetition, atomic code blocks, parent links, deterministic IDs, stable hashes, source page/span preservation, and no empty chunks.

```python
def test_chunk_ids_are_stable_for_same_version_and_policy(chunker):
    first = chunker.chunk(DOCUMENT, POLICY)
    second = chunker.chunk(DOCUMENT, POLICY)
    assert [x.chunk_id for x in first] == [x.chunk_id for x in second]
```

- [x] **Step 2: Verify red**

Run the Task 7 file. Expected: module import failure.

- [x] **Step 3: Implement sentence-aware and structure-aware chunking**

Use an injected tokenizer protocol so tests do not download a model. ID input must include `document_version_id`, policy version, ordered source block IDs, source span and normalized content hash.

- [x] **Step 4: Run tests**

Expected: PASS. Observed: `34 passed`.

### Phase 2 gate

- [x] Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_research_* backend/tests/unit/application/research_library backend/tests/unit/infrastructure/research_library -q` — `190 passed`
- [x] Run: `.venv\Scripts\python.exe -m ruff check .` — `All checks passed!`
- [x] Run: `.venv\Scripts\python.exe -m mypy backend/src/sector_pulse` — `Success: no issues found in 330 source files`
- [x] Run complete offline regression with a unique `--basetemp` and markers excluding live/live_llm/postgres/minio/milvus/live_rag. — `1030 passed, 90 skipped`; `web`: `64 files, 259 tests passed`

## Phase 3 — Providers, Milvus, Outbox, and Atomic Publication

### Task 8: Add fixture and API model providers

**Files:**
- Create: `backend/src/sector_pulse/infrastructure/research_library/providers/fixture.py`
- Create: `backend/src/sector_pulse/infrastructure/research_library/providers/openai_compatible.py`
- Create: `backend/tests/contracts/test_research_model_providers.py`
- Create: `backend/tests/unit/infrastructure/research_library/test_api_model_providers.py`

**Interfaces:**
- Implements Task 5 protocols: `EmbeddingProvider`, `RerankerProvider`, `ClaimExtractorProvider`, `NliProvider`, `OcrProvider`, and `VisionDocumentProvider`.

- [x] **Step 1: Write provider contracts**

Require deterministic batch order, vector dimension, strict JSON decoding, NLI enum, confidence bounds, timeout propagation, no secret logging, provider/model usage metadata, and cancellation preservation.

- [x] **Step 2: Verify red**

Run the Task 8 tests. Expected: missing implementations. Observed: `ModuleNotFoundError: No module named 'sector_pulse.infrastructure.research_library.providers'`.

- [x] **Step 3: Implement fixtures and separate HTTP adapters**

Reuse the repository's safe HTTP patterns, but keep independent endpoints/models/timeouts. Embeddings call an OpenAI-compatible embeddings endpoint; Reranker and NLI adapters parse provider-specific responses behind fixed domain protocols. Tests use `httpx.MockTransport` only.

- [x] **Step 4: Run tests**

Expected: PASS and no network calls. Observed: `83 passed`; an autouse fixture reroutes `socket.connect` to an assertion, so a future test that reaches the network fails instead of passing quietly.

### Task 9: Implement VectorIndex and Milvus hybrid schema

**Files:**
- Create: `backend/src/sector_pulse/ports/vector_index.py`
- Create: `backend/src/sector_pulse/infrastructure/research_library/vector/memory.py`
- Create: `backend/src/sector_pulse/infrastructure/research_library/vector/milvus.py`
- Create: `backend/tests/contracts/test_vector_index.py`
- Create: `backend/tests/integration/test_milvus_vector_index.py`

**Interfaces:**
- Produces: `stage`, `verify`, `publish`, `hybrid_search`, `delete_generation`.

- [x] **Step 1: Write reusable vector-index contracts**

Test staged invisibility, published visibility, generation isolation, idempotent same-record upsert, conflicting record rejection, Dense and BM25 contribution, RRF order, scalar filters, and generation deletion.

- [x] **Step 2: Verify red against memory and optionally dedicated Milvus**

Run offline contract first. Run real test only if collection name ends `_test`.

Red confirmed as `ModuleNotFoundError: No module named 'sector_pulse.infrastructure.research_library.vector'`.

- [x] **Step 3: Implement memory adapter**

Use deterministic cosine and token-frequency scoring only for contracts; do not claim it reproduces production BM25 exactly.

- [x] **Step 4: Implement Milvus collection schema**

Use `TEXT(enable_analyzer=True)`, a BM25 function into `SPARSE_FLOAT_VECTOR`, a dense vector field with configured dimension, scalar lineage fields, `index_generation`, and `index_state`. Use separate dense and sparse requests with `RRFRanker`. Never use Milvus Lite for the BM25 acceptance test because official Milvus documentation states full-text support requires server deployment for the relevant 2.x release.

`TEXT` is written as `VARCHAR(enable_analyzer=True)`: pymilvus has no `TEXT` datatype, and
`enable_analyzer` on the text field is what makes the BM25 function work. See E46.

- [x] **Step 5: Run contracts**

Offline PASS; real Milvus PASS with dedicated collection or explicit SKIP.

Offline: 26 passed. Real Milvus: 21 SKIPPED (pymilvus not installed), which is the explicit
SKIP the step allows — see E44 for what that leaves unverified.

### Task 10: Build ingestion coordinator, Outbox, and dual publication gate

**Files:**
- Create: `backend/src/sector_pulse/application/research_library/ingestion.py`
- Create: `backend/src/sector_pulse/application/research_library/indexing.py`
- Create: `backend/tests/integration/test_research_ingestion_pipeline.py`
- Create: `backend/tests/integration/test_research_index_publication.py`

**Interfaces:**
- Produces: `ResearchIngestionCoordinator.run(job_id, worker_id, now)` and `IndexOutboxWorker.run_once`.

- [x] **Step 1: Write failing end-to-end fixture tests**

Test success, parser failure, embedding failure, partial vector write, worker crash, expired takeover/new attempt, cancellation, old-attempt late completion, idempotent replay, count/ID mismatch, and old-version availability while a new version builds.

```python
def test_partial_milvus_write_is_never_visible(pipeline, vector_index, repository):
    vector_index.fail_after = 3
    pipeline.run(JOB_ID, "worker-1", NOW)
    assert repository.get_version(VERSION_ID).status is DocumentVersionStatus.PROCESSING
    assert pipeline.search_for_test("query") == ()
```

- [x] **Step 2: Verify red**

Run both Task 10 files. Expected: missing coordinator.

- [x] **Step 3: Implement staged pipeline**

Persist every phase transition before side effects. Store chunks before Outbox. Stage vectors, verify exact IDs/count/dimension/metadata, publish the generation, reverify, then conditionally activate in PostgreSQL. On new-version activation, supersede the previous version in the same transaction.

- [x] **Step 4: Add PostgreSQL final recheck helper**

`filter_active_hits(hits)` must batch-fetch version statuses and discard every non-`ACTIVE` hit regardless of Milvus `index_state`.

- [x] **Step 5: Run tests**

Expected: PASS with fake providers and memory vector index.

## Phase 4 — Hybrid Retrieval, Claims, NLI, and Conflict Resolution

### Task 11: Implement bounded hybrid retrieval and source inspection

**Files:**
- Create: `backend/src/sector_pulse/application/research_library/retrieval.py`
- Create: `backend/tests/unit/application/research_library/test_retrieval.py`
- Create: `backend/tests/integration/test_research_retrieval_visibility.py`

**Interfaces:**
- Produces: `ResearchRetrievalService.search(context, query)` and `.inspect(context, retrieval_id, candidate_id)`.

- [x] **Step 1: Write failing tests**

Cover query normalization, configured K limits, RRF, Reranker order, overlap dedupe, per-document diversity, parent expansion cap, active-state recheck, unverified-lead filtering, retrieval-bound inspection, cross-task denial, and no MinIO key leakage.

- [x] **Step 2: Verify red**

Run Task 11 tests.

- [x] **Step 3: Implement service**

Return opaque `retrieval_id` and candidate IDs. Persist query fingerprint, filters, provider/model versions, candidates and scores. `inspect` accepts only candidate IDs already returned to the same run/task/attempt and returns bounded text plus logical source locator.

- [x] **Step 4: Run tests**

Expected: PASS.

### Task 12: Implement query-scoped claim extraction and grouping

**Files:**
- Create: `backend/src/sector_pulse/application/research_library/claims.py`
- Create: `backend/tests/unit/application/research_library/test_claims.py`

**Interfaces:**
- Produces: `ClaimExtractionService.extract(question, candidates)` and `group_comparable_claims`.

- [x] **Step 1: Write failing tests**

Cover multiple claims in one chunk, zero relevant claims, exact source-span validation, unsupported hallucinated claim rejection, entity normalization, time overlap, and no Cartesian comparison for unrelated subjects/predicates.

```python
def test_claim_without_exact_source_span_is_rejected(service):
    provider.claims = [CLAIM_NOT_PRESENT_IN_SOURCE]
    assert service.extract(QUESTION, [CANDIDATE]) == ()
```

- [x] **Step 2: Verify red**

Run Task 12 tests.

- [x] **Step 3: Implement strict structured extraction**

Validate every statement against normalized source text and range. Keep claims retrieval-scoped; persist only claims used in the final result/audit.

- [x] **Step 4: Run tests**

Expected: PASS.

### Task 13: Implement NLI checks and deterministic resolver

**Files:**
- Create: `backend/src/sector_pulse/application/research_library/conflicts.py`
- Create: `backend/tests/unit/application/research_library/test_conflicts.py`
- Create: `backend/tests/fixtures/research_library/nli_cases.yaml`

**Interfaces:**
- Produces: `ConflictService.check(groups, context)` and pure `resolve_conflict(pair, metadata, policy)`.

- [x] **Step 1: Write table-driven failing tests**

Cases: active vs deleted; explicit new version; different effective times are not conflict; query-time match; source weight; original text vs low-confidence vision; equal independent active sources unresolved; NLI timeout/check failed; low confidence/uncertain; prediction vs observed fact; different units.

- [x] **Step 2: Verify red**

Run Task 13 tests.

- [x] **Step 3: Implement pair selection, NLI call and resolver priority**

Do not let Rerank score alone resolve independent-source contradiction. Return both source refs for `UNRESOLVED`; return `CHECK_FAILED` on provider failure without claiming no conflict.

- [x] **Step 4: Run tests**

Expected: PASS.

### Task 14: Add retrieval audit, cache generation, and provider budget binding

**Files:**
- Create: `backend/src/sector_pulse/application/research_library/audit.py`
- Create: `backend/src/sector_pulse/application/research_library/cache.py`
- Create: `backend/src/sector_pulse/application/research_library/observability.py`
- Create: `backend/src/sector_pulse/application/research_library/provider_calls.py`
- Modify: `backend/src/sector_pulse/application/orchestration/tool_budget.py`
- Modify: `backend/src/sector_pulse/application/research_library/retrieval.py`
- Modify: `backend/src/sector_pulse/infrastructure/research_library/providers/openai_compatible.py`
- Create: `backend/tests/integration/test_research_retrieval_audit.py`
- Create: `backend/tests/integration/test_research_provider_budget.py`

**Plan correction (E93):** the plan named neither `provider_calls.py` nor two of the three
modified files. (1) The pre-request lease rule and the per-provider call cap are two new
arguments on `SharedToolBudget.admit`, so the adapter that supplies them has to live
somewhere: `provider_calls.py`. (2) `retrieval.py` was writing the whole candidate, body
included, into `returned_evidence`, contradicting spec 20.1; Task 14 owns that field, so it
is fixed here. (3) `_HttpProvider` had no way to report the timeout it actually applies, so
the audit could only have recorded a configured number nobody enforces.

**Interfaces:**
- Produces complete safe audit records and cache keys.
- Consumes existing shared tool/model budget and attempt ownership services.

- [x] **Step 1: Write failing audit/budget tests**

Verify provider calls carry run/task/attempt/role, timeouts, reserved/actual CNY, terminal status, safe result refs; cache keys include corpus/model/policy generations; document publish/delete/restore/source-weight changes invalidate cache; logs omit content/secret/thoughts. Verify metrics expose ingestion duration/success, OCR ratio, provider latency/error/cost, empty retrievals, Dense/BM25 contribution, conflict outcomes and storage inconsistency without document bodies or secrets.

- [x] **Step 2: Verify red**

Run Task 14 tests.

- [x] **Step 3: Implement adapters around every external provider call**

Use the existing budgeted tool/provider semantics. Old attempt, expired lease, exceeded calls/CNY/deadline, unknown configured price, and conflicting replay must reject before the external request.

- [x] **Step 4: Run tests**

Expected: PASS.

## Phase 5 — Agent Tools, Evidence Artifacts, Skills, and Editorial Enforcement

### Task 15: Persist accepted internal evidence atomically

**Files:**
- Create: `backend/src/sector_pulse/application/research_library/artifacts.py`
- Create: `backend/tests/integration/test_internal_research_evidence_artifact.py`
- Modify: `backend/src/sector_pulse/application/research_library/conflicts.py` (`weakest_grade`)

**Plan correction (E100):** 计划只列了新建的两个文件。等级比较需要"更弱的一档"这个判定，
而档位次序已经由 `conflicts._GRADE_RANK` 定义；在 `conflicts.py` 里加一个公开的
`weakest_grade(grades)` 比在 `artifacts.py` 另立一份排序表更安全——两处各有一个"更弱"的
定义，迟早会分叉。

**Interfaces:**
- Produces: `AcceptInternalEvidenceService.accept(...) -> ArtifactRef(kind="internal_research_evidence")`.

- [x] **Step 1: Write failing atomicity and authorization tests**

Accept only current A2 run/task/attempt retrieval candidates. Reject forged chunk IDs, inactive versions, uninspected candidate refs, late attempts, missing conflict metadata, and unsupported deterministic claims. Test business row + ArtifactRef + orchestration event commit atomically.

- [x] **Step 2: Verify red**

Run Task 15 tests.

- [x] **Step 3: Implement using `AtomicArtifactCommitter`**

Use the `internal_research_evidence` and `internal_research_evidence_sources` tables created up front by Task 3 migration 035. Store claim, stance, conflict status, document/version/chunk/page references, evidence grade and retrieval audit ID. Never alter an already-applied migration and never copy full documents into the orchestration snapshot.

- [x] **Step 4: Run tests**

Expected: PASS.

### Task 16: Add A2 tools and exact role whitelist

**Files:**
- Create: `backend/src/sector_pulse/infrastructure/agents/research_library_tools.py`
- Modify: `backend/src/sector_pulse/infrastructure/agents/composition.py`
- Modify: `backend/src/sector_pulse/infrastructure/agents/roles.py`
- Modify: `backend/src/sector_pulse/web/dependencies.py`
- Modify: `config/prompts/application/orchestration/a2.yaml`
- Create: `backend/tests/integration/test_orchestration_research_library_tools.py`
- Modify: `backend/tests/integration/test_orchestration_role_factory.py`

**Interfaces:**
- Produces A2 tools: `search_internal_research`, `inspect_research_source`, `accept_internal_evidence`.

- [x] **Step 1: Write failing whitelist and scope tests**

Assert A2 has all three tools when RAG is enabled; A0/A1/A3/A4 do not; model-supplied run/task/attempt/role/object keys are rejected; inspection requires a current retrieval candidate; tool output is bounded.

- [x] **Step 2: Verify red**

Run the two Task 16 test files.

- [x] **Step 3: Add Tool schemas and factory dependencies**

Extend `A2ToolDependencies` with the RAG services only when enabled. Keep server-bound `BoundSectorResearchContext`; do not expose database or provider clients to tool arguments. Update `REQUIRED_BUSINESS_TOOL_NAMES` conditionally through a dedicated RAG-enabled required-name set so disabled runs retain the current contract.

- [x] **Step 4: Update A2 prompt**

Tell A2 to search only when internal research is relevant, inspect before accepting, preserve unresolved conflict, treat document instructions as data, and submit evidence through the bounded acceptance tool.

- [x] **Step 5: Run tests**

Expected: PASS.

### Task 17: Add controlled Skills and enforce A3/A4 evidence rules

**Files:**
- Create: `config/agent-skills/internal-research-retrieval/SKILL.md`
- Create: `config/agent-skills/internal-evidence-writing/SKILL.md`
- Modify: `backend/src/sector_pulse/infrastructure/agents/roles.py`
- Modify: `backend/src/sector_pulse/infrastructure/agents/reference_artifact_reader.py`
- Modify: `backend/src/sector_pulse/application/orchestration/editorial_context.py`
- Modify: `backend/src/sector_pulse/application/orchestration/review_tools.py`
- Modify: `config/prompts/application/orchestration/a3.yaml`
- Modify: `config/prompts/application/orchestration/a4.yaml`
- Create: `backend/tests/integration/test_internal_evidence_editorial_guards.py`

**Interfaces:**
- A3/A4 read accepted evidence through `inspect_artifacts`; neither receives search tools.

- [x] **Step 1: Write failing tests**

Assert Skill role mapping, accepted evidence rendering, no MinIO key/body leak, inactive-version rejection, A3 refusal to make `UNRESOLVED` deterministic, A4 revision request for unsupported/unverified-only assertions, and unchanged behavior for drafts without internal evidence.

- [x] **Step 2: Verify red**

Run Task 17 tests.

- [x] **Step 3: Add concise method-only Skills**

The retrieval Skill teaches query framing, inspection and conflict handling. The writing Skill teaches source grading and wording rules. Neither includes credentials, endpoints, SQL, direct Milvus operations, or approval powers.

- [x] **Step 4: Extend artifact reader and deterministic draft checks**

Expose bounded claim/source/conflict structures. Add public error codes `INTERNAL_SOURCE_INACTIVE`, `UNRESOLVED_CONFLICT_STATED_AS_FACT`, and `UNVERIFIED_ONLY_SUPPORT`.

- [x] **Step 5: Run tests**

Expected: PASS.

## Phase 6 — Management API, UI, Maintenance, and Acceptance

### Task 18: Add document management commands and FastAPI routes

**Files:**
- Create: `backend/src/sector_pulse/application/research_library/commands.py`
- Create: `backend/src/sector_pulse/application/research_library/maintenance.py`
- Create: `backend/src/sector_pulse/web/schemas/research_library.py`
- Create: `backend/src/sector_pulse/web/routers/research_library.py`
- Modify: `backend/src/sector_pulse/web/dependencies.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Create: `backend/tests/integration/test_research_library_api.py`
- Create: `backend/tests/integration/test_research_library_maintenance.py`

**Interfaces:**
- Produces `/api/research-library/documents`, version upload, status, source preview, delete, restore, rebuild, and ingestion retry endpoints.

- [x] **Step 1: Write failing API tests**

Cover multipart upload size/type/header/scan validation; explicit `new_document` vs `new_version` request; version target required; list/status; private source download; source-weight edit; archive; soft delete; restore; purge eligibility; rebuild; no Agent-accessible governance endpoint; disabled-RAG 404/feature-unavailable response.

- [x] **Step 2: Verify red**

Run Task 18 tests.

- [x] **Step 3: Implement commands and routes**

Stream uploads into the asset store while hashing; do not load unbounded files in memory. Generate object keys server-side. User actions append audit events. Only the user/API layer can create, delete, restore, set version relationships or edit source weights.

- [x] **Step 4: Implement reconciliation and purge**

Reconcile expected PostgreSQL chunks vs Milvus, retry Outbox, remove orphan vectors, validate MinIO asset hashes, and purge only `DELETED` records whose `purge_after <= now` still matches a conditional database update.

- [x] **Step 5: Run tests**

Expected: PASS.

### Task 19: Add the global research library UI

**Files:**
- Create: `web/src/researchLibraryApi.ts`
- Create: `web/src/researchLibraryApi.test.ts`
- Create: `web/src/pages/ResearchLibraryPage.tsx`
- Create: `web/src/pages/ResearchLibraryPage.test.tsx`
- Create: `web/src/pages/research-library/DocumentUploadPanel.tsx`
- Create: `web/src/pages/research-library/DocumentTable.tsx`
- Create: `web/src/pages/research-library/DocumentDetailDrawer.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/layout/navigation.ts`
- Modify: `web/src/styles/pages/operations-pages.css`

**Interfaces:**
- Consumes Task 18 API.

- [x] **Step 1: Write failing API/client and page tests**

Test new document upload, explicit new-version selection, progress/status display, failure message, version history, soft-delete confirmation, restore, source preview, RAG-disabled empty state, and keyboard-accessible controls.

- [x] **Step 2: Verify red**

Run: `Set-Location web; npm.cmd test -- --run src/researchLibraryApi.test.ts src/pages/ResearchLibraryPage.test.tsx`

- [x] **Step 3: Implement the smallest user-facing page using existing primitives**

Reuse `PageHeader`, `Panel`, `StatusBadge`, `ConfirmDialog`, `InlineAlert`, `LoadingState`, and `ManagementDrawer`. Do not expose model/provider configuration or raw object/vector identifiers in the browser.

- [x] **Step 4: Run web tests and build**

Run: `Set-Location web; npm.cmd test -- --run; npm.cmd run build`

Expected: PASS.

### Task 20: Add golden RAG evaluation and complete acceptance

**Files:**
- Create: `backend/tests/fixtures/research_library/golden_retrieval.yaml`
- Create: `backend/tests/evaluation/test_research_rag_golden.py`
- Create: `backend/tests/live/test_research_rag_providers_live.py`
- Create: `backend/tests/e2e/test_research_library_web.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `backend/README.md`
- Modify: `docs/PROJECT_STATUS.md`

**Interfaces:**
- Produces reproducible quality report and final release gate.

- [x] **Step 1: Add pytest markers**

Register `minio`, `milvus`, and `live_rag`. Marker tests must reject non-test bucket/collection/database identifiers before connecting.

- [x] **Step 2: Build the golden dataset and failing metric assertions**

Include native/scanned PDF, Markdown/TXT, exact identifiers, semantic paraphrases, explicit versions, independent conflicts, different-time non-conflicts, tables/charts, prompt injection and deleted documents. For the committed fixture baseline assert `Recall@12 >= 0.90`, `MRR >= 0.80`, `nDCG@12 >= 0.85`, duplicate candidate ratio `<= 0.15`, zero inactive-version leakage, 100% source locator success, zero unresolved-as-fact, and zero tool escalation. Real-provider shadow results are reported separately and do not rewrite these thresholds automatically.

- [x] **Step 3: Run offline golden evaluation**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_research_rag_golden.py -q`

Expected: PASS with fixture providers and memory adapters.

- [x] **Step 4: Run dedicated infrastructure contracts**

Run PostgreSQL, MinIO and Milvus marked suites only against `_test` resources. Record PASS counts separately; report SKIP honestly when a resource is absent.

- [x] **Step 5: Run opt-in real Provider smoke tests**

Only with explicit live consent, hard maximum calls/CNY/deadline, and a tiny fixture corpus. Verify Embedding dimension, Reranker schema, NLI contradiction, OCR one-page response, and optional Vision schema. Do not use production data.

- [x] **Step 6: Run one real A0→A4 RAG chain only after every prior gate passes**

Use a temporary run, dedicated test database/bucket/collection and a three-document corpus containing one resolvable and one unresolved conflict. Verify A2 cites accepted evidence, A3 expresses unresolved conflict cautiously, A4 reviews it, and final state remains `waiting_user_review`.

- [x] **Step 7: Run final quality commands**

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not live and not live_llm and not live_rag and not postgres and not minio and not milvus" --import-mode=importlib -p no:cacheprovider --basetemp=.tmp-test/rag-final
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy backend/src/sector_pulse
Set-Location web
npm.cmd test -- --run
npm.cmd run build
```

Expected: all commands PASS. Never report skipped infrastructure/live suites as passed.

- [x] **Step 8: Update documentation with verified reality only**

Move README wording from “规划中” to available only after acceptance passes. Document setup, provider replacement, private MinIO bucket, dedicated Milvus server requirement for BM25, maintenance commands, limitations, and exact verified test counts. Do not claim multi-tenant permissions, automatic version inference, image search, or automatic publishing.

## Implementation Evidence

Deviations from this plan are recorded here with the code evidence that forced them.
Nothing in this section replaces the spec's fixed decisions.

### E1 — RAG's PostgreSQL requirement reuses `resolve_database_config` (Task 1)

`backend/src/sector_pulse/storage/database_config.py:16` accepts `postgresql`,
`postgresql+asyncpg`, `postgresql+psycopg` and `postgres`, normalizing all of them to
`postgresql+psycopg://`. A literal `startswith("postgresql+psycopg://")` check in the
RAG guard would therefore reject the URL form the rest of the application accepts.
`ApplicationSettings.from_environment` calls the shared resolver instead and requires
`backend == "postgresql"`. This adds a `config → storage.database_config` import edge,
which is safe: that module is a pure value module in the storage root the layout test
already documents as shared infrastructure, and it does not import `config`.

### E2 — `ApplicationSettings.database_url` remains a plain `str` (Task 1)

`config/settings.py:20` and readers at `storage/database_runtime.py:13` and
`web/routers/operations.py:117` treat it as a URL string. Every RAG credential added by
this plan is a `SecretStr`, but narrowing `database_url` would ripple through those
call sites and is out of scope for Task 1. The RAG settings test asserts only RAG
secrets are absent from `model_dump_json()` and documents this gap in its docstring.

### E3 — Duplicate test module basenames require `--import-mode=importlib` (Task 1)

`backend/tests/unit/domain/test_candidate_selection.py` and
`backend/tests/unit/application/data_runs/test_candidate_selection.py` share a basename,
so a default-import-mode run of `backend/tests/unit` aborts during collection. This
predates the RAG work. The phase gate commands in this plan already pass
`--import-mode=importlib`, which collects all of them.

### E4 — Milvus collection and alias are exempt from the "required when enabled" check (Task 1)

Both carry spec defaults (`internal_research_chunks_v1`, and an optional alias), so a
non-`None` assertion on them would be a permanently true branch.

### E5 — `transition_ingestion` takes a keyword-only `reason` (Task 2)

The plan's signature `transition_ingestion(job, target, now, worker_id, attempt)` cannot
produce a valid `IngestionJob`: the model rejects `RETRYABLE_FAILED` /
`PERMANENT_FAILED` without a `failure_reason`, because an unexplained failure is
indistinguishable from a bug. The parameter is keyword-only and optional, so the
planned positional signature is unchanged and every documented call site still works.

### E6 — Shared domain value payloads live in `backend/tests/research_library_support.py` (Task 2)

Tasks 2, 7, 10, 15 and 20 all need the same document/version/chunk/claim payloads. The
file follows the existing `backend/tests/comparison_support.py` convention, holds only
plain dicts (no domain imports, so a test fails on the missing production model rather
than on the helper), and keeps `backend/tests/fixtures/research_library/` free for the
binary fixtures Task 5 adds.

### E7 — `ResearchDocumentVersion` requires generation, index time and chunk count to be ACTIVE (Task 2)

Spec section 10 makes a version visible only after its vectors are published and
reverified, and acceptance criterion 2 forbids partial visibility. The model refuses to
construct an `ACTIVE` version lacking `index_generation`, `indexed_at` or
`expected_chunk_count`, so Tasks 3 and 10 must perform the activation update after the
generation is published, not before.

## Final Review Checklist for the Implementer

- [ ] Every spec section maps to at least one task above.

> **未勾选，原因是核对下来不成立。** 逐节比对（spec 的 71 个内容标题对 20 个 Task 的 Files/Steps）后，绝大多数小节都有归属，但有四处没有任务覆盖，见文末 E157。这一条按原样留着比勾上更有用：它是这轮唯一一条知道没做到、并且写了下来的清单项。
- [x] No production code directly imports MinIO/Milvus clients outside their adapters.
- [x] RAG-disabled SQLite startup remains green.
- [x] RAG-enabled SQLite startup fails clearly.
- [x] New-version failure leaves the old version active.
- [x] Partially staged vectors never reach Agent context.
- [x] Every final claim has a resolvable document/version/chunk/page locator.
- [x] Independent equal active conflicts remain `UNRESOLVED`.
- [x] A3/A4 cannot call RAG search.
- [x] Document text cannot alter Tool/Skill permissions.
- [x] Old-attempt results cannot mutate current state.
- [x] Delete immediately removes search visibility; purge remains conditional and auditable.
- [x] No test used a production database, bucket, collection, external corpus or unrestricted LLM budget.
- [x] Final test counts, skipped suites and real-provider scope are written accurately.

## Implementation Order and Review Gates

Execute Tasks 1–20 in order. Stop after each phase gate for code review of the accumulated diff. Do not start a later phase while an earlier phase has failing targeted tests, Ruff errors, Mypy errors, migration ambiguity, or unresolved contract failures. If a planned interface proves wrong, update this plan and the design spec before propagating a different signature through later tasks.

### E8 — Three migration-count assertions, not the one file the plan names (Task 3)

The plan lists only `backend/tests/unit/storage/test_packaged_migrations.py` as needing
an update for migration 035. Two more files assert the same literal set and would have
failed at the phase gate:

- `backend/tests/unit/storage/sqlite/test_sqlite_schema.py:61`
- `backend/tests/unit/storage/sqlite/test_real_news_schema.py:30`

All three now expect `range(1, 36)`. The literals are deliberately kept literal rather
than derived from the migration directory: a derived value would make the assertion a
tautology and stop noticing an unexpected migration.

### E9 — The layout guard now names the PostgreSQL-only modules (Task 3)

`backend/tests/unit/test_package_layout.py` required the SQLite and PostgreSQL trees to
hold an identical set of modules, which the research library cannot satisfy: RAG requires
the authority store, so there is no SQLite repository to mirror. The test is now
`sqlite ⊆ postgres` plus an explicit `POSTGRES_ONLY_MODULES` allowlist
(`research_library/__init__.py`, `research_library/repository.py`), so an unlisted
divergence still fails. The plan attributed this edit to Task 1; the file list in Task 1
never included it.

### E10 — Migration 035 uses JSONB only in the PostgreSQL supplement, and keeps TEXT timestamps (Task 3)

The spec is silent on column types, so the plan's "Use JSONB only in the PostgreSQL
supplement" was followed: the common file creates every JSON payload as `TEXT` (SQLite
must be able to apply it — `test_default_migrations_apply_all_versions` proves it),
and the supplement converts 15 columns to `JSONB` in place. Writes therefore bind
`CAST(:param AS JSONB)`.

Timestamps stay `TEXT` in both dialects, matching `task_runs.lease_until` and the
existing PostgreSQL repositories. `_stamp()` normalises every write to UTC ISO-8601 so
the lexicographic `lease_expires_at <= :now` and `available_at <= :now` predicates stay
correct; the alternative (TIMESTAMPTZ in the supplement) would have diverged from the
established convention for no behavioural gain.

### E11 — The upgrade path for 035 was proven on a populated database, not a fresh one (Task 3)

`sectorpulse_test` already held migrations 1–34 when Task 3 ran, so
`PostgresDatabase.initialize()` applied the common file and the JSONB supplement in place
on an existing schema. Verified afterwards:
`schema_migrations` = 1..35 and `information_schema` reports the 15 payload columns as
`jsonb`. `test_incremental_migration_from_an_old_database.py` adds the same promise for
the common migration on SQLite: a file created before 035 gains the ten research tables
empty, with no invented rows, and still serves its pre-existing run.

### E12 — `requires_verification` is an INTEGER in the common migration (Task 3)

SQLite has no `BOOLEAN`, so the shared DDL uses `INTEGER ... CHECK (x IN (0, 1))`.
`psycopg` binds a Python `bool` as `boolean`, which PostgreSQL refuses to assign to an
`integer` column, so `PostgresResearchLibraryRepository` converts through `_flag()` on
write and `bool()` on read. This is the only boolean column the repository writes.

### E13 — The repository translates lease failures into `ResearchLibraryConflict` (Task 3)

The port promises one typed conflict when a precondition no longer holds, but the domain
raises `IngestionLeaseLost` / `InvalidIngestionTransition` for the same situations
(a live lease held by another worker, a terminal job). `acquire_ingestion_job` catches
both and re-raises `ResearchLibraryConflict` with the domain message chained, so callers
have one failure type to handle and the domain keeps deciding what is legal.

### E14 — Upload-key replay is idempotent; only a different hash under the same key conflicts (Task 3)

"Reject duplicate SHA within the same upload idempotency key" has two readings. Creating
a second row for a retried upload would defeat the key, and silently returning an
unrelated version would be worse, so `create_version` returns the existing version when
`(upload_key, original_file_hash)` matches and raises `ResearchLibraryConflict` when the
same key carries different content. Both cases are asserted.

### E15 — Asset integrity rules live in one shared module (Task 4)

Task 4's file list has `memory.py`, `minio.py`, and `scanner.py`. Key grammar, declared
hash/size verification, and the bounded read are identical for both adapters, so they went
into `backend/src/sector_pulse/infrastructure/research_library/assets/integrity.py`
instead of being written twice. The argument is not brevity: the MinIO adapter is the one
the offline gate cannot execute here, so a duplicated rule would drift on exactly the path
no test covers. `assert_unsafe_keys_are_refused_everywhere` runs the same key list against
both adapters precisely because the shared function is the only thing keeping them equal.

### E16 — The `minio`, `milvus`, and `live_rag` markers were registered in Task 4 (Task 4)

Task 4 Step 5 runs `pytest ... -m minio`, and `pyproject.toml` sets `--strict-markers`, so
`minio` had to exist before that command could run at all. `milvus` and `live_rag` were
registered in the same edit rather than in three separate ones; no test uses them yet.

### E17 — The MinIO adapter is unexecuted here, and says so (Task 4)

There is no MinIO server on this machine (`127.0.0.1:9000` and `:9001` refuse connections)
and the `rag` extra is not installed, so `test_minio_research_asset_store.py` skips with
`no dedicated MinIO test bucket is configured` rather than passing. The adapter therefore
has no passing evidence behind it in this environment, only the shared contract it is
written against; that is stated here so nobody reads the green offline gate as MinIO
coverage.

Two consequences were handled rather than hidden:

- The SDK is loaded through `importlib.import_module("minio")`. A static `import minio`
  needs a `# type: ignore`, and *which* code is correct depends on the environment
  (`import-not-found` without the extra, `import-untyped` with it) — mypy then fails on
  `unused-ignore` in whichever environment it was not written for. `importlib` removes the
  environment-dependent ignore entirely.
- `test_the_minio_adapter_explains_a_missing_sdk` asserts the failure is
  `AssetError("... install the 'rag' extra ...")`, not a bare `ImportError`. It skips
  itself if the SDK turns out to be installed, since the mode cannot then be exercised.

### E18 — `open()` is a context manager, so a bare call asserts nothing (Task 4)

The plan's Step 1 sketch ends with `with pytest.raises(AssetNotFound): store.open(ref.key)`.
That form passed vacuously: `@contextmanager` runs no body until `__enter__`, so the
lookup never happened and the test asserted nothing about either adapter. The offline run
went red (`DID NOT RAISE AssetNotFound`) and the contract now enters the context through
`open_must_fail`. Any later test that expects `open` to fail has to do the same.

### E19 — The upload size cap and the temp-file lifecycle have their own tests (Task 4)

`assert_asset_store_contract` never exceeds a size cap and never inspects the temp file
`spool_to_disk` creates, so `backend/tests/unit/infrastructure/test_asset_integrity_rules.py`
covers what the contract does not: an over-limit upload leaves nothing behind, the spool
file is unlinked on both the success and the failure path (checked by pointing
`tempfile.tempdir` at a directory the test owns), and a scan marker split across a read
boundary is still found. `spool_to_disk` closes the temp file before yielding its path —
on Windows an open file cannot be opened a second time, and every caller re-reads it by
path — which is why the `NamedTemporaryFile` carries `# noqa: SIM115`.

### E20 — `DocumentBlock` gained `source_span` (Task 5)

Spec 7.6 ("保留源字符范围，确保引用可以定位") and 7.7 ("记录规范化前后哈希和源字符范围")
both require the source character range, and §7.5's field list has nowhere to put it: a
Markdown or TXT block has no page and no rectangle, so dropping the range would drop the
only locator those two formats have. `DocumentBlock.source_span: SourceSpan | None` was
added to the Task 2 model, reusing the existing `SourceSpan` vocabulary. It is `None` for
PDF blocks on purpose — they locate themselves by page and bbox, and a second, uncomputed
locator would be a number nothing checks.

The Markdown fixture also changed: `## 美国市场` became `### 美国市场`. The test written in
Step 1 asserts both markets sit under `海外需求`, which is the document's actual structure;
the fixture had them as siblings.

### E21 — The pipeline owns `parser_version`, the extractors do not (Task 5)

`research_document_versions` (spec §21) has a single `parser_version` column, and Step 1's
test records `PARSE_PIPELINE_VERSION` on all three formats. What decides whether a document
must be re-parsed is never one extractor in isolation: swapping the PDF extractor, changing
a layout threshold, or changing how TXT wraps are joined all change the blocks. So
`ResearchParsePipeline.parse` stamps `PARSE_PIPELINE_VERSION` on the result and each
extractor keeps its own `PARSER_VERSION` for the case where it is used directly. Any change
to an extractor or to `LayoutPolicy` must bump the pipeline version; that rule is in the
module docstring rather than in a comment nobody reads.

### E22 — Parse limits are injected, not environment-configured (Task 5)

Spec 18.1 requires limiting file size and page count, but neither §21 nor the plan names an
environment key for them, and `RagSettings` (Task 2) explicitly owns "enabled, MinIO,
Milvus, collection alias, provider names/models, timeouts, concurrency, batch sizes,
retention, retrieval K, budgets and confidence thresholds" — not parse limits. Inventing
`SECTOR_PULSE_RAG_MAX_*` keys here would have put configuration in a task that does not own
it, so `DEFAULT_PARSE_LIMITS` lives in `ports/research_models.py` and is injected: the
pipeline checks `max_bytes` before dispatch (its purpose is not to open the file at all) and
passes the same object to the PDF extractor for `max_pages`. It sits in the port layer so
that the two call sites cannot end up with two different numbers. Wiring it to configuration
belongs to the task that owns the upload API.

### E23 — OCR output goes back through the same layout rules as native text (Task 5)

The plan says "merge OCR words into lines/blocks" but not with which rules. The OCR words
are converted to `ExtractedSpan`s (bbox as-is, line height as font size) and handed to the
same `group_spans_into_blocks`, so a scanned page and a native page of one document get the
same block granularity; a separate OCR-specific path would make the two halves of the same
report chunk differently. The provider's confidence becomes each block's
`extraction_confidence`, and the provider/model is aggregated per document — zero providers
or more than one yields `(None, None)` plus a warning, since the field attributes the parse
to one source.

### E24 — Two Step 1 assertions were corrected once the code existed (Task 5)

Step 1's sketch compares `extraction_method == "native"`, which is true for a `StrEnum`
member but not for the tests as finally written (`is ExtractionMethod.NATIVE`); the same
sketch calls the fixture `fake_ocr.pages`, and the fixture records `requested_pages` because
"pages" reads like the page list rather than the pages it was asked about. The one assertion
that was actually wrong rather than reworded was `test_the_quality_floor_is_configurable`:
it passed a 2-character span against `min_native_characters=5` and asserted `needs_ocr is
False`, which is the reverse of what the policy says. It now uses a 19-character page and
checks it against both the default floor of 40 and a lowered floor of 10, so the test fails
if the setting is ignored.

### E25 — PDF fixtures are generated at test time, and the builders are shared (Task 5)

Step 1 says "add tiny licensed/generated fixtures". The fixtures directory holds only
`industry_note.md` and `industry_note.txt`; every PDF is built by
`backend/tests/research_library_parsing_support.py` when the test runs. A committed PDF
cannot be reviewed in a diff, cannot be edited when an assertion changes, and carries its
own licence into the repository — and a "scanned page" would then be an opaque blob rather
than a structural fact (a page with a rendered image and no text layer). That module is also
where the fixture OCR provider and the fake-OCR builders live, because both Task 5 test files
need them and the plan's file list provides no shared home for them.

### E26 — Extractors extract, the pipeline normalizes (Task 6)

Step 3 attaches the normalization rules to the module the extractors feed, without saying
which side calls them. The split taken: an extractor says *here is a table, here is an image*
(it knows the format), and `_normalize_non_text` in `parsing.py` decides *what that content is
worth as evidence* (it knows the policy). Putting the rules inside each extractor would make
each format speak its own version of the same rule, and the Markdown, text and PDF parsers
would slowly drift apart on what counts as indexable. `ParsedDocument.tables` is the handoff:
keyed by `block_id`, so the extractor's structure and the block's text stay connected without
either side reaching into the other.

### E27 — An unindexable block leaves the block stream but stays in `non_text_blocks` (Task 6)

`indexable_text is None` is the only way this layer says "do not index". But a `DocumentBlock`
requires non-empty text, so keeping an unindexable block in `parsed.blocks` would mean either
relaxing that invariant or shipping an empty block — and Task 7 would then face "should an
empty chunk be embedded?" with no correct answer. The block is therefore dropped from the
stream and kept whole in `non_text_blocks`, which is where the locator (`page_number`,
`source_span`, `region`) is read from. Nothing is lost: an image with no caption is still
findable by a human, it just cannot be mistaken for an answer.

### E28 — `normalize_image` returns `None` for decorative images (Task 6)

Spec 7.10 says decorative images are excluded. That is a different statement from "not
indexable": a captionless image keeps its region so a human can look at it, whereas a logo
should leave no trace at all. Returning `None` is what lets the caller tell those two apart.
The `is_decorative` judgement itself belongs to layout detection, which is not in this layer's
field of view — the flag arrives from the caller, and this module only honours it.

### E29 — Chart and formula rules are implemented and tested, but have no producer yet (Task 6)

Specs 7.9 and 7.11 need a vision provider and a region cropper (PDF) or a formula detector
(Markdown), none of which exist in Tasks 5–6. `normalize_chart` and `normalize_formula` are
nevertheless implemented in full and covered by their own tests, because the rules are what
the spec pins down and they are cheaper to test directly than through a parser that does not
exist yet. `_normalize_block` deliberately has no branch for `BlockType.CHART`/`FORMULA`: a
branch with no input would hide the fact that the rule is not wired up, and silently doing
nothing is exactly how a "done" that is not done gets shipped. The producer arrives in the
task that adds region cropping, and the branch with it.

### E30 — `store_region` is called only from tests, and its document ids come from the caller (Task 6)

Step 3 requires region assets to go through `ResearchAssetStore`. The function takes
`document_id` and `document_version_id` rather than deriving them, because the object key is
the server's namespace and the ingest coordinator (Task 10) is what owns those ids — it is
also the first caller that will pass real ones. Until then the only callers are the tests,
which is the honest state of this function: implemented, exercised, not yet on the wire.

### E31 — `chunk()` takes the document identity as required keyword arguments (Task 7)

The plan's interface is `chunk(parsed, policy) -> tuple[ResearchChunk, ...]`, but Step 3
requires the chunk ID to include `document_version_id`, and `ParsedDocument` carries no
document identity at all — it is the parser's output, and a parser does not know which
document it was handed. Deriving an identity inside the chunker would mean inventing one,
and an invented identity would make two versions of the same document collide. So
`chunk(parsed, policy, *, document_id, document_version_id, created_at=None)` is the
signature the plan's own ID requirement implies; the two ids are the same ones Task 10's
ingest coordinator owns.

### E32 — `source.spans` are offsets into the chunk body, not into the original file (Task 7)

`ResearchChunk`'s validator requires `span.end <= len(content)`, and the chunk body is
*rendered*, not sliced: it is sentences rejoined, prefixed with the section path and
overlapped with the previous chunk's tail. That text does not exist as a contiguous range
in the source document, so an original-file offset would be a fabricated number. The route
back to the file is the one the spec already describes and this layer keeps intact:
`chunk → source.block_ids → normalized document → that block's page/coordinates or source
character span`. Each span here is still exact — it is verifiable against `content` — and
the tests assert both that it is in range and that it covers the text it claims to.

### E33 — A fragment always yields exactly one parent, and a heading-only fragment yields nothing (Task 7)

Every fragment produces one parent chunk unconditionally (when it holds at least one
readable block), rather than producing a parent only when there are multiple children.
Retrieval expands a child to its parent, and the alternative — a child whose
`parent_chunk_id` points at nothing — would make every consumer carry a special case for a
shape the spec does not describe. A fragment made only of headings is skipped entirely:
headings are structure, and a chunk whose whole body is `海外需求 > 欧洲市场` answers no
question and would only compete with the chunks that do. Headings still open their
section's parent body.

### E34 — A table row group is rendered by Task 6's `normalize_table` (Task 7)

`_table_slice` calls the same `normalize_table` the whole-table path uses, so a row group
and the full table phrase a row identically — same column labels, same unit, same "表名"
prefix. Rendering the slice with its own formatter would let a row read one way when
retrieved alone and another way when read as a whole, which is precisely the discrepancy
that makes a citation unverifiable. The table title, unit and columns are copied into
every group; the table's notes go only into the last group, because they describe the table
as a whole and repeating them is noise while dropping them loses them.

### E35 — Formula and chart blocks are never split, even above the soft cap (Task 7)

`_structural_groups` returns a single piece for them regardless of token count. A truncated
formula is still a formula, it still embeds, and it will be retrieved and cited as an
equation that does not exist — the same failure mode the spec cites for splitting tables.
Exceeding a soft budget is the lesser harm, and it is visible (the chunk is long) rather
than silent (the chunk is wrong).

### E36 — The default tokenizer is a documented approximation, not a real vocabulary (Task 7)

`ApproximateTokenCounter` (`cjk-approx-v1`) counts CJK characters as one token each and
splits the remainder on whitespace. Step 3 forbids downloading a model in tests, and the
token count decides chunk boundaries *and* chunk IDs — so a counter that varies by machine
or by model revision would break the one property the spec insists on: the same document
and the same policy cut the same chunks, on every run and in every environment. The
approximation is deterministic and explainable, and its error sits inside a budget that is
itself a range. A real counter arrives as a `TokenCounter` implementation with its own
`version`, at which point every chunk ID changes by design.

### E37 — Provider failures got their own error vocabulary in the port module (Task 8)

`ports/research_models.py` held only parse errors, and parse errors answer a different
question: "this file cannot be read" is decided once and for all, while "this call did not
land" may succeed on the next attempt with the same input. Task 14 has to spend money
based on exactly that difference, and reusing one exception for both would force it to
match on message strings to tell them apart. So `ProviderError` carries a
`retriable` bound per subclass (`ProviderTimeout` / `ProviderUnavailable` true;
`ProviderRejected` / `ProviderResponseInvalid` / `ProviderNotConfigured` false), and every
adapter raises from that set. The classes live in the port module rather than in the
adapter package because the fixture adapters raise them too — an error vocabulary that
only the HTTP adapters can express would leave the offline gate unable to reproduce the
paths the real adapters take.

### E38 — The RAG provider adapters are synchronous, and do not reuse the LLM client (Task 8)

`infrastructure/llm/openai_compatible.py` is `async`, per-agent priced, and reads prompts
from the registry; the RAG ports of Task 5 are synchronous and carry no conversation
history. The plan says "reuse the repository's safe HTTP patterns", which is what was
taken — retry with backoff, the timeout/HTTPError to error-code translation, the
`content`-may-be-a-list normalisation, and the injected `client`/`sleep` for tests. What
was deliberately *not* taken is the module: sharing one client would collapse
`SECTOR_PULSE_RAG_EMBEDDING_TIMEOUT_SECONDS` and `SECTOR_PULSE_RAG_NLI_TIMEOUT_SECONDS`
into a single number even though spec 21 configures them separately — embedding is a
high-concurrency batch call and NLI is a single call with a higher price per call. Each
adapter therefore owns a `ProviderEndpoint` value object with its own base URL, key,
model, timeout and retry budget.

### E39 — The claim adapter derives `claim_id` and validates every field itself (Task 8)

Two decisions the plan leaves open. First, `ExtractedClaim.claim_id` is computed from the
claim's lineage (`source_chunk_id`, span, statement) instead of being requested from the
model: an opaque model-generated string would differ on every retry, so the same fact
would be stored twice, and the ID exists precisely to recognise it as the same fact across
retries and replays. Second, each field is validated explicitly (`_text`, `_unit`,
`_stance`, `_time_range`, `_texts`) rather than letting a Pydantic `ValidationError` carry
the rejection: a wrapped shape error says "a field does not match a shape" where this layer
can say which part of the claim does not hold. The same reasoning rejects fenced or
brace-hunted JSON: a body whose boundaries had to be guessed cannot have its confidences
verified, and those confidences become evidence grades downstream.

### E40 — The fixtures return real structure, and fail loudly when nothing is declared (Task 8)

A fixture Embedding that returned one constant vector would reduce Task 11's hybrid
retrieval tests to "does the sort function sort", so `FixtureEmbeddingProvider` hashes
character bigrams into fixed dimensions (a deterministic hashing trick) and normalises —
deterministic, and closer for similar text. `FixtureRerankerProvider` scores by bigram
overlap and `FixtureNliProvider` decides from negation and overlap, both with explicit
override maps for table-driven tests. When nothing is declared for a page, an image or a
question, the fixtures raise `ProviderNotConfigured` rather than returning an empty or
default result: "this deployment is missing something" and "the provider says there is
nothing here" are different facts, and a fixture that conflated them would let Task 12's
"zero relevant claims" path pass without ever being exercised.

### E41 — The Milvus primary key is derived from `chunk_id + index_generation` (Task 9)

Spec 9.3 listed `chunk_id` as the primary key, while spec 19 requires writes to be
idempotent on `chunk_id + index_generation` and spec 16.2 requires the old and new
generations to coexist for the whole duration of a rebuild. These cannot all hold: with
`chunk_id` as the only key, staging a rebuild would overwrite the rows the live generation
is serving, so retrieval would point at the new vectors before the switch. Milvus primary
keys are also single-field, so the pair is stored as a derived value
(`pk = f"{chunk_id}:{generation}"`) with `chunk_id` and `index_generation` kept as separate
scalar fields. Spec 9.3 was corrected to say so; the port's `VectorRecord` still carries
neither field, because both are decided by `stage`'s argument and by `publish`'s action.
The Milvus integration test pins the consequence directly
(`test_the_same_chunk_in_two_generations_is_two_rows`).

### E42 — `IndexState` was already a domain concept, so the port does not redeclare it (Task 9)

The port first defined its own `IndexState` with the same two members.
`backend/src/sector_pulse/domain/research_library/models.py:38` already owns that enum from
Task 2, and a second definition would make an equality check between the two silently false
while both spell `PUBLISHED`. The duplicate was removed; adapters import the domain enum.

### E43 — The contract asserts no score values, and hits carry no per-list scores (Task 9)

Milvus performs fusion server-side (`RRFRanker`), so `hybrid_search` returns only the fused
score — there is no dense or BM25 score to hand back. `VectorHit` therefore has no
`dense_score` / `lexical_score`: a field that is always `None` on the real backend invites
caller logic that only ever works against the memory adapter. The contract follows the same
line and asserts only what both scorers must agree on: which candidates are reached
(`assert_keyword_and_meaning_both_reach_the_result` — a keyword-only match outranks a
semantically-nearest one, which fails if either recall half is dead) and that hits come back
in fused-score order. The RRF assertion is deliberately "first in both lists beats first in
one", because that ordering holds for any rank convention and any `k`, whereas a comparison
of raw fused scores would depend on whether Milvus ranks from 0 or 1. Lexical matching uses
`HITHIUM-2026`, a token no analyzer splits into a different pair than the query's, so the
lexical half behaves the same under the memory tokenizer and under Milvus's.

### E44 — What the Milvus adapter leaves unverified, and why (Task 9)

pymilvus is not installed and no server is configured, so all 21 Milvus contract tests SKIP
and **not one line of `vector/milvus.py` has ever been executed against a Milvus server**.
This is the explicit SKIP that Step 5 permits, but the honest reading is narrower than
"Task 9 passes": the memory adapter is verified, the Milvus adapter is written and
type-checks. Two calls in particular rest on documented behaviour rather than observation:

- `publish` uses `upsert(..., partial_update=True)` to flip `index_state`. Milvus 2.x has no
  `UPDATE ... WHERE`, and re-upserting whole rows is not an option here: the sparse vector is
  produced by the BM25 `Function` at write time and cannot be supplied by the caller, so a
  read-back-and-rewrite would store rows with a broken full-text index. If partial upsert is
  unavailable, `publish` fails loudly rather than silently publishing nothing.
- `published_at` and the effective window are stored as epoch seconds because Milvus has no
  date type, and the fields are declared `nullable=True`. A `null` fails every numeric
  comparison, which is what makes an undated record fall out of any window — the same rule
  the contract pins for the memory adapter.

Running the Milvus contract is a live-server step and is not claimed as done.

### E45 — `SearchFilters` has no `sector` or `companies` (Task 9)

Spec 11.1 lets A2 pass `sector` and `companies`, but spec 9.3's Milvus schema has no such
scalar fields. Accepting them here would produce a filter that silently filters nothing,
which is worse than not offering the field: the caller would believe a narrowed search
happened. They are instead expanded into the query text during query preparation
(spec 11.2 "查询准备提取：公司、板块、主题实体"), which is Task 11's job. What the index
filters on is exactly what it stores: document type, the published window, and whether
unverified leads are allowed.

### E46 — `TEXT` is spelled `VARCHAR(enable_analyzer=True)`, and the integration test needs a server (Task 9)

The plan says to use `TEXT(enable_analyzer=True)`. pymilvus has no `TEXT` datatype; the
full-text field is `DataType.VARCHAR` with `enable_analyzer=True`, and the BM25 `Function`
declares `content` as its input and the `SPARSE_FLOAT_VECTOR` field as its output.
`ensure_collection` also declares `SPARSE_INVERTED_INDEX` with `metric_type="BM25"` — the
analyzer flag alone is not enough to make the sparse half searchable.

The integration test refuses to run against a collection whose name is not marked as a test
collection (`_test` / `-test`) by *failing*, while it *skips* when nothing is configured or
the SDK is absent. The distinction matters: "nobody configured a test collection" is a
missing precondition, whereas "the configured collection is not a test collection" can only
mean production vectors, and that must stop the run rather than be skipped past.

### E47 — `transition_ingestion` produced a job its own model rejects, and `model_copy` hid it (Task 10)

Found by running the recovery path against real PostgreSQL, not by reading the code.

`IngestionJob` carries a validator that forbids a non-failed status from holding a
`failure_reason`. `transition_ingestion` builds each new job with `job.model_copy(update=...)`,
and Pydantic's `model_copy` **does not run validators**. The function set `failure_reason` on
the way into `RETRYABLE_FAILED` and never cleared it on the way out, so resuming a failed job
built an object the domain itself declares invalid — silently, because nothing re-validated it.
The first place that noticed was the `research_ingestion_jobs` CHECK constraint, whose violation
`save_ingestion_job` translates to `ResearchLibraryConflict`, which `ResearchIngestionCoordinator.run`
catches as "a concurrent writer won" and answers with `_current_state`. The observable result:
**a retriable failure could never be retried**, and every attempt to retry returned the stale
`RETRYABLE_FAILED` row with no new failure recorded — no error, no reason, nothing in the job to
say why. Six tests across two suites were red on it.

The fix is one line in `transition_ingestion`: `failure_reason` describes *this* failure, not a
history, so it is cleared whenever the target is not a failure status. Regression tests were
written first (`test_resuming_a_retryable_failure_clears_the_previous_failure_reason`,
`test_cancelling_a_failed_job_also_clears_the_failure_reason`, plus a positive case asserting two
failure statuses swap the reason rather than lose it) and they assert the result re-validates —
because `model_copy` is exactly the thing that will not do it for us.

### E48 — The in-memory fake was certifying a state the schema refuses (Task 10)

E47 has a second half, and it is the more uncomfortable one. `test_retrying_after_a_provider_failure_succeeds`
already existed and already passed offline. It passed because `InMemoryResearchLibraryRepository.save_ingestion_job`
only checked status and attempt, while `research_ingestion_jobs` also checks the
`failure_reason`/status pairing. The offline suite was green and the real database was red on
the same scenario — the failure mode a fake is supposed to prevent.

`saved_ingestion_job` now enforces the same pairing, with a comment saying why the duplication
is not redundancy. Verified load-bearing rather than assumed: with the domain fix reverted, the
offline suite goes from green to **4 failures** in the pipeline tests
(`test_retrying_after_a_provider_failure_succeeds`,
`test_a_half_written_generation_stays_invisible_after_a_successful_retry`,
`test_a_publish_failure_leaves_a_durable_intent_that_another_worker_finishes`,
`test_replaying_a_crashed_attempt_does_not_duplicate_chunks`), plus the 2 new domain tests.

### E49 — `research_document_versions_check1` makes provenance a precondition of activation (Task 10)

Spec 10 requires an ACTIVE version to record which index generation it came from, and the schema
enforces it: `status <> 'ACTIVE' OR (index_generation IS NOT NULL AND indexed_at IS NOT NULL AND
expected_chunk_count IS NOT NULL)`. This is stricter than "the coordinator happens to write
metadata first" — `activate_version` on a never-indexed version *fails*, and there is no way to
produce an ACTIVE version that cannot be reconciled against the index. Kept as a test of its own
(`test_the_schema_refuses_to_activate_a_version_without_index_provenance`) rather than worked
around, and the tests that need an ACTIVE version now go through `_complete_metadata` first,
which is the honest order.

The coordinator already satisfies this: `_publish_and_activate` writes `indexed_at` through
`save_version_metadata` immediately before the conditional `activate_version`, in that order.
The constraint and the code agree, which is worth stating because the constraint is what makes
that order non-optional.

### E50 — The retriable-failure backoff is the remaining lease, and it is deliberate (Task 10)

`RELEASING_INGESTION_STATUSES` covers `PUBLISHED`, `PERMANENT_FAILED` and `CANCELLED` but *not*
`RETRYABLE_FAILED`, so a retriable failure keeps its lease and nobody — not even the same worker
under a different `worker_id` — can pick the job up until it expires. Meanwhile the Outbox's
failed event is claimable on the next tick, because `CLAIM_STALE_SECONDS` applies only to events
left `CLAIMED`. The two clocks are independent by design.

The recovery test now asserts this instead of working around it: the second worker completes the
publish at `NOW + 5s` while the version stays `PROCESSING`, and the retry only starts at
`NOW + LEASE_SECONDS + 1s`, where it acquires attempt 2 and publishes. Writing it the first way
(a 6-second retry) is what surfaced the ordering, and the assertion that the version is still
`PROCESSING` after the Outbox succeeds is the part worth keeping: publishing a generation is not
the same event as activating a version.

### E51 — Task 10's gate results

- `backend/tests/integration/test_research_ingestion_pipeline.py` — 27 passed (offline fakes).
- `backend/tests/integration/test_research_index_publication.py` — 14 passed against real
  PostgreSQL, in a database named `sectorpulse_test`. The suite skips when
  `SECTOR_PULSE_DATABASE_URL` is unset and `tests/postgres_isolation.py` refuses any URL whose
  database name does not end in `_test`, so the business database is out of reach by construction.
- `backend/tests/unit/domain/test_research_ingestion_state.py` — 34 passed.
- Ruff clean over `backend/`; `mypy` clean over the 342 files it is configured to check.
- Full offline regression: **162 failed / 1008 passed** against a **168 failed / 1002 passed**
  baseline with the E47 fix reverted — the 6-test delta is exactly the retry path. The remaining
  162 failures are pre-existing and environmental (they need a built SPA under `web/dist`); none
  touch the research library.
- Frontend: 259 passed across 64 files.

Two of the three defects in this task (the shared parent/child chunk id from Task 7's review, and
E47 here) were found by running the code, not by reading it. That is the argument for the split
between the two test files: the in-memory suite can be made to exercise the logic cheaply, but
only the real schema can tell you which of the logic's outputs it will refuse.

### E52 — A parent and its child could share one `chunk_id`, and the fix raises the policy version (Task 7, found here)

Surfaced while building the Task 10 fixture: `_chunk_id` derived the id from the version, the
policy version, the counter version, the source spans and the content hash — but not from whether
the chunk was a parent or a child. For a passage with no section heading, the parent and the
child render the *same* text from the same spans, so both produce the same id. `chunk_id` is the
primary key in `research_chunks` and the write key in Milvus, so such a document could not be
stored at all: `append_chunks` would raise on the duplicate key, and the ingestion job would fail
permanently on a document that is perfectly ordinary.

Fixed by making the role part of the id (`ChunkRole.PARENT` / `ChunkRole.CHILD`) and raising
`CHUNKING_POLICY_VERSION` to `chunking-policy-v2`. The version bump is not bookkeeping: "re-running
the same policy on the same version yields the same ids" is the property that makes Milvus a
rebuildable derived index, and changing the id derivation without a new policy name would break it
while leaving the old promise in place.

The first regression test written for this passed for the wrong reason — it used a passage *with*
a section heading, where the parent renders a title the child does not, so the ids already
differed. Inspecting the actual collision showed it needs `section=()`, and the test now uses one
headed and one unheaded passage together. A test for an id collision that does not contain a
colliding pair is worse than no test: it certifies the bug is absent.

### E53 — Three port additions this task needed, and the shape they took (Task 10)

- `save_version_metadata(version, expected_status)` — a separate method from `activate_version`
  because "remember which index produced this" and "become visible" must have a state in between.
  It writes one group of columns at a time and refuses unless the version is still `PROCESSING`;
  the write is whole-group, so a caller that omits a column it is not changing will null it, which
  is why the coordinator reads-modifies-writes through the stored version rather than constructing
  a fresh one. `test_a_second_metadata_write_does_not_erase_the_first` pins that down.
- `get_original_asset_key(document_version_id)` — returns the object key only, not an asset
  description. Content type and hash come from `ResearchAssetStore.stat`, which is the only thing
  that knows what the object actually is; the authority store answers "where is the original".
  Rows with `deleted_at` set are not returned: "there used to be one" is not "you can read it".
- `enqueue_index_event` gained an explicit idempotency contract on `event_id`, and PostgreSQL
  implements it with `ON CONFLICT (event_id) DO NOTHING`. The coordinator names its publish intent
  after the generation (`idx_<generation>_publish_generation`), so replaying an ingestion records
  the same intent rather than a second one. `DO NOTHING` rather than `DO UPDATE` is the substance:
  re-registering an intent must not reset a `CLAIMED` or `FAILED` row back to `PENDING`, because
  that would erase another worker's claim and the reason it failed. Migration 035 has no unique
  index on `(document_version_id, index_generation, operation)`, so `event_id` is the only key this
  can honestly be built on.

### E54 — Failure classification is `ParseError` vs `ProviderError`, and unknown exceptions are retryable (Task 10)

`classify_failure` answers one question — would running it again help? — and the answer comes from
the error type, not from a string: `UnrecoverableIngestionError` and `ParseError` describe *this
file* and are permanent; a `ProviderError` carries its own `retriable` flag; `RetriableIngestionError`
covers "one more step is owed". Anything unrecognised is retryable, which is the conservative
direction: an unknown exception that is retried costs one re-run, whereas an unknown exception
called permanent silently drops a document. `max_attempts` exhaustion turns the last
`RETRYABLE_FAILED` into `PERMANENT_FAILED` with a reason that says so, because a job left
retryable forever is just a job that never finishes.

The distinction that mattered in practice was inside the publication gate, not at the edges:
"this generation is staged but not published" is *retriable* — the publish intent may be sitting in
the Outbox waiting for a worker, which is the one scenario the Outbox exists for — while a
generation holding records that do not belong to this version is *permanent*, because the vector
write is an upsert with no delete, so those records can never be removed by writing again.

### E55 — Four retrieval policy numbers went into `RagSettings`, not into the module (Task 11)

`max_candidates_per_document`, `duplicate_overlap_ratio`, `max_candidate_text_chars` and
`max_inspected_chars` are new settings with `SECTOR_PULSE_RAG_*` keys, even though spec 21's
listing does not name them. The listing is a set of *suggested* prefixes and already omits
`dense_top_k` / `bm25_top_k` / `fusion_top_k` / `rerank_top_k`, which exist; spec 11.3 says of the
retrieval pipeline "这些数量均为配置项", and these four are quantities in that pipeline. The
alternative — module constants — would put a number that a deployment may need to tune somewhere
ops cannot reach without a code change, and the reason each exists is a deployment property
(corpus shape, chunker overlap, answer length) rather than a property of the algorithm.

`duplicate_overlap_ratio` is checked as a *containment* ratio (how much of the shorter text is
covered by the longer), not as Jaccard. What it is meant to catch is one sentence cut twice, which
is an inclusion relation; Jaccard scores an inclusion as a middling similarity because the extra
tail of the longer passage inflates the union, so a Jaccard threshold either misses the duplicates
it was set for or starts merging genuinely different paragraphs.

### E56 — One port addition: `load_chunks` (Task 11)

Candidates carry page numbers and section paths. Those are not in the Milvus schema — the index
stores `chunk_id` and text and little else — so they come back from `research_chunks` with the
PostgreSQL recheck (spec 10), which means one batch read per retrieval. `get_chunk` already
existed, but looping it would turn every retrieval into N round-trips in the one code path that
runs on every question. `load_chunks` mirrors `load_version_statuses`, for the same stated reason,
and returns whole `ResearchChunk` rows rather than text because the locator is the point.

Unknown ids are silently absent from the result, matching `load_version_statuses`: the caller has
to be able to tell "not active" from "not found", and in the retrieval path both are reasons to
drop the hit rather than to carry on.

### E57 — `corpus_generation` is injected, not derived (Task 11)

Spec 17 requires the cache key to contain a `corpus_generation` that advances on publish, delete
and restore, and `RetrievalAuditRecord.corpus_generation` is `NOT NULL`. Nothing produces that
value yet — Task 14 owns `cache.py` — so the service takes a `Callable[[], str]` and does not
invent one.

Deriving it from the versions the retrieval happened to touch was considered and rejected: that
value would be a plausible-looking lie. A document published in a part of the corpus this
question never retrieves would not advance it, so a cached answer would survive exactly the
change the generation exists to catch. It is a callable rather than a string because it has to be
read at the moment of the search: reading it once at construction would conflate "the service is
alive" with "the corpus has not changed".

### E58 — `dense_candidates` and `bm25_candidates` stay empty in the audit (Task 11)

`VectorIndex.hybrid_search` returns `VectorHit`, which carries a fused score and nothing else;
fusion happens inside the index (`RRFRanker` on the Milvus side) and the per-half scores never
come back. That is a deliberate property of the port, argued in `ports/vector_index.py`: a field
that is always `None` invites logic that only ever works against the memory adapter.

So the audit records what the retrieval actually knows — the fused ranking with its scores, the
reranked order with its scores, and the candidates handed to the caller. Writing a reconstructed
per-half ranking would be fabricating the one thing an audit exists to make checkable.

### E59 — What `returned_evidence` holds today, and why (Task 11)

The field is written with the returned *candidates*, because that is what this task hands the
caller, and because it doubles as the authorisation list for `inspect`: "this retrieval issued
this handle" and "this handle may still be read" have to be the same fact, or one of them can drift
away from the other. Task 12–15 add claims and conflict decisions above this layer; when they do,
this is the field that has to keep meaning "what went out", and the accepted-evidence record is a
different thing (an A2 `internal_research_evidence` artifact), not a rewrite of this row.

The row is written once and never updated — `retrieval_id` is the primary key — so a second write
for the same retrieval is a conflict, not an update.

### E60 — The unverified-lead filter is applied twice, on purpose (Task 11)

`SearchFilters.include_unverified_leads` is passed to the index, which filters on the scalar it
stores. The service then re-checks `requires_verification` on the `ResearchChunk` it just loaded
from PostgreSQL. The duplication is the same argument `filter_active_hits` already makes for
version status (spec 10): the index holds a *copy* of a scalar that the authority store owns, and
a copy can be stale. It is testable only by staging a corpus where the two disagree, which is what
the `index_claims_verified` knob on the test harness does — one test, and removing the recheck
fails exactly it and nothing else.

### E61 — The service was mutation-checked, not just run green (Task 11)

All 35 unit tests passed on the first run against the implementation. That is a weak signal on its
own — it is also what a suite that asserts nothing would produce — so seven independent mutations
were applied to the service, each run, then reverted:

| Mutation | Tests that failed |
| --- | --- |
| drop NFKC + whitespace folding | `...full_width_question_and_a_half_width_one_share_a_fingerprint` |
| `_is_repeat` always false | `...repeats_another_in_the_same_section_is_dropped` |
| per-document cap disabled | `one_document_cannot_fill_the_whole_result`, `...slot_freed_by_the_document_cap...` |
| trust the index about verification | `...rechecks_verification_against_postgresql_not_the_index` |
| task/attempt binding removed from `inspect` | `...from_another_task_is_refused`, `...from_a_later_attempt_is_refused` |
| status recheck removed from `inspect` | `...whose_version_stopped_being_active_is_refused` |
| candidate text bound removed | `the_candidate_text_is_bounded` |

Each mutation failed exactly the tests that name the behaviour it removed, and no others. That is
the property the passing run could not have demonstrated.

### E62 — What this task does not verify (Task 11)

- **Milvus.** The retrieval tests run against `InMemoryVectorIndex`; the Milvus adapter still has
  never executed against a server (E44). Everything asserted here is asserted about the *service*,
  and the service talks to the port, so the tests do not become true of Milvus by passing.
- **No real provider was called.** Embedding and reranking are `FixtureEmbeddingProvider` and
  `FixtureRerankerProvider`, per the offline-gate rule. The fixture reranker scores by bigram
  overlap, which is why several tests pin explicit scores: relying on the fixture's own scoring to
  produce a *particular order* would test the fixture.
- **`inspect` has no audit of its own.** Spec 20.1 covers retrievals; who looked at which source
  is not recorded. If that becomes a requirement it belongs with the rest of the audit in Task 14.
- **Synonyms have no configured source.** `_prepare_query_text` expands a glossary that the caller
  injects; nothing loads one yet. Spec 11.2's "行业缩写和受限同义词" is honoured in shape (bounded,
  additive, original question retained) but the table itself is empty until something supplies it.

### E63 — Grounding is checked against the span, not the chunk (Task 12)

Spec 12 says the span "必须精确匹配 chunk 原文" and that facts the original text cannot support are
rejected. Those two sentences admit either reading, so the stricter one was taken: the subject, the
object and every qualifier must appear inside the text the span selects, not merely somewhere in the
passage. The looser reading would make `source_span` decorative — a claim could name a subject that
appears in the passage and quote a span about something else entirely, and the field that exists to
say "this is what I read" would not be checking anything.

The consequence is deliberate: a narrow span rejects a claim whose evidence lies outside it. That is
the point. An extractor that wants to assert something a single sentence does not contain has to
widen its span, and widening it is visible in the audit.

### E64 — The predicate is exempt from grounding, and the assertion is subject + object + qualifiers (Task 12)

Spec 12's own example carries `"predicate": "增长情况"`. That string is a normalised property label,
not a phrase any report writes; requiring it to appear in the source would be requiring the document
to use our field names. So the components that are checked are the ones a document actually contains:
`subject`, `object`, and each `qualifier`.

`statement` itself is not checked as a literal string either. It is a composition of those components
— spec 12's example statement ("海外储能订单在2026年第二季度明显增长") does not appear verbatim in any
reasonable source, and demanding that it did would reject the spec's own example. Validating the parts
is both stricter than validating the whole (each part must be present) and more honest (a paraphrase
that adds no content is accepted; one that adds a number is not).

### E65 — Entity normalisation is mechanical; the alias table is injected (Task 12)

`normalise_entity` folds NFKC, removes whitespace and casefolds. It does not know that `CATL` and
`宁德时代` are the same company and must not: that is a fact about the world, and a hard-coded table
inside a grouping function would silently fail on the third spelling a real corpus uses.
`group_comparable_claims` therefore takes an optional `aliases` mapping, applied to the normalised key
so a caller may write its keys in any case. **Nothing supplies that table yet** — the same gap as
Task 11's synonym glossary (E62), and it belongs with the governance configuration that spec 14 rule 4
("来源权重由资料治理配置") will need.

Whitespace is removed rather than folded because PDF extraction inserts line breaks mid-word; a
subject split across two lines is one subject.

### E66 — Time comparability is an edge, not a grouping key (Task 12)

Spec 13 lists three conditions, and the third — "时间范围重叠或存在可比较关系" — relates *two* claims
rather than describing one. Putting it in the bucket key is impossible; folding it into a pairwise
check inside a bucket walks back toward the Cartesian product spec 13 forbids. So a group is a
connected component: claims are connected when their windows overlap.

The bridge case is why this is not merely elegant. With Q1, Q2 and a claim covering the whole year,
first-fit would attach the third claim to whichever quarter it happened to see first and leave the two
quarters in separate groups; the resulting decision would then depend on the order the model emitted
claims in. `test_a_claim_bridging_two_disjoint_ones_merges_them_into_one_group` pins that.

A claim with no `valid_time` is comparable with anything. Excluding it would turn "I did not record a
window" into a way of escaping comparison.

Disjoint windows are **not** grouped, so a Q1 claim and a Q2 claim never reach NLI. Task 13 should
note this: its "different effective times are not conflict" case must be built from *overlapping*
windows (a year against a quarter, say), because fully disjoint windows are filtered here and will
never produce a `NOT_CONFLICT` decision.

### E67 — Only groups of two or more are returned, in first-appearance order (Task 12)

A lone claim has nothing to compare against, and `ConflictDecision.claim_ids` already requires at
least two (it is a pair's verdict). Returning singletons would invite a caller to construct a
decision for a group of one. Task 13 assigns `NOT_CONFLICT` to ungrouped claims without needing a
group object to do it.

Order is first appearance for groups and arrival for claims inside them, not sorted. Both orders are
cited by position in the audit, so an order that came from the alphabet would report the same facts
under different numbers than the order they arrived in. `海外` sorts after `欧洲` by code point, which
is why the ordering test uses those two.

### E68 — The extractor owns relevance; the service owns admissibility (Task 12)

Spec 12's "只从 Rerank 后的 Top-N 中提取与当前问题有关的事实" has two halves, and only the second is
here. The candidates *are* the Top-N, and the question is passed to the provider; which facts in a
passage answer the question is a judgement, and re-deriving it with a string comparison would either
duplicate the reranker's scoring or quietly disagree with it. What this layer decides is narrower and
mechanical: whether a claim is admissible at all.

Zero candidates short-circuits before the provider is called — a request with no chunks is invalid by
construction (`ClaimExtractionRequest.chunks` has `min_length=1`), and paying for an empty call would
be paying for nothing.

### E69 — Claims are not persisted, and the class cannot persist them (Task 12)

Spec 12: extraction results belong to the current retrieval run by default; only claims that are
adopted or enter conflict resolution are saved with the audit. `ClaimExtractionService` therefore
takes a provider and settings and **no repository at all** — it has nothing to write with. That is
stronger than a promise not to write, and it is the reason no test asserts "nothing was stored":
there is no code path that could.

The `min_claim_confidence` setting gets its first consumer here. It existed in `RagSettings` from
Task 1 with no reader; a claim below it is not returned, because a fact the extractor itself is unsure
of cannot be the thing a report rests on. The comparison is `<`, so the floor is inclusive — pinned
by a test, since an off-by-one here silently discards exactly the claims at the boundary.

Duplicate `claim_id`s are kept once. Two copies of one claim would place the same fact in two groups
and, in Task 13, produce a conflict between a claim and itself.

### E70 — Open item: the claim extractor's provider version is not obtainable (Task 12)

`RetrievalAuditRecord.provider_versions` has to name every model that contributed to an answer, and
spec 20.1 lists the claim extractor among them. The port as it stands returns a bare
`tuple[ExtractedClaim, ...]` — no provider, no `model_version`. Task 11 hit the same shape with
`RerankerProvider` and solved it by reading the versions off the *result* (`RerankResult` carries
them), which is also the more honest source, since a provider swapped underneath a cached instance
would otherwise be missed.

There is no equivalent place to read them from for extraction, so Task 14 has to choose: widen the
port to return a result object carrying the attribution, or accept an adapter attribute and the
weaker guarantee that comes with it. Not changed here — the plan gives Task 12 no interface change,
and picking one now without the audit in front of it would be guessing.

### E71 — Wiring requirement for the extraction prompt (Task 16/17)

`CLAIM_INSTRUCTION` in `providers/openai_compatible.py` currently says the span is "statement 在该片段
文本里的字符区间". That is compatible with E63 in the case that matters — a model quoting the sentence
it drew from produces a span containing everything it asserted — but it does not *tell* the model that
the span must contain the asserted content. A model that paraphrases more freely than the sentence it
quotes will have its claims dropped wholesale rather than flagged.

The prompt was not edited: it is a Task 8 artifact whose contract tests pin its behaviour, and Task 12's
plan gives no file there. Recorded so the change is made deliberately when the prompt is next touched,
together with a live check that real extractions survive validation.

Verified offline in the meantime: `FixtureClaimExtractorProvider` and this validator agree when the
fixture's span covers what it asserts, and disagree exactly when the span is a truncated prefix of the
statement — which is the behaviour E63 asks for.

### E72 — Mutation check (Task 12)

All 29 tests passed on the first run, so the suite was checked against 18 mutations of the
implementation. Each was applied alone, the suite re-run, and the file restored:

| Mutation | Test that caught it |
| --- | --- |
| span bounds check removed | `a_span_that_runs_past_the_end_of_the_chunk_is_dropped` |
| grounding checked against the whole chunk | `content_present_in_the_chunk_but_outside_the_span_is_still_dropped` |
| unknown chunk validated against another chunk's text | `a_claim_citing_a_chunk_that_was_never_sent_is_dropped` |
| object not required to appear in the source | `an_object_that_contradicts_the_span_is_dropped` |
| qualifiers not required to appear in the source | `a_qualifier_the_span_does_not_contain_is_dropped` |
| confidence floor removed / made exclusive | `a_claim_below_the_confidence_floor...`, `...exactly_at_the_confidence_floor_is_kept` |
| duplicate claim ids kept | `the_same_claim_returned_twice_is_kept_once` |
| empty candidate list no longer short-circuits | `no_candidates_means_no_provider_call_at_all` |
| entity normalisation loses case folding | `matching_survives_full_width_digits_and_letter_case` |
| every claim is time-comparable | `claims_whose_times_do_not_overlap_are_not_comparable` |
| claims never join through a bridge | `a_claim_bridging_two_disjoint_ones_merges_them_into_one_group` |
| subject / property ignored when grouping | `different_subjects_are_never_paired`, `different_properties_are_never_paired` |
| aliases not applied to subjects | `an_injected_alias_merges_two_names_for_one_entity` |
| groups sorted instead of first-appearance order | `groups_appear_in_the_order_their_subjects_first_appeared` |

Two mutations were missed on the first pass and both were test defects rather than holes in the
implementation. The ordering test used `海外储能订单` and `欧洲储能订单` in an order that happened to
match sorted order, so sorting changed nothing; it now lists `海外` first. Two grouping mutations were
caught by `ComparableClaimGroup`'s `min_length=1` on the key fields rather than by the assertion —
they were re-run with non-empty constant keys so that the assertions, not a validation error, are what
fails. The key fields keeping their non-empty constraint is itself load-bearing: an empty grouping key
is unrepresentable, so "the key was not computed" cannot be mistaken for "the key is empty".

### E73 — What this task does not verify (Task 12)

- **No real extractor was called.** The provider is a stub returning what the test staged; per the
  offline-gate rule no LLM was reached, and E71 records what has to be checked when one is.
- **Grounding is not entailment.** A string check confirms the asserted words are in the span. It
  cannot detect a claim that quotes real words and reverses their relation; that is what Task 13's NLI
  call and spec 14's resolver exist for, and nothing here reduces that need.
- **Nothing is grouped against the corpus.** Grouping sees only the claims from this retrieval, so two
  sources that contradict each other only enter one group if both were recalled by this question.
  Spec 11's recall bounds the conflict detection, and no test here can widen that.
- **Aliases, synonyms and source weights have no configuration source** (E65, E62). Three functions
  take injected tables that nothing populates yet.

### E74 — The offline regression is only a regression result when run from the repository root (Task 12)

Measured today, same working tree, same command, differing only in the directory it was launched
from:

| launched from | result |
| --- | --- |
| repository root | `1234 passed, 133 skipped`, **0 failed** |
| `backend/` | `162 failed, 1072 passed, 133 skipped` |

The 162 are the SPA-serving tests in `backend/tests/unit/web/`. They resolve `web/dist` relative to
the process's working directory; `web/dist` exists and was built on 15 September, but
`backend/web/dist` does not. Running from `backend/` cannot find a build that is there.

This makes the "162 failed" figures in E51 and in this plan's earlier gate notes a measurement
artifact rather than a property of the tree. Both invocations collect the same tests — 1008 + 162 =
1170 before Task 11, 1043 + 162 = 1205 after it, 1234 now — so those 162 were passing from the root
the whole time, and the "delta is exactly +35" observation was a delta measured against a baseline
that was already zero.

The reason this is worth its own entry rather than a footnote: a standing baseline of 162 failures
makes a real regression invisible. A genuine break would show up as 163 and read as "one more of the
same". From here on, the offline regression runs from the repository root, and a total that was
collected from anywhere else is not a regression result — which is also what the plan's own final
acceptance command does (`pytest -q -m "not live and ..."`, with no path argument, so `testpaths`
supplies `backend/tests` and the rootdir is the root).

### E75 — The verdict is an input to the resolver, not something it fetches (Task 13)

`resolve_conflict(pair, metadata, policy)` takes the `NliVerdict` in `metadata` instead of holding a
provider, which is the whole reason spec 22.3's "exhaustively table-driven, no real model" is
achievable: `fixtures/research_library/nli_cases.yaml` feeds in every conclusion a model could return
and asserts what the rules do with it. 28 rows; 109 tests (28 × 3 table assertions + 25 behavioural).
A meta-test asserts the table's `rule` column covers all six `ConflictRule` values plus `None` and its
`status` column covers all four `ConflictStatus` values, so deleting a row turns the suite red rather
than quietly shrinking the claim of exhaustiveness.

### E76 — The table pits adjacent rules against each other, not just exercises them (Task 13)

A row that exercises STATUS proves STATUS exists; a row where STATUS and SOURCE_WEIGHT disagree proves
STATUS *outranks* SOURCE_WEIGHT. Five rows are of the second kind (status vs weight, explicit version
vs weight, effective time vs weight, weight vs evidence quality, and an archived ACTIVE-vs-newer pair),
and the mutation harness includes one that swaps rules 4 and 5 in the source. Without those rows that
swap is invisible: every other row has the two rules agreeing.

### E77 — Disjoint effective times are decided before NLI, including when the check failed (Task 13)

`_windows_are_disjoint` is consulted first. Two claims about provably different periods are not a
conflict regardless of what the model would have said, so a provider outage must not turn them into
`CHECK_FAILED` — that would report "unknown" where a deterministic answer exists. This does weaken
"a failed check is never reported as no conflict" in one direction, and only that one: the resulting
`NOT_CONFLICT` carries `rule=EFFECTIVE_TIME`, so the audit says *why* it was not a conflict rather than
resting on the absence of a verdict. Row `disjoint_windows_beat_a_failed_check` pins the ordering.

### E78 — A non-RESOLVED decision may still name a rule (Task 13)

`NOT_CONFLICT` reached through disjoint windows carries `rule=EFFECTIVE_TIME` and no selection;
`NOT_CONFLICT` reached because NLI said ENTAILMENT/NEUTRAL carries no rule at all. `ConflictDecision`
permits both (it requires a rule when RESOLVED and forbids a selection otherwise). Two assertions in my
first fixture-validation probe assumed the opposite and were wrong — the model was right and the probe
was over-strict, which is the direction that matters: the constraint is "no winner without a rule",
not "no rule without a winner".

### E79 — The confidence floor is inclusive at its own value (Task 13)

Below `min_nli_confidence` → `UNCERTAIN`; exactly at it → trusted. Row
`a_verdict_exactly_at_the_threshold_is_trusted` sits on 0.70 so the boundary is pinned from both sides,
because a table of 0.4 and 0.9 confidences cannot distinguish `<` from `<=`. This matches Task 12's
`min_claim_confidence` (E69), so the two thresholds are read the same way.

### E80 — `nli_relation` records the effective relation, `nli_confidence` the raw measurement (Task 13)

Spec 13 says a below-threshold result *is* uncertain, so the column reads `UNCERTAIN`; the raw
confidence is preserved unchanged, and the rationale names what the model actually said
(`模型给出 CONTRADICTION（0.40），低于阈值 0.70`). Recording the downgraded relation while discarding
the number would make "how far below the floor was it" unanswerable from the audit.

### E81 — `ClaimSource` derives its grade instead of carrying one (Task 13)

It holds `content_origin` and `requires_verification` and exposes `grade` as a property computed by
`evidence_grade(...)`. A stored grade could disagree with the inputs that are supposed to determine it;
a derived one cannot. `requires_verification` overrides the origin rather than adjusting it, so a
native-text vision-era lead is `DERIVED_UNVERIFIED` — if good provenance could restore it, the
verification flag would be an annotation rather than a downgrade (spec 7.9).

### E82 — `published_at` and `uploaded_at` are deliberately absent from `ClaimSource` (Task 13)

Spec 14 requires the three time fields to stay distinguishable, and they are: the field the rules read
is named as what they read it as (`ExtractedClaim.valid_time`, the effective time), it is what rule 3
compares against the question window, and it is what gets appended to the NLI text. `published_at` and
`uploaded_at` are audit facts about a document version — no rule consults them, and carrying unread
fields is how a resolver starts making decisions nobody wrote down. Task 14's audit is where they
belong; adding them to `ClaimSource` later is additive.

### E83 — Source metadata is keyed by `chunk_id` and an unknown chunk raises (Task 13)

`ConflictContext.sources` maps `chunk_id` → `ClaimSource`, and `ClaimSource` does not also store its own
`chunk_id`: a key and a field holding the same identity is two answers to one question, and they
eventually differ. A claim citing a chunk that is not in the map raises `UnknownClaimSource` — the
opposite of `ClaimExtractionService`, which drops such a claim. The asymmetry is deliberate: there the
claim is model output and may be entirely invented; here extraction has already validated chunk
membership, so a miss means the caller forgot to pass a source. Silently skipping the pair would erase
a real conflict from the audit while leaving both claims looking processed.

### E84 — Pair selection and its deliberate blind spot (Task 13)

A pair is sent to NLI when the two claims come from different `document_version_id`s, or from the same
version with differing `stance`. Same version *and* same stance is skipped, which means a version that
contradicts itself is not detected — recorded as a known bound rather than an optimisation: comparing
two halves of one passage reliably produces conclusions about the passage rather than about the corpus.
`ClaimStance` therefore has a real effect on the bill for the first time; before this task nothing read
it.

### E85 — Two table rows had to set `stance: opposing` to stay reachable (Task 13)

Rules 5 and 6 fire only when the earlier rules tie. Within one version the evidence grade always ties
(same chunk provenance ⟹ same grade), so rule 6 is reachable exactly for two chunks of one version
whose stances differ — and only then, because otherwise E84 skips the pair. The two same-version rows
originally left the default `supporting` stance, which meant the table asserted a path production never
walks. They now declare the opposing stance.

### E86 — A missing ranking score is not a low one (Task 13)

When one side has a `relevance` and the other has `None` inside a single source, no winner is chosen
(row `a_missing_ranking_score_is_not_a_low_one`). Reachable because reranking can cover only part of
the candidate list, so "this chunk was never scored" and "this chunk scored badly" are different
states. Treating a missing measurement as a low one would decide the conflict with a number that was
never taken.

### E87 — Only `ProviderError` is read as an outage (Task 13)

`_classify` catches `ProviderError` and lets everything else propagate, with its own test
(`test_a_programming_error_is_not_mistaken_for_a_provider_outage`). Catching broadly would file a code
defect in the audit under "external outage" and mark the pair `CHECK_FAILED`, which is a true statement
about nothing.

### E88 — One failed check fails one pair (Task 13)

A provider failure marks only its own pair `CHECK_FAILED`; the remaining pairs in the same run continue
and are decided normally. Abandoning the batch would let one timeout erase conclusions that are still
derivable.

### E89 — What this task does not verify (Task 13)

- **No real NLI model was called.** The verdict is a fixture input; per the offline-gate rule no model
  was reached, and spec 22.3's dataset categories (units, condition scope, forecast vs observed, OCR
  typos, subject confusion) are represented by rows asserting the *resolver's* response to a verdict,
  not by any measurement of a model's behaviour on them. A real provider may return CONTRADICTION where
  the table assumes NEUTRAL, and only a later gated run can say.
- **"Return both source refs for UNRESOLVED" is satisfied here only as both `claim_ids`.** The
  `source_refs` tuple lives on `RetrievedEvidence` / `InternalEvidenceClaim`, which are assembled in
  Tasks 15 and 16; this layer holds no candidates and cannot build them.
- **Nothing is persisted.** Decisions are returned as a tuple. `RetrievalAuditRecord.conflicts` is
  populated by Task 14.
- **No cache, budget or timeout bound is applied to NLI calls.** `ConflictService` calls the provider
  and catches its errors; counting calls, reserving CNY and enforcing deadlines is Task 14.

### E90 — Mutation check (Task 13)

All 109 tests passed on the first run, so the suite was checked against 33 mutations of
`conflicts.py`. Each was applied alone, the suite re-run, and the file restored (verified afterwards:
no mutation residue in the file). **33 applied, 33 caught, 0 missed, 0 inapplicable.**

The harness asserts each mutation's anchor string occurs exactly once, so a mutation that silently
fails to apply is reported rather than counted as caught. Coverage: each of the six rules removed,
inverted or applied out of order; the cross-document guard on rule 2; the `<=`-vs-`<` boundary on the
threshold; the None-verdict branch reclassified as `NOT_CONFLICT`; the UNCERTAIN branch reclassified as
agreement; entailment reclassified as conflict; the time qualifier dropped from the NLI text; both
branches of `_needs_nli` disabled; `except ProviderError` widened to `except Exception` and narrowed to
a re-raise; one-pivot pairing substituted for all pairs; pair order reversed; the unknown-source guard
disabled; provider attribution and the rationale dropped from the decision; the query window dropped
from the metadata; and the disjoint-window pre-check removed.

### E91 — A process mistake worth recording: `write_text` rewrote the plan's line endings (Task 13)

The plan file is CRLF throughout (E74's neighbourhood, E63–E74). Ticking Task 13's checkboxes with
`Path.read_text()` + `Path.write_text()` silently rewrote all 1884 lines to LF: `read_text` applies
universal-newline translation, so the `\r` never reaches the string being written, and no error is
raised because the *content* is unchanged. The file is untracked, so git could not have restored it.

Detected by counting bytes immediately after writing (`CRLF: 0, bare LF: 1884`), and restored by a
byte-level `raw.replace(b"\n", b"\r\n")` guarded by assertions that no `\r\n` and no stray `\r` were
already present. Verified afterwards: 1884 CRLF, 0 bare LF, 0 stray CR, 59 ticked step boxes intact.
The rule for this file is that every read and write touches bytes, never `str`.

### E92 — Gate results (Task 13)

| Gate | Result |
| --- | --- |
| Task 13 tests | 109 passed |
| Full offline regression, repo root | 1343 passed, 133 skipped, 0 failed (baseline 1234 + 109 new) |
| Frontend (`cd web && npm test`) | 259 passed, 64 files — unchanged |
| Ruff (`check` + `format --check`) | clean on both new files; `evidence_grade` import dropped as unused (exercised through `ClaimSource.grade`) |
| Mypy | success, 345 source files |
| Pre-existing modifications | 32, untouched; all Task 13 work is in untracked new files |

### E93 — Plan correction: three files the plan did not name (Task 14)

The plan's Task 14 file list named `audit.py`, `cache.py`, `observability.py`, `tool_budget.py` and the
two test files. Three further files were necessary, and none of them is a change of architecture:

1. **Create `application/research_library/provider_calls.py`.** The plan says "use the existing budgeted
   tool/provider semantics", but `SharedToolBudget.admit` had no lease rule and no per-provider cap, so
   those become two new arguments — and an argument needs a caller. Putting the adapter inside
   `tool_budget.py` was rejected: that module is orchestration-generic and would have had to import the
   research-library audit and observability modules. `provider_calls.py` imports the other way, keeping
   the dependency pointing from the library into orchestration.

2. **Modify `application/research_library/retrieval.py`.** It wrote `candidate.model_dump(mode="json")` —
   the document body included — into `returned_evidence`, while spec 20.1 says the audit carries handles
   and locators and the body stays in the authoritative store. This is the same class of defect E71
   recorded for the extraction prompt: existing code that passes its own tests while contradicting the
   spec. Task 14 owns `returned_evidence` (the plan's own note on `RetrievalAuditRecord` says its ranking
   fields are "由 Task 14 决定最终形态"), so the fix belongs here. `inspect` reads only
   `entry["chunk_id"]` from this field, so narrowing it keeps inspection working — asserted by a test that
   inspects a source after a search.

3. **Modify `infrastructure/research_library/providers/openai_compatible.py`.** `_send` passes
   `timeout=self._endpoint.timeout_seconds`, but the class exposed no way to read that value. The adapter
   refuses to assemble when the provider's applied timeout and its configured limit disagree, and records
   `None` (unknown) when neither is available — a timeout in the audit that nobody enforces is worse than
   a blank one. That refusal needs the property; hence the addition.

Two places where the spec is silent and a choice was made, recorded rather than presented as derived:

- **The lease check is a liveness check, not an ownership check.** `admit` receives no caller identity, so
  it cannot establish *which* caller is asking. It verifies the task is `RUNNING` and its lease has not
  expired, with attempt currency checked separately. That covers the failure that matters — a worker whose
  lease expired (partitioned, then recovered elsewhere) continuing to spend the run's money — and the code
  says so rather than implying an ownership guarantee it cannot make.
- **The two OCR ratios share the page denominator.** Spec line 813 lists `OCR 页面占比` and `低置信度比例`
  in parallel without naming a denominator; the shared one (`low_confidence_pages / pages`) was chosen so
  the two numbers stay comparable on the same base.

### E94 — What the audit may contain, and the leak that was already there (Task 14)

`candidate_reference` is a **subtraction**, not an addition: it dumps the candidate and removes `text` and
`retrieval_id`. The direction matters — the next field added to `RetrievedCandidate` is recorded by
default, so the failure mode is "we recorded something new" rather than "we silently stopped recording the
location". The retained 13 keys are asserted as an exact set, so a future field has to be looked at
deliberately.

`safe_result_reference` accepts identifier characters only (`[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}`, joined by
`/`), and its exception message carries only a **length**, never the rejected text — an exception message
is transcribed into logs, tickets and alert titles, so quoting the body there would defeat the whole rule
through a different door. Tested with a provider whose self-reported model version *is* a document body.

The whole audit, the plain-log projection and the metric snapshot are each serialised and then searched
for the corpus text and the question, rather than asserted field by field: a body written into a free-text
field is invisible to a test that reads back only the fields it expects.

### E95 — Corpus generation is a fingerprint of corpus state, not a counter and not the index generation (Task 14)

`CorpusGeneration` hashes the state the corpus is actually in: per document its soft-deletion flag, source
weight and current version, and per version the nine fields that can change what is retrievable (number,
status, index generation, embedding model, chunking policy, parser and OCR model versions, expected chunk
count). Publish, delete, restore and re-weight each move it — all four are driven by tests — plus one
asserting it does **not** depend on the clock.

It is deliberately not the index generation (`gen_…`): the index is a rebuildable derivative (spec 9.4), so
keying on it would invalidate the whole cache on every rebuild while possibly still serving a corpus that
genuinely changed.

The scan is bounded and refuses to guess: `list_documents` has one page and no offset, so a full page
raises `IncompleteCorpusScan` rather than computing a generation from half the corpus — the half that was
not read would never be served from cache, and would look exactly like a correct generation.

`conflict_policy_version` is derived from the policy fields that exist (a hand-written version number
drifts from the policy it names), and the cache key **refuses to be built** when any model version is
missing rather than substituting a placeholder for a version it did not observe. `NO_NLI_MODEL` is only for
a retrieval that genuinely ran no NLI.

One consequence is recorded because it constrains the design: the key cannot be looked up *before* the
provider call, because provider model versions exist only on results (`EmbeddingBatch.model_version`), not
on the provider protocol — Task 11 deliberately moved version reporting from results into the audit. So
`corpus_generation` is injected into the service as a callable and the key is assembled from what the audit
recorded; a test rebuilds the key from a stored audit to prove the audit carries enough.

### E96 — A retry is another external request (Task 14)

`openai_compatible` retries 429/5xx internally and explicitly defers timeout retries upward ("上层（Task
14）知道这次的预算还剩多少，这里只知道超时了"). The adapter therefore retries only `ProviderTimeout`, and
each try is admitted, settled and ledgered separately: the ledger holds `call-1`, `call-1:r1`, `call-1:r2`
with FAILED/FAILED/SUCCEEDED and try numbers 1..3. `ProviderUnavailable` is not retried a second time — two
layers of retry multiply.

When a retry cannot be afforded, the budget error is raised **with the timeout attached as `__cause__`**:
stopping was a budget decision, and reporting the timeout would tell the caller that trying again might work
when no request will go out. A denied call is never laundered into a settled outcome either — the
`CHECK_FAILED` path in `ConflictService` catches `ProviderError` only, so `ToolBudgetExceeded` (a
`RuntimeError`) propagates out of `check`, asserted with an NLI stub whose upstream is never reached.

Failure accounting is deliberate in two places: a request that failed is still settled at the configured
price (a zero would keep the run underestimating what it spent), and a caller-side coding error settles as
`UNKNOWN` rather than `FAILED` (whether the request left the process is genuinely unknown, and `FAILED`
would be the adapter speaking for the provider).

### E97 — What cannot be derived, and therefore is not (Task 14)

`VectorHit` carries no per-side score and `hybrid_search` returns only fused hits (the port's own docstring:
to find out why one side missed, use `verify` and the audit, "不是靠猜分数"). So `record_retrieval` never
synthesises a Dense/BM25 contribution — only `record_recall_contribution`, called by an index that *can*
report both sides, writes those two metrics. A test asserts the samples are absent after a real retrieval,
so the absence is a property rather than an omission.

The same reasoning produced `ProviderCallReplay`: the ledger keeps a result *reference*, not a result, so a
replayed `call_id` is refused rather than answered "already done". Answering without the vector would mean
inventing one. Callers that want reuse want a cache, keyed by input fingerprint (E95).

An "unattributed" role became a real label value rather than an empty one: an empty label and an absent
label collapse into the same series in a time-series store, so a caller that did not report a role would be
indistinguishable from one that did not exist.

### E98 — Mutation results (Task 14)

Twelve mutations, each applied alone, the four most relevant suites re-run, and the file restored from the
original bytes. The harness asserts every anchor occurs exactly once, so a mutation that fails to apply is
reported instead of counted as caught. **12 applied, 12 caught, 0 missed, 0 inapplicable.**

Removed or inverted: the reference length cap; the body-stripping in `candidate_reference`; the replay
refusal; the retry call-id suffix; the charge for a failed request; the live-lease rule; the per-provider
cap; soft deletion and source weight in the corpus fingerprint; the full-page refusal; the unattributed role
label; and the derived duplicate rate.

### E99 — Gate results (Task 14)

| Gate | Result |
| --- | --- |
| Task 14 tests | 76 passed (`test_research_retrieval_audit.py` 46, `test_research_provider_budget.py` 30) |
| Full offline regression, repo root | 1419 passed, 133 skipped, 0 failed (baseline 1343 + 76 new) |
| Frontend (`cd web && npm test`) | 259 passed, 64 files — unchanged |
| Ruff (`check` + `format --check`) | clean; one line split for E501, five import orders fixed |
| Mypy strict, repo root | success, 349 source files |
| Pre-existing modifications | untouched; the only tracked file Task 14 modifies is `tool_budget.py`, and its two existing tests pass unmodified |

Two notes that are not Task 14 defects. `ruff format --check` reports **201 pre-existing unformatted
files** under `backend/src` and `backend/tests`; the repo is not format-clean at baseline, so only files in
this task's scope were formatted (verified afterwards: 0 unformatted in scope). And the
`research_library` trees are entirely untracked, so formatting them produces no diff against committed
content — the full regression above is the check that formatting did not disturb earlier tasks' behaviour.


## Implementation Evidence (Task 15)

**E100 — Plan deviation, recorded before coding.** 计划把 Task 15 描述成纯粹的"新建两个文件"。
实际需要第三个文件：`conflicts.py` 新增公开的 `weakest_grade(grades)`，复用已有的
`_GRADE_RANK`。「一条事实引用多份来源时取哪一档」这个判断必须有唯一的定义，否则
`artifacts.py` 会再写一份次序表。上面 Files 清单已按此补齐。

**E101 — `accept` 与 `inspect` 同属一个服务，台账在内存里。** 计划只要求 `accept`。但"必须先
inspect 再接纳"这条规则要成立，就必须有一份**服务端**的查看记录：候选摘要不是原文，检索返回
它不等于这一段被读过。因此 `AcceptInternalEvidenceService` 同时拥有 `inspect` 与 `accept`，
并在内存里保留一份**不含正文**的台账（`InspectedSource`：切片、版本、页码区间、章节路径、
内容来源、待核验标记）。台账随进程结束——它描述的是"这一次尝试做过什么"，而尝试随进程一起死；
尝试号 +1 之后的接纳本来就会被 `AtomicArtifactCommitter` 以 `stale task attempt` 拒绝。

**E102 — 等级只能往低了申报，不能往高了申报。** 规格 14 第 5 条的等级是**推导**出来的。校验
只在申报值**高于**内容应得的档位时拒绝：一页 OCR 申报成 `PRIMARY_SOURCE` 是在按证据质量排序的
裁决里升了一档。自愿申报得更低是保守，不是撒谎，因此放行——这条不对称是有意的，写进了
`_require_grade` 的文档串。

**E103 — 多来源取最弱档。** 一条事实同时引用原生文本与 OCR 页面时，它挣到的是**最低**的那一档。
取最高的那一档等于让最体面的来源替整条事实背书。测试覆盖两个方向（声明 `PRIMARY_SOURCE` 被拒、
声明 `PARSED_STRUCTURE` 通过）。

**E104 — 待核验的标记与等级是两件事。** 等级被压低只是结果；`requires_verification` 这个标记
本身也必须落到事实行上（A3/A4 读的是标记）。任一来源带标记而事实不带 → `EvidenceGradeMismatch`。

**E105 — UNRESOLVED 数"不同的切片"，不是列表长度。** 领域模型 `InternalEvidence` 的校验器已经
要求至少两条 `source_refs`，但那是列表长度：同一段话写两遍就够了。本层另数 `chunk_id` 的去重
集合。计划里"missing conflict metadata"的一条测试因此被改写——只留一方的载荷**构造不出来**，
不可能有测试覆盖它，强行保留只会是一个永远绿的假测试。

**E106 — `CHECK_FAILED` 必须带核验标记。** Task 13 把"检查没做成"与"检查做完了，没有冲突"分得
很清楚；一份 `CHECK_FAILED` 的证据不带标记地交出去，下游只会读成一条被接纳的事实。

**E107 — 出处只能带查看时真的交出来的定位。** 页码区间、版本、章节路径、以及**包围盒**都要与
台账逐字段相同。`SourceInspection` 不发包围盒，因此 `bounding_boxes` 非空即拒绝——库里那一列
只能写空。放行一个没人交出来的定位，等于让引用自己声明它指到了哪一块，而没有任何东西能核对它。

**E108 — 原子性用真实 SQLite 触发，而不是靠上层的校验。** 上层的每一种出处偏差都会被拦下，
因此"库里拒绝了半批写入"这件事需要一条**上层不管、库管**的坏数据才能逼近：一条空白事实
（`min_length=1` 放它进来，`length(trim(statement)) > 0` 拦它出去）。此时前一条事实的正文与
出处都已写过，回滚必须把它们一起撤掉。另一条路径是删除 `research_retrieval_audits` 里的审计行，
让外键拒绝整批写入。两条都断言业务行、出处行与 `ArtifactRef` 全部为空。

**E109 — 身份由内容决定。** `artifact_id = uuid5(命名空间, 载荷摘要)`，载荷含 run/task/attempt/
retrieval 与全部事实；`evidence_id` 同样由摘要加序号推出。因此同样的证据重放撞上的是自己
（`duplicate artifact ID`），而不是留下第二份看起来一样的证据。

**E110 — 测试夹具的诚实边界。** 研究库至今只有 PostgreSQL 实现与测试用的内存实现，**没有 SQLite
实现**，而来源表的外键指着 `research_retrieval_audits`。因此测试把检索服务**实际写出**的那条审计
记录镜像进 SQLite（`seed_audit`），而不是另编一条。这个缺口（没有 SQLite 研究库仓库）是既有事实，
不是本任务引入的。

**E111 — 一处必须记下的基线行为。** `SQLiteDatabase.connection()` **不提交**：它只借出一个开了
外键的连接，提交由 `transaction()` 负责。夹具最初的审计行写入用了 `connection()`，于是静默丢弃、
外键报错。这不是产品缺陷，而是这个 API 的语义，写在这里免得下一个人再踩一次。

**E112 — 变异测试：26 个变异，22 个被抓住。** 逐条规则施加一个变异后重跑本任务的测试：
A2 角色检查失效、定位不再与台账比对、伪造切片不再要求查看过、在架状态检查失效、软删除检查失效、
包围盒检查失效、等级取最强档、等级上限检查失效、待核验标记检查失效、UNRESOLVED 改数列表长度、
CHECK_FAILED 标记检查失效、空载荷检查失效、尝试号下界检查失效、检索归属检查失效、身份不再由内容
决定、出处行整体不写、出处序号不按事实分开、等级／待核验标记／冲突状态三列各自写死、
`weakest_grade` 取错方向——**全部被抓住**。

四个未被抓住，逐条说明：

1. **台账键里的尝试号失效**（`min(attempt_id, 1)`）——**等价变异**。同一个键里还有
   `retrieval_id`，而一次检索只属于一次尝试，且 `_require_current_retrieval` 已经先比对过
   审计三元组。尝试号在键里不可能成为决定因素。为它专门加的测试
   （`test_an_inspection_from_an_earlier_attempt_does_not_satisfy_the_retry`）保留，因为它把
   "重试时旧引用没有落脚点"这个真实场景写清楚了，但它证明的是 `retrieval_id` 那一半。
2. **摘要不再规范化键序**（`sort_keys=False`）——载荷总是用固定键序构造，因此这一项在公开
   API 上不可观测。它是防御性的，不是被保证的性质。
3. **出处序号一律从 0 开始**（`start=0`）——**空变异**，用于确认夹具不会凭空报出抓住。正确地
   报告为未发现。
4. **写后可见性核对恒真**（`_EvidenceTables.exists` 返回 `True`）——要触发它需要"写下去了但
   事务里看不见"的持久化实现，那属于别的一层，本任务不伪造它。

**E113 — 门禁。** 目标测试 44 passed；全量离线回归 **1463 passed, 133 skipped, 0 failed**
（基线 1419/133，+44 即本任务新增）；前端 vitest 259 passed / 64 files、tooling 4 passed；
Ruff 全部通过且新文件已格式化；Mypy strict 350 个源文件无问题（基线 349，+1 为新模块）。

**E114 — 交接。** `internal_research_evidence` **尚未**加入
`application/orchestration/referenced_context.py` 的 `ALLOWED_CONTEXT_ARTIFACT_KINDS`——那是
Task 17 的 A3/A4 读取授权，本任务只负责把证据接纳进来。`internal_research_evidence.claim_id`
与 `bounding_boxes_json` 两列本任务写 NULL／空：前者属于抽取阶段的事实 ID，后者要等
`SourceInspection` 开始发放包围盒。


## Implementation Evidence (Task 16)

**E115 — 计划修正（Task 16 Step 1 补一条）：工厂装出来的那三件工具必须真的跑一遍。**
Task 16 的 Files 与 Step 1 只要求"断言 RAG 打开时 A2 有三件工具"，没有要求把组合这条路真的走
一遍。变异测试把这一点暴露得很直接：把 `accept_internal_evidence` 构建器换成**另一个**
`AcceptInternalEvidenceService` 实例（于是"查看台账"与"接纳台账"不再是同一本），38 条测试全绿——
因为每一条都直接构造工具，绕过了组合。补了一条端到端用例：用真实 `A2BusinessToolFactory`
（配一份完整的 A2 研究上下文：`sector:INDUSTRY:sector-1` 范围、固定选择版本、候选批次工件、
锁定的截止时间）装出三件工具，检索 → 查看 → 接纳走通并留下工件。同一条变异随即失败，报的正是
`chunk 'chunk_1' was never inspected in this attempt`。

这不是产品缺陷，而是"局部测试通过不等于系统通过"的一个具体例子：三件工具各自正确，装配起来
仍可能互相不认。修正落在测试一侧，因为计划缺的是那一句要求，不是那一行代码。

**E116 — 计划偏离：Files 清单少了一个文件。** Task 16 的 Files 里没有
`backend/src/sector_pulse/application/research_library/artifacts.py`，实际需要在那里加一个只读的
`accepted_artifact(reference)`。理由：`AcceptInternalEvidenceTool.replay` **不能**把接纳重写一遍——
重复提交会撞上 `duplicate artifact ID`，而"被拒绝的那一次"看起来像一次成功的重放。所以重放只回
快照核对效果还在不在：找出这次 run 真的提交过、且引用相符的那一份 `ArtifactRef`，找不到就报
`KeyError`。变异（去掉引用比对，改成"随便哪一份证据工件都算"）被
`test_accept_replay_names_only_an_artifact_this_run_committed` 抓住。

**E117 — 契约跟着 RAG 走，而且是"期望"而不是"反推"。** `REQUIRED_BUSINESS_TOOL_NAMES` 一个字都
没动，另立一份 `RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES = 既有集合 | 那三件`。若从"结果里减去
现存的名字"反推契约，一个只接了一半的部署会静默退化成"没开 RAG"，而它们是两件不同的事：前者是
半接线，后者是刻意关闭的能力。`web/dependencies.py` 用同一份集合给工具报价——注册表里出现一个
没有报价的工具，角色工厂会直接拒绝建这个 Agent。名字钉死的断言（`RAG_BUSINESS_TOOL_NAMES` 恰好
等于那三个名字）是这条契约的一部分：少一个名字，一份缺接纳工具的部署就会被当成完整的部署放行。

**E118 — 开着 RAG 却接不上资料库，拒绝启动。** `build_runtime_dependencies` 在
`enable_multi_agent and settings.rag.enabled and research_library is None` 时抛 `RuntimeError`。
理由：那样跑出来的 A2 是一个检索不到任何内部资料的 A2，而它交出的证据与"资料库是空的"完全一样；
这两件事必须能被分辨。这一层不是接线而是**缺失接线**的显式表达：目前既没有 SQLite 的
`ResearchLibraryRepositoryPort`，`RuntimeStorageBundle` 里也没有资料库条目，所以 Task 16 在
`web/dependencies.py` 加的是一条可选的 `research_library: A2ResearchLibraryServices | None` 缝，
与既有的 `business_tool_factory` / `agent_provider_factory` 可选项同形。RAG 关闭时拿到的是原来
那一份 14 件工具的契约，一行没变。

**E119 — 角色白名单说的是"可以"，构建器在场才是"能用"。** `ROLE_TOOL_NAMES[A2]` 里加的那三个名字
是**权限**；RAG 关掉时那三件工具根本不注册，名字不会凭空出现在注册表里。`RoleAgentFactory` 对
"白名单里有、构建器没有"的名字是跳过而不是报错，A1/A3/A4 的既有测试确认这条路径没被改坏。

**E120 — 变异结果（Task 16）：18 处变异，18 处被抓。** 每处单独施加，两个 Task 16 测试文件各跑一遍，
再按原始字节还原；锚点出现次数不为 1 时报 INAPPLICABLE，而不是算作抓住。第一轮是 17 抓 1 漏、
1 处锚点写错——两处"漏"经核查都不是等价变异，而是**测试缺口**，就地补了用例：

1. `_candidate_payload` 里那次截断漏网：测试给检索服务与工具的本来就是同一份 `RagSettings`，
   服务已经按同一个上限截过了，于是工具这一刀不可观测。补的用例把两份配置分开（服务 600，
   工具 200），工具自己的上限才成为一条可观测的承诺——"这份输出不会超过多少"是工具的承诺，
   不能只是服务的承诺。
2. `RAG_BUSINESS_TOOL_NAMES` 少一个名字漏网：原来那几条断言只要求"这一组与它自己一致"
   （`isdisjoint` 与并集恒等式在两边同时变化时都成立）。补的名字钉死断言让"少一个名字"直接失败。
3. `inspect` 的等级写死成 `PRIMARY_SOURCE` 漏网：查看路径只用过原生解析的语料，OCR 与待核验
   从没被查看过。补的用例查看一页 OCR 与一条待核验，断言拿到 `PARSED_STRUCTURE` /
   `DERIVED_UNVERIFIED`，且 `requires_verification` 跟着内容走。

被抓住的 18 处覆盖：三件工具各自对服务端绑定键的拒绝、检索身份里声明了无权读取的角色、候选
摘要不截断、等级写死、待核验标记被丢、结果引用用错前缀、查看不报截断、查看等级写死、
RAG 契约退化成旧契约、RAG 工具集少一件、A2 工厂不装那三件工具、组合工厂默认空契约、
查看与接纳不共用一本台账、A2 白名单少接纳工具、A3 白名单多了检索工具、重放不比对引用。

**E121 — 闸门。** 全部在仓库根执行（`--import-mode=importlib --basetemp=.tmp-test`）。

| 闸门 | 结果 |
| --- | --- |
| Task 16 测试 | 38 passed（`test_orchestration_research_library_tools.py` 25，`test_orchestration_role_factory.py` 13） |
| 全量离线回归 | 1489 passed, 133 skipped, 0 failed（Task 15 后基线 1463，+25 本任务新用例，+1 角色工厂新用例） |
| 前端 `npm test` | 259 passed, 64 files —— 未变 |
| 前端 `npm run test:tooling` | 4 passed |
| Ruff（`check` + `format --check`） | 通过；新建的两个文件已格式化，一条 import 顺序自动修正 |
| Mypy strict（仓库根） | 通过，351 个源文件（Task 15 后 350，+1 为新模块） |

未在本任务关闭、已转交的：`internal_research_evidence` 仍不在 `referenced_context.py` 的
`ALLOWED_CONTEXT_ARTIFACT_KINDS` 里（Task 17 的 A3/A4 读取授权，见 E114）。
## Implementation Evidence (Task 17)

**E122 — 引用通道复用 `Claim.evidence_ids`，不改领域模型。**
Task 17 要求 A3/A4 对内部证据执行三条确定性规则，但草稿模型里没有一个字段承载"引用一条内部事实"：`Claim.evidence_ids` 是新闻事件 ID 空间，`SubmitRevisionService` 的 `_apply` 又把改写范围限死在新闻 ID 空间。可选方案是给 `Claim` 加一个内部证据列表（改领域模型、改迁移、改所有写入方），或者把"不在本板块新闻事件空间里的句柄"认作内部引用。选了后者：不改领域模型、不新增字段、不需要新迁移，而且凭空写出的句柄在提交时仍被既有的来源校验挡住——"加了前缀但没登记"这种半套状态不会出现。内部来源由服务端拼成 `ArticleSource`（标题含文档、版本与定位，`citation_url` 留空，规格 15.2 不把内部下载地址交给任何 Agent）。

**E123 — "这个 run 里现在还能引用哪些证据"由新端口回答，不挂在 `ResearchLibraryRepositoryPort` 上。**
那个端口描述的是资料库自身的治理（资料、版本、摄取任务、索引代次、可见性），这里问的是"某次运行的某份 Artifact 里有哪些已被接纳的事实、它们站的版本还在不在架"。合在一起会让检索侧的实现被迫回答治理问题。因此新增 `AcceptedEvidenceRepositoryPort`（`get_accepted_evidence` + `load_active_version_ids`），SQLite 与 PostgreSQL 各一份只读实现，由 `runtime_bundle` 组装。写入端不动：证据行本来就由接纳服务经事务会话写进当前方言的库。

**E124 — A3 的"拒绝"就是已有的提交闸，不新增第二条路径。**
`SubmitDraftService.submit` 本来就对 `draft_quality_issues` 的任何一条抛 `ValueError`。把 `internal_evidence_issues` 并进同一个元组，A3 的拒绝闸、错误码与消息格式一次到位；三条规则的级别一律 `IssueSeverity.BLOCKING`，于是 `ReviewReport` 自己就拒绝带 BLOCKING 问题的 PASS——"把未决冲突写成确定事实"不可能靠某个 Agent 点头通过。A4 的 `check_draft_rules` 接同一份检查，规格 15.4 要求的复核因此不是另写一套判断。

**E125 — 证据状态在提交/复核时读，不在绑定时读（计划 Files 里的 `editorial_context.py` 因此没有改）。**
计划把 `backend/src/sector_pulse/application/orchestration/editorial_context.py` 列进 Task 17 的修改清单。实际改动落在 `SubmitDraftService`、`CheckDraftRulesService` 与 artifact reader 里：绑定时读会把"版本此刻是否还在架"冻结成构造工具那一刻的答案，而 A3 提交与 A4 复核可能相隔数分钟，资料删除与替换必须立刻生效。`editorial_context.py` 保持原样是有意的，不是漏改。

**E126 — `_READABLE_KINDS` 要给 A3/A4 开出 `internal_research_evidence`（计划 Files 里没有这个文件）。**
规格 15.3/15.4 说 A3/A4"只能通过 `inspect_artifacts` 读 A2 已接纳的证据"，而没有这个 kind 的读取权限时 `ArtifactInspector._ensure_readable` 会直接拒掉请求——Skill 里写的规则、草稿里的引用检查都无从谈起。因此 `application/orchestration/controls.py` 的 A3、A4 两份白名单各加一项，并附规格出处注释。

**E127 — 迁移 035 已冻结，读取顺序只能靠内容无关的稳定键。**
两张证据表里没有"第几条事实"这一列，而审计要的是同一批行每次都按同一顺序出现。读取端因此按 `artifact_ref, evidence_id` 排序、出处按 `source_order` 排序；加列需要新迁移，不在本任务范围内。

**E128 — SQLite 部署里 `research_document_versions` 永远为空，因此每条内部引用都会被判失效。**
`research_document_versions` 由 PostgreSQL 的资料库仓库写入；SQLite 上没有 `ResearchLibraryRepositoryPort` 的实现（`test_package_layout.POSTGRES_ONLY_MODULES` 原本就写着这一点），所以 `load_active_version_ids` 在 SQLite 上报的永远是空集，"版本还在不在架"的答案是"查不到"。方向是 fail-closed——无法核对的引用不会悄悄通过——不是漏洞，但离线路径上一条合法的内部引用也会被标 BLOCKING。留给 Task 18/20 决定：要么给 SQLite 补上资料库仓库，要么在评测里按迁移 035 的约束播种版本行（本任务的测试就是这么做的）。

**E129 — `test_package_layout.POSTGRES_ONLY_MODULES` 收窄为 `research_library/repository.py`。**
那条不变式原本写的是"RAG 需要权威库，所以研究资料库没有 SQLite 实现可镜像"。Task 17 给两种方言都加了已接纳证据的**读取端**，于是这个断言第一次失败——这正是它该做的事。按 E123 的理由更新常量与注释：权威仓库仍只有 PostgreSQL 一份，读取端两种方言都有，因为证据行本来就写进当前方言的库，只让 PostgreSQL 读得回来等于让 SQLite 运行接纳一批谁也读不到的证据。

**E130 — Task 17 实际改动的文件超出计划的 Files 清单。**
计划列了 8 个文件。实际另外新增/修改：`domain/research_library/retrieval.py`（`AcceptedEvidenceClaim` 读模型）、`storage/ports/research_library.py`（新端口）、`storage/sqlite|postgres/research_library/evidence_repository.py`（各一份只读实现）、`storage/runtime_bundle.py`（组装）、`application/research_library/evidence_access.py`（`AcceptedEvidenceIndex`）、`application/writing/draft_quality.py`（三条规则与三个公开错误码）、`application/orchestration/editorial_tools.py`、`application/orchestration/controls.py`（E126）、`infrastructure/agents/composition.py`、`web/dependencies.py`、`backend/tests/unit/test_package_layout.py`（E129），以及测试辅助函数 `test_orchestration_review_tools.build_review_context`（加两个可选参数，默认行为不变）。理由：没有读模型就没有可渲染的东西；没有端口就没有权威读路径；没有组装点就没有部署形态；没有 `controls.py` 的读取权限就没有通道；`composition.py` 与 `web/dependencies.py` 是把端口接到工具上的那两处。

**E131 — 证据通道这一半是"先实现、后补测试"，测试的杀伤力用变异验证。**
Task 17 的两半顺序不同，如实记录：Skill 那一半按 TDD 走（先写测试，红在 `ImportError: cannot import name 'ROLE_SKILL_NAMES'`，再实现，8 个测试转绿）；证据通道那一半先写实现、再补 Step 1 的测试，因此没有观察到自然的红。为了让"测试真的在测东西"有证据，补做了一次变异检查，7 处变异全部被抓住：

| 变异 | 结果 |
| --- | --- |
| `internal_evidence_issues` 的三条结论改成 `WARNING` | 5 failed |
| A3 提交闸不再并入内部证据结论 | 2 failed |
| A4 的 `check_draft_rules` 不再并入内部证据结论 | 2 failed |
| `is_citable` 退化成"句柄存在即可" | 3 failed |
| `is_citable` 忽略版本是否仍在架 | 3 failed |
| artifact reader 不再渲染事实 | 2 failed |
| `roles.py` 里 A3 丢掉写作 Skill | 1 failed |

**E132 — 闸门。** 全部在仓库根执行（`--import-mode=importlib --basetemp=.tmp-test`）。

| 闸门 | 结果 |
| --- | --- |
| Task 17 目标测试 | 29 passed（`test_internal_evidence_editorial_guards.py`：Skill 8 个、证据通道 21 个） |
| 相邻套件 | 127 passed, 2 skipped（草稿、修订、复核、证据、A2 工具、角色工厂、业务工具工厂） |
| 全量离线回归 | 1518 passed, 133 skipped, 0 failed（Task 16 基线 1489 + 29 个新测试） |
| 前端 `npm test` | 259 passed, 64 files 全通过 |
| 前端 `npm run test:tooling` | 4 passed |
| Ruff（`check`） | 通过 |
| Mypy strict（仓库根 `mypy`） | 通过（355 个源文件） |

`ruff format --check` 在本仓库不是闸门：对未改动的既有文件跑它同样会报 108 个文件需要重排。
先前记录的待办（E70、E71、`RetrievalAuditRecord.claims`/`conflicts` 从未写入、证据表的 `claim_id` 与 `bounding_boxes_json` 仍写 NULL/空）状态不变。

**E133 — `published_at` 必须在任何派生数据之前定下来（Task 18 期间发现并修复）。** 重建一个已发布版本时，摄取流水线抛
`IndexRecordConflict: chunk ... is already staged in generation ... with different content`。根因是结算时机的顺序：`_settle_published_at` 原本在
`_index` 里调用，而 `state.records` 早在 `_embed` 阶段就由 `state.chunks` 建好了——切片行先于索引记录落库，索引记录带着
`published_at` 这个标量，于是"权威库里的那一列"和"记录里的那个值"差了一次调用。两个后端的反应不同：内存索引大声报冲突，
Milvus 静默覆盖，后者更难发现。修法是把结算提到 `_advance` 里紧接 `state = self._open(job)` 之后、整段阶段循环之前。
副作用是 PostgreSQL 的 `activate_version` 里那句 `COALESCE(published_at, now)` 变成空操作——这正是想要的结果：时间戳由
流水线在一个确定的位置上定，而不是由某次激活调用用它自己的墙钟顺手发明一个。

**E134 — 已兑现的索引意图必须能被重新登记（Task 18 期间发现并修复）。** `POST /api/research-library/documents/{id}/rebuild` 返回
500 `RetriableIngestionError: generation ... is staged but not published yet`。原因是两条规则正好互斥：`verify().published` 要求这一代里
**每一条**在册记录都是 PUBLISHED，而重建会把刚删掉的那条重新建成 STAGED，其余仍是 PUBLISHED；同时那条发布意图已经是
DONE，出箱永远不会再兑现它——同一个 generation 因此会永久卡在"已暂存但未发布"。修法是在 `enqueue_index_event` 里对
**仅限 DONE** 的那一行重新激活（PostgreSQL：`ON CONFLICT (event_id) DO UPDATE ... WHERE research_index_outbox.status = :done`；
内存仓库：存的不是 DONE 就原样返回）。PENDING／CLAIMED／FAILED 三态仍返回原行不变，因此 E53 当初 `DO NOTHING` 要保护的
东西（一次认领、一条失败原因）没有被这次修改擦掉。红先行：新增
`test_re_enqueuing_a_settled_intent_re_arms_it_and_leaves_the_others_alone` 最初报 `assert <OutboxStatus.DONE> is <OutboxStatus.PENDING>`。
同一条契约在 PostgreSQL 上另有一份 `test_re_enqueuing_a_finished_intent_re_arms_it_for_the_rebuild`——**本轮未验证**：本机
`localhost:5432` 上的 `_test` 库连不上（`psycopg.errors.ConnectionTimeout`），这个用例只做到了离线语法检查与跳过，真实数据库上的行为
待 Task 20 接上专用测试库后补验。

**E135 — 上传端点是原始字节，不是 multipart。** 计划 Step 1 写"multipart upload size/type/header/scan validation"，Step 3 写
"Stream uploads ... do not load unbounded files in memory"——这两句在执行层是冲突的：`File(...)`／`UploadFile` 需要
`python-multipart`（它不在依赖里），而且 FastAPI 的默认路径是先把整个请求体收进内存再交给处理函数，恰恰是 Step 3 禁止的做法。
因此请求体取原始字节，媒体类型读 `Content-Type`，文件名读 `X-Research-Filename`；`AssetSpool` 边收边算散列流式落盘，落盘上限与
对象存储上限共用同一份规则。Step 1 点名的那些校验（大小／类型／请求头／扫描判定）一条不少，只是载体换了。

**E136 — 扫描判定为恶意的上传：留隔离证据，不静默删除。** 扫描结论是 INFECTED／FAILED 时，命令登记资产行、写一行
`REFUSE_UPLOAD` 审计，然后抛 `UploadScanRejected`；不建摄取任务，因此这份文件永远不会被解析、也不会进索引。文件本身刻意留在
对象存储里：静默删掉一份被判定为恶意的文件，等于把它变成一次"没有发生过"的事件，而审计表存在的意义正是让这类事件留痕。
迁移 036 因此把 `refuse_upload` 写进 action 的 CHECK 列表。036 也顺带把 3 个测试文件里 5 处迁移版本断言从 `range(1, 36)` 顶到
`range(1, 37)`——第一次全量回归正是被这 4 个用例拦住的（见 E140）。

**E137 — `indexable_chunk_ids` 是公开方法，因为维护流程必须用同一份定义。** 父块只做上下文、不进向量索引（规格 8）。核对报告要回答
"这一版该有哪些向量"，如果它自己重写一遍这个判断，两份规则漂移的那一天，报告会声称索引缺了它本来就不该有的东西——而一份
开始误报的报告会立刻失去全部价值。所以这个定义留在摄取服务上，维护流程调用它，不复制它。

**E138 — `create_app` 只接受注入的装配结果，本任务不产出生产装配器。** `create_app(..., overrides={"research_library": ...})` 用注入的
`ResearchLibraryServices` 挂上治理路由，并通过 `agent_services()` 派生出 A2 要的窄接口；没有注入时整个路由 404
`RESEARCH_LIBRARY_DISABLED`（RAG 默认关闭，"这个部署没有资料库"是正常形态）。这里刻意没有 MinIO／Milvus／真实 Provider 的装配
函数：Task 18 的 Files 清单里没有它，它在离线状态下无法验证（那几个 SDK 都是延迟导入），而真实链路归 Task 20。两个应用级测试
钉住了这个行为（注入了→200 且空列表；没注入→404 `RESEARCH_LIBRARY_DISABLED`）。这条与 E118 是同一条规则的上下两半：开着 RAG
却什么都没接，拒绝启动；没开 RAG，路由整体不存在。

**E139 — `embedding_dimension` 是新增必需配置。** 集合的维度不是每一批 embedding 自带的属性（同一部署换模型是允许的），而
Milvus 建集合时就要这个数，`EmbeddingProvider` 端口因此故意不提供维度。既然唯一知道它的地方是配置，它就写在 RAG 配置里
（`SECTOR_PULSE_RAG_EMBEDDING_DIMENSION`，1..8192），并且在 RAG 开启时缺失即拒绝加载——否则这种失败会推迟到第一次建集合时
才出现，那时运维看到的是一份上传失败的报告，而不是一份配置报告。

**E140 — 闸门（Task 18）。** 全部离线执行（`--import-mode=importlib --basetemp=.tmp-test`，仓库根目录）。

| 项 | 结果 |
| --- | --- |
| Task 18 目标文件（API／维护／摄取流水线／索引发布） | 98 passed, 15 skipped |
| 资料库相关子集（`-k "research_library or research_ingestion or research_index or research_retrieval"`） | 631 passed, 47 skipped |
| 全量离线回归 | 1592 passed, 134 skipped, 0 failed（E132 基线 1518／133／0，即 +74 passed、+1 skipped） |
| 前端 `npm test` | 259 passed, 64 files 全通过 |
| Ruff（`check`） | 通过 |
| Mypy strict（仓库根 `mypy`） | 通过（361 个源文件） |

那一处新增的 skip 就是 E134 里那份 PostgreSQL 契约用例：它只在配置了专用 `_test` 库时运行，本轮连不上，因此没有在真实
PostgreSQL 上验证过。第一次全量回归曾经是 **4 failed**——全部来自迁移版本断言，036 落地后 3 个测试文件里 5 处
`range(1, 36)` 需要顶到 `range(1, 37)`；修掉之后即上表的 0 failed。`ruff format --check` 在本仓库仍不是闸门（对未改动的既有
文件它会报 108 个文件需要重排），这一点与 E132 相同。先前记录的待办（E70、E71、`RetrievalAuditRecord.claims`/`conflicts` 从未写入、
证据表的 `claim_id` 与 `bounding_boxes_json` 仍写 NULL／空、SQLite 部署下 `research_document_versions` 为空、没有生产装配器）状态不变，
均未因本任务而改变；"局部测试通过不等于完整 RAG 系统已完成"这条判断在本轮依然成立。

**E141 — 上传的文件名在请求头里必须转义，而且两个方向要互逆（Task 19 期间发现并修复）。** 客户端测试第一次跑就报
`TypeError: Cannot convert argument to a ByteString because the character at index 0 has a value of 20648 which is greater than 255`：HTTP 头只能放
latin-1，`fetch` 见到非 ASCII 的头值直接抛异常——一份中文名的报告在浏览器里**连请求都发不出去**。下载那一步早就在转义
（`quote(download.filename, safe="")`，前端解码），上传这一步没有对应的另一半。两处一起补上：客户端用
`encodeURIComponent(file.name)` 写 `X-Research-Filename`，路由在把文件名交给命令之前 `unquote()` 回来。后端红先行：新增
`test_a_percent_encoded_filename_comes_back_as_the_name_the_user_uploaded`，先失败在"库里存着的名字是
`%E5%82%A8%E8%83%BD%E6%8A%A5%E5%91%8A.txt`"，修完通过。ASCII 文件名不受影响（`unquote` 对它们是空操作），因此既有的
`report.txt` 断言原样通过。

**E142 — 文件输入不写 `required`。** jsdom 不会把 `files` 反映到 `value` 上，于是带 `required` 的文件输入在测试环境里**永远无效**，
表单根本提交不出去（表现是所有上传用例"点击了提交但什么都没发生"）。没有为此绕开测试，而是去掉了这个属性：真正的闸门是
那个读同一份状态的禁用提交按钮，而 `required` 只在"状态与 DOM 不一致"时才可能生效，那种情况在这里构造不出来。

**E143 — 页面测试只替换网络调用，保留真实的错误类。** `vi.mock(path)` 会把构造器一起换成假函数，于是
`ResearchLibraryApiError.code` 变成 `undefined`，页面那条"没有资料库 vs 资料库坏了"的分支就测不到了（错误提示渲染成
`（undefined）`）。改成工厂式 mock：展开真实模块，只替换收发请求的那几个函数。被替换的函数逐个列了出来，漏掉一个就是一次
真实的网络调用，而不是一次静默通过。

**E144 — 状态码到中文标签的映射放在 `DocumentTable.tsx` 并导出。** 流水线的阶段码（`EMBEDDING`……）不该出现在屏幕上；
认不出来的码**原样显示**，因为一个新加的阶段应当可见，而不是被塞进"处理中"里假装正常。映射没有单独建文件，而是放在
列表组件里导出、由抽屉复用：Task 19 的 Files 清单点名了三个页面组件，多一个模块就是一份清单外的文件，而让抽屉从列表里
导入一个展示函数，是比这更小的偏离。同样地，页面上**刻意没有**"重建索引"和"维护核对"两个入口——计划 Step 1 的测试清单里
没有它们，维护面属于 Task 18 的 API，真实链路由 Task 20 负责。

**E145 — 计划 Files 清单之外改动的文件只有一个测试文件。** `web/src/App.test.tsx` 不在 Task 19 的 Files 里（清单里是
`App.tsx` 与 `navigation.ts`），但那条路由和那个导航项是"渲染得出来"才算数，而这个文件本来就是测路由的地方，因此在里面
加了一条 `/research-library` 的用例（断言一级标题与 `aria-current`）。其余改动文件与清单一致。

**E146 — 闸门（Task 19）。** 全部离线执行。

| 项 | 结果 |
| --- | --- |
| Task 19 目标文件（API 客户端 + 页面） | 26 passed（`researchLibraryApi.test.ts` 11，`ResearchLibraryPage.test.tsx` 15） |
| 前端全量 `npm test` | 286 passed, 66 files 全通过（E140 基线 259／64，+27 条／+2 个文件） |
| 前端 `npm run build`（`tsc -b && vite build`） | 通过 |
| 前端 `npm run test:tooling` | 4 passed |
| 后端全量离线回归 | 1593 passed, 134 skipped, 0 failed（E140 基线 1592／134／0，+1 即 E141 那条新用例） |
| Ruff（`check`） | 通过 |
| Mypy strict（仓库根 `mypy`） | 通过（361 个源文件） |

Task 19 的计划测试清单逐条对上了：新文档上传、明确的新版本选择（含"选了新版本没选资料时提交按钮禁用"）、上传进度
与摄取状态显示、失败提示、版本历史、软删除确认、恢复、原件取回、RAG 未启用的空态，以及键盘可达（只用键盘开合抽屉；
没有执行人时治理按钮禁用、阅读按钮照常可用）。E141 是这个任务里唯一改到后端的一处，它来自客户端测试的第一次失败，
而不是来自前端代码本身——两个方向的转义只做一半，中文名的报告在浏览器里发不出去，这一点在离线后端测试里看不出来。
**E147 — 黄金集的两条冲突用例共用同一次检索，审计镜像必须是幂等的（Task 20 期间发现并修复）。**
黄金集里两条冲突用例都从模块级的 `runs` 夹具取同一条检索，于是 `seed_audit` 会把同一条 `research_retrieval_audits` 记录写两次，第二次撞主键。单跑一条看不出问题，整份文件跑才失败——这正是"逐条绿、整份红"的典型形状，而它报出来的是一条 Python 异常，不是一条检索质量结论。修法是把镜像改成幂等：先查该 `retrieval_id` 是否已有行，有就返回。这不是把断言删掉：审计行本身是**不可变记录的一份副本**，同一份副本镜像两次就不该产生两条，重复插入失败在这里是正确的行为，需要的是调用方不去重复写，而不是放宽约束。修完整份文件 14 passed（1 warning，3.40s）。

锁定的基线（夹具 Provider 与内存适配器，门槛写在用例里）：

| 指标 | 实测 | 门槛 |
| --- | --- | --- |
| Recall@12 | `1.000` | `>= 0.90` |
| MRR | `0.9167` | `>= 0.80` |
| nDCG@12 | `0.9074` | `>= 0.85` |
| 重复候选比例 | `0.0000` | `<= 0.15` |

另外四项断言为零：非活跃版本泄漏（`test_no_candidate_comes_from_a_version_that_is_no_longer_active`）、来源定位失败（`test_every_candidate_can_be_inspected_down_to_a_locator`）、未解决冲突被写成事实（`test_an_unresolved_conflict_cannot_be_recorded_as_a_settled_fact`）、越权工具升级（`test_text_in_the_corpus_cannot_change_what_the_tools_may_do`）。这些是**夹具基线**：真实 Provider 的影子结果另报，不自动改写门槛。

**E148 — Task 20 Step 4：三档专用基础设施契约全部跳过。** 本机没有专用资源，三档只被收集：

| 档 | 结果 |
| --- | --- |
| `postgres` | `75 skipped` |
| `minio` | `10 skipped` |
| `milvus` | `21 skipped` |

跳过原因是两类，分开报是因为含义不同：`postgres` 与 `minio` 是"没有配置专用测试资源"，`milvus` 是"`pymilvus` 没装"（它是 `rag` extra）。两类都是前提缺失而不是实现坏了——但**都不是通过**。这三档要等一台接上了专用 `_test` 库、`-test` bucket、`_test` collection 的机器才有意义。

**E149 — Task 20 Step 5：真实 Provider 冒烟套件，预算是有闸的而不是有注释的。**
新增 `backend/tests/live/test_research_rag_providers_live.py`，只回答一个问题：这几类端点按我们写的提示词与 JSON 形状真的跑得通吗。三件事是刻意的：

1. **标记只用 `live_rag`，不带 `live`**，因此行情那一份同意书不会把它捎带进来（Step 5 与 Step 4 授权的是两笔不同的预算）。
2. **预算在调用之前扣数**：`Budget.spend` 是一个 contextmanager，扣不动就断言失败，`MAX_CALLS = 8`（Embedding 1、Reranker 1、NLI 2、OCR 1、Vision 1，共 6 次，留 2 次余量）与 `DEADLINE_SECONDS = 600.0` 都写死在文件里、不读配置——一份可以被环境改大的预算不是预算。
3. **语料是自己生成的**：正文、查询、PDF 与图表全在测试里画出来，不碰生产数据，也不读仓库外的文件。

断言落在契约上而不是"拿到了结果"上：Embedding 的向量个数与输入下标对齐且维度等于 `SECTOR_PULSE_RAG_EMBEDDING_DIMENSION`；Reranker 给每份文档都打分、`best_order()` 是一个排列、三份内容不同的文档不能拿到三个一模一样的分数；NLI 把相反的两句判成 `CONTRADICTION`、把同义改写判成 `ENTAILMENT`，两者置信度都不低于 `SECTOR_PULSE_RAG_MIN_NLI_CONFIDENCE`；OCR 读出的词坐标全部落在 `0..1`（返回像素坐标的端点不会报错，只会让版面规则算出一堆荒谬的数）。

离线时它报告为 `6 skipped: requires --run-live-rag and .live-rag-consent`。

**E150 — `backend/tests/conftest.py` 的 Live 门禁认错了标记（Task 20 期间发现并修复）。**
原来的三档门禁用 `if "live" in item.keywords` 判断。pytest 的 `NodeKeywords` 不只有 marker 名，还有**目录名与节点名**，而 `backend/tests/live/` 这个目录本身就叫 `live`。于是带 `live_rag` 标记的整套文件会被行情那一档拦下，报出的原因还是行情那份同意书——Task 20 实测：整份 RAG 冒烟套件在离线运行里被报成 `requires --run-live and .live-data-consent`，即使它一次行情都不取。

这条**为什么算缺陷而不算措辞问题**：两个同意书授权的是两笔不同的预算，门禁认错标记意味着"用行情同意书放行 RAG 调用"或者"配了 RAG 同意书却永远跑不起来"，两者都是错的。

修法是把三档全部换成精确匹配：`item.get_closest_marker("...") is not None`。路径与用例名都不会再误伤，`live_llm` 那一档也不必再写一条"排除自己"的条件。新增 `backend/tests/unit/test_live_marker_gating.py`（6 项，全绿）把这个语义钉住：它的假 Item **没有 `.keywords` 属性**，因此任何一次改回 `in item.keywords` 都会立刻报错，而不是悄悄放过或悄悄拦下。

**E151 — 计划 Files 清单之外新增一个共享装配模块（Task 20 Step 5/6 共用）。**
新增 `backend/tests/research_library_live_support.py`：PostgreSQL 权威库、MinIO 原件存储（带生产 `build_scanner`）、Milvus 派生索引、一份共享的解析流水线、outbox、摄取、检索与资料库服务，装配方式与生产一致。放在测试目录里，是因为仓库还没有生产级的组合装配器（与 E138 同一条缺口，Task 18 的 Files 清单里没有它），而 Step 6 必须跑通一次真实链路。**两处各拼一次的后果是**"冒烟测试连的端点"与"端到端连的端点"会慢慢变成两个不同的东西，且没有任何一条测试会发现这件事。

同一个模块记下了第二个缺口：每类 RAG Provider 的 base URL 与 key 在配置层**还没有归属**，因此这里暂时借用仓库里唯一那处已配置的 OpenAI 兼容端点（`SECTOR_PULSE_LLM_BASE_URL` / `_API_KEY`），provider 名与模型名则读 `SECTOR_PULSE_RAG_<KIND>_PROVIDER` / `_MODEL`——那是 `load_rag_settings` 真的会读的键。这不是一套新配置面，而是"还没有归属的值暂时用现有那一处"。装配器落地时应当有自己的键，届时这两处跟着改。

**E152 — Task 20 Step 6 的验收用例从未执行过，这一点写在文件里。**
新增 `backend/tests/e2e/test_research_library_web.py`，标记 `[live_llm, live_rag]`：从 `create_app` 的真实 HTTP 入口开一次运行，语料是三份自编文档，装着**一个可裁决的冲突与一个不可裁决的冲突**（来源权重 0.90 对 0.50 → 权重规则选出赢家；两份互相独立且权重相同 → 没有规则能分出高下）。断言落在"运行停下来时的状态"上：状态停在 `WAITING_USER_REVIEW`、证据表里存在 `UNRESOLVED` 行且**该行的来源条数不少于 2**（只引一边的 UNRESOLVED 是一句没有出处的结论）、草稿提到未决主体且带着不确信的措辞、A4 留下了评校 Artifact。

它的 docstring 明写"本机从未跑通过"，并说明为什么这段状态写在文件里而不只写在报告里：读代码的人有权知道，自己看到的这份绿色到底是不是跑出来的。离线时报告为 `1 skipped: requires --run-live-llm and .live-llm-consent`。**先写好的验收脚本不是已通过的验收。**

**E153 — `UP047` 用 PEP 695 语法消掉，而不是放宽 ruff 配置。**
`connect_to_dedicated_resource` 原来靠模块级 `T = TypeVar("T")` 泛型化。新版 ruff 的 `UP047` 要求改用 `def f[T](...)`。改语法只动一个函数；加一条仓库级 `ignore` 则会让这个规则在**整个仓库**失效——为了一个函数付全仓的代价，不划算。

**E154 — 未提交改动里那条"把新文件转成 CRLF"的收尾项不必要。**
仓库 `core.autocrlf=true` 且没有 `.gitattributes`，索引里永远是 LF，因此新建的 LF 文件与 CRLF 文件提交进仓库的字节完全相同（`git ls-files --eol` 可复核）。真正需要按字节处理的是**计划文件自己**：它是 UTF-8 + CRLF，用 `read_text`/`write_text` 会被静默改写成 LF。本次所有计划文件改动都走字节读写，改完复核 `crlf == lf`（2547 / 2547），`docs/PROJECT_STATUS.md` 的 4 行历史 LF 行也保持原样未动。

**E155 — 闸门（Task 20 Step 7）。** 全部在仓库根目录执行：

- 全量离线回归：`1620 passed, 19 skipped, 122 deselected`（223.59s，exit 0）。19 条跳过全部是"没有配置专用数据库"（14 条 `requires SECTOR_PULSE_DATABASE_URL`、5 条 `requires dedicated SECTOR_PULSE_TEST_DATABASE_URL`），与本功能无关；RAG 的 7 条 live/e2e 用例是被 `-m` 表达式**排除**（deselected）的，单独跑时报告为 `6 skipped` + `1 skipped`，原因各自正确。
- `ruff check .` → `All checks passed!`
- `mypy backend/src/sector_pulse` → `Success: no issues found in 358 source files`
- 前端 `npm.cmd test -- --run` → 66 个文件 / 286 项通过；`npm.cmd run build` 通过；`npm.cmd run test:tooling` 4 项通过。

**E156 — Task 20 Step 8：文档只写已核实的事实。**
Step 8 的条件是"验收通过后才把 README 从『规划中』改为可用"。**验收没有通过**（Step 4/5/6 全部跳过），因此 README 没有改成"可用"：标题改为"内部研究资料库（代码已完成，未通过实机验收）"，正文先写清楚状态——离线夹具 14 项与整仓 `1620 passed` 是已验证的，专用基础设施 75/10/21、Provider 冒烟 6、真实链路 1 是未验证的，并明写"跳过不是通过"。同时补齐了启用配置、Provider 替换、私有 MinIO bucket、BM25 需要服务端 Milvus（Milvus Lite 不支持）、维护接口与边界清单（不做多租户权限、不自动推断版本、不支持以图搜图、不自动发布，并在此处补上了 E157 查出的三处未实现能力：没有告警、不含查询改写、换模型时缺别名原子切换）。`backend/README.md` 补了资料库的目录归属、修改入口与三档真实用例的跑法。`docs/PROJECT_STATUS.md` 新增一节，用一张表把"离线已验证"与"未验证"分开，并写明**本节不能作为"RAG 已可用"的证据引用**。

**E157 — 计划清单项「每个 spec 小节都有任务覆盖」核对结果为不成立，四处缺口记录下来。**
Task 20 Step 8 与全部 Tasks 完成后，逐节核对了 spec 的 71 个内容标题与 20 个 Task 的 Files/Steps。绝大多数小节都有明确归属，但有四处没有任务覆盖，因此计划末尾的 "Every spec section maps to at least one task above" **不勾选**——它是这一轮唯一一条明确知道没做到的清单项：

1. **§20.3 告警——整节没有任务。** 在计划的任务正文里检索 `alert` / `告警`，零命中（唯一的 `Alert` 是前端 `InlineAlert` 组件）。这一节的六条触发条件里，前两条与第五条**由预防机制覆盖而不是由告警覆盖**：`DELETED`/`SUPERSEDED`/`PROCESSING` 版本进不了最终证据（检索侧只认活跃版本），A3 把 `UNRESOLVED` 写成确定结论会被提交闸以 BLOCKING 拦下（E124）。剩下四条——索引与数据库长期不一致、摄取租约反复过期、Provider 错误率超阈值、物理清理失败——**既没有告警也没有替代机制**，只有 Task 14 的指标与 Task 18 的对账接口，需要人去查。这是**规格要求了、计划没安排**，不是实现写错了。
2. **§16.5 Embedding 升级——只做了一半。** `index_generation` 的分代投放与重建有任务（Task 9/10/18），但集合 alias 的原子切换、离线影子评测、以及保留 v1 回滚窗口再清理这三步没有任何任务。计划里 `alias` 只出现一次，是 Task 1 的一个配置字段（E4）。
3. **§11.2 查询准备——可选的查询改写 Provider 没有任务。** 计划的任务正文里检索改写相关字面零命中，Task 11 只覆盖了查询归一化与指纹。规格原文用的是「可以」，因此这一条是软缺口；但在补上之前，不要声称支持查询改写。
4. **§18.1 文件安全——「解析器运行在受限 worker 中」没有实现。** Task 10 的解析跑在持有租约的 worker 里，但没有任何隔离或沙箱约束。该节其余几条（恶意文件、加密 PDF、超限页数、不执行 PDF 脚本）都有任务。

另有两处轻微不齐，记下来是因为它们同样属于规格提到、实现没做：**§20.2** 的 `chunk` 数量与长度分布、来源多样性没有作为运行时指标实现（来源多样性只是黄金集与检索里的验收断言）；**§11.3** 的「适当超额召回」没有写成任何一步，只能从配置的 K 与多样性处理里读出来。

**这一条与「验收被跳过」是两件不同的事**：即使 Step 4/5/6 在真机上全部通过，上面四处仍然不会被那些用例发现——它们不是没跑，而是没写。按既定的验收边界，通过局部测试不代表完整 RAG 系统已完成，这四处正是那句话的具体位置。


## 实现证据（审查门：E158～E170）

**E158 —— 计划全部完成之后补做的一次代码审查，以及它的边界。** 20 个 Task 全部勾选之后，按
`## Implementation Order and Review Gates` 里那句 "Stop after each phase gate for code review of
the accumulated diff"，对累计 diff 做了一次只读审查：四个并行评审各看一段（测试完整性、检索与
冲突、摄取与存储、Agent 工具与 Web）。报告里的每一条前身我都回到代码里自己复核过，**复核不成立
的没有写进来**；成立的分两类——能安全修掉的当轮修掉并补了用例（E159～E166），需要改架构、或只能
在真实 PostgreSQL / MinIO / Milvus 上验证的记为已知缺口（E167、E168）。审查没有接触任何真实资源，
也没有提交任何改动。

**E159 —— 已接纳证据的读取端在 PostgreSQL 上必然抛 `TypeError`（本轮修掉）。**
`storage/postgres/research_library/evidence_repository.py` 读的 `qualifiers_json`、
`section_path_json`、`bounding_boxes_json` 三列在迁移 035 里是 JSONB，而 psycopg 3 对 JSONB 直接
返回 `list`；读取端写的是无条件 `json.loads`，于是对着一个 list 调用解析器。同目录的
`repository.py` 早就有 `_payload`（"JSONB 由驱动直接给出 Python 对象，TEXT 列则需要显式解析"）并在
14 处正确使用——规则是作者自己写下的，另一个读取端没有遵守。**后果是重的：PostgreSQL 是 RAG 唯一
的生产装配，所以 A2→A3/A4 的已接纳证据路径在每一台真实部署上都是崩的**，而离线套件看不见，因为
SQLite 那一侧读的正是 TEXT，显式解析才对。修法：把规则提成一个共享模块
`storage/postgres/research_library/json_columns.py`（`payload`），读取端改用它，`repository.py` 的
`_payload` 委托过去，规则从此只有一份。用例
`backend/tests/unit/storage/postgres/test_research_evidence_jsonb.py` 用驱动形状的假连接（行里的
`*_json` 是 list 而不是字符串）走完真实的读取代码；把 `payload` 换回无条件解析，它报的正是
`TypeError: the JSON object must be str, bytes or bytearray, not list`，其中一条失败的是默认值
`'[]'::jsonb` 的行——即"每一行都带空数组"的常态，不是边角。

**E160 —— `_governed` 接不住它自己那张表里写着的异常。** `_STATUS_BY_ERROR` 里
`(VectorIndexError, 503)` 与 `(ProviderError, 503)` 两行从来没有生效过：装饰器当时只接
`ResearchLibraryCommandError`，而这两个是 `RuntimeError` 的另一支。于是"派生索引连不上"在每个端点
上都绕过那张表，落到通用处理器变成 500。表说 503、代码给 500，是同一件事的两处定义。修法：
`_GOVERNED_ERRORS: tuple[type[Exception], ...] = tuple(kind for kind, _ in _STATUS_BY_ERROR)`，
装饰器接住的集合从表里取，一处定义、不会再分叉。用例
`test_maintenance_reports_an_unreachable_index_as_unavailable_not_as_a_crash` 让"一个已发布的版本"
与"一个抛错的索引"相遇，断言 503 且 `retryable=true`。

**E161 —— 四个维护端点漏在 `_governed` 之外，空 actor 报 500。**
`GET /maintenance`、`POST .../maintenance/reconcile|outbox|purge` 是路由里唯一没有 `@_governed` 的
四个。另外 `maintenance.py` 对"空 actor"抛的是裸 `ValueError`，而同一条规则在
`commands._require_actor` 里抛 `GovernanceRefused`（→409）——同一个错误在两边两种状态码，`purge`
会以一个 `retryable=true` 的 500 回答"你没有给名字"，而那是一条永远不会因为重试而成功的请求。修法：
四个端点补 `@_governed`；`maintenance.py` 两处改抛 `GovernanceRefused`（含导入；`commands` 不反向
依赖 `maintenance`，无环）。三条用例：空 actor 是 409 `GOVERNANCE_REFUSED`、服务层直接调用同样被拒、
索引连不上是 503（红→绿两半都验过）。

**E162 —— 维护接口把对象存储键交回浏览器。** `MaintenanceResponse` 的
`AssetDiscrepancyResponse.object_key` 是服务端派生的存储标识，而
`web/src/researchLibraryApi.ts` 的模块注释写的正是"浏览器拿不到模型与存储的实现标识"，
`commands.source` 一路都在避免这个键外泄（下载走的是按文档/版本查出来的键）。前端没有任何代码读
它。修法：删掉该字段——文档 + 版本 + 角色足以定位一项对不上的资产。两条用例：模型字段里没有
`object_key`，以及把整份响应的键名递归扫一遍（字段是后面加的，规则要能挡住后面加的那个）。

**E163 —— 重放会把已被撤回的正文继续递给模型。** `SearchInternalResearchTool.replay` 按审计取回
chunk 之后直接用 `chunk.content`，没有像 `search`（`filter_active_hits`）与 `inspect`
（`CandidateWithdrawn`）那样重新确认这一版还是不是 ACTIVE。审计记的是**当时**的结果：资料被软删除
或被新版本取代之后，重放成了唯一还在把撤回正文递出去的通道——而它恰好是模型直接能走的那条。修法：
重放时按版本批量问一次状态，不是 ACTIVE 就抛 `CandidateWithdrawn`。用例
`test_replay_refuses_a_candidate_the_library_has_since_withdrawn`；把检查禁掉，它报
`DID NOT RAISE CandidateWithdrawn`。

**E164 —— 上传响应用 `has_source=True` 代替询问。** 上传那一支写死 `has_source=True`，而另外三个
调用点都是从仓库问出来的（`get_original_asset_key(...) is not None`）。新建那一支当然刚写完原件，
但幂等重放那一支返回的是**已有**版本——它当初可能根本没写进原件（上次上传被拒、或那次没跑完），
照着 True 写回去等于替它担保。改成同样的询问，四个调用点从此一致。

**E165 —— `saveSource` 在同一轮里撤销 blob URL。** `anchor.click()` 只是把下载排进队列，浏览器读
这个 URL 是之后的事；在紧接着的同一轮里 `revokeObjectURL`，会不会把下载掐掉取决于实现时序，而下载
是用户按下按钮之后唯一还在等的事。改成下一轮回收。前端两条用例：撤销必须晚一轮（改回同一轮即失败，
报 `expected [ 'blob:research/1' ] to deeply equal []`），以及没有 `createObjectURL` 时什么都不做。

**E166 —— 两条对任何实现都成立的断言（测试完整性）。**
`test_a_retriable_provider_failure_stays_retryable` 里的
`all(event.status is not DONE for event in broken.events())` 在空列表上恒真，因此它区分不了"没有登记
任何事件"与"实现把事件错标成了 DONE"。改成写明 `broken.events() == ()`：失败发生在 `_embed`，
`_index` 还没轮到，所以"一条登记都没有"才是可断言的事实。
`test_a_stale_worker_stops_instead_of_failing_the_job` 里内联注释说"这一次 run 用的是 worker-2 的
租约"，而 `WORKER` 就是 `"worker-1"`、`run` 默认用它——**注释与事实相反**（这一次 run 正是那个租约
已被拿走的 worker-1）；断言 `attempt_id >=`、`status is not PERMANENT_FAILED` 也放过了"退回一格"与
"写成可重试失败"。改成：租约仍属 worker-2、`attempt_id` 未前进、状态未变、`failure_reason is None`。
收紧之后仍然通过，这同时证明冲突路径确实收敛成"返回权威库里的现状"。

**E167 —— 查询期的事实抽取、NLI 冲突检测与确定性裁决从未接进任何生产链路（本轮记录，不修）。**
全仓搜 `ClaimExtractionService` / `ConflictService` / `resolve_conflict` / `group_comparable_claims`：
构造点只在测试里（黄金集、Provider 预算集成、两个单测文件），`storage/runtime_bundle.py` 与
`web/dependencies.py` 对 claim / conflict 零引用，`ResearchLibraryServices` 也没有这两个字段。接替
它的是：`accept_internal_evidence` 把 `conflict_status` 做成**模型必填**的枚举参数
（`research_library_tools.py:390,426`），服务端只校验两件事——`CHECK_FAILED` 必须带
`requires_verification`、`UNRESOLVED` 必须来自两个不同切片（`artifacts.py:450-468`）。
**没有任何地方校验 `RESOLVED` 是被挣来的**：两份权重相同、互相矛盾、各自独立的文档，只要模型写下
`RESOLVED`，就会被当作已定论的事实存进权威库。规格 §13/§14 与 README 的流程图把这条链写成系统
行为（相关事实抽取 → NLI 冲突检测 → 规则能否解决），而它在本仓库里的真实状态是"部件已实现、单测
通过、从未组装"。这正是规格第 11、13 条点名要防的事，也是这个功能名字所系的保证
（"两条独立等权文档必须停在 UNRESOLVED"）。**不修的理由**：把它接上先要有生产 Provider 装配——
E138 记的缺口是每个 RAG Provider 连 base URL 与 key 都还没有自己的配置键——那是一个新计划的工作量，
不是审查门里顺手改一处就能安全完成的改动；在只有 SQLite 的离线环境里"修"它，只会得到一份看起来
接好了、却没有任何一次真实 NLI 调用验证过的装配。因此这里记成**已知缺口**，并在 README 里改正它
的现状描述（E169）。

**E168 —— 已核实、本轮未修的其余缺陷（逐条在案，供后续计划取用）。** 这些都需要真实 PostgreSQL /
MinIO / Milvus 才能验证或验收，本机没有 `_test` 实例（75 个 postgres 用例全部 skip），所以改它们
等于对着无法运行的代码猜；写在案上比改一半更诚实。
（1）**Provider 预算与配额是死的。** `BudgetedProviderCall` 在生产里零构造：`retrieval.py:244/329`
直接调 `self._embedding.embed` / `self._reranker.rerank`，`provider_calls` 是个写死的整数，于是每个
Provider 的调用上限、预留金额、租约，以及设置里的 `daily_budget_cny` 全都不参与任何决策；
`min_ocr_confidence` 同样只被读进配置对象，从来没有被任何一个分支用过。
（2）**Milvus 适配器 re-stage 会把 PUBLISHED 写回 STAGED。** 内存适配器刻意不这样，注释写着"已发布
的记录再 stage 一次是重试，不是回退"，两个实现不一致。而 `verify` 把 staged 当成存在、
`_check_index` 不看 `report.published`——对一份正在服务的版本执行 rebuild，可能让它查不到，同时维护
报告说"一致"。
（3）**保留期清理只清 PostgreSQL 的行。** `purge_expired` 只写信令库；`ResearchAssetStore.delete` /
`list_asset_keys` 在生产里零调用。保留期到期后原件仍留在 MinIO，而审计行写着"已清理"——对一份
"删除即不可再检索"的承诺来说，这是原件与承诺不符。
（4）**同一个 `upload_key` 重放会产生孤儿文档。** 重放路径先建出一份文档，再返回"新文档 + 别人的
版本"这一对互相矛盾的结果（`document_id != version.document_id`）。
（5）**purge 可重复执行，restore 不认 PURGED。** purge 的判据在 `deleted_at` / `purge_after` 未被
清空的情况下仍然命中，第二次照样成功并再写一条 PURGE 审计行；`restore` 对已 PURGED 的文档照样成功，
把它重新列进默认列表。
（6）**Milvus 的页边界被当成全集。** `_query` 在 `QUERY_LIMIT` 处截断，而 `publish` / `verify` /
stage 的冲突检测都把一页当作全量。需要一个版本的切片数超过上限才会触发，属潜在而非日常——但触发
时表现为"索引里明明有重复，冲突检测说没有"。

**E169 —— README 与状态文档按 E167 / E168 更正。** README 的流程图原先写着"融合、Rerank 与相关
事实提取 → NLI 冲突检测 → 规则能否解决冲突?"，读起来像这条链已经在跑；按 E167 它没有组装，图与
边界清单一起改了：新增"冲突裁决与事实抽取尚未接进运行时"的说明，并把 E157 已记的覆盖缺口（§20.3
告警、§16.5 Embedding 升级、§11.2 查询改写、§18.1 受限 worker 解析）与 E168 的缺陷并列成"已知
缺口"一节。`docs/PROJECT_STATUS.md` 同一处补上 E167 / E168 两条。其余说明不变：Provider 配置、
Milvus 必须服务端部署、三档测试的调用方式都保持原样。

**E170 —— 本轮门禁（改动后重跑）。** `ruff` All checks passed；`mypy` 362 files 无问题；前端
`66 files / 288 tests` 通过（本轮新增 2 条）、`npm run build` ✓（`✓ built in 253ms`）、
`test:tooling` pass 4 / fail 0；四个受影响的后端测试文件全绿（**这一组并不完整，见 E171**）：`test_research_library_api.py` 51、
`test_orchestration_research_library_tools.py` 26、`test_research_ingestion_pipeline.py` 28、
`test_research_evidence_jsonb.py` 3（新增文件）。E159 / E160 / E163 / E165 四处都做过红→绿：先用
补丁把修复拿掉，确认失败原因就是所描述的那一个，再恢复。全仓离线回归的数字见 E171。
**本轮仍未提交任何改动。**

**E171 —— 全量离线回归，以及它抓出的三处由本轮改动引入的失败。**
完整命令（仓库根）：`python -m pytest -q -m "not live and not live_llm and not live_rag and not
postgres and not minio and not milvus" --import-mode=importlib -p no:cacheprovider
--basetemp=.tmp-test/rag-review2`，结果 `1629 passed, 19 skipped, 122 deselected`（154.78s，exit 0）。
基线是 1620 passed，净增 9 条，正好等于本轮新增的用例数（`test_research_evidence_jsonb.py` 3、
`test_research_library_api.py` 5、`test_orchestration_research_library_tools.py` 1）。19 条跳过仍然
全部是"没有配置专用数据库"。

**这次全量回归第一次跑出来的是 3 处失败，三处都是本轮改动造成的，也都记在这里。** E170 只跑了
四个自认为受影响的文件，那一次是绿的；漏掉的两个文件才是真正受影响的地方。跳过它们没有别的理由，
就是没有把"我改了哪些行为"换算成"哪些文件在断言那个行为"。
（1）（2）`backend/tests/integration/test_research_library_maintenance.py` 的两条
（`test_repairing_without_an_actor_is_refused`、`test_a_purge_must_name_its_actor`）断言的是
`pytest.raises(ValueError, ...)`，而 E161 把这条拒绝从裸 `ValueError` 换成了
`GovernanceRefused`（`ResearchLibraryCommandError` 的子类，不是 `ValueError` 的子类）——失败正是这
一处行为变更的直接证据。修改方向是**收紧**，不是放宽：两条改成断言 `GovernanceRefused`，并写明
它是同一条规则在两边同型之后的结果，端到端那一半由 `test_research_library_api.py` 的 409 用例守着。
（3）`backend/tests/unit/test_package_layout.py::test_storage_dialects_have_matching_business_modules`
断言两种方言的业务模块一一对应，只允许 `POSTGRES_ONLY_MODULES` 里点名的例外。E159 新增的
`storage/postgres/research_library/json_columns.py` 没有 SQLite 一侧的孪生模块，于是它报的正是那句
"unlisted divergence still fails"。修法是把该模块登记进 `POSTGRES_ONLY_MODULES` 并写明理由
（"要不要再解析一次"是方言差异，SQLite 那一侧继续显式 `json.loads` 是对的）——用的是这条不变式
本身提供的出口，不是绕过它。

**E171 附：JSONB 这个坑的边界，全仓查过一遍。** `grep -rl JSONB migrations/` 只有
`035_research_library.sql` 与 `postgres/035_research_library.sql` 两个文件命中：前者建表用 TEXT，
后者是 PostgreSQL 补充迁移，把 **16 个** `*_json` 列改成 JSONB。也就是说，其余各域
（market / news / runs / review / writing / evaluation）的 `json.loads(row[...])` 写法**是对的**，
因为那些列本来就是 TEXT——仓库里那套惯用写法没有错，错的是这一份把它抄到了一个类型已经不同的列上。
这也解释了为什么它从来没被人碰到：每一个其他读取端都长成同一个样子，而且都对。
修完之后的核查：`storage/postgres/research_library/` 下对 JSONB 列的 17 处读取（`repository.py` 14 处
经 `_payload`、`evidence_repository.py` 3 处经 `payload`）全部经过这一处共享规则，没有剩下裸
`json.loads`。另外 `postgres/035` 还转换了 `claim_ids_json`，而这一列在 Python 侧既没有读端也没有写端
——它属于 E167 里那条没有接线的冲突链。

**E171 附：本轮门禁的最终数字。** Ruff `All checks passed`；Mypy `Success: no issues found in 362
source files`；前端 `66 files / 288 tests passed`、`npm run build` ✓、`test:tooling` pass 4 / fail 0；
后端全量离线 `1629 passed, 19 skipped, 122 deselected`（exit 0）。**仍然没有提交任何改动**，也没有
执行过 pull / reset / checkout / clean / stash。
