# THS Market Field Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate truthful THS industry market metrics, keep THS concept data explicitly list-only, and prevent unavailable market fields from influencing candidate ranking.

**Architecture:** The THS client will merge its industry name and summary DataFrames before the existing mapper boundary, while concept collection remains a code/name snapshot. Candidate selection will use snapshot field coverage to choose scoring dimensions, and a shared frontend capability helper will explain whether each snapshot is full, partial, or list-only.

**Tech Stack:** Python 3.12, AKShare 1.18.87, pandas, Pydantic 2, pytest, Ruff, React 18, TypeScript, Vitest.

## Global Constraints

- EastMoney remains the primary Provider for complete industry and concept market data.
- THS industry must merge `stock_board_industry_name_ths()` with `stock_board_industry_summary_ths()` by trimmed exact board name.
- THS industry collection fails if the two returned board sets do not match exactly.
- THS concept collection must not map `stock_board_concept_summary_ths()` into market fields.
- A snapshot with explicit `available_fields` but without `pct_change` cannot enter market candidate ranking.
- Optional unavailable metrics do not enter normalization as zero; available scoring weights are rescaled to a total market weight of `0.90`.
- News adds at most `0.10` and cannot promote a list-only sector into a market candidate.
- Missing Provider values continue to display as `未返回`; explicit zero remains a real zero.
- Do not add a database migration, new Provider, per-concept bulk crawl, or any LLM call.
- Do not commit or push unless the user explicitly requests it.

---

### Task 1: Merge truthful THS industry rows

**Files:**
- Create: `backend/tests/unit/infrastructure/test_akshare_client.py`
- Modify: `backend/src/sector_pulse/infrastructure/providers/akshare/client.py`
- Modify: `backend/src/sector_pulse/infrastructure/providers/akshare/mapper.py`
- Modify: `backend/tests/unit/infrastructure/test_akshare_mapper.py`

**Interfaces:**
- Consumes: `ak.stock_board_industry_name_ths() -> pandas.DataFrame`
- Consumes: `ak.stock_board_industry_summary_ths() -> pandas.DataFrame`
- Produces: `PandasThsAkShareClient.fetch(SectorKind.INDUSTRY) -> RawSectorBatch`
- Preserves: `PandasThsAkShareClient.fetch(SectorKind.CONCEPT)` uses only `stock_board_concept_name_ths()`.

- [ ] **Step 1: Write failing THS client tests**

Create tests that monkeypatch the AKShare functions with real DataFrames:

```python
import pandas as pd
import pytest

from sector_pulse.domain.market import SectorKind
from sector_pulse.infrastructure.providers.akshare import client as client_module
from sector_pulse.infrastructure.providers.akshare.client import PandasThsAkShareClient


async def test_ths_industry_merges_name_codes_with_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        client_module.ak,
        "stock_board_industry_name_ths",
        lambda: pd.DataFrame([{"name": "半导体", "code": "881121"}]),
    )
    monkeypatch.setattr(
        client_module.ak,
        "stock_board_industry_summary_ths",
        lambda: pd.DataFrame([{
            "板块": "半导体",
            "涨跌幅": 2.3,
            "上涨家数": 20,
            "下跌家数": 4,
            "领涨股": "测试股份",
            "领涨股-涨跌幅": 9.8,
        }]),
    )

    batch = await PandasThsAkShareClient().fetch(SectorKind.INDUSTRY)

    assert batch.rows == [{
        "name": "半导体",
        "code": "881121",
        "板块": "半导体",
        "涨跌幅": 2.3,
        "上涨家数": 20,
        "下跌家数": 4,
        "领涨股": "测试股份",
        "领涨股-涨跌幅": 9.8,
    }]


async def test_ths_industry_rejects_incomplete_name_join(monkeypatch) -> None:
    monkeypatch.setattr(
        client_module.ak,
        "stock_board_industry_name_ths",
        lambda: pd.DataFrame([{"name": "半导体", "code": "881121"}]),
    )
    monkeypatch.setattr(
        client_module.ak,
        "stock_board_industry_summary_ths",
        lambda: pd.DataFrame([{"板块": "白酒", "涨跌幅": 1.0}]),
    )

    with pytest.raises(ValueError, match="THS industry field contract mismatch"):
        await PandasThsAkShareClient().fetch(SectorKind.INDUSTRY)


async def test_ths_concept_remains_name_code_only(monkeypatch) -> None:
    monkeypatch.setattr(
        client_module.ak,
        "stock_board_concept_name_ths",
        lambda: pd.DataFrame([{"name": "AI 概念", "code": "309000"}]),
    )

    batch = await PandasThsAkShareClient().fetch(SectorKind.CONCEPT)

    assert batch.rows == [{"name": "AI 概念", "code": "309000"}]
```

