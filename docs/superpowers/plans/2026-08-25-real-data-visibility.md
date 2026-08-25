# Real Data Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every persisted data run show what each Provider actually returned, which normalized records were saved, and which news records entered the evidence chain without presenting missing fields as real zero values.

**Architecture:** Extend persisted market snapshots with field-coverage metadata and response hashes, add a run/query/document junction for complete future news lineage, then expose read-only acquisition and news-record APIs. The React workbench adds an always-visible acquisition summary and a paginated news-record tab while preserving the existing evidence tab as the processed subset.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy/asyncpg, SQLite/PostgreSQL migrations, React 18, TypeScript, Vitest, pytest.

## Global Constraints

- Missing Provider fields display as `未返回`; a real numeric zero remains `0` or `0%`.
- UI labels distinguish `Provider 返回`, `规范化保存`, and `进入证据链`.
- No endpoint triggers Provider or LLM calls; all detail endpoints are read-only.
- Do not store or return news full text, request headers, API keys, proxy configuration, or complete third-party exception messages.
- Historical runs without query-document lineage return `coverage=LINKED_ONLY` and an explicit notice.
- Preserve the existing uncommitted `backend/src/sector_pulse/web/server.py` port change and never stage it.
- Use project-owned `TEMP` and `TMP` for backend tests on Windows.

---

### Task 1: Preserve market field coverage truthfully

**Files:**
- Modify: `backend/src/sector_pulse/domain/market.py`
- Modify: `backend/src/sector_pulse/infrastructure/providers/akshare/mapper.py`
- Modify: `backend/src/sector_pulse/infrastructure/providers/akshare/adapter.py`
- Test: `backend/tests/unit/infrastructure/test_akshare_mapper.py`
- Test: `backend/tests/unit/infrastructure/test_akshare_adapter.py`

**Interfaces:**
- Produces: `SectorUniverseSnapshot.available_fields: frozenset[str]`
- Produces: `SectorUniverseSnapshot.raw_artifact_sha256: str | None`
- Valid field names: `provider_sector_id`, `name`, `pct_change`, `turnover_rate`, `total_market_cap`, `advancers`, `decliners`, `leader_name`, `leader_pct_change`
- Existing `SectorSnapshot.pct_change` remains `Decimal`; display truth comes from `available_fields`, avoiding candidate-algorithm changes.

- [ ] **Step 1: Write failing mapper tests**

Add tests that map a THS-style row containing only code/name and an EastMoney-style row containing an explicit zero change:

```python
def test_mapper_records_only_fields_present_in_provider_rows() -> None:
    snapshot = map_sector_rows(
        ({"代码": "881121", "名称": "半导体"},),
        SectorKind.INDUSTRY,
        OBSERVED,
        COLLECTED,
        "test",
        provider_id="akshare-ths",
        classification_prefix="ths",
        raw_artifact_sha256="abc123",
    )
    assert snapshot.available_fields == frozenset({"provider_sector_id", "name"})
    assert snapshot.raw_artifact_sha256 == "abc123"
    assert snapshot.sectors[0].pct_change == Decimal("0")


def test_mapper_marks_explicit_zero_as_available() -> None:
    snapshot = map_sector_rows(
        ({"板块代码": "BK1", "板块名称": "测试", "涨跌幅": 0},),
        SectorKind.INDUSTRY,
        OBSERVED,
        COLLECTED,
        "test",
    )
    assert "pct_change" in snapshot.available_fields
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure/test_akshare_mapper.py backend/tests/unit/infrastructure/test_akshare_adapter.py -q -p no:cacheprovider
```

Expected: failure because `available_fields`, `raw_artifact_sha256`, and the mapper argument do not exist.

- [ ] **Step 3: Implement field-key presence detection**

Add the two backward-compatible fields to `SectorUniverseSnapshot`, defaulting to empty/`None`. In the mapper, detect semantic field presence from keys rather than values so an explicit zero is present. Pass the batch SHA-256 from both adapters into `map_sector_rows`.

```python
class SectorUniverseSnapshot(BaseModel):
    # existing fields...
    available_fields: frozenset[str] = frozenset()
    raw_artifact_sha256: str | None = None


def _has_field(row: Mapping[str, Any], key: str) -> bool:
    return FIELD[key] in row or any(alias in row for alias in ALIASES.get(key, ()))
```

- [ ] **Step 4: Run focused tests and linters**

Run the Step 2 command, then:

```powershell
.\.venv\Scripts\ruff.exe check backend/src/sector_pulse/domain/market.py backend/src/sector_pulse/infrastructure/providers/akshare backend/tests/unit/infrastructure/test_akshare_mapper.py backend/tests/unit/infrastructure/test_akshare_adapter.py
```

