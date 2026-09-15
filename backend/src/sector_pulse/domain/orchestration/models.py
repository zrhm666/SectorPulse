from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BudgetLimits(Record):
    max_tokens: int = Field(default=120000, gt=0, strict=True)
    max_calls: int = Field(default=80, gt=0, strict=True)
    max_tool_calls: int = Field(default=120, gt=0, strict=True)
    max_cny: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)


class ModelPricing(Record):
    input_cny_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    output_cny_per_million: Decimal = Field(ge=0, allow_inf_nan=False)

    def estimate(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            input_tokens * self.input_cny_per_million + output_tokens * self.output_cny_per_million
        ) / Decimal("1000000")


class ModelCallStatus(StrEnum):
    RESERVED = "reserved"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class BudgetReservation(Record):
    call_id: str = Field(min_length=1)
    task_id: UUID | None = None
    attempt: int | None = Field(default=None, ge=1, strict=True)
    role: str | None = Field(default=None, min_length=1)
    provider: str | None = Field(default=None, min_length=1, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    action_summary: str | None = Field(default=None, min_length=1, max_length=200)
    status: ModelCallStatus | None = None
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    reserved_tokens: int = Field(ge=0, strict=True)
    settled: bool = False
    actual_tokens: int | None = Field(default=None, ge=0, strict=True)
    reserved_cny: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    actual_cny: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_settlement(self) -> Self:
        identity = (self.task_id, self.attempt, self.role)
        if any(value is None for value in identity) and any(
            value is not None for value in identity
        ):
            raise ValueError("model invocation identity must be complete")
        endpoint = (self.provider, self.model)
        if any(value is None for value in endpoint) and any(
            value is not None for value in endpoint
        ):
            raise ValueError("model endpoint identity must be complete")
        if not self.settled and (self.actual_tokens is not None or self.actual_cny is not None):
            raise ValueError("unsettled reservation cannot contain actual usage")
        if not self.settled and self.completed_at is not None:
            raise ValueError("unsettled reservation cannot be completed")
        if self.settled and self.status is ModelCallStatus.RESERVED:
            raise ValueError("settled reservation cannot remain reserved")
        return self


class ToolCallStatus(StrEnum):
    RESERVED = "reserved"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ToolInvocation(Record):
    call_id: str = Field(min_length=1)
    task_id: UUID
    attempt: int = Field(ge=1, strict=True)
    role: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ToolCallStatus = ToolCallStatus.RESERVED
    reserved_cny: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    actual_cny: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    result_reference: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status is ToolCallStatus.RESERVED and (
            self.actual_cny is not None or self.result_reference is not None
        ):
            raise ValueError("reserved tool call cannot contain a result")
        return self


class BudgetLedger(Record):
    reservations: tuple[BudgetReservation, ...] = ()
    tool_invocations: tuple[ToolInvocation, ...] = ()

    @model_validator(mode="after")
    def unique_calls(self) -> Self:
        if len({r.call_id for r in self.reservations}) != len(self.reservations):
            raise ValueError("duplicate call ID")
        if len({r.call_id for r in self.tool_invocations}) != len(self.tool_invocations):
            raise ValueError("duplicate tool call ID")
        return self

    @property
    def charged_tokens(self) -> int:
        return sum(
            r.actual_tokens if r.settled and r.actual_tokens is not None else r.reserved_tokens
            for r in self.reservations
        )

    @property
    def calls(self) -> int:
        return len(self.reservations)

    @property
    def tool_calls(self) -> int:
        return len(self.tool_invocations)

    @property
    def charged_cny(self) -> Decimal:
        """Known charges plus conservative holds; consult has_unknown_cost for certainty."""
        model_cost = sum(
            (
                r.actual_cny
                if r.settled and r.actual_cny is not None
                else r.reserved_cny
                if r.reserved_cny is not None
                else Decimal("0")
                for r in self.reservations
            ),
            Decimal("0"),
        )
        tool_cost = sum(
            (
                invocation.actual_cny
                if invocation.status is not ToolCallStatus.RESERVED
                and invocation.actual_cny is not None
                else invocation.reserved_cny
                if invocation.reserved_cny is not None
                else Decimal("0")
                for invocation in self.tool_invocations
            ),
            Decimal("0"),
        )
        return model_cost + tool_cost

    @property
    def has_unknown_cost(self) -> bool:
        return any(not r.settled or r.actual_cny is None for r in self.reservations) or any(
            invocation.status in {ToolCallStatus.RESERVED, ToolCallStatus.UNKNOWN}
            or invocation.actual_cny is None
            for invocation in self.tool_invocations
        )

    @property
    def has_unpriced_history(self) -> bool:
        return any(
            reservation.reserved_cny is None and reservation.actual_cny is None
            for reservation in self.reservations
        ) or any(
            invocation.reserved_cny is None and invocation.actual_cny is None
            for invocation in self.tool_invocations
        )


class TaskStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    WAITING = "waiting"
    WAITING_USER_SELECTION = "waiting_user_selection"
    WAITING_USER_REVIEW = "waiting_user_review"


class TaskRecord(Record):
    task_id: UUID
    parent_id: UUID | None = None
    role: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    attempt: int = Field(default=1, ge=1)
    status: TaskStatus = TaskStatus.CREATED
    worker_id: str | None = Field(default=None, min_length=1, max_length=200)
    lease_expires_at: AwareDatetime | None = None
    public_error_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    input_artifact_ids: tuple[UUID, ...] = ()
    selection_version: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode="after")
    def validate_ownership(self) -> Self:
        if len(set(self.input_artifact_ids)) != len(self.input_artifact_ids):
            raise ValueError("task input artifact IDs must be unique")
        if (self.worker_id is None) != (self.lease_expires_at is None):
            raise ValueError("worker and lease must be set together")
        if self.status is TaskStatus.RUNNING and self.worker_id is None:
            raise ValueError("running task requires a worker lease")
        if (
            self.status not in {TaskStatus.RUNNING, TaskStatus.INTERRUPTED}
            and self.worker_id is not None
        ):
            raise ValueError("only a running or interrupted task may hold a worker lease")
        if self.public_error_code is not None and self.status is not TaskStatus.FAILED:
            raise ValueError("only a failed task may have a public error code")
        return self