- [ ] **Step 2: Run the client tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure/test_akshare_client.py -q -p no:cacheprovider
```

Expected: the merge test fails because industry currently calls only `stock_board_industry_name_ths`; the mismatch test fails because no join validation exists.

- [ ] **Step 3: Implement the minimal client merge**

Add focused helpers in `client.py`:

```python
def _normalized_board_name(value: object) -> str:
    return str(value).strip()


def _merge_ths_industry_rows(name_frame: Any, summary_frame: Any) -> list[dict[str, Any]]:
    names = name_frame.to_dict(orient="records")
    summaries = summary_frame.to_dict(orient="records")
    by_name = {_normalized_board_name(row.get("板块")): row for row in summaries}
    expected = {_normalized_board_name(row.get("name")) for row in names}
    if expected != set(by_name):
        raise ValueError("THS industry field contract mismatch")
    return [
        {**row, **by_name[_normalized_board_name(row.get("name"))]}
        for row in names
    ]
```

In `fetch(INDUSTRY)`, run both AKShare calls sequentially through `asyncio.to_thread(...)`; both initialize `py_mini_racer`/V8 and concurrent initialization can crash the Windows process. For concept, keep the existing single name call. Compute the SHA-256 over the final merged rows.

- [ ] **Step 4: Write and verify a failing mapper alias test**

Add a test mapping a merged THS industry row and assert `leader_name`, `leader_pct_change`, and all corresponding `available_fields` are present. Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure/test_akshare_mapper.py::test_mapper_supports_ths_industry_summary_fields -q -p no:cacheprovider
```

Expected: FAIL because `领涨股` and `领涨股-涨跌幅` are not mapper aliases.

- [ ] **Step 5: Add only the required mapper aliases**

Extend aliases without changing the domain schema:

```python
"name": ("名称", "板块", "name"),
"leader": ("领涨股票", "领涨股", "leader_name"),
"leader_pct": ("领涨股票-涨跌幅", "领涨股-涨跌幅", "leader_pct_change"),
```

- [ ] **Step 6: Run focused client, mapper, and adapter tests**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure/test_akshare_client.py backend/tests/unit/infrastructure/test_akshare_mapper.py backend/tests/unit/infrastructure/test_akshare_adapter.py -q -p no:cacheprovider
.\.venv\Scripts\ruff.exe check backend/src/sector_pulse/infrastructure/providers/akshare backend/tests/unit/infrastructure/test_akshare_client.py backend/tests/unit/infrastructure/test_akshare_mapper.py backend/tests/unit/infrastructure/test_akshare_adapter.py
```

Expected: all tests pass and Ruff prints `All checks passed!`.

---

### Task 2: Exclude unavailable fields from candidate ranking

**Files:**
- Modify: `backend/tests/unit/application/test_candidate_selection.py`
- Modify: `backend/src/sector_pulse/application/candidate_selection.py`

**Interfaces:**
- Preserves: `select_market_precandidates(...) -> tuple[SectorCandidate, ...]`
- Preserves: `select_candidates(...) -> tuple[SectorCandidate, ...]`
- Adds internal rule: explicit field coverage controls scoring eligibility; empty coverage remains legacy-compatible.

- [ ] **Step 1: Write a failing list-only exclusion test**

Construct a full industry universe and a THS concept universe with `available_fields=frozenset({"provider_sector_id", "name"})`. Assert every candidate is industry, even when a news event references the concept.

```python
def test_candidate_selection_excludes_explicit_list_only_universe() -> None:
    concept = universe(
        SectorKind.CONCEPT,
        available_fields=frozenset({"provider_sector_id", "name"}),
    )
    event = NewsEvent(
        event_id="concept-news",
        canonical_title="概念新闻",
        first_published_at=datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
        document_ids=("doc",),
        deduplication_reason="content_hash",
        sector_ids=("CONCEPT-A",),
    )

    candidates = select_candidates(full_industry(), concept, (event,), limit=12)

    assert candidates
    assert {item.kind for item in candidates} == {SectorKind.INDUSTRY}
