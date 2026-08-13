# Phase 0 Foundation and Market Data Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立最小但可扩展的 Python 领域契约，并用真实 AKShare/东方财富行业与概念板块数据证明 cutoff、字段映射、覆盖率、错误语义和候选雷达的可行性。

**Architecture:** Phase 0 只实现 Domain、Port、AKShare Adapter、质量检查和只读探测 CLI，不创建九个业务模块空壳。实时运行先采集核心行情，再按实际观测时间锁定 cutoff；所有供应商 DataFrame 在 Adapter 边界内转换为 Pydantic 领域对象。

**Tech Stack:** Python 3.12+、Pydantic v2、Pandas、AKShare、Typer、pytest、Ruff、mypy。

## Global Constraints

- 市场范围固定为 A 股行业板块 + 概念板块。
- Phase 0 不调用 LLM，不采集社区内容，不生成文案，不实现 Web。
- LIVE 任务在行业与概念核心行情采集且通过时点检查后锁定 `run_cutoff_at`。
- AS_OF 任务启动时锁定指定 cutoff；AKShare 实时板块列表 Adapter 明确声明不支持 AS_OF。
- `EMPTY`、`PARTIAL`、`STALE`、`UNAVAILABLE`、`FAILED` 必须是不同结果。
- 公共契约不暴露 pandas DataFrame、AKShare 中文列名或供应商异常类型。
- 原始响应和真实运行产物写入 `data/phase0/`，不得提交 Git。
- AKShare/东方财富 Provider Manifest 初始授权状态固定为 `RESEARCH_ONLY`，不得标记为正式公开生产源。
- 每个 Task 必须先写失败测试，再实现，再运行完整相关测试并提交。
- Python 文件使用 UTF-8；时间必须是带时区的 UTC `datetime`。

---

## File Structure

```text
pyproject.toml                         # Python 包、依赖和质量工具配置
backend/src/sector_pulse/
  __init__.py                         # 包版本
  domain/
    time.py                           # AnalysisRun、模式、cutoff 锁定
    provider.py                       # ProviderResult、Manifest、错误语义
    market.py                         # 板块与全市场快照领域对象
    quality.py                        # 覆盖、重复、时点质量规则
    radar.py                          # Phase 0 诊断雷达，不是正式选板分
  ports/
    market_data.py                    # MarketDataPort
  infrastructure/providers/akshare/
    client.py                         # AKShare DataFrame 调用封装
    mapper.py                         # 中文字段到领域对象的纯映射
    adapter.py                        # Port Adapter 和异常转换
  application/
    phase0_probe.py                   # 采集、质量、cutoff、雷达编排
  reporting/
    phase0_report.py                  # JSON/Markdown 验收报告
  cli.py                              # `sector-pulse phase0-probe`
backend/tests/
  unit/domain/                        # 时间、结果、质量、雷达测试
  unit/infrastructure/                # AKShare 固定样本映射测试
  integration/                        # 假 Provider 的 Phase 0 全链路
  live/                               # 显式 `--run-live` 才执行的真实网络测试
  fixtures/                           # 去标识化固定字段样本
plugins/providers/
  akshare-eastmoney/manifest.json     # 能力与授权状态
  tushare-pro/manifest.json           # 第二来源能力调研，不实现 Adapter
docs/provider-matrix/phase-0.md       # 来源、能力、风险和进入生产的条件
docs/phase0/latest-market-data-validation.md  # 真实探测生成的摘要
data/phase0/                          # 被忽略的真实运行产物
```

---

### Task 1: Bootstrap the Python Quality Baseline

**Files:**
- Create: `pyproject.toml`
- Create: `backend/src/sector_pulse/__init__.py`
- Create: `backend/tests/test_package_smoke.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Python 3.12 or newer.
- Produces: importable package `sector_pulse`, `sector-pulse` CLI entry point, pytest/Ruff/mypy configuration.

- [ ] **Step 1: Add the packaging and test configuration**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[project]
name = "sector-pulse"
version = "0.1.0"
description = "Evidence-first A-share sector analysis assistant"
requires-python = ">=3.12"
dependencies = [
  "akshare>=1.17,<2",
  "pandas>=2.2,<4",
  "pydantic>=2.11,<3",
  "typer>=0.16,<1",
]

[project.optional-dependencies]
dev = [
  "mypy>=1.17,<2",
  "pandas-stubs>=2.2,<3",
  "pytest>=8.4,<10",
  "pytest-cov>=6,<8",
  "ruff>=0.12,<1",
]

[project.scripts]
sector-pulse = "sector_pulse.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["backend/src/sector_pulse"]

[tool.pytest.ini_options]
testpaths = ["backend/tests"]
addopts = "-ra --strict-markers"
markers = ["live: requires explicit live network access"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["sector_pulse"]
mypy_path = "backend/src"
```

Append these exact lines to `.gitignore`:

```gitignore
artifacts/
.live-data-consent
```

- [ ] **Step 2: Create an isolated environment and install the editable package**

Run:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Expected: all commands exit `0`; no dependency is installed globally.

- [ ] **Step 3: Write the failing smoke test**

Create `backend/tests/test_package_smoke.py`:

```python
def test_package_exposes_version() -> None:
    import sector_pulse

    assert sector_pulse.__version__ == "0.1.0"
```

- [ ] **Step 4: Run the test and verify the package module is missing**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_package_smoke.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'sector_pulse'`.

- [ ] **Step 5: Add the minimal package**

Create `backend/src/sector_pulse/__init__.py`:

```python
"""A-share sector analysis assistant."""

__version__ = "0.1.0"
```

- [ ] **Step 6: Run the baseline checks**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_package_smoke.py -v
.venv\Scripts\python.exe -m ruff check backend
.venv\Scripts\python.exe -m mypy backend/src
```

Expected: one test PASS; Ruff and mypy exit `0`.

- [ ] **Step 7: Commit**

```powershell
git add .gitignore pyproject.toml backend/src/sector_pulse/__init__.py backend/tests/test_package_smoke.py
git commit -m "build: bootstrap Python quality baseline"
```

---

### Task 2: Define LIVE and AS_OF Cutoff Semantics

**Files:**
- Create: `backend/src/sector_pulse/domain/__init__.py`
- Create: `backend/src/sector_pulse/domain/time.py`
- Create: `backend/tests/unit/domain/test_time.py`

**Interfaces:**
- Consumes: Pydantic v2.
- Produces: `AnalysisMode`, `AnalysisRun`, `CutoffAlreadyLockedError`, `InvalidCutoffError`.

- [ ] **Step 1: Write the cutoff contract tests**