Expected: all focused tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 5: Commit market truthfulness**

```powershell
git add backend/src/sector_pulse/domain/market.py backend/src/sector_pulse/infrastructure/providers/akshare/mapper.py backend/src/sector_pulse/infrastructure/providers/akshare/adapter.py backend/tests/unit/infrastructure/test_akshare_mapper.py backend/tests/unit/infrastructure/test_akshare_adapter.py
git commit -m "feat: preserve provider market field coverage"
```

---

### Task 2: Persist complete news query lineage

**Files:**
- Create: `backend/src/sector_pulse/storage/migrations/014_real_data_visibility.sql`
- Modify: `backend/src/sector_pulse/domain/news_retrieval.py`
- Modify: `backend/src/sector_pulse/application/news_retrieval.py`
- Modify: `backend/src/sector_pulse/application/phase1a2_probe.py`
- Modify: `backend/src/sector_pulse/storage/news_retrieval_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_news_retrieval_repository.py`
- Test: `backend/tests/unit/application/test_news_retrieval_plan.py`
- Test: `backend/tests/integration/test_news_retrieval_repository.py`
- Test: `backend/tests/integration/test_postgres_news_retrieval_repository.py`
- Test: `backend/tests/unit/storage/test_real_news_schema.py`

**Interfaces:**
- Produces: `NewsQueryDocumentLink(run_id: UUID, query_id: str, document_id: str)`
- Produces: `QueryExecutionResult.started_at` and `completed_at`
- Extends: `save_audit(run_id, metrics, query_results, links, query_documents)`
- Adds table: `news_query_documents(run_id, query_id, document_id)`

- [ ] **Step 1: Write failing SQLite repository and migration tests**

Create an audit containing one query, one metric and two `NewsQueryDocumentLink` values. Assert the junction rows can be read back and migration versions are `1..14`.

```python
links = (
    NewsQueryDocumentLink(run_id=run.run_id, query_id=query.query_id, document_id="doc-1"),
    NewsQueryDocumentLink(run_id=run.run_id, query_id=query.query_id, document_id="doc-2"),
)
repository.save_audit(run.run_id, (metric,), ((query, DataStatus.SUCCESS, 2, None),), (), links)
assert repository.list_query_documents(run.run_id) == links
```

- [ ] **Step 2: Run repository tests and verify RED**

```powershell
$env:TEMP=(Resolve-Path .test-tmp); $env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_news_retrieval_repository.py backend/tests/unit/storage/test_real_news_schema.py -q -p no:cacheprovider
```

Expected: failures for missing migration/model/signature/read method.

- [ ] **Step 3: Add migration and domain lineage model**

Use this migration shape:

```sql
CREATE TABLE news_query_documents (
    run_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES news_documents(document_id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, query_id, document_id),
    FOREIGN KEY (run_id, query_id) REFERENCES news_queries(run_id, query_id) ON DELETE CASCADE
);
CREATE INDEX idx_news_query_documents_run ON news_query_documents(run_id);
```

Add the frozen Pydantic `NewsQueryDocumentLink` model to `domain/news_retrieval.py`.

- [ ] **Step 4: Persist and read lineage in both repositories**

Extend both repository signatures, insert every link with conflict-safe semantics, and add:

```python
def list_query_documents(self, run_id: UUID) -> tuple[NewsQueryDocumentLink, ...]: ...
```

The PostgreSQL implementation remains async and is exposed through the existing blocking repository wrapper.

- [ ] **Step 5: Record accurate source metrics and query-document links**

Capture UTC `started_at`/`completed_at` in `_execute_one`. In `phase1a2_probe.py`, group executions by `source_id`, aggregate calls, retries, duration, safe error code and status, and create one lineage link for every execution/document pair before calling `save_audit`.

Status aggregation rule:

```python
def aggregate_status(statuses: Sequence[DataStatus]) -> DataStatus:
    if all(status is DataStatus.SUCCESS for status in statuses):
        return DataStatus.SUCCESS
    if all(status is DataStatus.FAILED for status in statuses):
        return DataStatus.FAILED
    return DataStatus.PARTIAL
```

- [ ] **Step 6: Run SQLite and PostgreSQL repository tests**

```powershell
$env:TEMP=(Resolve-Path .test-tmp); $env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_news_retrieval_plan.py backend/tests/integration/test_news_retrieval_repository.py backend/tests/integration/test_postgres_news_retrieval_repository.py backend/tests/unit/storage/test_real_news_schema.py -q -p no:cacheprovider
```

