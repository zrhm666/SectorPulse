"""Persistent admission and settlement for run-scoped business tool calls."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sector_pulse.domain.orchestration.models import (
    RunSnapshot,
    TaskRecord,
    ToolCallStatus,
    ToolInvocation,
)
from sector_pulse.ports.orchestration import RevisionConflict, SnapshotRepository


class ToolBudgetExceeded(RuntimeError):
    """A tool call was denied before its side effect started."""


@dataclass(frozen=True)
class ToolAdmission:
    invocation: ToolInvocation
    execute: bool


class SharedToolBudget:
    def __init__(self, repository: SnapshotRepository, run_id: UUID) -> None:
        self.repository = repository
        self.run_id = run_id

    @staticmethod
    def _validate_money(amount: Decimal | None) -> None:
        if amount is not None and (
            not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0
        ):
            raise ValueError("invalid money amount")

    @staticmethod
    def _task(state: RunSnapshot, task_id: UUID, attempt: int) -> TaskRecord:
        task = next((item for item in state.tasks if item.task_id == task_id), None)
        if task is None:
            raise KeyError("orchestration task not found")
        if task.attempt != attempt:
            raise ValueError("stale task attempt")
        return task

    def admit(
        self,
        *,
        task_id: UUID,
        attempt: int,
        call_id: str,
        tool_name: str,
        input_fingerprint: str,
        reserved_cny: Decimal | None = None,
    ) -> ToolAdmission:
        self._validate_money(reserved_cny)
        for _ in range(32):
            current = self.repository.load(self.run_id)
            if current is None:
                raise KeyError("orchestration run not found")
            task = self._task(current, task_id, attempt)
            existing = next(
                (item for item in current.ledger.tool_invocations if item.call_id == call_id), None
            )
            if existing is not None:
                identity = (
                    existing.task_id,
                    existing.attempt,
                    existing.role,
                    existing.tool_name,
                    existing.input_fingerprint,
                    existing.reserved_cny,
                )
                requested = (
                    task_id,
                    attempt,
                    task.role,
                    tool_name,
                    input_fingerprint,
                    reserved_cny,
                )
                if identity != requested:
                    raise ValueError("conflicting tool replay")
                return ToolAdmission(existing, execute=False)
            if datetime.now(UTC) >= current.deadline:
                raise ToolBudgetExceeded("run deadline exceeded")
            if current.ledger.tool_calls >= current.limits.max_tool_calls:
                raise ToolBudgetExceeded("run tool call budget exhausted")
            if current.limits.max_cny is not None:
                if current.ledger.has_unpriced_history:
                    raise ToolBudgetExceeded("unpriced history prevents money admission")
                if reserved_cny is None:
                    raise ToolBudgetExceeded("tool price unknown; money admission denied")
                if current.ledger.charged_cny + reserved_cny > current.limits.max_cny:
                    raise ToolBudgetExceeded("run money budget exhausted")
            invocation = ToolInvocation(
                call_id=call_id,
                task_id=task_id,
                attempt=attempt,
                role=task.role,
                tool_name=tool_name,
                input_fingerprint=input_fingerprint,
                reserved_cny=reserved_cny,
            )
            changed = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "ledger": current.ledger.model_copy(
                        update={
                            "tool_invocations": (
                                *current.ledger.tool_invocations,
                                invocation,
                            )
                        }
                    ),
                }
            )
            try:
                self.repository.save(
                    changed, current.revision, f"tool.reserved:{tool_name}:{call_id}"
                )
                return ToolAdmission(invocation, execute=True)
            except RevisionConflict:
                continue
        raise RevisionConflict("tool admission contention exceeded retry limit")

    def settle(
        self,
        call_id: str,
        *,
        succeeded: bool | None,
        actual_cny: Decimal | None,
        result_reference: str | None = None,
    ) -> ToolInvocation:
        self._validate_money(actual_cny)
        for _ in range(32):
            current = self.repository.load(self.run_id)
            if current is None:
                raise KeyError("orchestration run not found")
            existing = next(
                (item for item in current.ledger.tool_invocations if item.call_id == call_id), None
            )
            if existing is None:
                raise KeyError("unknown tool call")
            self._task(current, existing.task_id, existing.attempt)
            status = (
                ToolCallStatus.UNKNOWN
                if succeeded is None
                else ToolCallStatus.SUCCEEDED
                if succeeded
                else ToolCallStatus.FAILED
            )
            if existing.status is not ToolCallStatus.RESERVED:
                if (
                    existing.status is not status
                    or existing.actual_cny != actual_cny
                    or existing.result_reference != result_reference
                ):
                    raise ValueError("conflicting tool settlement")
                return existing
            updated = existing.model_copy(
                update={
                    "status": status,
                    "actual_cny": actual_cny,
                    "result_reference": result_reference,
                }
            )
            invocations = tuple(
                updated if item.call_id == call_id else item
                for item in current.ledger.tool_invocations
            )
            changed = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "ledger": current.ledger.model_copy(update={"tool_invocations": invocations}),
                }
            )
            try:
                self.repository.save(
                    changed, current.revision, f"tool.settled:{existing.tool_name}:{call_id}"
                )
                return updated
            except RevisionConflict:
                continue
        raise RevisionConflict("tool settlement contention exceeded retry limit")
