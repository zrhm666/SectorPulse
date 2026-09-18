"""Every external provider call goes through the run's budget before it leaves the process.

An external call is the one action in this system that costs money, takes time, and cannot be
taken back. The rules that have to hold *before* the request goes out — the task still owns a
live lease, the attempt is current, the run has calls, money and time left, the price is known,
the call id was not already used for something else — are all cheap to check and impossible to
check afterwards. So each one gets a test that asserts the provider was never called: the stub
counts its own incoming requests, and every rejection asserts that count did not move.

The same argument decides the two shapes this adapter refuses to guess at. A retry is another
external request, so it is admitted like one, and each try gets its own ledger row — when the
run cannot afford the retry, the budget error propagates instead of the timeout, because
reporting a timeout would tell the caller that trying again might work. And a call id that
replays cannot be answered from the ledger, which keeps a result *reference*, not a result;
answering "already done" without the result would be a lie, so the replay is refused.

Two tests are about the other direction — what must *not* be written down. The ledger's result
reference and the metric labels carry identities only, because a document body in either one
would outlive every retention rule the corpus has.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sector_pulse.application.orchestration.tasks import TaskOwnershipError
from sector_pulse.application.orchestration.tool_budget import (
    SharedToolBudget,
    ToolBudgetExceeded,
)
from sector_pulse.application.research_library.audit import UnsafeResultReference
from sector_pulse.application.research_library.claims import ComparableClaimGroup
from sector_pulse.application.research_library.conflicts import (
    ClaimSource,
    ConflictContext,
    ConflictService,
)
from sector_pulse.application.research_library.observability import (
    MetricName,
    MetricsRegistry,
)
from sector_pulse.application.research_library.provider_calls import (
    BudgetedProviderCall,
    ProviderCallRecord,
    ProviderCallReplay,
)
from sector_pulse.config.rag_settings import ProviderLimits, RagSettings
from sector_pulse.domain.orchestration.models import (
    BudgetLimits,
    RunSnapshot,
    TaskRecord,
    TaskStatus,
    ToolCallStatus,
)
from sector_pulse.domain.research_library.models import (
    DocumentVersionStatus,
    ExtractionMethod,
    SourceSpan,
)
from sector_pulse.domain.research_library.retrieval import (
    ClaimStance,
    ExtractedClaim,
)
from sector_pulse.ports.research_models import (
    EmbeddingBatch,
    NliVerdict,
    ProviderTimeout,
    ProviderUnavailable,
)

EMBEDDING = "provider.embedding"
NLI = "provider.nli"
FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64
FINGERPRINT_D = "d" * 64
VECTOR = (1.0, 0.0, 0.0, 0.0)
TEXT = "储能海外需求在 2026 年上半年同比增长 42%"


@dataclass
class _StubEmbedding:
    """A provider that counts its own incoming requests.

    Every rejection in this file is a claim about *before* the request, and this counter is the
    only witness that can settle it.
    """

    timeout_seconds: float = 30.0
    model_version: str = "stub-embedding-v1"
    outcomes: list[object] = field(default_factory=list)
    requests: int = 0
    seen: list[Sequence[str]] = field(default_factory=list)

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        self.requests += 1
        self.seen.append(texts)
        outcome: object = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, EmbeddingBatch):
            return outcome
        return EmbeddingBatch(
            vectors=(VECTOR,),
            dimension=len(VECTOR),
            provider="stub",
            model_version=self.model_version,
        )


def _limits(**overrides: Any) -> ProviderLimits:
    base: dict[str, Any] = {
        "provider": "stub",
        "model": "stub-embedding-v1",
        "timeout_seconds": 30.0,
        "max_retries": 2,
        "max_calls_per_run": 10,
        "reserve_cny_per_call": Decimal("0.0100"),
    }
    return ProviderLimits(**(base | overrides))


def setup_state(
    tmp_path: Any,
    *,
    max_tools: int = 10,
    max_cny: Decimal | None = Decimal("1.00"),
    lease: timedelta = timedelta(minutes=5),
    claim_lease: bool = True,
):
    """A run whose research task holds a live worker lease."""
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "provider_budget.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    root = TaskRecord(task_id=uuid4(), role="supervisor", scope="run")
    child = TaskRecord(
        task_id=uuid4(),
        parent_id=root.task_id,
        role="research",
        scope="industry:1",
        status=TaskStatus.RUNNING if claim_lease else TaskStatus.CREATED,
        worker_id="worker-1" if claim_lease else None,
        lease_expires_at=datetime.now(UTC) + lease if claim_lease else None,
    )
    snapshot = RunSnapshot(
        run_id=uuid4(),
        limits=BudgetLimits(max_tool_calls=max_tools, max_cny=max_cny),
        deadline=datetime.now(UTC) + timedelta(minutes=30),
        tasks=(root, child),
    )
    repository.save(snapshot, -1, "created")
    return database, repository, snapshot, child


def build_adapter(
    repository: Any,
    snapshot: Any,
    task: Any,
    provider: _StubEmbedding,
    *,
    limits: ProviderLimits | None,
    kind: str = "embedding",
    provider_name: str = "stub",
    model: str = "stub-embedding-v1",
    metrics: MetricsRegistry | None = None,
    attempt: int = 1,
    require_lease: bool = True,
    sleep: Any = None,
) -> BudgetedProviderCall:
    return BudgetedProviderCall(
        repository=repository,
        run_id=snapshot.run_id,
        task_id=task.task_id,
        attempt=attempt,
        kind=kind,
        provider_name=provider_name,
        model=model,
        provider=provider,
        limits=limits,
        metrics=metrics,
        require_lease=require_lease,
        sleep=sleep if sleep is not None else (lambda _seconds: None),
    )


def ledger(repository: Any, snapshot: Any):
    return repository.load(snapshot.run_id).ledger


def invoke(provider: _StubEmbedding):
    return lambda: provider.embed([TEXT])


# --- 一次成功的调用留下了什么 ------------------------------------------------


def test_a_successful_provider_call_lands_in_the_ledger_with_its_identity(tmp_path: Any) -> None:
    _, repository, snapshot, child = setup_state(tmp_path)
    provider = _StubEmbedding()

    result = build_adapter(repository, snapshot, child, provider, limits=_limits()).call(
        call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider)
    )

    assert result.vectors == (VECTOR,)
    assert provider.requests == 1
    invocations = ledger(repository, snapshot).tool_invocations
    assert len(invocations) == 1
    invocation = invocations[0]
    assert (invocation.call_id, invocation.task_id, invocation.attempt) == (
        "call-1",
        child.task_id,
        1,
    )
    assert invocation.role == "research"
    assert invocation.tool_name == EMBEDDING
    assert invocation.input_fingerprint == FINGERPRINT_A
    assert invocation.reserved_cny == Decimal("0.0100")
    assert invocation.actual_cny == Decimal("0.0100")
    assert invocation.status is ToolCallStatus.SUCCEEDED
    assert invocation.result_reference == f"{EMBEDDING}/stub/stub-embedding-v1"
    assert ledger(repository, snapshot).tool_calls == 1


def test_the_record_names_the_run_the_task_and_the_timeout_that_was_in_force(
    tmp_path: Any,
) -> None:
    _, repository, snapshot, child = setup_state(tmp_path)
    provider = _StubEmbedding(timeout_seconds=12.5)
    metrics = MetricsRegistry()
    adapter = build_adapter(
        repository,
        snapshot,
        child,
        provider,
        limits=_limits(timeout_seconds=12.5),
        metrics=metrics,
    )

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    record = adapter.records[0]
    assert isinstance(record, ProviderCallRecord)
    assert (record.run_id, record.task_id, record.attempt, record.role) == (
        str(snapshot.run_id),
        str(child.task_id),
        1,
        "research",
    )
    assert (record.kind, record.tool_name) == ("embedding", EMBEDDING)
    assert record.timeout_seconds == 12.5
    assert record.try_number == 1
    assert record.latency_ms >= 0
    assert record.status is ToolCallStatus.SUCCEEDED
    assert record.error_kind is None
    assert metrics.total(MetricName.PROVIDER_LATENCY_MS, provider="stub", kind="embedding") >= 0
    assert metrics.total(
        MetricName.PROVIDER_COST_CNY, provider="stub", kind="embedding"
    ) == pytest.approx(0.01)


def test_a_provider_that_applies_a_different_timeout_than_its_limit_is_refused(
    tmp_path: Any,
) -> None:
    """审计里写的超时必须就是这一次调用真正用的那个。取不到、或对不上，就拒绝装配——
    填一个配置值进去，事后读到的"最多等了 30 秒"会是一个没人能核实的数字。"""
    _, repository, snapshot, child = setup_state(tmp_path)
    provider = _StubEmbedding(timeout_seconds=90.0)

    with pytest.raises(ValueError, match="timeout"):
        build_adapter(repository, snapshot, child, provider, limits=_limits(timeout_seconds=30.0))

    provider.timeout_seconds = 30.0
    build_adapter(repository, snapshot, child, provider, limits=_limits(timeout_seconds=30.0))


def test_a_provider_result_that_reports_a_body_as_its_version_is_refused(tmp_path: Any) -> None:
    """结果引用只装身份。Provider 自报的版本号会进审计与账本，正文不能从这里溜进去。"""
    _, repository, snapshot, child = setup_state(tmp_path)
    provider = _StubEmbedding()
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits())

    with pytest.raises(UnsafeResultReference):
        adapter.call(
            call_id="call-1",
            input_fingerprint=FINGERPRINT_A,
            invoke=invoke(provider),
            served_model=lambda result: TEXT,
        )

    assert ledger(repository, snapshot).tool_invocations[0].status is ToolCallStatus.UNKNOWN


def test_neither_the_record_nor_the_ledger_keeps_the_text_that_was_sent(tmp_path: Any) -> None:
    _, repository, snapshot, child = setup_state(tmp_path)
    provider = _StubEmbedding()
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits())

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    written = json.dumps(
        {
            "records": [record.model_dump(mode="json") for record in adapter.records],
            "ledger": [
                invocation.model_dump(mode="json")
                for invocation in ledger(repository, snapshot).tool_invocations
            ],
        },
        ensure_ascii=False,
    )
    assert TEXT not in written
    assert TEXT[:12] not in written


def test_the_served_model_is_recorded_when_the_provider_reports_one(tmp_path: Any) -> None:
    """Provider 静默换版本时，账本里留下的是**实际服务**的那一个。"""
    _, repository, snapshot, child = setup_state(tmp_path)
    provider = _StubEmbedding()
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits())

    adapter.call(
        call_id="call-1",
        input_fingerprint=FINGERPRINT_A,
        invoke=invoke(provider),
        served_model=lambda result: result.model_version,
    )

    assert adapter.records[0].served_model == "stub-embedding-v1"
    assert (
        ledger(repository, snapshot).tool_invocations[0].result_reference
        == f"{EMBEDDING}/stub/stub-embedding-v1"
    )


# --- 拒绝发生在请求之前 ------------------------------------------------------


def test_an_expired_worker_lease_is_rejected_before_the_provider_is_called(tmp_path: Any) -> None:
    _, repository, snapshot, child = setup_state(tmp_path, lease=timedelta(seconds=-1))
    provider = _StubEmbedding()

    with pytest.raises(TaskOwnershipError, match="lease"):
        build_adapter(repository, snapshot, child, provider, limits=_limits()).call(
            call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider)
        )

    assert provider.requests == 0
    assert ledger(repository, snapshot).tool_invocations == ()


def test_a_task_without_a_lease_cannot_make_a_provider_call(tmp_path: Any) -> None:
    _, repository, snapshot, child = setup_state(tmp_path, claim_lease=False)
    provider = _StubEmbedding()

    with pytest.raises(TaskOwnershipError):
        build_adapter(repository, snapshot, child, provider, limits=_limits()).call(
            call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider)
        )

    assert provider.requests == 0


def test_a_caller_outside_the_worker_path_may_wave_the_lease_requirement(tmp_path: Any) -> None:
    """要求租约是默认值；能关掉它，是为了让不属于任何 worker 的调用方（一次同步检索）
    也有话可说，而不是因为它们可以借这个口子跳过预算。"""
    _, repository, snapshot, child = setup_state(tmp_path, claim_lease=False)
    provider = _StubEmbedding()

    build_adapter(
        repository, snapshot, child, provider, limits=_limits(), require_lease=False
    ).call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    assert provider.requests == 1


def test_a_stale_attempt_is_rejected_before_the_provider_is_called(tmp_path: Any) -> None:
    _, repository, snapshot, child = setup_state(tmp_path)
    provider = _StubEmbedding()

    with pytest.raises(ValueError, match="stale task attempt"):
        build_adapter(repository, snapshot, child, provider, limits=_limits(), attempt=2).call(
            call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider)
        )

    assert provider.requests == 0


def test_exhausting_the_run_call_budget_rejects_before_the_provider_is_called(
    tmp_path: Any,
) -> None:
    _, repository, snapshot, child = setup_state(tmp_path, max_tools=1, max_cny=None)
    provider = _StubEmbedding()
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits())

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))
    with pytest.raises(ToolBudgetExceeded, match="tool call budget"):
        adapter.call(call_id="call-2", input_fingerprint=FINGERPRINT_B, invoke=invoke(provider))

    assert provider.requests == 1


def test_the_per_provider_call_cap_rejects_before_the_provider_is_called(tmp_path: Any) -> None:
    """规格 12：每类 Provider 的上限是独立配置的。它比 run 的总上限先到，也要先拒。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_tools=10, max_cny=None)
    provider = _StubEmbedding()
    adapter = build_adapter(
        repository, snapshot, child, provider, limits=_limits(max_calls_per_run=1)
    )

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))
    with pytest.raises(ToolBudgetExceeded, match="provider"):
        adapter.call(call_id="call-2", input_fingerprint=FINGERPRINT_B, invoke=invoke(provider))

    assert provider.requests == 1