Create `backend/tests/unit/domain/test_time.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sector_pulse.domain.time import (
    AnalysisMode,
    AnalysisRun,
    CutoffAlreadyLockedError,
    InvalidCutoffError,
)

UTC = timezone.utc


def test_live_run_locks_actual_cutoff_once() -> None:
    requested = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)
    observed = datetime(2026, 8, 13, 6, 0, 8, tzinfo=UTC)
    locked_at = datetime(2026, 8, 13, 6, 0, 9, tzinfo=UTC)

    run = AnalysisRun.create_live(requested_at=requested)
    locked = run.lock_live_cutoff(observed_at=observed, locked_at=locked_at)

    assert locked.mode is AnalysisMode.LIVE
    assert locked.run_cutoff_at == observed
    assert locked.cutoff_locked_at == locked_at
    with pytest.raises(CutoffAlreadyLockedError):
        locked.lock_live_cutoff(observed_at=observed, locked_at=locked_at)


def test_live_cutoff_cannot_be_later_than_lock_time() -> None:
    run = AnalysisRun.create_live(
        requested_at=datetime(2026, 8, 13, 6, 0, tzinfo=UTC)
    )
    with pytest.raises(InvalidCutoffError):
        run.lock_live_cutoff(
            observed_at=datetime(2026, 8, 13, 6, 1, tzinfo=UTC),
            locked_at=datetime(2026, 8, 13, 6, 0, 59, tzinfo=UTC),
        )


def test_as_of_run_locks_requested_cutoff_at_creation() -> None:
    run = AnalysisRun.create_as_of(
        requested_at=datetime(2026, 8, 13, 8, 0, tzinfo=UTC),
        requested_cutoff_at=datetime(2026, 8, 12, 7, 0, tzinfo=UTC),
    )
    assert run.mode is AnalysisMode.AS_OF
    assert run.run_cutoff_at == datetime(2026, 8, 12, 7, 0, tzinfo=UTC)
    assert run.cutoff_locked_at == datetime(2026, 8, 13, 8, 0, tzinfo=UTC)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AnalysisRun.create_live(requested_at=datetime(2026, 8, 13, 6, 0))
```

- [ ] **Step 2: Run the tests and verify the domain module is missing**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_time.py -v`

Expected: FAIL during collection because `sector_pulse.domain.time` does not exist.

- [ ] **Step 3: Implement the immutable time model**

Create an empty `backend/src/sector_pulse/domain/__init__.py`, then create `backend/src/sector_pulse/domain/time.py`:

```python
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class AnalysisMode(StrEnum):
    LIVE = "LIVE"
    AS_OF = "AS_OF"


class CutoffAlreadyLockedError(RuntimeError):
    pass


class InvalidCutoffError(ValueError):
    pass


class AnalysisRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    mode: AnalysisMode
    requested_at: datetime
    requested_cutoff_at: datetime | None = None
    run_cutoff_at: datetime | None = None
    cutoff_locked_at: datetime | None = None

    @field_validator(
        "requested_at", "requested_cutoff_at", "run_cutoff_at", "cutoff_locked_at"
    )
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() != timedelta(0):
            raise ValueError("datetime must use UTC")
        return value

    @model_validator(mode="after")
    def validate_mode_state(self) -> "AnalysisRun":
        if self.mode is AnalysisMode.AS_OF:
            if (
                self.requested_cutoff_at is None
                or self.run_cutoff_at != self.requested_cutoff_at
                or self.cutoff_locked_at is None
            ):
                raise ValueError("AS_OF runs must be locked to requested cutoff")
        elif self.requested_cutoff_at is not None:
            raise ValueError("LIVE runs cannot carry requested_cutoff_at")
        elif (self.run_cutoff_at is None) != (self.cutoff_locked_at is None):
            raise ValueError("LIVE cutoff and lock time must be set together")
        return self

    @classmethod
    def create_live(cls, requested_at: datetime) -> "AnalysisRun":
        return cls(run_id=uuid4(), mode=AnalysisMode.LIVE, requested_at=requested_at)

    @classmethod
    def create_as_of(
        cls, requested_at: datetime, requested_cutoff_at: datetime
    ) -> "AnalysisRun":
        run = cls(
            run_id=uuid4(),
            mode=AnalysisMode.AS_OF,
            requested_at=requested_at,
            requested_cutoff_at=requested_cutoff_at,
            run_cutoff_at=requested_cutoff_at,
            cutoff_locked_at=requested_at,
        )
        assert run.requested_cutoff_at is not None
        if run.requested_cutoff_at > run.requested_at:
            raise InvalidCutoffError("AS_OF cutoff cannot be later than requested_at")
        return run

    def lock_live_cutoff(
        self, observed_at: datetime, locked_at: datetime
    ) -> "AnalysisRun":
        if self.mode is not AnalysisMode.LIVE:
            raise InvalidCutoffError("only LIVE runs lock cutoff after collection")
        if self.run_cutoff_at is not None:
            raise CutoffAlreadyLockedError("run cutoff is immutable once locked")
        if observed_at > locked_at:
            raise InvalidCutoffError("observed_at cannot be later than locked_at")
        return AnalysisRun.model_validate(
            {
                **self.model_dump(),
                "run_cutoff_at": observed_at,
                "cutoff_locked_at": locked_at,
            }
        )
```

- [ ] **Step 4: Run the domain tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_time.py -v`

Expected: four tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/domain backend/tests/unit/domain/test_time.py
git commit -m "feat: define immutable analysis cutoff semantics"
```

---

### Task 3: Define Provider and Market Contracts

**Files:**
- Create: `backend/src/sector_pulse/domain/provider.py`
- Create: `backend/src/sector_pulse/domain/market.py`
- Create: `backend/src/sector_pulse/ports/__init__.py`
- Create: `backend/src/sector_pulse/ports/market_data.py`
- Create: `backend/tests/unit/domain/test_provider.py`
- Create: `backend/tests/unit/domain/test_market.py`

**Interfaces:**
- Consumes: aware UTC datetimes and `AnalysisMode`.
- Produces: `DataStatus`, `ProviderResult[T]`, `ProviderManifest`, `SectorKind`, `SectorSnapshot`, `SectorUniverseSnapshot`, `MarketDataPort.fetch_sector_universe()`.

- [ ] **Step 1: Write result-state tests**

Create `backend/tests/unit/domain/test_provider.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sector_pulse.domain.provider import DataStatus, ProviderError, ProviderResult

NOW = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)


def test_failed_result_requires_error_and_forbids_data() -> None:
    result = ProviderResult[list[str]](
        provider_id="example",
        capability="sector_universe",
        status=DataStatus.FAILED,
        data=None,
        collected_at=NOW,
        error=ProviderError(code="NETWORK", message="timeout", retriable=True),
    )
    assert result.error is not None
    with pytest.raises(ValidationError):
        ProviderResult[list[str]](
            provider_id="example",
            capability="sector_universe",
            status=DataStatus.FAILED,
            data=["not allowed"],
            collected_at=NOW,
            error=ProviderError(code="NETWORK", message="timeout", retriable=True),
        )


def test_empty_is_not_failed() -> None:
    result = ProviderResult[list[str]](
        provider_id="example",
        capability="sector_universe",
        status=DataStatus.EMPTY,
        data=None,
        collected_at=NOW,
    )
    assert result.status is DataStatus.EMPTY
    assert result.error is None
```

Create `backend/tests/unit/domain/test_market.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot

NOW = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)


def test_universe_exposes_sector_count_and_breadth() -> None:
    industry = SectorSnapshot(
        provider_sector_id="BK0001",
        name="行业示例",
        kind=SectorKind.INDUSTRY,
        pct_change=Decimal("1.2"),
        turnover_rate=Decimal("2.5"),
        advancers=10,
        decliners=4,
        leader_name="示例公司",
        leader_pct_change=Decimal("5.0"),
    )
    universe = SectorUniverseSnapshot(
        provider_id="fixture",
        classification_version="fixture-v1",
        source_version="fixture-v1",
        kind=SectorKind.INDUSTRY,
        observed_at=NOW,
        collected_at=NOW,
        sectors=[industry],
    )
    assert universe.sector_count == 1
    assert universe.sectors[0].breadth_ratio > Decimal("0.7")