```

- [ ] **Step 2: Run the exclusion test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_candidate_selection.py::test_candidate_selection_excludes_explicit_list_only_universe -q -p no:cacheprovider
```

Expected: FAIL because current ranking includes concept rows with synthetic zero metrics.

- [ ] **Step 3: Write a failing partial-dimension weighting test**

Create a THS industry snapshot with fields `provider_sector_id`, `name`, `pct_change`, `advancers`, `decliners`, `leader_name`, and `leader_pct_change`, but no turnover. Assert the stronger market move ranks first and scores stay at or below `0.90` without news.

- [ ] **Step 4: Run the weighting test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_candidate_selection.py::test_candidate_selection_rescales_only_available_market_dimensions -q -p no:cacheprovider
```

Expected: FAIL because turnover currently enters normalization as zero.

- [ ] **Step 5: Implement field-aware dimensions**

Use these exact rules:

```python
MARKET_SCORE_WEIGHT = Decimal("0.90")


def _field_available(universe: SectorUniverseSnapshot, field: str) -> bool:
    return not universe.available_fields or field in universe.available_fields


def _dimension_weights(universe: SectorUniverseSnapshot) -> tuple[tuple[str, Decimal], ...]:
    if not _field_available(universe, "pct_change"):
        return ()
    dimensions = [("pct_change", Decimal("0.45"))]
    if _field_available(universe, "turnover_rate"):
        dimensions.append(("turnover_rate", Decimal("0.25")))
    if _field_available(universe, "advancers") and _field_available(universe, "decliners"):
        dimensions.append(("breadth", Decimal("0.20")))
    return tuple(dimensions)
```

Skip a universe when the tuple is empty. Precompute values per included dimension, normalize them, multiply each original weight by `MARKET_SCORE_WEIGHT / sum(weights)`, and then add the existing news `0.10`. Only append `turnover` reason when turnover is available.

- [ ] **Step 6: Run candidate-selection regression**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/unit/application/test_candidate_selection.py backend/tests/integration/test_phase1a2_probe.py -q -p no:cacheprovider
.\.venv\Scripts\ruff.exe check backend/src/sector_pulse/application/candidate_selection.py backend/tests/unit/application/test_candidate_selection.py
```

Expected: all focused tests pass and Ruff is clean.

---

### Task 3: Explain Provider capability in the workbench

**Files:**
- Create: `web/src/pages/data-run/marketCapability.ts`
- Create: `web/src/pages/data-run/marketCapability.test.ts`
- Modify: `web/src/pages/data-run/MarketPanel.tsx`
- Modify: `web/src/pages/data-run/AcquisitionSummary.tsx`
- Modify: `web/src/pages/DataRunPage.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Produces: `marketCapability(source: MarketSnapshotSummary) -> { level, label, notice }`
- Consumes: existing `MarketSnapshotSummary.available_fields`.

- [ ] **Step 1: Write failing capability helper tests**

Cover three snapshots:

```typescript
expect(marketCapability({ ...source, available_fields: FULL_FIELDS }).label)
  .toBe('完整行情字段')