def test_exhausting_the_run_money_budget_rejects_before_the_provider_is_called(
    tmp_path: Any,
) -> None:
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=Decimal("0.015"))
    provider = _StubEmbedding()
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits())

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))
    with pytest.raises(ToolBudgetExceeded, match="money budget"):
        adapter.call(call_id="call-2", input_fingerprint=FINGERPRINT_B, invoke=invoke(provider))

    assert provider.requests == 1


def test_an_unknown_price_is_rejected_when_the_run_budgets_money(tmp_path: Any) -> None:
    """没有配置单价的 Provider 不能在一个管钱的 run 里发出请求：连预留多少都不知道，
    就无从阻止它把预算花光。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=Decimal("1.00"))
    provider = _StubEmbedding()

    with pytest.raises(ToolBudgetExceeded, match="price unknown"):
        build_adapter(repository, snapshot, child, provider, limits=None).call(
            call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider)
        )

    assert provider.requests == 0
    assert ledger(repository, snapshot).tool_invocations == ()


def test_a_run_without_a_money_budget_admits_an_unpriced_provider(tmp_path: Any) -> None:
    """不管钱的 run 里，没有单价不构成拒绝的理由——拒绝的理由是花超了，不是没定价。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    provider = _StubEmbedding()

    build_adapter(repository, snapshot, child, provider, limits=None).call(
        call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider)
    )

    assert provider.requests == 1
    assert ledger(repository, snapshot).tool_invocations[0].reserved_cny is None