Expected: all tests pass; PostgreSQL test uses the configured local test database path already established by the repository suite.

- [ ] **Step 7: Commit news lineage**

```powershell
git add backend/src/sector_pulse/storage/migrations/014_real_data_visibility.sql backend/src/sector_pulse/domain/news_retrieval.py backend/src/sector_pulse/application/news_retrieval.py backend/src/sector_pulse/application/phase1a2_probe.py backend/src/sector_pulse/storage/news_retrieval_repository.py backend/src/sector_pulse/storage/postgres_news_retrieval_repository.py backend/tests/unit/application/test_news_retrieval_plan.py backend/tests/integration/test_news_retrieval_repository.py backend/tests/integration/test_postgres_news_retrieval_repository.py backend/tests/unit/storage/test_real_news_schema.py
git commit -m "feat: persist news query document lineage"
```

---

### Task 3: Build acquisition and news-record read models

**Files:**
- Modify: `backend/src/sector_pulse/storage/news_retrieval_repository.py`
- Modify: `backend/src/sector_pulse/storage/postgres_news_retrieval_repository.py`
- Modify: `backend/src/sector_pulse/application/data_run_workbench_queries.py`
- Test: `backend/tests/unit/application/test_data_run_workbench_queries.py`

**Interfaces:**
- Produces: `DataRunWorkbenchQueries.acquisition(run_id) -> dict[str, object]`
- Produces: `DataRunWorkbenchQueries.news_records(run_id, source_id, status, offset, limit) -> dict[str, object]`
- Extends: `DataRunWorkbenchQueries.market()` response with coverage metadata.

- [ ] **Step 1: Write failing query-layer tests**

Cover these exact cases with real temporary SQLite persistence:

1. A complete run reports industry/concept Provider counts, field lists, news query counts and three distinct count levels.
2. A historical run without junction rows reports `coverage == "LINKED_ONLY"` and returns only linked evidence documents.
3. News records filter by `source_id` and status, paginate deterministically by published/collected time, and never include another run's documents.
4. Market rows expose `field_availability`, causing absent THS metrics to be `available: false` while explicit zero remains available.

Expected acquisition shape:

```python
assert result["market_sources"][0]["available_fields"] == [
    "provider_sector_id", "name"
]
assert result["news_sources"][0]["query_count"] == 24
assert result["counts"] == {
    "provider_results": 255,
    "normalized_documents": 240,
    "evidence_events": 12,
}
```

- [ ] **Step 2: Run query tests and verify RED**

```powershell
$env:TEMP=(Resolve-Path .test-tmp); $env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_data_run_workbench_queries.py -q -p no:cacheprovider
```

Expected: failures for missing query methods and response metadata.

- [ ] **Step 3: Add repository audit readers**

Add matching SQLite/async PostgreSQL methods:

```python
def list_queries(self, run_id: UUID) -> tuple[NewsQueryAuditRecord, ...]: ...
def list_source_metrics(self, run_id: UUID) -> tuple[SourceRunMetric, ...]: ...
```

`NewsQueryAuditRecord` contains only persisted safe fields: query ID/type, source ID, sector IDs, priority, window, status, result count and error code. It does not expose the hashed query value as if it were readable text.

- [ ] **Step 4: Implement acquisition and news-record queries**

Aggregate source status from saved metrics when present and query rows otherwise. For complete runs, resolve document IDs through `news_query_documents`; for historical runs, derive only linked evidence documents and set `LINKED_ONLY`. Enrich evidence links with sector names from persisted snapshots.

- [ ] **Step 5: Run focused tests, Ruff and Mypy**

```powershell
$env:TEMP=(Resolve-Path .test-tmp); $env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_data_run_workbench_queries.py backend/tests/integration/test_news_retrieval_repository.py -q -p no:cacheprovider
.\.venv\Scripts\ruff.exe check backend/src/sector_pulse/application/data_run_workbench_queries.py backend/src/sector_pulse/storage/news_retrieval_repository.py backend/src/sector_pulse/storage/postgres_news_retrieval_repository.py backend/tests/unit/application/test_data_run_workbench_queries.py
.\.venv\Scripts\mypy.exe backend/src/sector_pulse/application/data_run_workbench_queries.py
```

Expected: all commands succeed.

- [ ] **Step 6: Commit read models**

```powershell
git add backend/src/sector_pulse/storage/news_retrieval_repository.py backend/src/sector_pulse/storage/postgres_news_retrieval_repository.py backend/src/sector_pulse/application/data_run_workbench_queries.py backend/tests/unit/application/test_data_run_workbench_queries.py
git commit -m "feat: query actual provider acquisition data"
```