```

- [ ] **Step 2: Run both files and verify imports fail**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_provider.py backend/tests/unit/domain/test_market.py -v
```

Expected: FAIL during collection because the domain modules do not exist.

- [ ] **Step 3: Implement provider result invariants**

Create `backend/src/sector_pulse/domain/provider.py`:

```python
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

T = TypeVar("T")


class DataStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class AuthorizationStatus(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    VERIFIED_PRODUCTION = "VERIFIED_PRODUCTION"
    BLOCKED = "BLOCKED"


class ProviderError(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    message: str
    retriable: bool


class ProviderResult(BaseModel, Generic[T]):
    model_config = ConfigDict(frozen=True)
    provider_id: str
    capability: str
    status: DataStatus
    data: T | None
    collected_at: datetime
    observed_at: datetime | None = None
    source_version: str | None = None
    raw_artifact_sha256: str | None = None
    error: ProviderError | None = None

    @field_validator("collected_at", "observed_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() != timedelta(0):
            raise ValueError("provider datetimes must use UTC")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> "ProviderResult[T]":
        has_data = self.data is not None
        if self.status in {DataStatus.SUCCESS, DataStatus.PARTIAL, DataStatus.STALE}:
            if not has_data or self.error is not None or self.observed_at is None:
                raise ValueError("data statuses require data, observed_at, and no error")
        elif self.status is DataStatus.FAILED:
            if has_data or self.error is None:
                raise ValueError("FAILED requires error and forbids data")
        elif has_data or self.error is not None:
            raise ValueError("EMPTY/UNAVAILABLE forbid data and error")
        return self


class ProviderManifest(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_id: str
    version: str
    capabilities: frozenset[str]
    authorization_status: AuthorizationStatus
    supports_live: bool
    supports_as_of: bool
    source_attribution: str
    retention_note: str
```

- [ ] **Step 4: Implement market models and Port**

Create `backend/src/sector_pulse/domain/market.py`:

```python
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


class SectorKind(StrEnum):
    INDUSTRY = "INDUSTRY"
    CONCEPT = "CONCEPT"


class SectorSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_sector_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: SectorKind
    pct_change: Decimal
    turnover_rate: Decimal | None = None
    total_market_cap: Decimal | None = None
    advancers: int = Field(ge=0)
    decliners: int = Field(ge=0)
    leader_name: str | None = None
    leader_pct_change: Decimal | None = None

    @field_validator(
        "pct_change", "turnover_rate", "total_market_cap", "leader_pct_change"
    )
    @classmethod
    def require_finite_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("market decimals must be finite")
        return value

    @computed_field
    @property
    def breadth_ratio(self) -> Decimal:
        total = self.advancers + self.decliners
        return Decimal(self.advancers) / Decimal(total) if total else Decimal("0")


class SectorUniverseSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_id: str
    classification_version: str
    source_version: str
    kind: SectorKind
    observed_at: datetime
    collected_at: datetime
    sectors: tuple[SectorSnapshot, ...]

    @field_validator("observed_at", "collected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("market datetimes must use UTC")
        return value

    @model_validator(mode="after")
    def require_single_kind(self) -> "SectorUniverseSnapshot":
        if any(sector.kind is not self.kind for sector in self.sectors):
            raise ValueError("universe cannot mix sector kinds")
        return self

    @computed_field
    @property
    def sector_count(self) -> int:
        return len(self.sectors)
```

Create empty `backend/src/sector_pulse/ports/__init__.py` and create `backend/src/sector_pulse/ports/market_data.py`:

```python
from typing import Protocol

from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import ProviderManifest, ProviderResult
from sector_pulse.domain.time import AnalysisMode


class MarketDataPort(Protocol):
    @property
    def manifest(self) -> ProviderManifest: ...

    async def fetch_sector_universe(
        self, kind: SectorKind, mode: AnalysisMode
    ) -> ProviderResult[SectorUniverseSnapshot]: ...
```

- [ ] **Step 5: Run contract tests and type checks**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_provider.py backend/tests/unit/domain/test_market.py -v
.venv\Scripts\python.exe -m mypy backend/src
```

Expected: three tests PASS; mypy exits `0`.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/sector_pulse/domain backend/src/sector_pulse/ports backend/tests/unit/domain
git commit -m "feat: define provider and market contracts"
```

---

### Task 4: Add Quality Gates and Cutoff Coordination

**Files:**
- Create: `backend/src/sector_pulse/domain/quality.py`
- Create: `backend/tests/unit/domain/test_quality.py`

**Interfaces:**
- Consumes: two `ProviderResult[SectorUniverseSnapshot]` objects and a LIVE `AnalysisRun`.
- Produces: `QualityReport`, `QualityStatus`, `evaluate_universe()`, `lock_cutoff_from_core_market()`.

- [ ] **Step 1: Write coverage, duplicate, and skew tests**

Create `backend/tests/unit/domain/test_quality.py` with helpers and these assertions:

```python
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.quality import (
    QualityStatus,
    QualityThresholds,
    evaluate_universe,
    lock_cutoff_from_core_market,
)
from sector_pulse.domain.time import AnalysisRun

UTC = timezone.utc
NOW = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)


def result(kind: SectorKind, count: int, observed_at: datetime = NOW) -> ProviderResult[SectorUniverseSnapshot]:
    sectors = tuple(
        SectorSnapshot(
            provider_sector_id=f"{kind.value}-{index}",
            name=f"板块-{index}",
            kind=kind,
            pct_change=Decimal("1"),
            advancers=10,
            decliners=5,
        )
        for index in range(count)
    )
    universe = SectorUniverseSnapshot(
        provider_id="fixture",
        classification_version="v1",
        source_version="v1",
        kind=kind,
        observed_at=observed_at,
        collected_at=observed_at,
        sectors=sectors,
    )
    return ProviderResult(
        provider_id="fixture",
        capability="sector_universe",
        status=DataStatus.SUCCESS,
        data=universe,
        observed_at=observed_at,
        collected_at=observed_at,
    )


def test_universe_below_minimum_is_blocked() -> None:
    report = evaluate_universe(
        result(SectorKind.INDUSTRY, 2),
        QualityThresholds(min_industry_count=50, min_concept_count=100),
    )
    assert report.status is QualityStatus.BLOCKED
    assert "SECTOR_COUNT_TOO_LOW" in {issue.code for issue in report.issues}


def test_live_cutoff_uses_latest_observation_within_skew() -> None:
    industry = result(SectorKind.INDUSTRY, 50, NOW)
    concept = result(SectorKind.CONCEPT, 100, NOW + timedelta(seconds=30))
    run = AnalysisRun.create_live(requested_at=NOW - timedelta(seconds=5))

    locked = lock_cutoff_from_core_market(
        run, [industry, concept], locked_at=NOW + timedelta(seconds=31), max_skew_seconds=60
    )
    assert locked.run_cutoff_at == NOW + timedelta(seconds=30)


def test_live_cutoff_rejects_mixed_market_times() -> None:
    industry = result(SectorKind.INDUSTRY, 50, NOW)
    concept = result(SectorKind.CONCEPT, 100, NOW + timedelta(minutes=5))
    run = AnalysisRun.create_live(requested_at=NOW - timedelta(seconds=5))

    try:
        lock_cutoff_from_core_market(
            run, [industry, concept], locked_at=NOW + timedelta(minutes=6), max_skew_seconds=60
        )
    except ValueError as exc:
        assert "observation skew" in str(exc)
    else:
        raise AssertionError("mixed market times must be rejected")
```