def test_a_run_past_its_deadline_rejects_before_the_provider_is_called(tmp_path: Any) -> None:
    _, repository, snapshot, child = setup_state(tmp_path)
    current = repository.load(snapshot.run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "deadline": datetime.now(UTC) - timedelta(seconds=1),
            }
        ),
        current.revision,
        "expired",
    )
    provider = _StubEmbedding()

    with pytest.raises(ToolBudgetExceeded, match="deadline"):
        build_adapter(repository, snapshot, child, provider, limits=_limits()).call(
            call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider)
        )

    assert provider.requests == 0


def test_a_call_id_reused_for_something_else_is_rejected_before_the_request(tmp_path: Any) -> None:
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    provider = _StubEmbedding()
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits())

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))
    with pytest.raises(ValueError, match="conflicting tool replay"):
        adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_B, invoke=invoke(provider))

    assert provider.requests == 1


def test_a_replayed_call_is_refused_rather_than_answered_without_a_result(tmp_path: Any) -> None:
    """账本里留下的是结果引用，不是向量。答不出结果却说"已经做过了"，等于凭空造一个答案。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    provider = _StubEmbedding()
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits())

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))
    with pytest.raises(ProviderCallReplay):
        adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    assert provider.requests == 1


# --- 重试 --------------------------------------------------------------------


def test_a_timeout_is_retried_as_its_own_admitted_request(tmp_path: Any) -> None:
    """Provider 把超时的重试留给上层（见 `openai_compatible` 里的注释）：上层知道预算还
    剩多少，下层只知道超时了。重试是又一次外部请求，因此要再准入一次、再结算一次。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_tools=5, max_cny=None)
    provider = _StubEmbedding(outcomes=[ProviderTimeout("slow"), ProviderTimeout("slow")])
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits(max_retries=2))

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    assert provider.requests == 3
    invocations = ledger(repository, snapshot).tool_invocations
    assert [invocation.call_id for invocation in invocations] == [
        "call-1",
        "call-1:r1",
        "call-1:r2",
    ]
    assert [invocation.status for invocation in invocations] == [
        ToolCallStatus.FAILED,
        ToolCallStatus.FAILED,
        ToolCallStatus.SUCCEEDED,
    ]
    assert [record.try_number for record in adapter.records] == [1, 2, 3]
    assert [record.error_kind for record in adapter.records] == [
        "ProviderTimeout",
        "ProviderTimeout",
        None,
    ]


