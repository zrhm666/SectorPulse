"""外部 Provider 调用的受控通路：先准入、再发请求、再结算（规格 20.1、20.2，任务 14）。

这是整个资料库里唯一一处**真正花钱、真正花时间、并且收不回来**的动作，因此它周围的规则
全部安排在请求之前：任务还持有有效的 worker 租约、尝试号是当前的、run 还有调用次数、
还有钱、还没到截止时间、单价是已知的、这个 call_id 没有被用在别的事情上。这六条都便宜
可查，而且事后一条都补不回来。

两个不肯猜的地方：

**重试是又一次外部请求。** 因此它要再准入一次、再结算一次、在账本里各占一行——哪个请求
花了钱、花在哪一次，事后数得出来。Provider 把超时的重试留给这一层（见
`infrastructure/research_library/providers/openai_compatible` 里的注释：它知道超时了，
只有上层知道预算还剩多少），但 429 与 5xx 已经在 Provider 内部重试过，这里不再重试一次：
两次重试叠起来，次数会乘。

**重试被拒时抛的是预算错误，不是超时。** 停下来的原因是钱/次数用完了；报一个超时会让
调用方以为再试一次还有希望，而那次请求根本不会发出去。

账本里留下的是一条**结果引用**（`provider.embedding/openai/text-embedding-3-small`），
不是结果。因此同一个 call_id 再来时不能"假装已经做过了"——向量与分数不在手上，答不出
结果却回一句"已经完成"，等于凭空造一个答案（`ProviderCallReplay`）。想复用结果的调用方
要的是一条缓存，缓存键由输入指纹给出，存哪儿由调用方决定。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

from pydantic import Field
from sector_pulse.application.orchestration.tool_budget import (
    SharedToolBudget,
    ToolAdmission,
    ToolBudgetExceeded,
)
from sector_pulse.application.research_library.audit import safe_result_reference
from sector_pulse.application.research_library.observability import MetricsRegistry
from sector_pulse.config.rag_settings import ProviderLimits
from sector_pulse.domain.orchestration.models import Record, ToolCallStatus
from sector_pulse.ports.orchestration import SnapshotRepository
from sector_pulse.ports.research_models import ProviderError, ProviderTimeout

__all__ = [
    "PROVIDER_TOOL_PREFIX",
    "RETRY_BACKOFF_SECONDS",
    "BudgetedProviderCall",
    "ProviderCallRecord",
    "ProviderCallReplay",
]

#: 账本里每类 Provider 各占一个 tool_name（`provider.embedding`、`provider.nli`…）。
#: 规格 12 说每类 Provider 的上限独立配置，共用一个名字会把它们混成一份额度。
PROVIDER_TOOL_PREFIX = "provider."

#: 重试之间的退避。与 Provider 内部重试用的是同一个量级；写成常量而不是配置，
#: 是因为它不影响任何决策，只影响等多久。
RETRY_BACKOFF_SECONDS = 0.5

T = TypeVar("T")


class ProviderCallReplay(RuntimeError):
    """这个 call_id 已经发出过请求，而结果不在手上。

    账本里只有结果引用。答不出结果却说"已经做过了"，就是替 Provider 编了一个答案。
    """


class ProviderCallRecord(Record):
    """一次**外部请求**的完整痕迹（一次调用重试了三次，留下三条）。

    不含输入文本、不含结果内容：`result_reference` 指回结果，而结果本身在 Provider 那边。
    出错的场合只记异常的**类名**——异常消息会被日志与工单系统转抄，而它由 Provider 决定，
    内容不受这里控制。
    """

    call_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    role: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    served_model: str | None = None
    try_number: int = Field(ge=1)
    timeout_seconds: float | None = Field(default=None, gt=0)
    latency_ms: int = Field(ge=0)
    status: ToolCallStatus
    reserved_cny: Decimal | None = None
    actual_cny: Decimal | None = None
    result_reference: str | None = None
    error_kind: str | None = None


class BudgetedProviderCall:
    """把某类 Provider 的调用接到 run 预算、worker 租约与审计上。"""

    def __init__(
        self,
        *,
        repository: SnapshotRepository,
        run_id: UUID,
        task_id: UUID,
        attempt: int,
        kind: str,
        provider_name: str,
        model: str,
        provider: Any,
        limits: ProviderLimits | None,
        metrics: MetricsRegistry | None = None,
        require_lease: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if attempt < 1:
            raise ValueError("attempt must be a positive integer")
        self._budget = SharedToolBudget(repository, run_id)
        self._run_id = run_id
        self._task_id = task_id
        self._attempt = attempt
        self._kind = kind
        self._tool_name = f"{PROVIDER_TOOL_PREFIX}{kind}"
        self._provider_name = provider_name
        self._model = model
        self._provider = provider
        self._timeout_seconds = self._resolve_timeout(provider, limits)
        #: 没有配置上限的 Provider 不重试：没有任何东西说过可以重试几次。
        self._max_tries = (limits.max_retries if limits is not None else 0) + 1
        self._max_calls = limits.max_calls_per_run if limits is not None else None
        self._price = limits.reserve_cny_per_call if limits is not None else None
        self._metrics = metrics
        self._require_lease = require_lease
        self._sleep = sleep
        self._records: list[ProviderCallRecord] = []

    @property
    def records(self) -> tuple[ProviderCallRecord, ...]:
        return tuple(self._records)

    def call(
        self,
        *,
        call_id: str,
        input_fingerprint: str,
        invoke: Callable[[], T],
        served_model: Callable[[T], str] | None = None,
    ) -> T:
        """发一次调用（含重试）。

        `invoke` 由调用方给出，它是唯一真正碰到 Provider 的一行——准入、结算与记录都在它
        两边，因此"拒绝发生在请求之前"是可以被数出来的（测试数的是 Provider 自己的计数器）。
        """
        last_timeout: ProviderTimeout | None = None
        for try_number in range(1, self._max_tries + 1):
            attempt_call_id = call_id if try_number == 1 else f"{call_id}:r{try_number - 1}"
            try:
                admission = self._admit(attempt_call_id, input_fingerprint)
            except ToolBudgetExceeded as denied:
                if last_timeout is None:
                    raise
                # 把"为什么本来要重试"接在后面：只报预算，排查的人看不到前两次已经超时了。
                raise denied from last_timeout
            started = time.monotonic()
            try:
                result = invoke()
            except ProviderTimeout as timeout:
                self._finish(admission, started, try_number, error=timeout)
                last_timeout = timeout
                if try_number < self._max_tries:
                    self._sleep(RETRY_BACKOFF_SECONDS * (2 ** (try_number - 1)))
                continue
            except ProviderError as error:
                self._finish(admission, started, try_number, error=error)
                raise
            except Exception as error:
                # 不是 Provider 说"这次不行"，而是这一行根本没跑通。记 UNKNOWN：请求可能
                # 出去了也可能会没出去，把它记成 FAILED 是在替 Provider 表态。
                self._finish(
                    admission, started, try_number, error=error, status=ToolCallStatus.UNKNOWN
                )
                raise
            try:
                served = served_model(result) if served_model is not None else None
                reference = safe_result_reference(
                    self._tool_name, self._provider_name, served or self._model
                )
            except Exception as error:
                self._finish(
                    admission, started, try_number, error=error, status=ToolCallStatus.UNKNOWN
                )
                raise
            self._finish(
                admission, started, try_number, result_reference=reference, served_model=served
            )
            return result
        # 循环要么返回要么抛出；走到这里说明每一次都超时了。
        assert last_timeout is not None
        raise last_timeout

    # --- 内部 ---

    @staticmethod
    def _resolve_timeout(provider: Any, limits: ProviderLimits | None) -> float | None:
        """这一次调用真正会用的超时。

        Provider 自报的那个优先：它是**会生效**的那个值，而配置只是被交下去的参数。两者
        都给出来且不一致时拒绝装配——审计里写的超时必须是调用真正用的那一个，否则事后
        读到的数字谁也核实不了。取不到也不算错：那时记 `None`（未知），而不是替它填一个。
        """
        declared = getattr(provider, "timeout_seconds", None)
        configured = limits.timeout_seconds if limits is not None else None
        if declared is not None and configured is not None and float(declared) != float(configured):
            raise ValueError(
                f"the provider applies a {float(declared)}s timeout but its configured limit is "
                f"{float(configured)}s; the audit would record a timeout nobody enforces"
            )
        if declared is None and configured is None:
            return None
        return float(declared if declared is not None else configured)  # type: ignore[arg-type]

    def _admit(self, call_id: str, input_fingerprint: str) -> ToolAdmission:
        admission = self._budget.admit(
            task_id=self._task_id,
            attempt=self._attempt,
            call_id=call_id,
            tool_name=self._tool_name,
            input_fingerprint=input_fingerprint,
            reserved_cny=self._price,
            require_lease=self._require_lease,
            max_calls_for_tool=self._max_calls,
        )
        if not admission.execute:
            raise ProviderCallReplay(
                f"call {call_id!r} was already made for {self._tool_name}; the ledger keeps a "
                "result reference, not a result, so it cannot answer this call"
            )
        return admission

    def _finish(
        self,
        admission: ToolAdmission,
        started: float,
        try_number: int,
        *,
        result_reference: str | None = None,
        served_model: str | None = None,
        error: Exception | None = None,
        status: ToolCallStatus | None = None,
    ) -> None:
        """结算 + 记录。

        失败的那一次也按单价结算：请求已经发出去了，把它记成 0 元会让预算一直低估自己
        花掉的钱。
        """
        latency_ms = int((time.monotonic() - started) * 1000)
        settled_status = status
        if settled_status is None:
            settled_status = (
                ToolCallStatus.FAILED if error is not None else ToolCallStatus.SUCCEEDED
            )
        succeeded = (
            None
            if settled_status is ToolCallStatus.UNKNOWN
            else settled_status is ToolCallStatus.SUCCEEDED
        )
        invocation = self._budget.settle(
            admission.invocation.call_id,
            succeeded=succeeded,
            actual_cny=self._price,
            result_reference=result_reference,
        )
        record = ProviderCallRecord(
            call_id=invocation.call_id,
            run_id=str(self._run_id),
            task_id=str(self._task_id),
            attempt=self._attempt,
            role=invocation.role,
            kind=self._kind,
            tool_name=self._tool_name,
            provider=self._provider_name,
            model=self._model,
            served_model=served_model,
            try_number=try_number,
            timeout_seconds=self._timeout_seconds,
            latency_ms=latency_ms,
            status=settled_status,
            reserved_cny=invocation.reserved_cny,
            actual_cny=invocation.actual_cny,
            result_reference=result_reference,
            error_kind=None if error is None else type(error).__name__,
        )
        self._records.append(record)
        if self._metrics is not None:
            self._metrics.record_provider_call(record)
