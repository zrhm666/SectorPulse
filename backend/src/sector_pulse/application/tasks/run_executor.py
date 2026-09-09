import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sector_pulse.domain.runs.task import Checkpoint, TaskStage
from sector_pulse.storage.sqlite.runs.task_repository import SQLiteTaskRepository


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    delay_seconds: int
    terminal_status: str
    error_code: str


class RetryPolicy:
    def __init__(self, max_attempts: int, backoff_seconds: int) -> None:
        if max_attempts < 1 or backoff_seconds < 0:
            raise ValueError("retry policy values must be non-negative and usable")
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds

    def classify(self, error: Exception, *, attempt_no: int) -> RetryDecision:
        if isinstance(error, (TimeoutError, ConnectionError)) and attempt_no < self.max_attempts:
            return RetryDecision(
                retryable=True,
                delay_seconds=self.backoff_seconds * (2 ** (attempt_no - 1)),
                terminal_status="RETRY_WAITING",
                error_code="TASK_PROVIDER_TRANSIENT",
            )
        if (
            getattr(error, "status_code", None) in {429, 500, 502, 503, 504}
            and attempt_no < self.max_attempts
        ):
            return RetryDecision(
                retryable=True,
                delay_seconds=self.backoff_seconds * (2 ** (attempt_no - 1)),
                terminal_status="RETRY_WAITING",
                error_code="TASK_PROVIDER_TRANSIENT",
            )
        return RetryDecision(
            retryable=False,
            delay_seconds=0,
            terminal_status="FAILED",
            error_code=(
                "TASK_VALIDATION_FAILED"
                if isinstance(error, ValueError)
                else "TASK_EXECUTION_FAILED"
            ),
        )


@dataclass(frozen=True)
class StageWork:
    stage: TaskStage
    input_fingerprint: str
    execute: Callable[[], Awaitable[dict[str, Any]]]


class RunExecutor:
    """执行单阶段工作并优先复用完整检查点，供任务状态机调用。"""

    def __init__(
        self,
        repository: SQLiteTaskRepository,
        *,
        implementation_version: str,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._implementation_version = implementation_version
        self._retry_policy = retry_policy or RetryPolicy(max_attempts=3, backoff_seconds=2)

    async def run_stage(self, run_id: UUID, work: StageWork) -> Checkpoint:
        checkpoint = self._repository.get_latest_valid_checkpoint(
            run_id, work.stage, work.input_fingerprint, self._implementation_version
        )
        if checkpoint is not None:
            return checkpoint

        for attempt_no in range(1, self._retry_policy.max_attempts + 1):
            try:
                payload = await work.execute()
                return self._repository.save_checkpoint(
                    run_id,
                    work.stage,
                    work.input_fingerprint,
                    self._implementation_version,
                    payload,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                decision = self._retry_policy.classify(error, attempt_no=attempt_no)
                if not decision.retryable:
                    raise RuntimeError(decision.error_code) from error
                await asyncio.sleep(decision.delay_seconds)
        raise RuntimeError("TASK_EXECUTION_FAILED")