---

### Task 4: Expose read-only visibility APIs

**Files:**
- Modify: `backend/src/sector_pulse/web/app.py`
- Test: `backend/tests/unit/web/test_app.py`
- Test: `backend/tests/integration/test_web_api.py`

**Interfaces:**
- Produces: `GET /api/data-runs/{run_id}/acquisition`
- Produces: `GET /api/data-runs/{run_id}/news-records?source_id=&status=&offset=&limit=`
- Extends: `GET /api/data-runs/{run_id}/market`

- [ ] **Step 1: Write failing API tests**

Assert 200 responses and exact pagination fields for both endpoints, 404 for an unknown run, and 422 for `offset=-1`, `limit=0`, `limit=101`, or an invalid status. Assert endpoints do not invoke the injected market/news/LLM providers.

- [ ] **Step 2: Run API tests and verify RED**

```powershell
$env:TEMP=(Resolve-Path .test-tmp); $env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/web/test_app.py backend/tests/integration/test_web_api.py -q -p no:cacheprovider
```

Expected: acquisition and news-record routes return 404 before implementation.

- [ ] **Step 3: Implement FastAPI routes**

Use `Query` constraints for pagination and map `KeyError` to HTTP 404. Accept `status` only from `DataStatus` and pass its value into the query layer. Do not include write methods or background tasks.

```python
@app.get("/api/data-runs/{run_id}/acquisition")
async def get_data_run_acquisition(run_id: UUID) -> dict[str, object]: ...

@app.get("/api/data-runs/{run_id}/news-records")
async def get_data_run_news_records(
    run_id: UUID,
    source_id: str | None = None,
    status: DataStatus | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]: ...
```

- [ ] **Step 4: Run API tests and commit**

Run the Step 2 command and Ruff on `app.py` plus the two test files. Expected: all pass.

```powershell
git add backend/src/sector_pulse/web/app.py backend/tests/unit/web/test_app.py backend/tests/integration/test_web_api.py
git commit -m "feat: expose real acquisition records api"
```

---

### Task 5: Add typed frontend clients

**Files:**
- Modify: `web/src/dataRunsApi.ts`
- Modify: `web/src/dataRunsApi.test.ts`

**Interfaces:**
- Produces: `fetchDataRunAcquisition(runId): Promise<DataRunAcquisitionView>`
- Produces: `fetchDataRunNewsRecords(runId, params): Promise<DataRunNewsRecordsView>`
- Extends: market snapshot and row types with availability metadata.

- [ ] **Step 1: Write failing API client tests**

Verify URL encoding for `source_id`, status and pagination, response parsing, and existing error-detail behavior.

```typescript
await fetchDataRunNewsRecords('run-1', {
  sourceId: 'eastmoney', status: 'SUCCESS', offset: 20, limit: 20,
})
expect(fetch).toHaveBeenCalledWith(
  '/api/data-runs/run-1/news-records?source_id=eastmoney&status=SUCCESS&offset=20&limit=20',
  expect.anything(),
)
```

- [ ] **Step 2: Run client tests and verify RED**

```powershell
npm.cmd --prefix web test -- dataRunsApi.test.ts
```

Expected: TypeScript/test failure because the new exports do not exist.

- [ ] **Step 3: Implement exact view types and clients**

Define typed source cards, count levels, news record, coverage (`COMPLETE | LINKED_ONLY`), field availability, filters and pagination. Reuse the existing `request` and `dataRunPath` helpers.

- [ ] **Step 4: Run tests, build and commit**

```powershell
npm.cmd --prefix web test -- dataRunsApi.test.ts
npm.cmd --prefix web run build
git restore -- web/tsconfig.tsbuildinfo
git add web/src/dataRunsApi.ts web/src/dataRunsApi.test.ts
git commit -m "feat: add acquisition visibility client"
```

Expected: client tests and production build pass; generated build-info is not committed.

---

### Task 6: Render actual acquisition data in the workbench

