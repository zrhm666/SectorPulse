# Tonghuashun Market Provider Fallback Implementation Plan

> **For implementation:** follow this plan task by task, using TDD and verifying each checkpoint before proceeding.

## Goal

在保留东方财富 AKShare Provider 为首选的前提下，接入免费的同花顺 AKShare 行情 Provider；当东方财富返回 `FAILED`、`EMPTY` 或 `UNAVAILABLE` 时，自动切换到同花顺，并让最终结果明确标识实际数据来源。

## Architecture

- `AkShareMarketDataAdapter` 继续作为首选 Provider，现有行为和 Eastmoney 映射保持兼容。
- 新增 `AkShareThsMarketDataAdapter`，通过 AKShare 的同花顺行业/概念板块名称接口获取数据。
- 新增 `FallbackMarketDataAdapter`，只在首选结果不可用时调用备用 Provider，不合并两个来源的数据。
- `RealDataProviderFactory.build()` 返回包装后的市场 Provider；新闻 Provider 和 AS_OF 行为不变。

## Tech Stack

- Python 3.12, asyncio, pytest, pytest-asyncio
- AKShare DataFrame/record 结果
- 现有 `ProviderResult`、`DataStatus`、`SectorUniverseSnapshot` 领域契约

## Global Constraints

- 不需要 API Key；使用现有 AKShare 免费接口。
- 不改变现有 Eastmoney Provider 的公开类名和调用方式。
- 保留中文字段映射及现有错误契约；异常必须转换为 `ProviderError`。
- 不在单元测试中发起真实网络请求；使用注入的 fake fetcher。
- 不改动用户已有的未提交 Phase 1D-1 工作。

## Task 1: Define THS row mapping and adapter contract

**Files:**
- Create/modify: `backend/src/sector_pulse/infrastructure/providers/akshare/adapter.py`
- Modify: `backend/src/sector_pulse/infrastructure/providers/akshare/mapper.py`
- Create/modify: `backend/tests/unit/infrastructure/test_akshare_adapter.py`

**Tests first:**

1. Add a fake-fetcher test for industry and concept rows, asserting code/name/change-rate and optional turnover/advance/decline fields are mapped into `SectorUniverseSnapshot`.
2. Assert the THS result has `provider_id="akshare-ths"` and a THS classification/source version.
3. Assert `AS_OF` returns `UNAVAILABLE` without calling the fetcher.
4. Run the focused tests and confirm they fail before implementation.

**Implementation:**

1. Make the mapper accept optional provider/classification identifiers while preserving Eastmoney defaults.
2. Add `AkShareThsMarketDataAdapter` with injectable async/sync fetcher support; the default fetcher selects the corresponding AKShare THS industry or concept function and executes blocking calls off the event loop.
3. Normalize DataFrame results to records, map supported THS aliases, and return the existing `ProviderResult` contract.

## Task 2: Add primary/secondary fallback behavior

**Files:**
- Create: `backend/src/sector_pulse/infrastructure/providers/fallback.py`
- Create/modify: `backend/tests/unit/infrastructure/test_market_provider_fallback.py`

**Tests first:**

1. Assert a primary `SUCCESS` is returned unchanged and the secondary is not called.
2. Assert primary `FAILED`, `EMPTY`, and `UNAVAILABLE` each invoke the secondary and return its successful result.
3. Assert both failures return one `FAILED` result with a safe fallback error and no data.
4. Run the focused tests and confirm they fail before implementation.

**Implementation:**

1. Implement a generic market fallback adapter over the existing async market-provider protocol.
2. Preserve successful results, including their actual `provider_id` and `source_version`.
3. Keep the primary error as diagnostic context while preventing exception leakage from either provider.

## Task 3: Integrate the fallback into the real-data factory

**Files:**
- Modify: `backend/src/sector_pulse/infrastructure/providers/real_data_factory.py`
- Create/modify: `backend/tests/unit/infrastructure/test_real_data_factory.py`

**Tests first:**

1. Assert `RealDataProviderFactory.build().market` is the fallback composition with Eastmoney first and THS second.
2. Assert existing news and constituent providers remain unchanged.
3. Run the focused factory tests and confirm they fail before implementation.

**Implementation:**

1. Construct `AkShareMarketDataAdapter()` as primary and `AkShareThsMarketDataAdapter()` as secondary.
2. Inject both into `FallbackMarketDataAdapter` from the factory.
3. Keep preflight consent, live-mode gating, and all non-market providers unchanged.

## Task 4: Verification and regression checks

**Files:**
- No additional production files; update docs only if provider manifests require it.

**Checks:**

1. Run focused adapter, fallback, and factory tests.
2. Run Ruff on changed backend files.
3. Run the backend unit suite and report any pre-existing failures separately from this change.
4. Run the existing live test only when the user explicitly wants a real-network check; it remains environment-dependent.

## Completion Criteria

- Eastmoney remains first choice.
- THS is attempted automatically for `FAILED`, `EMPTY`, or `UNAVAILABLE` primary results.
- Successful output identifies the actual source Provider.
- Unit tests cover success, fallback, both-fail, AS_OF, and factory wiring paths.
- Existing offline tests and lint pass, with live-network limitations reported honestly.