- [ ] **Step 2: Run tests and verify the quality module is missing**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_quality.py -v`

Expected: FAIL during collection.

- [ ] **Step 3: Implement quality rules**

Create `backend/src/sector_pulse/domain/quality.py`:

```python
from datetime import datetime
from enum import StrEnum
from typing import Iterable

from pydantic import BaseModel, ConfigDict

from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.time import AnalysisRun


class QualityStatus(StrEnum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


class QualityIssue(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    message: str


class QualityThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)
    min_industry_count: int = 50
    min_concept_count: int = 100


class QualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: QualityStatus
    sector_count: int
    issues: tuple[QualityIssue, ...]


def evaluate_universe(
    result: ProviderResult[SectorUniverseSnapshot], thresholds: QualityThresholds
) -> QualityReport:
    if result.status not in {DataStatus.SUCCESS, DataStatus.PARTIAL, DataStatus.STALE}:
        return QualityReport(
            status=QualityStatus.BLOCKED,
            sector_count=0,
            issues=(QualityIssue(code="PROVIDER_NOT_USABLE", message=result.status.value),),
        )
    assert result.data is not None
    minimum = (
        thresholds.min_industry_count
        if result.data.kind is SectorKind.INDUSTRY
        else thresholds.min_concept_count
    )
    issues: list[QualityIssue] = []
    if result.data.sector_count < minimum:
        issues.append(
            QualityIssue(
                code="SECTOR_COUNT_TOO_LOW",
                message=f"expected at least {minimum}, got {result.data.sector_count}",
            )
        )
    ids = [sector.provider_sector_id for sector in result.data.sectors]
    if len(ids) != len(set(ids)):
        issues.append(QualityIssue(code="DUPLICATE_SECTOR_ID", message="duplicate IDs"))
    status = QualityStatus.BLOCKED if issues else QualityStatus.NORMAL
    if result.status in {DataStatus.PARTIAL, DataStatus.STALE} and not issues:
        status = QualityStatus.DEGRADED
    return QualityReport(status=status, sector_count=result.data.sector_count, issues=tuple(issues))


def lock_cutoff_from_core_market(
    run: AnalysisRun,
    results: Iterable[ProviderResult[SectorUniverseSnapshot]],
    locked_at: datetime,
    max_skew_seconds: int,
) -> AnalysisRun:
    observed = [item.observed_at for item in results if item.observed_at is not None]
    if len(observed) < 2:
        raise ValueError("both industry and concept observations are required")
    earliest, latest = min(observed), max(observed)
    if (latest - earliest).total_seconds() > max_skew_seconds:
        raise ValueError("core market observation skew exceeds limit")
    return run.lock_live_cutoff(observed_at=latest, locked_at=locked_at)
```

- [ ] **Step 4: Run quality tests**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_quality.py -v`

Expected: three tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/domain/quality.py backend/tests/unit/domain/test_quality.py
git commit -m "feat: add market quality and cutoff gates"
```

---

### Task 5: Map AKShare Rows Behind a Provider Adapter

**Files:**
- Create: `backend/src/sector_pulse/infrastructure/__init__.py`
- Create: `backend/src/sector_pulse/infrastructure/providers/__init__.py`
- Create: `backend/src/sector_pulse/infrastructure/providers/akshare/__init__.py`
- Create: `backend/src/sector_pulse/infrastructure/providers/akshare/client.py`
- Create: `backend/src/sector_pulse/infrastructure/providers/akshare/mapper.py`
- Create: `backend/src/sector_pulse/infrastructure/providers/akshare/adapter.py`
- Create: `backend/tests/fixtures/akshare_sector_rows.json`
- Create: `backend/tests/unit/infrastructure/test_akshare_mapper.py`
- Create: `backend/tests/unit/infrastructure/test_akshare_adapter.py`

**Interfaces:**
- Consumes: AKShare industry/concept row dictionaries.
- Produces: `AkShareMarketDataAdapter.fetch_sector_universe()` returning `ProviderResult[SectorUniverseSnapshot]`; AS_OF returns `UNAVAILABLE` without network access.

- [ ] **Step 1: Add a fixed provider-shaped fixture**

Create `backend/tests/fixtures/akshare_sector_rows.json`:

```json
[
  {
    "板块名称": "示例板块甲",
    "板块代码": "BK0001",
    "涨跌幅": 2.5,
    "总市值": 1000000000,
    "换手率": 3.2,
    "上涨家数": 20,
    "下跌家数": 5,
    "领涨股票": "示例公司甲",
    "领涨股票-涨跌幅": 7.1
  },
  {
    "板块名称": "示例板块乙",
    "板块代码": "BK0002",
    "涨跌幅": -1.2,
    "总市值": 2000000000,
    "换手率": 1.1,
    "上涨家数": 3,
    "下跌家数": 17,
    "领涨股票": "示例公司乙",
    "领涨股票-涨跌幅": 2.0
  }
]
```

- [ ] **Step 2: Write mapper and adapter tests**

Create `backend/tests/unit/infrastructure/test_akshare_mapper.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from sector_pulse.domain.market import SectorKind
from sector_pulse.infrastructure.providers.akshare.mapper import map_sector_rows


def test_mapper_converts_chinese_columns_to_domain_model() -> None:
    fixture = Path("backend/tests/fixtures/akshare_sector_rows.json")
    rows = json.loads(fixture.read_text(encoding="utf-8"))
    now = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)

    universe = map_sector_rows(
        rows=rows,
        kind=SectorKind.CONCEPT,
        observed_at=now,
        collected_at=now,
        source_version="fixture",
    )

    assert universe.sector_count == 2
    assert universe.sectors[0].provider_sector_id == "BK0001"
    assert str(universe.sectors[0].pct_change) == "2.5"
```

Create `backend/tests/unit/infrastructure/test_akshare_adapter.py`:

```python
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.time import AnalysisMode
from sector_pulse.infrastructure.providers.akshare.adapter import AkShareMarketDataAdapter


async def test_as_of_is_unavailable_without_calling_client() -> None:
    adapter = AkShareMarketDataAdapter()
    result = await adapter.fetch_sector_universe(SectorKind.INDUSTRY, AnalysisMode.AS_OF)
    assert result.status is DataStatus.UNAVAILABLE
    assert result.data is None
```

Add `asyncio_mode = "auto"` under `[tool.pytest.ini_options]` and add `pytest-asyncio>=1,<2` to the `dev` dependency list in `pyproject.toml`.

- [ ] **Step 3: Run tests and verify provider modules are missing**

Run:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure -v
```

Expected: FAIL during collection.

- [ ] **Step 4: Implement the pure mapper**

Create the three empty `__init__.py` files, then create `backend/src/sector_pulse/infrastructure/providers/akshare/mapper.py`:

```python
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "" or str(value).lower() == "nan":
        return None
    return Decimal(str(value))


def map_sector_rows(
    rows: Sequence[Mapping[str, Any]],
    kind: SectorKind,
    observed_at: datetime,
    collected_at: datetime,
    source_version: str,
) -> SectorUniverseSnapshot:
    sectors = tuple(
        SectorSnapshot(
            provider_sector_id=str(row["板块代码"]),
            name=str(row["板块名称"]),
            kind=kind,
            pct_change=Decimal(str(row["涨跌幅"])),
            turnover_rate=decimal_or_none(row.get("换手率")),
            total_market_cap=decimal_or_none(row.get("总市值")),
            advancers=int(row["上涨家数"]),
            decliners=int(row["下跌家数"]),
            leader_name=str(row["领涨股票"]) if row.get("领涨股票") else None,
            leader_pct_change=decimal_or_none(row.get("领涨股票-涨跌幅")),
        )
        for row in rows
    )
    return SectorUniverseSnapshot(
        provider_id="akshare-eastmoney",
        classification_version=f"eastmoney-{kind.value.lower()}",
        source_version=source_version,
        kind=kind,
        observed_at=observed_at,
        collected_at=collected_at,
        sectors=sectors,
    )
```