def test_the_backoff_between_two_tries_is_waited_out(tmp_path: Any) -> None:
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    provider = _StubEmbedding(outcomes=[ProviderTimeout("slow")])
    slept: list[float] = []
    adapter = build_adapter(
        repository, snapshot, child, provider, limits=_limits(), sleep=slept.append
    )

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    assert len(slept) == 1
    assert slept[0] > 0


def test_timeouts_that_do_not_stop_are_raised_after_the_configured_tries(tmp_path: Any) -> None:
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    provider = _StubEmbedding(
        outcomes=[ProviderTimeout("slow"), ProviderTimeout("slow"), ProviderTimeout("slow")]
    )
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits(max_retries=2))

    with pytest.raises(ProviderTimeout):
        adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    assert provider.requests == 3
    assert all(
        invocation.status is ToolCallStatus.FAILED
        for invocation in ledger(repository, snapshot).tool_invocations
    )


def test_a_retry_the_run_cannot_afford_reports_the_budget_and_not_the_timeout(
    tmp_path: Any,
) -> None:
    """重试被拒说明停下来的原因是预算。报一个超时，调用方会以为再试一次还有希望。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_tools=2, max_cny=None)
    provider = _StubEmbedding(
        outcomes=[ProviderTimeout("slow"), ProviderTimeout("slow"), ProviderTimeout("slow")]
    )
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits(max_retries=5))

    with pytest.raises(ToolBudgetExceeded) as denied:
        adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    assert provider.requests == 2
    assert isinstance(denied.value.__cause__, ProviderTimeout)


def test_a_provider_that_is_unavailable_is_not_retried_here(tmp_path: Any) -> None:
    """429 与 5xx 已经在 Provider 内部重试过了；在这里再重试一次，次数会乘起来。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    provider = _StubEmbedding(outcomes=[ProviderUnavailable("stub is down")])
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits(max_retries=3))

    with pytest.raises(ProviderUnavailable):
        adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    assert provider.requests == 1
    assert ledger(repository, snapshot).tool_invocations[0].status is ToolCallStatus.FAILED
    assert adapter.records[0].error_kind == "ProviderUnavailable"


