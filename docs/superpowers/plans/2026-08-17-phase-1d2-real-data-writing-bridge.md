# Phase 1D-2 Real Data Writing Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert a persisted `READY_FOR_ATTRIBUTION` real-data run into the existing Phase 1B pipeline and generate an auditable article with the configured third-party OpenAI-compatible LLM.

**Architecture:** Repair run identity so Phase 1D-1 artifacts share one `run_id`, then add a repository-backed bridge that rebuilds `AttributionContext` and `AttributionGateResult` from persisted snapshots, evidence, events, documents, and links. A Web command invokes the existing Phase 1B pipeline with a real OpenAI-compatible provider; configuration is loaded from environment variables and project-root `.env` without exposing secrets.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLite, httpx, python-dotenv, pytest/pytest-asyncio, React/TypeScript/Vitest.

## Global Constraints

- Only `READY_FOR_ATTRIBUTION` runs may invoke an LLM.
- All Phase 1D-1 and Phase 1B artifacts for a new run use the same UUID.
- Configuration precedence is OS environment > project-root `.env` > `config/llm.yaml`.
- `.env` is ignored by Git; `.env.example` contains no real secret.
- `attribution`, `editorial`, `writing`, `review`, and `revision` share `SECTOR_PULSE_LLM_MODEL` in this phase.
- Real LLM calls require `.live-llm-consent`; ordinary tests never make network calls.
- API keys, Authorization headers, and raw third-party response bodies are never logged or persisted.
- Phase 2 scheduling, recovery, editing, publishing, and local market cache are out of scope.

---

### Task 1: Environment-backed application settings