expect(marketCapability({
  ...source,
  available_fields: ['provider_sector_id', 'name', 'pct_change', 'advancers', 'decliners', 'leader_name', 'leader_pct_change'],
}).label).toBe('部分行情字段')
expect(marketCapability({
  ...source,
  kind: 'CONCEPT',
  available_fields: ['provider_sector_id', 'name'],
}).notice).toBe('仅板块清单，不参与行情排序')
```

- [ ] **Step 2: Run the helper test and verify RED**

```powershell
npm.cmd --prefix web test -- marketCapability.test.ts
```

Expected: TypeScript resolution failure because the helper does not exist.

- [ ] **Step 3: Implement the capability helper**

Use `pct_change` as the ranking eligibility boundary. Classify full coverage only when all current market fields are present, partial when `pct_change` is present, list-only when it is absent, and unknown when `available_fields` is missing.

- [ ] **Step 4: Write failing page assertions**

Extend `DataRunPage.test.tsx` so:

- THS industry displays `部分行情字段` and `未返回：换手率、总市值`;
- THS concept displays `仅板块清单，不参与行情排序`;
- explicit zero values still render as `0%`.

- [ ] **Step 5: Run page tests and verify RED**

```powershell
npm.cmd --prefix web test -- DataRunPage.test.tsx
```

Expected: FAIL because the capability labels and notice are not rendered.

- [ ] **Step 6: Render the capability in both market locations**

Use the helper in `MarketPanel` next to Provider/count metadata and in each `AcquisitionSummary` market card. Add a small badge style using existing color tokens; do not introduce a dependency or layout rewrite.

- [ ] **Step 7: Run focused frontend tests and build**

```powershell
npm.cmd --prefix web test -- marketCapability.test.ts DataRunPage.test.tsx dataRunsApi.test.ts
npm.cmd --prefix web run build
git restore -- web/tsconfig.tsbuildinfo
```

Expected: focused tests and production build pass.

---

### Task 4: Run regression and real field-contract acceptance

**Files:**
- Modify only Task 1–3 files if verification exposes a defect.

**Interfaces:**
- Verifies: THS industry Provider returns real metrics through `AkShareThsMarketDataAdapter`.
- Verifies: THS concept Provider remains list-only.
- Does not invoke: LLM generation.

- [ ] **Step 1: Run complete non-live backend tests**

```powershell
New-Item -ItemType Directory -Force .test-tmp | Out-Null
$env:TEMP=(Resolve-Path .test-tmp); $env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider -m "not live"
.\.venv\Scripts\ruff.exe check backend/src backend/tests
```

Expected: all non-live tests pass and Ruff prints `All checks passed!`.

- [ ] **Step 2: Run complete frontend tests and build**

```powershell
npm.cmd --prefix web test -- --pool=threads --maxWorkers=1
npm.cmd --prefix web run build
git restore -- web/tsconfig.tsbuildinfo
```

Expected: all frontend tests and the production build pass.

- [ ] **Step 3: Probe the real THS adapter without LLM**

Run a read-only script that calls only the THS market adapter and prints status, count, and field coverage:

```powershell
$env:PYTHONIOENCODING='utf-8'
@'
import asyncio
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.time import AnalysisMode
from sector_pulse.infrastructure.providers.akshare.adapter import AkShareThsMarketDataAdapter

async def main():
    adapter = AkShareThsMarketDataAdapter()
    for kind in (SectorKind.INDUSTRY, SectorKind.CONCEPT):
        result = await adapter.fetch_sector_universe(kind, AnalysisMode.LIVE)
        print(kind.value, result.status.value)
        if result.data:
            print("count", result.data.sector_count)
            print("fields", sorted(result.data.available_fields))
            print("sample", result.data.sectors[0].model_dump(mode="json"))

asyncio.run(main())
'@ | .\.venv\Scripts\python.exe -
```

Expected:

- industry: `SUCCESS`, 90 rows, with `pct_change`, `advancers`, `decliners`, `leader_name`, and `leader_pct_change` available;
- concept: `SUCCESS`, approximately 375 rows, with only `provider_sector_id` and `name` available;
- no LLM request is made.

- [ ] **Step 4: Review the worktree boundary**

```powershell
git diff --check
git status --short
git diff --stat
```

Expected: only the design, plan, intended source files, and tests are modified; no `.env`, credentials, generated build artifacts, or unrelated user files are included.