def test_a_failed_call_is_still_charged_for_the_request_it_sent(tmp_path: Any) -> None:
    """请求已经发出去了。把它记成 0 元，预算就会一直低估它自己花掉的钱。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    provider = _StubEmbedding(outcomes=[ProviderUnavailable("stub is down")])
    metrics = MetricsRegistry()
    adapter = build_adapter(
        repository, snapshot, child, provider, limits=_limits(), metrics=metrics
    )

    with pytest.raises(ProviderUnavailable):
        adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    assert ledger(repository, snapshot).tool_invocations[0].actual_cny == Decimal("0.0100")
    assert (
        metrics.total(MetricName.PROVIDER_ERRORS, kind="ProviderUnavailable", provider="stub") == 1
    )


def test_a_coding_error_leaves_the_call_unknown_rather_than_failed(tmp_path: Any) -> None:
    """不是 Provider 说"这次不行"，而是这一行根本没跑通。两种事实不能记成同一种。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    provider = _StubEmbedding()
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits())

    def broken() -> EmbeddingBatch:
        raise RuntimeError("a bug in the caller")

    with pytest.raises(RuntimeError):
        adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=broken)

    assert ledger(repository, snapshot).tool_invocations[0].status is ToolCallStatus.UNKNOWN
    assert ledger(repository, snapshot).has_unpriced_history is False
    assert adapter.records[0].error_kind == "RuntimeError"


