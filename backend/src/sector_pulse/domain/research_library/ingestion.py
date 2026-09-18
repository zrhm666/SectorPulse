"""摄取状态机与租约规则。

规格 7.2 与 19：只有文档化的前进路径加上重试/取消边；状态推进必须由持有有效租约
的当前 attempt 发起；过期租约接管必须产生新的 attempt，旧 attempt 的迟到结果因此
在领域层就被拒绝，而不是依赖调用方自觉。
"""

from datetime import datetime, timedelta

from pydantic import AwareDatetime, TypeAdapter

from sector_pulse.domain.research_library.models import (
    FAILURE_INGESTION_STATUSES,
    IngestionJob,
    IngestionStatus,
)

__all__ = [
    "INGESTION_TRANSITIONS",
    "RESUMABLE_INGESTION_STAGES",
    "IngestionLeaseLost",
    "IngestionStatus",
    "InvalidIngestionTransition",
    "acquire_ingestion_lease",
    "is_terminal",
    "requeue_ingestion",
    "transition_ingestion",
]

_AWARE_DATETIME = TypeAdapter(AwareDatetime)


class InvalidIngestionTransition(ValueError):
    """状态机不允许这次迁移。"""


class IngestionLeaseLost(ValueError):
    """调用方不再持有该任务的当前 attempt 或有效租约。"""


RESUMABLE_INGESTION_STAGES: tuple[IngestionStatus, ...] = (
    IngestionStatus.VALIDATING,
    IngestionStatus.PARSING,
    IngestionStatus.NORMALIZING,
    IngestionStatus.CHUNKING,
    IngestionStatus.EMBEDDING,
    IngestionStatus.INDEXING,
    IngestionStatus.VERIFYING,
)


def _stage_edges(next_status: IngestionStatus) -> frozenset[IngestionStatus]:
    return frozenset(
        {
            next_status,
            IngestionStatus.RETRYABLE_FAILED,
            IngestionStatus.PERMANENT_FAILED,
            IngestionStatus.CANCELLED,
        }
    )


INGESTION_TRANSITIONS: dict[IngestionStatus, frozenset[IngestionStatus]] = {
    IngestionStatus.RECEIVED: frozenset(
        {IngestionStatus.VALIDATING, IngestionStatus.CANCELLED}
    ),
    IngestionStatus.VALIDATING: _stage_edges(IngestionStatus.PARSING),
    IngestionStatus.PARSING: _stage_edges(IngestionStatus.NORMALIZING),
    IngestionStatus.NORMALIZING: _stage_edges(IngestionStatus.CHUNKING),
    IngestionStatus.CHUNKING: _stage_edges(IngestionStatus.EMBEDDING),
    IngestionStatus.EMBEDDING: _stage_edges(IngestionStatus.INDEXING),
    IngestionStatus.INDEXING: _stage_edges(IngestionStatus.VERIFYING),
    IngestionStatus.VERIFYING: _stage_edges(IngestionStatus.PUBLISHED),
    IngestionStatus.RETRYABLE_FAILED: frozenset(
        {
            *RESUMABLE_INGESTION_STAGES,
            IngestionStatus.PERMANENT_FAILED,
            IngestionStatus.CANCELLED,
        }
    ),
    IngestionStatus.PERMANENT_FAILED: frozenset(),
    IngestionStatus.CANCELLED: frozenset(),
    IngestionStatus.PUBLISHED: frozenset(),
}

RELEASING_INGESTION_STATUSES = (
    IngestionStatus.PUBLISHED,
    IngestionStatus.PERMANENT_FAILED,
    IngestionStatus.CANCELLED,
)


def is_terminal(status: IngestionStatus) -> bool:
    return not INGESTION_TRANSITIONS[status]


def _aware(moment: datetime) -> datetime:
    """拒绝 naive 时间。比较带时区与不带时区的时间会静默给出错误答案。"""
    return _AWARE_DATETIME.validate_python(moment)


def _require_lease(job: IngestionJob, now: datetime, worker_id: str, attempt: int) -> None:
    if job.attempt_id != attempt:
        raise IngestionLeaseLost(
            f"attempt {attempt} is not the current attempt {job.attempt_id} of job {job.job_id}"
        )
    if job.worker_id != worker_id:
        raise IngestionLeaseLost(
            f"worker {worker_id!r} does not own job {job.job_id}; "
            f"the lease belongs to {job.worker_id!r}"
        )
    if job.lease_expires_at is None or job.lease_expires_at <= now:
        raise IngestionLeaseLost(f"the lease of job {job.job_id} has expired")