**Files:**
- Modify: `pyproject.toml`
- Create: `.env.example`
- Create: `backend/src/sector_pulse/config/settings.py`
- Modify: `backend/src/sector_pulse/config/llm_config.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `backend/src/sector_pulse/web/live_provider.py`
- Test: `backend/tests/unit/config/test_settings.py`
- Test: `backend/tests/unit/config/test_llm_config.py`

**Interfaces:**
- Produces: `load_environment(dotenv_path: Path = Path(".env")) -> None`
- Produces: `ApplicationSettings.from_environment(yaml_config: LLMRuntimeConfig) -> ApplicationSettings`
- Produces fields: `database_path`, `llm_provider`, `llm_base_url`, `llm_api_key`, `llm_model`, `llm_timeout_seconds`, `budget_cny_per_run`, `max_attribution_concurrency`, `max_revision_rounds`.

- [ ] **Step 1: Write failing settings tests**

Cover `.env` loading with `override=False`, environment-over-YAML precedence, database path, shared model override, decimal budget, integer concurrency/revisions, timeout validation, and `SecretStr` serialization that never reveals the key.

- [ ] **Step 2: Run tests and verify failure**

Run: `./.venv/Scripts/python.exe -m pytest backend/tests/unit/config/test_settings.py backend/tests/unit/config/test_llm_config.py -v -p no:cacheprovider`

Expected: collection fails because `sector_pulse.config.settings` does not exist.

- [ ] **Step 3: Add configuration implementation**

Add `python-dotenv>=1.0,<2`; call `load_dotenv(dotenv_path, override=False)`. Build immutable Pydantic settings from exact `SECTOR_PULSE_*` names in the design. Apply environment budget/concurrency/revision/model overrides to the loaded YAML config without changing its pricing map.

- [ ] **Step 4: Wire application startup**

`create_app()` loads `.env` before building database and services, defaults `database_path` from settings, and supplies timeout/base URL/key/model through the live provider builder. Existing test overrides must still bypass real credentials.

- [ ] **Step 5: Add safe examples and local configuration**

Create `.env.example` with all names and blank secret fields. Create the ignored local `.env` using the user-supplied third-party URL, API key, and shared model; do not print or commit its contents.

- [ ] **Step 6: Verify task**

Run the focused tests and `ruff check` on changed configuration files. Expected: all pass and no secret appears in test output or `git diff`.

---

### Task 2: Unify Phase 1D run identity and persist candidates

**Files:**
- Modify: `backend/src/sector_pulse/domain/time.py`
- Modify: `backend/src/sector_pulse/application/phase1a2_probe.py`
- Modify: `backend/src/sector_pulse/application/real_data_orchestrator.py`
- Modify: `backend/src/sector_pulse/domain/real_data_run.py`
- Test: `backend/tests/integration/test_real_data_orchestrator.py`
- Test: `backend/tests/unit/domain/test_time.py`

**Interfaces:**
- Produces: `AnalysisRun.create_live(requested_at: datetime, run_id: UUID | None = None) -> AnalysisRun`
- Adds: `Phase1A2Request.run_id: UUID | None`
- Adds to `Phase1A2Report`: `final_candidates: tuple[SectorCandidate, ...]` and `evidence_packs: tuple[EvidencePack, ...]`.

- [ ] **Step 1: Write failing identity and candidate-persistence tests**

Assert a supplied UUID reaches `AnalysisRun`, snapshots/evidence use the same UUID, and `SQLiteRealDataRunRepository.get_candidates()` returns the Phase 1A.2 final ranking after a ready run.

- [ ] **Step 2: Run tests and verify failure**

Run: `./.venv/Scripts/python.exe -m pytest backend/tests/unit/domain/test_time.py backend/tests/integration/test_real_data_orchestrator.py -v -p no:cacheprovider`

Expected: failure because `create_live` and `Phase1A2Request` do not accept `run_id` and candidates are not saved.

- [ ] **Step 3: Implement identity propagation**

Use the supplied UUID when present; preserve `uuid4()` for existing callers. Pass the real run UUID from `run_real_data_workflow()` into `Phase1A2Request` and ensure all produced packs/links use it.

- [ ] **Step 4: Persist final candidates**

Convert every `SectorCandidate` into `RealDataCandidate(sector_id, sector_kind, rank, score, reasons)` and call `repository.save_candidates()` only after Phase 1A.2 completes. Expose candidates and packs on `RealDataRunResult`.

- [ ] **Step 5: Verify task**

Run focused tests and confirm both identity and candidate round trips pass.

---

### Task 3: Add repository read models for the persisted bridge

**Files:**
- Modify: `backend/src/sector_pulse/storage/evidence_repository.py`
- Modify: `backend/src/sector_pulse/storage/news_repository.py`
- Modify: `backend/src/sector_pulse/storage/news_retrieval_repository.py`
- Test: `backend/tests/unit/storage/test_phase1d2_bridge_repositories.py`

**Interfaces:**
- Produces: `SQLiteEvidenceRepository.list_for_run(run_id: UUID) -> tuple[EvidencePack, ...]`
- Produces: `SQLiteNewsRepository.get_events(event_ids: Sequence[str]) -> tuple[NewsEvent, ...]`
- Produces: `SQLiteNewsRepository.get_documents(document_ids: Sequence[str]) -> dict[str, NewsDocument]`
- Produces: `SQLiteNewsRetrievalRepository.list_links(run_id: UUID) -> tuple[SectorEventLink, ...]`

- [ ] **Step 1: Write failing repository round-trip tests**

Save two evidence packs, events/documents, and sector-event links, then load by run/event/document ID. Assert domain objects, ordering, and empty-input behavior.

- [ ] **Step 2: Run tests and verify failure**

Run: `./.venv/Scripts/python.exe -m pytest backend/tests/unit/storage/test_phase1d2_bridge_repositories.py -v -p no:cacheprovider`

Expected: attribute errors for the new read methods.

- [ ] **Step 3: Implement read methods**

Read `payload_json`/`metadata_json` and validate with the existing domain models. Use SQL placeholders only for non-empty ID sequences and stable ordering by stored IDs.

- [ ] **Step 4: Verify task**

Run focused tests and Ruff. Expected: all pass.

---

### Task 4: Build the Phase 1D-2 request bridge and gate

**Files:**
- Create: `backend/src/sector_pulse/application/real_data_writing_bridge.py`
- Test: `backend/tests/unit/application/test_real_data_writing_bridge.py`

**Interfaces:**
- Produces exceptions: `RealDataRunNotReady`, `RealDataBridgeIncomplete`
- Produces: `build_phase1b_request(database: SQLiteDatabase, run_id: UUID) -> Phase1BRequest`

- [ ] **Step 1: Write failing gate tests**

Assert missing runs, every non-ready status, missing cutoff, missing snapshots, fewer than three candidates, and missing evidence packs fail before any LLM dependency is constructed.

- [ ] **Step 2: Write failing happy-path test**

Seed one ready run with both snapshots, three candidates, evidence packs, events, documents, and links. Assert the returned request preserves `run_id`, requested time, context cutoff, market facts, eligible/background/excluded event IDs, source grades, and one gate per context.

- [ ] **Step 3: Run tests and verify failure**

Run: `./.venv/Scripts/python.exe -m pytest backend/tests/unit/application/test_real_data_writing_bridge.py -v -p no:cacheprovider`

Expected: module import failure.

- [ ] **Step 4: Implement bridge**

Load persisted artifacts through Task 3 repositories. Locate sector snapshots by `(sector_id, sector_kind)`, call `build_attribution_context()` and `evaluate_attribution_gate()`, and return an immutable `Phase1BRequest`. Never rerank candidates or increase attribution levels.

- [ ] **Step 5: Verify task**

Run focused tests. Expected: all gate and happy paths pass.

---

### Task 5: Add idempotent Web generation command

**Files:**
- Create: `backend/src/sector_pulse/web/data_run_writing_service.py`
- Modify: `backend/src/sector_pulse/web/app.py`
- Modify: `backend/src/sector_pulse/web/data_run_schemas.py`
- Test: `backend/tests/unit/web/test_data_run_writing_service.py`
- Modify: `backend/tests/integration/test_web_api.py`

**Interfaces:**
- Produces: `DataRunWritingService.generate(run_id: UUID) -> UUID`
- Adds endpoint: `POST /api/data-runs/{run_id}/generate` returning HTTP 202 and `{ "run_id": "..." }`.

- [ ] **Step 1: Write failing service tests**

Assert consent/config checks happen before task creation, non-ready runs map to stable errors, duplicate in-flight calls reuse the same task, completed drafts do not trigger a second LLM call, and a ready run executes `run_phase1b_pipeline()` with the bridged request.

- [ ] **Step 2: Write failing API tests**

Assert 202 for accepted generation, 404 for missing run, 409 for gate/config/consent failures, and no API response contains an API key.

- [ ] **Step 3: Run tests and verify failure**

Run: `./.venv/Scripts/python.exe -m pytest backend/tests/unit/web/test_data_run_writing_service.py backend/tests/integration/test_web_api.py -v -p no:cacheprovider`

Expected: missing service/route failures.

- [ ] **Step 4: Implement service and route**

Reuse existing `Phase1BDependencies`, repositories, prompt registry, invocation audit, progress bus, and live provider. Require `.live-llm-consent`; map internal exceptions to stable public messages. Keep one in-process task per UUID and check existing Phase 1B run/draft state for idempotency.

- [ ] **Step 5: Verify task**

Run focused tests and Ruff. Expected: all pass.

---

### Task 6: Add the generate action to the real-data detail page

**Files:**
- Modify: `web/src/dataRunsApi.ts`
- Modify: `web/src/pages/DataRunPage.tsx`
- Modify: `web/src/pages/DataRunPage.test.tsx`

**Interfaces:**
- Produces: `generateDataRunArticle(runId: string): Promise<{ run_id: string }>`

- [ ] **Step 1: Write failing UI tests**

Assert “生成分析稿” appears only for `READY_FOR_ATTRIBUTION`, clicking invokes the API once, success navigates to `/runs/{runId}`, and blocked/degraded states display a non-actionable reason.

- [ ] **Step 2: Run tests and verify failure**

Run: `npm --prefix web test -- DataRunPage.test.tsx`

Expected: missing API/button assertions fail.

- [ ] **Step 3: Implement API and page behavior**

Add the typed POST request, disabled/loading state, safe error message, and navigation to the existing Phase 1B detail route. Keep existing quality/candidate rendering unchanged.

- [ ] **Step 4: Verify task**

Run the focused Vitest test and `npm --prefix web run build`. Expected: pass.

---

### Task 7: Integration and explicit real-LLM acceptance

**Files:**
- Create: `backend/tests/integration/test_phase1d2_pipeline.py`
- Create: `backend/tests/live/test_phase1d2_live_llm.py`
- Create: `scripts/verify-phase1d2.ps1`
- Create: `docs/phase1d2/README.md`
- Create: `docs/phase1d2/latest-live-validation.md`

**Interfaces:**
- Adds pytest marker flow: existing `live_llm` plus explicit `--run-live-llm` option if not already present.

- [ ] **Step 1: Add local fake-provider integration test**

Seed a ready persisted run and use a deterministic fake OpenAI-compatible HTTP transport for attribution, editorial, writing, review, and optional revision. Assert a draft, review, invocation records, model name, cost, and the shared run UUID are persisted.

- [ ] **Step 2: Add guarded live acceptance test**

Skip unless `.live-data-consent`, `.live-llm-consent`, required `SECTOR_PULSE_LLM_*` configuration, and `--run-live-llm` are present. Run real data acquisition followed by Phase 1D-2 and assert a non-empty draft plus audit metadata; never print the key or raw response.

- [ ] **Step 3: Add verification script and docs**

The PowerShell script runs Ruff, backend unit/integration tests, frontend tests/build, and optionally guarded live checks. The live validation report records command, date, provider ID, model, final status, elapsed time, estimated cost, and article metadata without secrets.

- [ ] **Step 4: Run offline verification**

Run: `powershell -ExecutionPolicy Bypass -File ./scripts/verify-phase1d2.ps1`

Expected: all offline checks pass; live tests skip without explicit flags.

- [ ] **Step 5: Run explicit real acceptance**

After the local `.env` and `.live-llm-consent` are present, run the documented `--run-live --run-live-llm` command. Expected: a real-data run reaches `READY_FOR_ATTRIBUTION`, the configured third-party model produces a non-empty article, and the audit report contains no secret.

---

## Final Verification

- [ ] Run Ruff across `backend/src` and `backend/tests`.
- [ ] Run all backend tests with a workspace-local pytest temp directory on Windows.
- [ ] Run all frontend tests and production build.
- [ ] Verify `.env` is ignored and absent from `git diff --cached`.
- [ ] Verify non-ready runs make zero LLM HTTP calls.
- [ ] Verify the explicit live run reports provider, model, status, cost, elapsed time, and draft ID without exposing the API key.