def test_a_call_that_never_happened_is_not_recorded_as_a_provider_error(tmp_path: Any) -> None:
    _, repository, snapshot, child = setup_state(tmp_path, max_tools=1, max_cny=None)
    provider = _StubEmbedding()
    metrics = MetricsRegistry()
    adapter = build_adapter(
        repository, snapshot, child, provider, limits=_limits(), metrics=metrics
    )

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))
    with pytest.raises(ToolBudgetExceeded):
        adapter.call(call_id="call-2", input_fingerprint=FINGERPRINT_B, invoke=invoke(provider))

    assert metrics.total(MetricName.PROVIDER_ERRORS) == 0
    assert len(adapter.records) == 1


def test_each_external_request_is_settled_exactly_once(tmp_path: Any, monkeypatch: Any) -> None:
    """结算把它自己的重试算进去，就等于替 Provider 又发了一次请求。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    provider = _StubEmbedding()
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits())
    original = SharedToolBudget.settle
    settled: list[str] = []

    def counted(self: Any, call_id: str, **kwargs: Any):
        settled.append(call_id)
        return original(self, call_id, **kwargs)

    monkeypatch.setattr(SharedToolBudget, "settle", counted)

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    assert settled == ["call-1"]
    assert provider.requests == 1


def test_the_record_carries_the_money_that_was_reserved_and_what_it_cost(tmp_path: Any) -> None:
    _, repository, snapshot, child = setup_state(tmp_path)
    provider = _StubEmbedding()
    adapter = build_adapter(repository, snapshot, child, provider, limits=_limits())

    adapter.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))

    record = adapter.records[0]
    assert record.reserved_cny == Decimal("0.0100")
    assert record.actual_cny == Decimal("0.0100")
    assert UUID(record.run_id) == snapshot.run_id


# --- 与冲突裁决合起来看 ------------------------------------------------------


def test_a_denied_nli_call_is_not_laundered_into_a_completed_check(tmp_path: Any) -> None:
    """Task 13 把"检查没做成"（CHECK_FAILED）与"检查做完了"分得很开。一次买不起的调用
    如果被吞成 CHECK_FAILED，审计里会留下一条"这次没检查出来"，而真相是"这次没发出去"。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_tools=1, max_cny=None)
    provider = _StubEmbedding()
    adapter = build_adapter(
        repository, snapshot, child, provider, limits=_limits(), kind="nli", model="stub-nli-v1"
    )
    adapter.call(call_id="warm-up", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))
    nli = _BudgetedNli(adapter)
    service = ConflictService(provider=nli, settings=RagSettings())

    with pytest.raises(ToolBudgetExceeded):
        service.check((_group(),), _context())

    assert nli.reached == 0