def acquire_ingestion_lease(
    job: IngestionJob,
    *,
    now: datetime,
    worker_id: str,
    lease_seconds: int,
) -> IngestionJob:
    """取得或接管租约；接管只有在旧租约过期时才产生新的 attempt。"""
    moment = _aware(now)
    if is_terminal(job.status):
        raise InvalidIngestionTransition(f"a {job.status} job cannot be leased again")
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")

    held_until = job.lease_expires_at
    lease_is_live = held_until is not None and held_until > moment
    if lease_is_live and job.worker_id != worker_id:
        assert held_until is not None  # implied by lease_is_live
        raise IngestionLeaseLost(
            f"job {job.job_id} still holds a lease until {held_until.isoformat()}"
        )
    attempt = job.attempt_id if lease_is_live else job.attempt_id + 1
    if attempt > job.max_attempts:
        raise IngestionLeaseLost(
            f"job {job.job_id} exhausted its {job.max_attempts} attempts"
        )
    return job.model_copy(
        update={
            "attempt_id": attempt,
            "worker_id": worker_id,
            "lease_expires_at": moment + timedelta(seconds=lease_seconds),
            "updated_at": moment,
        }
    )


def requeue_ingestion(job: IngestionJob, *, now: datetime) -> IngestionJob:
    """把一个已经失败的任务重新放回队列开头。**这不是一次状态迁移。**

    状态机描述的是"一次尝试能往前走到哪里"，而这里做的是"让这一行重新开始一次生命"：状态
    回到 `RECEIVED`、attempt 归零、租约清空、失败原因清掉。把它写成一次迁移会立刻自相矛盾，
    因为 `PERMANENT_FAILED` 没有任何出边（`INGESTION_TRANSITIONS`），而"修好对象之后重跑"
    恰恰需要它有一条出边。

    因此它有两条与迁移不同的性质，都必须显式成立：

    - **只能由用户发起**。规格 19 的重试预算约束的是 worker 的自动重试；把终态任务重新排队
      是人的决定，因此调用方必须写下审计记录，并且绝不在失败处理路径上顺手调用它。
    - **attempt 归零而不是 +1**。它表达的是"之前的尝试都不算数了"，而不是"再给一次机会"。
      这不是放宽并发保护，而是加强它：上一个 attempt 的迟到结果带着旧 attempt 号，与归零后
      的当前 attempt 对不上，因此照旧写不进任何东西。
    """
    moment = _aware(now)
    if job.status not in FAILURE_INGESTION_STATUSES:
        raise InvalidIngestionTransition(
            f"job {job.job_id} is {job.status}; only a failed job can be requeued"
        )
    return job.model_copy(
        update={
            "status": IngestionStatus.RECEIVED,
            "attempt_id": 0,
            "worker_id": None,
            "lease_expires_at": None,
            "failure_reason": None,
            "updated_at": moment,
        }
    )


def transition_ingestion(
    job: IngestionJob,
    target: IngestionStatus,
    now: datetime,
    worker_id: str,
    attempt: int,
    *,
    reason: str | None = None,
) -> IngestionJob:
    """按状态机推进任务，返回新的不可变任务副本。

    取消由用户发起，不要求持有租约；其余迁移都必须来自当前 attempt 的持租 worker。
    失败迁移必须说明原因，否则后续无法区分可重试与永久失败。

    `failure_reason` 是"这一次失败的原因"，不是一段历史：离开失败状态时它必须被清掉。
    不清会有两个后果——`IngestionJob` 自己拒绝这种组合，而 `model_copy` 不跑校验器，于是
    不合法的任务被造出来、一路走到数据库才被 CHECK 顶回去；那条 CHECK 违规又会被翻译成
    "写入输给了并发者"，让一次本可以成功的重试安静地停在原地。
    """
    moment = _aware(now)
    if target not in INGESTION_TRANSITIONS[job.status]:
        raise InvalidIngestionTransition(
            f"job {job.job_id} cannot move from {job.status} to {target}"
        )
    if target is not IngestionStatus.CANCELLED:
        _require_lease(job, moment, worker_id, attempt)
    if target in FAILURE_INGESTION_STATUSES and not reason:
        raise ValueError(f"a transition to {target} must state a failure reason")

    update: dict[str, object] = {"status": target, "updated_at": moment}
    update["failure_reason"] = reason if target in FAILURE_INGESTION_STATUSES else None
    if target in RELEASING_INGESTION_STATUSES:
        update["worker_id"] = None
        update["lease_expires_at"] = None
    return job.model_copy(update=update)