- [ ] **Step 5: Implement the client and adapter**

Create `backend/src/sector_pulse/infrastructure/providers/akshare/client.py`:

```python
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any

import akshare as ak

from sector_pulse.domain.market import SectorKind


@dataclass(frozen=True)
class RawSectorBatch:
    rows: list[dict[str, Any]]
    observed_at: datetime
    collected_at: datetime
    source_version: str
    raw_artifact_sha256: str


class PandasAkShareClient:
    async def fetch(self, kind: SectorKind) -> RawSectorBatch:
        function = (
            ak.stock_board_industry_name_em
            if kind is SectorKind.INDUSTRY
            else ak.stock_board_concept_name_em
        )
        started_at = datetime.now(timezone.utc)
        frame = await asyncio.to_thread(function)
        completed_at = datetime.now(timezone.utc)
        rows = frame.to_dict(orient="records")
        digest = hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return RawSectorBatch(
            rows=rows,
            observed_at=started_at,
            collected_at=completed_at,
            source_version=version("akshare"),
            raw_artifact_sha256=digest,
        )
```

Create `backend/src/sector_pulse/infrastructure/providers/akshare/adapter.py`:

```python
from datetime import datetime, timezone

from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderError,
    ProviderManifest,
    ProviderResult,
)
from sector_pulse.domain.time import AnalysisMode
from sector_pulse.infrastructure.providers.akshare.client import PandasAkShareClient
from sector_pulse.infrastructure.providers.akshare.mapper import map_sector_rows


class AkShareMarketDataAdapter:
    def __init__(self, client: PandasAkShareClient | None = None) -> None:
        self._client = client or PandasAkShareClient()

    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="akshare-eastmoney",
            version="1.0.0",
            capabilities=frozenset({"sector_universe.industry", "sector_universe.concept"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="AKShare adapter over Eastmoney public endpoints",
            retention_note="Phase 0 raw responses remain local and are not committed",
        )

    async def fetch_sector_universe(
        self, kind: SectorKind, mode: AnalysisMode
    ) -> ProviderResult[SectorUniverseSnapshot]:
        collected_at = datetime.now(timezone.utc)
        if mode is AnalysisMode.AS_OF:
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability=f"sector_universe.{kind.value.lower()}",
                status=DataStatus.UNAVAILABLE,
                data=None,
                collected_at=collected_at,
            )
        try:
            batch = await self._client.fetch(kind)
            if not batch.rows:
                return ProviderResult(
                    provider_id=self.manifest.provider_id,
                    capability=f"sector_universe.{kind.value.lower()}",
                    status=DataStatus.EMPTY,
                    data=None,
                    collected_at=batch.collected_at,
                )
            universe = map_sector_rows(
                rows=batch.rows,
                kind=kind,
                observed_at=batch.observed_at,
                collected_at=batch.collected_at,
                source_version=batch.source_version,
            )
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability=f"sector_universe.{kind.value.lower()}",
                status=DataStatus.SUCCESS,
                data=universe,
                observed_at=batch.observed_at,
                collected_at=batch.collected_at,
                source_version=batch.source_version,
                raw_artifact_sha256=batch.raw_artifact_sha256,
            )
        except Exception as exc:
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability=f"sector_universe.{kind.value.lower()}",
                status=DataStatus.FAILED,
                data=None,
                collected_at=datetime.now(timezone.utc),
                error=ProviderError(
                    code="AKSHARE_FETCH_FAILED", message=str(exc), retriable=True
                ),
            )
```

- [ ] **Step 6: Run adapter tests and static checks**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/unit/infrastructure -v
.venv\Scripts\python.exe -m ruff check backend
.venv\Scripts\python.exe -m mypy backend/src
```

Expected: two tests PASS; Ruff and mypy exit `0`.

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml backend/src/sector_pulse/infrastructure backend/tests/fixtures backend/tests/unit/infrastructure
git commit -m "feat: add AKShare market data adapter"
```

---

### Task 6: Build a Deterministic Phase 0 Diagnostic Radar

**Files:**
- Create: `backend/src/sector_pulse/domain/radar.py`
- Create: `backend/tests/unit/domain/test_radar.py`

**Interfaces:**
- Consumes: one `SectorUniverseSnapshot`.
- Produces: ranked `DiagnosticRadarRow` values. This is explicitly not the final content-value score from the product spec.

- [ ] **Step 1: Write ranking tests**

Create `backend/tests/unit/domain/test_radar.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.radar import build_diagnostic_radar


def test_radar_ranks_stronger_broader_sector_first() -> None:
    now = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)
    sectors = (
        SectorSnapshot(provider_sector_id="A", name="甲", kind=SectorKind.INDUSTRY, pct_change=Decimal("3"), turnover_rate=Decimal("4"), advancers=20, decliners=2, leader_pct_change=Decimal("8")),
        SectorSnapshot(provider_sector_id="B", name="乙", kind=SectorKind.INDUSTRY, pct_change=Decimal("0.5"), turnover_rate=Decimal("1"), advancers=6, decliners=10, leader_pct_change=Decimal("2")),
    )
    universe = SectorUniverseSnapshot(provider_id="fixture", classification_version="v1", source_version="v1", kind=SectorKind.INDUSTRY, observed_at=now, collected_at=now, sectors=sectors)

    rows = build_diagnostic_radar(universe)

    assert [row.provider_sector_id for row in rows] == ["A", "B"]
    assert rows[0].diagnostic_score > rows[1].diagnostic_score
```

- [ ] **Step 2: Run the test and verify the radar module is missing**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_radar.py -v`

Expected: FAIL during collection.

- [ ] **Step 3: Implement rank-percentile scoring**

Create `backend/src/sector_pulse/domain/radar.py`:

```python
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from sector_pulse.domain.market import SectorUniverseSnapshot


class DiagnosticRadarRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    rank: int
    provider_sector_id: str
    name: str
    diagnostic_score: Decimal
    pct_change: Decimal
    breadth_ratio: Decimal


def percentile_ranks(values: list[Decimal]) -> list[Decimal]:
    if len(values) == 1:
        return [Decimal("1")]
    ordered = sorted(values)
    return [Decimal(ordered.index(value)) / Decimal(len(values) - 1) for value in values]


def build_diagnostic_radar(universe: SectorUniverseSnapshot) -> tuple[DiagnosticRadarRow, ...]:
    sectors = list(universe.sectors)
    movement = percentile_ranks([abs(item.pct_change) for item in sectors])
    turnover = percentile_ranks([item.turnover_rate or Decimal("0") for item in sectors])
    breadth = percentile_ranks([abs(item.breadth_ratio - Decimal("0.5")) for item in sectors])
    leader = percentile_ranks([abs(item.leader_pct_change or Decimal("0")) for item in sectors])
    scored = [
        (
            item,
            movement[index] * Decimal("0.40")
            + turnover[index] * Decimal("0.25")
            + breadth[index] * Decimal("0.20")
            + leader[index] * Decimal("0.15"),
        )
        for index, item in enumerate(sectors)
    ]
    scored.sort(key=lambda pair: (-pair[1], pair[0].provider_sector_id))
    return tuple(
        DiagnosticRadarRow(
            rank=index,
            provider_sector_id=item.provider_sector_id,
            name=item.name,
            diagnostic_score=score,
            pct_change=item.pct_change,
            breadth_ratio=item.breadth_ratio,
        )
        for index, (item, score) in enumerate(scored, start=1)
    )