class _BudgetedNli:
    """An NLI provider whose only call has to go through an already-exhausted run budget.

    The upstream verdict is never computed: the adapter is supposed to refuse before `invoke`
    runs, so reaching it is a bug and is reported as one instead of looking like a failed check.
    """

    def __init__(self, adapter: BudgetedProviderCall) -> None:
        self._adapter = adapter
        self.reached = 0

    def classify(self, *, premise: str, hypothesis: str) -> NliVerdict:
        def invoke() -> NliVerdict:
            self.reached += 1
            raise AssertionError("the call must be denied before it reaches the provider")

        return self._adapter.call(call_id="nli-1", input_fingerprint=FINGERPRINT_D, invoke=invoke)


def test_two_kinds_of_provider_do_not_share_one_call_budget(tmp_path: Any) -> None:
    """规格 12：Embedding 与 NLI 的上限各自独立。记在同一个 tool_name 上，一类的高并发
    会把另一类的额度吃掉。"""
    _, repository, snapshot, child = setup_state(tmp_path, max_cny=None)
    provider = _StubEmbedding()
    embedding = build_adapter(
        repository, snapshot, child, provider, limits=_limits(max_calls_per_run=1)
    )
    nli = build_adapter(
        repository,
        snapshot,
        child,
        provider,
        limits=_limits(max_calls_per_run=1),
        kind="nli",
        model="stub-nli-v1",
    )

    embedding.call(call_id="call-1", input_fingerprint=FINGERPRINT_A, invoke=invoke(provider))
    nli.call(call_id="call-2", input_fingerprint=FINGERPRINT_B, invoke=invoke(provider))

    assert provider.requests == 2
    assert {
        invocation.tool_name for invocation in ledger(repository, snapshot).tool_invocations
    } == {
        EMBEDDING,
        NLI,
    }
    with pytest.raises(ToolBudgetExceeded):
        embedding.call(call_id="call-3", input_fingerprint=FINGERPRINT_B, invoke=invoke(provider))
    assert provider.requests == 2


def _claim(claim_id: str, *, chunk_id: str, stance: ClaimStance = ClaimStance.SUPPORTING):
    return ExtractedClaim(
        claim_id=claim_id,
        statement=f"{claim_id} 的说法",
        subject="储能海外需求",
        predicate="同比增速",
        object="42%",
        source_chunk_id=chunk_id,
        source_span=SourceSpan(start=0, end=4),
        extraction_confidence=0.9,
        stance=stance,
    )


def _group() -> ComparableClaimGroup:
    return ComparableClaimGroup(
        subject_key="储能海外需求",
        predicate_key="同比增速",
        claims=(
            _claim("cl_a", chunk_id="c_1"),
            _claim("cl_b", chunk_id="c_2", stance=ClaimStance.OPPOSING),
        ),
    )


def _context() -> ConflictContext:
    return ConflictContext(
        sources={
            "c_1": ClaimSource(
                document_id="doc_0001",
                document_version_id="ver_0001",
                version_number=1,
                status=DocumentVersionStatus.ACTIVE,
                source_weight=Decimal("0.5"),
                content_origin=ExtractionMethod.NATIVE,
            ),
            "c_2": ClaimSource(
                document_id="doc_0002",
                document_version_id="ver_0002",
                version_number=1,
                status=DocumentVersionStatus.ACTIVE,
                source_weight=Decimal("0.5"),
                content_origin=ExtractionMethod.NATIVE,
            ),
        }
    )