**Files:**
- Create: `web/src/pages/data-run/AcquisitionSummary.tsx`
- Create: `web/src/pages/data-run/NewsRecordsPanel.tsx`
- Modify: `web/src/pages/data-run/MarketPanel.tsx`
- Modify: `web/src/pages/data-run/EvidencePanel.tsx`
- Modify: `web/src/pages/DataRunPage.tsx`
- Modify: `web/src/pages/DataRunPage.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `DataRunAcquisitionView`, `DataRunNewsRecordsView`, enhanced market/evidence views.
- Produces: always-visible `本次实际获取` summary and new `新闻记录` tab.

- [ ] **Step 1: Write failing workbench tests**

Add tests for:

- Provider cards showing `行业行情 90 条`, `概念行情 375 条`, `东方财富 24 次查询 / 240 条返回`;
- three count-level labels;
- THS missing change rendering `未返回` and explicit available zero rendering `0%`;
- news record title/summary/source/time/link;
- Provider/status filters and pagination;
- historical `LINKED_ONLY` notice;
- independent acquisition/news errors not hiding candidates or evidence;
- refresh restoring the new sections without a new Provider request.

- [ ] **Step 2: Run page tests and verify RED**

```powershell
npm.cmd --prefix web test -- DataRunPage.test.tsx
```

Expected: failures because the summary and news tab do not exist.

- [ ] **Step 3: Implement acquisition summary**

Render market and news source cards with accessible headings and status labels. Display raw SHA-256 as a copyable text value only when present. Use `未记录` for historical missing hashes/field metadata.

- [ ] **Step 4: Implement truthful market rendering**

Centralize formatting:

```typescript
function metric(value: string | null, available: boolean, suffix = '') {
  if (!available) return '未返回'
  return value == null ? '空值' : `${value}${suffix}`
}
```

Do not infer availability from `value === '0'`.

- [ ] **Step 5: Implement news records and evidence lineage**

Add the `新闻记录` tab between行情 and candidates. Load it independently, apply Provider/status filters, reset offset on filter change, and render safe external links. Enhance evidence items with sector name, matched entities, confidence and mapping reason.

- [ ] **Step 6: Add responsive styles**

Use the existing card/table tokens. On narrow screens, stack source cards and filter controls and preserve horizontal table scrolling. Do not introduce a new UI dependency.

- [ ] **Step 7: Run focused tests and build**

```powershell
npm.cmd --prefix web test -- DataRunPage.test.tsx dataRunsApi.test.ts RunListPage.test.tsx
npm.cmd --prefix web run build
git restore -- web/tsconfig.tsbuildinfo
```

Expected: all focused tests and production build pass.

- [ ] **Step 8: Commit workbench UI**

```powershell
git add web/src/pages/data-run/AcquisitionSummary.tsx web/src/pages/data-run/NewsRecordsPanel.tsx web/src/pages/data-run/MarketPanel.tsx web/src/pages/data-run/EvidencePanel.tsx web/src/pages/DataRunPage.tsx web/src/pages/DataRunPage.test.tsx web/src/styles.css
git commit -m "feat: show actual provider acquisition data"
```

---

### Task 7: Migrate and perform end-to-end acceptance

**Files:**
- Modify only files from Tasks 1–6 if a verified defect is found.

- [ ] **Step 1: Verify fresh SQLite migration**

Create a project-owned temporary SQLite database, initialize it twice, and assert schema versions `1..14` plus the `news_query_documents` table and index.

- [ ] **Step 2: Apply PostgreSQL migration 014**

Load `.env` without printing credentials, run the normal PostgreSQL initializer, then query `schema_migrations`, `information_schema.tables`, and constraints. Expected: version 14 and the junction table/foreign keys exist.

- [ ] **Step 3: Run complete backend regression**

```powershell
$env:TEMP=(Resolve-Path .test-tmp); $env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider -m "not live" --ignore=backend/tests/unit/web/test_server.py
.\.venv\Scripts\ruff.exe check backend/src backend/tests
```

Expected: all in-scope non-live tests pass. Separately rerun `test_server.py` and record the existing `9000 != 8000` mismatch caused by the preserved user change.

- [ ] **Step 4: Run complete frontend regression and build**

```powershell
npm.cmd --prefix web test -- --pool=threads --maxWorkers=1
npm.cmd --prefix web run build
git restore -- web/tsconfig.tsbuildinfo
```

Expected: all frontend tests and production build pass.

- [ ] **Step 5: Perform local read-only HTTP/UI acceptance**

Start the current app on an unused loopback port. Against an existing historical run verify acquisition reports `LINKED_ONLY`, THS fields display `未返回`, linked news remain visible, and no Provider/LLM calls occur. Then run one separately authorized live data collection only if needed to verify `COMPLETE`; this task does not itself authorize that network mutation.

- [ ] **Step 6: Review worktree boundaries**

```powershell
git diff --check
git status --short
git diff -- backend/src/sector_pulse/web/server.py
```

Expected: only the original `server.py` port change remains uncommitted; no generated build-info or credential-bearing files are staged.

- [ ] **Step 7: Commit only verified corrections**

Stage exact correction files only. Do not create an empty commit and do not stage `server.py`.