```

- [ ] **Step 4: Run tests and commit**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_radar.py -v
git add backend/src/sector_pulse/domain/radar.py backend/tests/unit/domain/test_radar.py
git commit -m "feat: add phase zero diagnostic radar"
```

Expected: test PASS and commit succeeds.

---

### Task 7: Orchestrate the Probe and Persist Sanitized Artifacts

**Files:**
- Create: `backend/src/sector_pulse/application/__init__.py`
- Create: `backend/src/sector_pulse/application/phase0_probe.py`
- Create: `backend/src/sector_pulse/reporting/__init__.py`
- Create: `backend/src/sector_pulse/reporting/phase0_report.py`
- Create: `backend/tests/integration/test_phase0_probe.py`

**Interfaces:**
- Consumes: any `MarketDataPort` and an output directory.
- Produces: `Phase0ProbeReport`, `probe.json`, `industry.json`, `concept.json`, `radar.json`; raw supplier frames are not persisted.

- [ ] **Step 1: Write an integration test with a fake Port**

Create `backend/tests/integration/test_phase0_probe.py`:

```python
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sector_pulse.application.phase0_probe import run_phase0_probe
from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderManifest,
    ProviderResult,
)
from sector_pulse.domain.quality import QualityThresholds
from sector_pulse.domain.time import AnalysisMode
from sector_pulse.ports.market_data import MarketDataPort

NOW = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)


class FakeMarketPort:
    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="fixture",
            version="1.0.0",
            capabilities=frozenset({"sector_universe.industry", "sector_universe.concept"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="test fixture",
            retention_note="test only",
        )

    async def fetch_sector_universe(
        self, kind: SectorKind, mode: AnalysisMode
    ) -> ProviderResult[SectorUniverseSnapshot]:
        assert mode is AnalysisMode.LIVE
        count = 50 if kind is SectorKind.INDUSTRY else 100
        observed = NOW if kind is SectorKind.INDUSTRY else NOW + timedelta(seconds=10)
        sectors = tuple(
            SectorSnapshot(
                provider_sector_id=f"{kind.value}-{index}",
                name=f"板块-{index}",
                kind=kind,
                pct_change=Decimal(index) / Decimal("10"),
                turnover_rate=Decimal("2"),
                advancers=10,
                decliners=5,
            )
            for index in range(count)
        )
        universe = SectorUniverseSnapshot(
            provider_id="fixture",
            classification_version="fixture-v1",
            source_version="fixture-v1",
            kind=kind,
            observed_at=observed,
            collected_at=observed,
            sectors=sectors,
        )
        return ProviderResult(
            provider_id="fixture",
            capability=f"sector_universe.{kind.value.lower()}",
            status=DataStatus.SUCCESS,
            data=universe,
            observed_at=observed,
            collected_at=observed,
            source_version="fixture-v1",
        )


@pytest.fixture
def fake_market_port() -> MarketDataPort:
    return FakeMarketPort()


async def test_probe_locks_cutoff_and_writes_artifacts(tmp_path, fake_market_port) -> None:
    report = await run_phase0_probe(
        provider=fake_market_port,
        output_dir=tmp_path,
        requested_at=datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc),
        thresholds=QualityThresholds(min_industry_count=50, min_concept_count=100),
        max_skew_seconds=60,
    )
    assert report.run.run_cutoff_at is not None
    assert report.usable is True
    assert {path.name for path in tmp_path.iterdir()} == {
        "concept.json", "industry.json", "probe.json", "radar.json"
    }
```

- [ ] **Step 2: Run the test and verify the application module is missing**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase0_probe.py -v`

Expected: FAIL during collection.

- [ ] **Step 3: Implement the probe report and JSON writer**

Create empty package `__init__.py` files and implement `backend/src/sector_pulse/application/phase0_probe.py`:

```python
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import AuthorizationStatus, ProviderResult
from sector_pulse.domain.quality import (
    QualityReport,
    QualityStatus,
    QualityThresholds,
    evaluate_universe,
    lock_cutoff_from_core_market,
)
from sector_pulse.domain.radar import build_diagnostic_radar
from sector_pulse.domain.time import AnalysisMode, AnalysisRun
from sector_pulse.ports.market_data import MarketDataPort
from sector_pulse.reporting.phase0_report import write_utf8_atomic


class Phase0ProbeReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    run: AnalysisRun
    provider_id: str
    provider_version: str
    provider_authorization: AuthorizationStatus
    industry_source_version: str | None
    concept_source_version: str | None
    industry_quality: QualityReport
    concept_quality: QualityReport
    usable: bool


async def run_phase0_probe(
    provider: MarketDataPort,
    output_dir: Path,
    requested_at: datetime,
    thresholds: QualityThresholds,
    max_skew_seconds: int,
) -> Phase0ProbeReport:
    run = AnalysisRun.create_live(requested_at=requested_at)
    industry, concept = await asyncio.gather(
        provider.fetch_sector_universe(SectorKind.INDUSTRY, AnalysisMode.LIVE),
        provider.fetch_sector_universe(SectorKind.CONCEPT, AnalysisMode.LIVE),
    )
    industry_quality = evaluate_universe(industry, thresholds)
    concept_quality = evaluate_universe(concept, thresholds)
    usable = all(
        report.status is not QualityStatus.BLOCKED
        for report in (industry_quality, concept_quality)
    )
    report = Phase0ProbeReport(
        run=run,
        provider_id=provider.manifest.provider_id,
        provider_version=provider.manifest.version,
        provider_authorization=provider.manifest.authorization_status,
        industry_source_version=industry.source_version,
        concept_source_version=concept.source_version,
        industry_quality=industry_quality,
        concept_quality=concept_quality,
        usable=usable,
    )
    if not usable:
        write_utf8_atomic(output_dir / "probe.json", report.model_dump_json(indent=2))
        return report

    assert industry.data is not None and concept.data is not None
    locked_run = lock_cutoff_from_core_market(
        run,
        [industry, concept],
        locked_at=datetime.now(timezone.utc),
        max_skew_seconds=max_skew_seconds,
    )
    report = report.model_copy(update={"run": locked_run})
    _write_universe(output_dir / "industry.json", industry)
    _write_universe(output_dir / "concept.json", concept)
    radar = {
        "industry": [
            row.model_dump(mode="json")
            for row in build_diagnostic_radar(industry.data)[:20]
        ],
        "concept": [
            row.model_dump(mode="json")
            for row in build_diagnostic_radar(concept.data)[:20]
        ],
    }
    write_utf8_atomic(
        output_dir / "radar.json",
        json.dumps(radar, ensure_ascii=False, indent=2),
    )
    write_utf8_atomic(output_dir / "probe.json", report.model_dump_json(indent=2))
    return report


def _write_universe(
    path: Path, result: ProviderResult[SectorUniverseSnapshot]
) -> None:
    assert result.data is not None
    write_utf8_atomic(path, result.data.model_dump_json(indent=2))
