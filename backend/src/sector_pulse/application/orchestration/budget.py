from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sector_pulse.application.orchestration.tasks import TaskOwnershipError
from sector_pulse.domain.orchestration.models import BudgetReservation, ModelCallStatus, RunSnapshot
from sector_pulse.ports.orchestration import RevisionConflict, SnapshotRepository


class BudgetExceeded(RuntimeError):
    """Admission denied before any external model request."""


class SharedBudget:
    """Persist reservations before sending requests; CAS is shared across processes."""

    def __init__(
        self,
        repository: SnapshotRepository,
        run_id: UUID,
        *,
        task_id: UUID | None = None,
        attempt: int | None = None,
        role: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        action_summary: str | None = None,
    ) -> None:
        identity = (task_id, attempt, role)
        if any(value is None for value in identity) and any(
            value is not None for value in identity
        ):
            raise ValueError("model invocation identity must be complete")
        endpoint = (provider, model)
        if any(value is None for value in endpoint) and any(
            value is not None for value in endpoint
        ):
            raise ValueError("model endpoint identity must be complete")
        self.repository = repository
        self.run_id = run_id
        self.task_id = task_id
        self.attempt = attempt
        self.role = role
        self.provider = provider
        self.model = model
        self.action_summary = action_summary

    @staticmethod
    def _ensure_attempt(
        state: RunSnapshot,
        task_id: UUID | None,
        attempt: int | None,
        role: str | None,
    ) -> None:
        if task_id is None:
            return
        task = next((item for item in state.tasks if item.task_id == task_id), None)
        if task is None:
            raise KeyError("orchestration task not found")
        if task.attempt != attempt:
            raise TaskOwnershipError("stale task attempt")
        if task.role != role:
            raise TaskOwnershipError("task role does not match model invocation")

    def _change(self, transform: Callable[[RunSnapshot], RunSnapshot], event: str) -> None:
        for _ in range(32):
            current = self.repository.load(self.run_id)
            if current is None:
                raise KeyError("orchestration run not found")
            changed = transform(current)
            if changed == current:
                return
            changed = changed.model_copy(update={"revision": current.revision + 1})
            try:
                self.repository.save(changed, current.revision, event)
                return
            except RevisionConflict:
                continue
        raise RevisionConflict("budget contention exceeded retry limit")

    def reserve(
        self,
        call_id: str,
        input_tokens: int,
        output_tokens: int,
        *,
        reserved_cny: Decimal | None = None,
    ) -> None:
        self._validate_money(reserved_cny)
        if not call_id.strip() or any(
            type(n) is not int or n < 0 for n in (input_tokens, output_tokens)
        ):
            raise ValueError("invalid reservation")
        amount = input_tokens + output_tokens
        if output_tokens == 0:
            raise ValueError("output limit must be positive")

        def apply(state: RunSnapshot) -> RunSnapshot:
            self._ensure_attempt(state, self.task_id, self.attempt, self.role)
            if any(r.call_id == call_id for r in state.ledger.reservations):
                raise ValueError("call already reserved; do not replay the external request")
            if state.limits.max_cny is not None:
                if state.ledger.has_unpriced_history:
                    raise BudgetExceeded("unpriced history prevents money admission")
                if reserved_cny is None:
                    raise BudgetExceeded("model price unknown; money admission denied")
                if state.ledger.charged_cny + reserved_cny > state.limits.max_cny:
                    raise BudgetExceeded("run money budget exhausted")
            if (
                datetime.now(UTC) >= state.deadline
                or state.ledger.calls >= state.limits.max_calls
                or state.ledger.charged_tokens + amount > state.limits.max_tokens
            ):
                raise BudgetExceeded("run deadline or budget exhausted")
            reservation = BudgetReservation(
                call_id=call_id,
                task_id=self.task_id,
                attempt=self.attempt,
                role=self.role,
                provider=self.provider,
                model=self.model,
                action_summary=self.action_summary,
                status=ModelCallStatus.RESERVED,
                started_at=datetime.now(UTC),
                reserved_tokens=amount,
                reserved_cny=reserved_cny,
            )
            return state.model_copy(
                update={
                    "ledger": state.ledger.model_copy(
                        update={"reservations": (*state.ledger.reservations, reservation)}
                    )
                }
            )

        self._change(apply, f"budget.reserved:{call_id}")

    @staticmethod
    def _validate_money(amount: Decimal | None) -> None:
        if amount is not None and (
            not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0
        ):
            raise ValueError("invalid money amount")

    def settle(
        self,
        call_id: str,
        actual_tokens: int | None,
        *,
        actual_cny: Decimal | None = None,
        succeeded: bool | None = True,
    ) -> None:
        self._validate_money(actual_cny)
        if actual_tokens is not None and (type(actual_tokens) is not int or actual_tokens < 0):
            raise ValueError("invalid usage")

        def apply(state: RunSnapshot) -> RunSnapshot:
            existing = next((r for r in state.ledger.reservations if r.call_id == call_id), None)
            if existing is None:
                raise KeyError("unknown reservation")
            self._ensure_attempt(state, existing.task_id, existing.attempt, existing.role)
            if existing.settled:
                status = (
                    ModelCallStatus.UNKNOWN
                    if succeeded is None
                    else ModelCallStatus.SUCCEEDED
                    if succeeded
                    else ModelCallStatus.FAILED
                )
                if (
                    existing.actual_tokens != actual_tokens
                    or existing.actual_cny != actual_cny
                    or existing.status is not status
                ):
                    raise ValueError("conflicting settlement")
                return state
            status = (
                ModelCallStatus.UNKNOWN
                if succeeded is None
                else ModelCallStatus.SUCCEEDED
                if succeeded
                else ModelCallStatus.FAILED
            )
            updated = existing.model_copy(
                update={
                    "settled": True,
                    "status": status,
                    "completed_at": datetime.now(UTC),
                    "actual_tokens": actual_tokens,
                    "actual_cny": actual_cny,
                }
            )
            return state.model_copy(
                update={
                    "ledger": state.ledger.model_copy(
                        update={
                            "reservations": tuple(
                            updated if r.call_id == call_id else r
                            for r in state.ledger.reservations
                            )
                        }
                    )
                }
            )

        self._change(apply, f"budget.settled:{call_id}")