class ArtifactRef(Record):
    artifact_id: UUID
    task_id: UUID
    attempt: int = Field(default=1, ge=1, strict=True)
    kind: str = Field(min_length=1)
    reference: str = Field(min_length=1)


class RunSnapshot(Record):
    run_id: UUID
    requested_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: AwareDatetime | None = None
    execution_engine: Literal["multi_agent"] = "multi_agent"
    provider: Literal["fixture", "live"] = "fixture"
    selection_policy: Literal["manual", "server_default"] = "manual"
    retry_of_run_id: UUID | None = None
    revision: int = Field(default=0, ge=0)
    limits: BudgetLimits = BudgetLimits()
    deadline: AwareDatetime
    ledger: BudgetLedger = BudgetLedger()
    tasks: tuple[TaskRecord, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        tasks = {task.task_id: task for task in self.tasks}
        artifact_ids = {artifact.artifact_id for artifact in self.artifacts}
        if len(tasks) != len(self.tasks):
            raise ValueError("duplicate task ID")
        if self.tasks and sum(t.parent_id is None for t in self.tasks) != 1:
            raise ValueError("run requires exactly one root task")
        for task in self.tasks:
            if task.parent_id is not None:
                parent = tasks.get(task.parent_id)
                if parent is None or parent.parent_id is not None or parent.task_id == task.task_id:
                    raise ValueError("task hierarchy must have exactly two levels")
        if len({a.artifact_id for a in self.artifacts}) != len(self.artifacts):
            raise ValueError("duplicate artifact ID")
        if any(a.task_id not in tasks for a in self.artifacts):
            raise ValueError("artifact task is outside this run")
        if any(
            not set(task.input_artifact_ids).issubset(artifact_ids) for task in self.tasks
        ):
            raise ValueError("task input artifact is outside this run")
        return self