```

The early blocked path writes only `probe.json`; the successful path writes all four files and writes `probe.json` last.

Implement atomic writes in `backend/src/sector_pulse/reporting/phase0_report.py`:

```python
from pathlib import Path


def write_utf8_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
```

- [ ] **Step 4: Run the integration test and all non-live tests**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/integration/test_phase0_probe.py -v
.venv\Scripts\python.exe -m pytest backend/tests -m "not live" -v
```

Expected: integration test PASS; all non-live tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/sector_pulse/application backend/src/sector_pulse/reporting backend/tests/integration
git commit -m "feat: orchestrate phase zero market probe"
```

---

### Task 8: Add Provider Manifests, CLI, and Explicit Live Consent

**Files:**
- Create: `backend/src/sector_pulse/cli.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/live/test_akshare_live.py`
- Create: `plugins/providers/akshare-eastmoney/manifest.json`
- Create: `plugins/providers/tushare-pro/manifest.json`
- Create: `docs/provider-matrix/phase-0.md`
- Create: `backend/tests/unit/domain/test_manifests.py`

**Interfaces:**
- Consumes: provider Manifest JSON and explicit `.live-data-consent` file.
- Produces: `sector-pulse phase0-probe`; live test is skipped unless both `--run-live` and consent file are present.

- [ ] **Step 1: Write manifest-validation and consent tests**

Create `backend/tests/unit/domain/test_manifests.py`:

```python
import json
from pathlib import Path

from sector_pulse.domain.provider import AuthorizationStatus, ProviderManifest


def test_phase_zero_manifests_are_not_production_authorized() -> None:
    paths = Path("plugins/providers").glob("*/manifest.json")
    manifests = [ProviderManifest.model_validate(json.loads(path.read_text("utf-8"))) for path in paths]
    assert {item.provider_id for item in manifests} == {"akshare-eastmoney", "tushare-pro"}
    assert all(item.authorization_status is not AuthorizationStatus.VERIFIED_PRODUCTION for item in manifests)
```

- [ ] **Step 2: Run the test and verify manifests are absent**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/domain/test_manifests.py -v`

Expected: FAIL because the manifest set is empty.

- [ ] **Step 3: Add exact Phase 0 manifests**

Create `plugins/providers/akshare-eastmoney/manifest.json`:

```json
{
  "provider_id": "akshare-eastmoney",
  "version": "1.0.0",
  "capabilities": ["sector_universe.industry", "sector_universe.concept"],
  "authorization_status": "RESEARCH_ONLY",
  "supports_live": true,
  "supports_as_of": false,
  "source_attribution": "AKShare adapter over Eastmoney public endpoints",
  "retention_note": "Phase 0 local validation only; production rights require separate review"
}
```

Create `plugins/providers/tushare-pro/manifest.json`:

```json
{
  "provider_id": "tushare-pro",
  "version": "0.1.0",
  "capabilities": ["sector_classification", "sector_membership", "sector_history"],
  "authorization_status": "RESEARCH_ONLY",
  "supports_live": false,
  "supports_as_of": false,
  "source_attribution": "Tushare Pro capability research; adapter not implemented in Phase 0",
  "retention_note": "Requires token, endpoint permission, points and terms verification"
}
```

Create `docs/provider-matrix/phase-0.md` with this exact decision table:

```markdown
# Phase 0 Provider Matrix

| Provider | Phase 0 use | LIVE | AS_OF | Authorization | Main risk | Production gate |
|---|---|---:|---:|---|---|---|
| AKShare over Eastmoney | Real industry/concept universe spike | Yes | No | RESEARCH_ONLY | Public endpoint/field drift; `observed_at` is conservatively recorded at request start because the feed exposes no exchange timestamp | Written terms review, fallback source, 20-day stability record |
| Tushare Pro | Capability and schema comparison only | Not implemented | Not implemented; selected historical endpoints require verification | RESEARCH_ONLY | Token/points/endpoint permission and retention terms | Real token test, contract review, adapter contract suite |

AKShare technical availability is not treated as commercial authorization. Phase 0 artifacts stay local and are excluded from Git.

- AKShare documentation: <https://akshare.akfamily.xyz/>
- Tushare Pro documentation: <https://tushare.pro/document/2>
```

- [ ] **Step 4: Implement CLI and live test gate**

Create `backend/src/sector_pulse/cli.py`:

```python
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import typer

from sector_pulse.application.phase0_probe import run_phase0_probe
from sector_pulse.domain.quality import QualityThresholds
from sector_pulse.infrastructure.providers.akshare.adapter import AkShareMarketDataAdapter

app = typer.Typer(no_args_is_help=True)


@app.command("phase0-probe")
def phase0_probe(
    output_dir: Path = typer.Option(Path("data/phase0/latest")),
    consent_file: Path = typer.Option(Path(".live-data-consent")),
) -> None:
    if not consent_file.is_file():
        raise typer.BadParameter(
            "live probe requires .live-data-consent; create it only after reviewing provider terms"
        )
    report = asyncio.run(
        run_phase0_probe(
            provider=AkShareMarketDataAdapter(),
            output_dir=output_dir,
            requested_at=datetime.now(timezone.utc),
            thresholds=QualityThresholds(),
            max_skew_seconds=120,
        )
    )
    typer.echo(report.model_dump_json(indent=2))
```

Create `backend/tests/live/test_akshare_live.py`:

```python
from pathlib import Path

import pytest

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.time import AnalysisMode
from sector_pulse.infrastructure.providers.akshare.adapter import AkShareMarketDataAdapter

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    not Path(".live-data-consent").is_file(),
    reason="provider terms consent file is absent",
)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "minimum"),
    [(SectorKind.INDUSTRY, 50), (SectorKind.CONCEPT, 100)],
)
async def test_akshare_live_sector_coverage(kind: SectorKind, minimum: int) -> None:
    result = await AkShareMarketDataAdapter().fetch_sector_universe(kind, AnalysisMode.LIVE)
    assert result.status is DataStatus.SUCCESS
    assert result.data is not None
    assert result.data.sector_count >= minimum
```

Create `backend/tests/conftest.py`:

```python
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests that access live market providers",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    enabled = config.getoption("--run-live") and Path(".live-data-consent").is_file()
    if enabled:
        return
    marker = pytest.mark.skip(reason="requires --run-live and .live-data-consent")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(marker)
```

- [ ] **Step 5: Run non-live tests and verify live tests skip by default**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -m "not live" -v
.venv\Scripts\python.exe -m pytest backend/tests/live -v
```

Expected: all non-live tests PASS; both live parameter cases SKIP because consent is absent.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/sector_pulse/cli.py backend/tests/conftest.py backend/tests/live backend/tests/unit/domain/test_manifests.py plugins docs/provider-matrix
git commit -m "feat: add governed phase zero live probe"
```

---

### Task 9: Run the Real Trading-Day Probe and Generate the Acceptance Record

**Files:**
- Modify: `backend/src/sector_pulse/reporting/phase0_report.py`
- Create: `backend/tests/unit/reporting/test_phase0_markdown.py`
- Create: `docs/phase0/latest-market-data-validation.md` through the report renderer

**Interfaces:**
- Consumes: `data/phase0/latest/probe.json`, universe JSON and radar JSON from a consented real run.
- Produces: sanitized Markdown with counts, timestamps, Provider versions, quality status and explicit authorization limitations.

- [ ] **Step 1: Write a Markdown renderer test**

Create `backend/tests/unit/reporting/test_phase0_markdown.py`:

```python
from datetime import datetime, timezone

from sector_pulse.application.phase0_probe import Phase0ProbeReport
from sector_pulse.domain.provider import AuthorizationStatus
from sector_pulse.domain.quality import QualityReport, QualityStatus
from sector_pulse.domain.time import AnalysisRun
from sector_pulse.reporting.phase0_report import render_phase0_markdown


def test_markdown_states_counts_cutoff_and_authorization() -> None:
    now = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)
    run = AnalysisRun.create_live(now).lock_live_cutoff(now, now)
    report = Phase0ProbeReport(
        run=run,
        provider_id="fixture",
        provider_version="1.0.0",
        provider_authorization=AuthorizationStatus.RESEARCH_ONLY,
        industry_source_version="fixture-v1",
        concept_source_version="fixture-v1",
        industry_quality=QualityReport(status=QualityStatus.NORMAL, sector_count=50, issues=()),
        concept_quality=QualityReport(status=QualityStatus.NORMAL, sector_count=100, issues=()),
        usable=True,
    )

    markdown = render_phase0_markdown(report)

    assert "# Phase 0 Market Data Validation" in markdown
    assert "run_cutoff_at" in markdown
    assert "RESEARCH_ONLY" in markdown
    assert "INDUSTRY" in markdown
    assert "CONCEPT" in markdown
    assert "not production authorization" in markdown
```

- [ ] **Step 2: Run the test and verify renderer is missing**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/unit/reporting/test_phase0_markdown.py -v`

Expected: FAIL because `render_phase0_markdown` is absent.

- [ ] **Step 3: Implement `render_phase0_markdown()`**

Replace `backend/src/sector_pulse/reporting/phase0_report.py` with:

```python
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sector_pulse.application.phase0_probe import Phase0ProbeReport


def write_utf8_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def render_phase0_markdown(report: "Phase0ProbeReport") -> str:
    cutoff = report.run.run_cutoff_at.isoformat() if report.run.run_cutoff_at else "UNLOCKED"
    return "\n".join(
        [
            "# Phase 0 Market Data Validation",
            "",
            f"- run_id: `{report.run.run_id}`",
            f"- run_cutoff_at: `{cutoff}`",
            f"- provider: `{report.provider_id}`",
            f"- provider adapter version: `{report.provider_version}`",
            f"- industry source version: `{report.industry_source_version}`",
            f"- concept source version: `{report.concept_source_version}`",
            f"- authorization: `{report.provider_authorization.value}`",
            f"- INDUSTRY count/status: `{report.industry_quality.sector_count}` / `{report.industry_quality.status.value}`",
            f"- CONCEPT count/status: `{report.concept_quality.sector_count}` / `{report.concept_quality.status.value}`",
            f"- usable: `{str(report.usable).lower()}`",
            "",
            "This record proves technical availability only. RESEARCH_ONLY is not production authorization.",
            "",
        ]
    )
```

- [ ] **Step 4: Run renderer and full non-live suite**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/unit/reporting/test_phase0_markdown.py -v
.venv\Scripts\python.exe -m pytest backend/tests -m "not live" -v
```

Expected: all tests PASS.

- [ ] **Step 5: Review provider terms before enabling real access**

Read the current official AKShare documentation and the upstream service terms linked from `docs/provider-matrix/phase-0.md`. If this local technical spike is acceptable, create a local consent marker:

```powershell
New-Item -ItemType File -Path .live-data-consent -Force
```

Expected: `.live-data-consent` exists and `git check-ignore .live-data-consent` prints the path. Do not commit it.

- [ ] **Step 6: Run the real provider contract and CLI**

Run during a normal A-share market session or shortly after close:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/live/test_akshare_live.py --run-live -v
.venv\Scripts\sector-pulse.exe phase0-probe --output-dir data/phase0/latest
```

Expected:

- both live cases PASS;
- industry count is at least 50;
- concept count is at least 100;
- `probe.json` records `usable: true`;
- `run_cutoff_at` is non-null and no earlier than both accepted observation times;
- no raw artifact appears in `git status`.

If the command returns `FAILED`, `EMPTY`, insufficient coverage, or observation skew over 120 seconds, do not lower thresholds. Record the exact Provider error and treat Gate 0 as failed.

- [ ] **Step 7: Render and inspect the committed validation summary**

Add these imports and command to `backend/src/sector_pulse/cli.py`:

```python
from sector_pulse.application.phase0_probe import Phase0ProbeReport, run_phase0_probe
from sector_pulse.reporting.phase0_report import render_phase0_markdown, write_utf8_atomic


@app.command("render-report")
def render_report(
    input_path: Path = typer.Option(..., "--input"),
    output_path: Path = typer.Option(..., "--output"),
) -> None:
    report = Phase0ProbeReport.model_validate_json(input_path.read_text(encoding="utf-8"))
    write_utf8_atomic(output_path, render_phase0_markdown(report))
    typer.echo(str(output_path))
```

Replace the earlier `run_phase0_probe` import with the combined import above so the file has no duplicate imports.

Run:

```powershell
.venv\Scripts\sector-pulse.exe render-report --input data/phase0/latest/probe.json --output docs/phase0/latest-market-data-validation.md
Get-Content -Encoding UTF8 docs/phase0/latest-market-data-validation.md
git status --short
```

Expected: the Markdown contains real counts and cutoff but no raw response, secret or complete upstream payload; `data/` and consent marker remain ignored.

- [ ] **Step 8: Run the Phase 0 verification gate**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -m "not live" -v
.venv\Scripts\python.exe -m pytest backend/tests/live/test_akshare_live.py --run-live -v
.venv\Scripts\python.exe -m ruff check backend
.venv\Scripts\python.exe -m mypy backend/src
git diff --check
```

Expected: all tests PASS, live tests do not skip, Ruff/mypy/diff checks exit `0`.

- [ ] **Step 9: Commit the acceptance record**

```powershell
git add backend/src/sector_pulse/cli.py backend/src/sector_pulse/reporting/phase0_report.py backend/tests/unit/reporting docs/phase0/latest-market-data-validation.md
git commit -m "docs: record phase zero market data validation"
```

---

## Phase 0 Exit Checklist

- [ ] Industry and concept live provider tests pass on a real trading day.
- [ ] `run_cutoff_at` is locked only after both core market results pass skew checks.
- [ ] AS_OF against the live AKShare Adapter returns `UNAVAILABLE` without network access.
- [ ] Provider failures do not appear as empty market data.
- [ ] DataFrame and Chinese supplier fields do not escape the Adapter layer.
- [ ] Diagnostic radar is labeled as Phase 0 only and is not presented as investment ranking.
- [ ] AKShare and Tushare manifests remain `RESEARCH_ONLY`.
- [ ] Raw runtime artifacts, consent marker and secrets are absent from Git.
- [ ] Sanitized validation Markdown records real counts, versions, cutoff and limitations.
- [ ] Full non-live tests, explicit live tests, Ruff and mypy pass.
- [ ] User reviews the validation report before Phase 1A planning begins.

## Deferred Until Phase 1A

The following work is intentionally absent from Phase 0: news ingestion, article extraction, event deduplication, SQLite repositories, final content-value scoring, Agent runtime, LLM calls, article generation, FastAPI, React, scheduling and automatic recovery. Their detailed file plans must use the real Phase 0 fields and failure evidence.
