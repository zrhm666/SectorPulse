"""Unified, read-only usage projection for legacy and multi-agent runs."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sector_pulse.domain.llm import AgentInvocation
from sector_pulse.domain.orchestration.models import ToolCallStatus
from sector_pulse.ports.orchestration import SnapshotRepository


class LegacyInvocationReader(Protocol):
    def list_for_run(self, run_id: UUID) -> list[AgentInvocation]: ...


@dataclass(frozen=True)
class InvocationUsage:
    call_id: str
    source: str
    status: str
    provider: str | None
    model: str | None
    task_id: UUID | None
    attempt: int | None
    role: str | None
    tool_name: str | None
    total_tokens: int | None
    cost_cny: Decimal | None
    usage_known: bool
    cost_known: bool
    action_summary: str | None = None
    result_reference: str | None = None


@dataclass(frozen=True)
class UsageSummary:
    call_count: int
    model_call_count: int
    tool_call_count: int
    known_tokens: int
    known_cost_cny: Decimal
    has_unknown_usage: bool
    has_unknown_cost: bool


class InvocationUsageProjection:
    """Associate old invocation rows with the new authoritative run ledger."""

    def __init__(
        self,
        legacy: LegacyInvocationReader,
        orchestration: SnapshotRepository,
    ) -> None:
        self.legacy = legacy
        self.orchestration = orchestration

    def list_for_run(self, run_id: UUID) -> tuple[InvocationUsage, ...]:
        rows: dict[str, InvocationUsage] = {}
        for legacy_invocation in self.legacy.list_for_run(run_id):
            call_id = str(legacy_invocation.invocation_id)
            rows[call_id] = InvocationUsage(
                call_id=call_id,
                source="legacy_model",
                status=legacy_invocation.status.value.lower(),
                provider=legacy_invocation.provider_id,
                model=legacy_invocation.model,
                task_id=None,
                attempt=None,
                role=None,
                tool_name=None,
                total_tokens=legacy_invocation.usage.total_tokens,
                cost_cny=legacy_invocation.estimated_cost_cny.amount,
                usage_known=True,
                cost_known=True,
                action_summary=legacy_invocation.stage,
            )
        state = self.orchestration.load(run_id)
        if state is None:
            return tuple(rows.values())
        for reservation in state.ledger.reservations:
            usage_known = reservation.settled and reservation.actual_tokens is not None
            cost_known = reservation.settled and reservation.actual_cny is not None
            rows[reservation.call_id] = InvocationUsage(
                call_id=reservation.call_id,
                source="multi_agent_model",
                status=(reservation.status.value if reservation.status is not None else "reserved"),
                provider=reservation.provider,
                model=reservation.model,
                task_id=reservation.task_id,
                attempt=reservation.attempt,
                role=reservation.role,
                tool_name=None,
                total_tokens=reservation.actual_tokens if usage_known else None,
                cost_cny=reservation.actual_cny if cost_known else None,
                usage_known=usage_known,
                cost_known=cost_known,
                action_summary=reservation.action_summary,
            )
        for tool_invocation in state.ledger.tool_invocations:
            cost_known = (
                tool_invocation.status is not ToolCallStatus.RESERVED
                and tool_invocation.actual_cny is not None
            )
            rows[tool_invocation.call_id] = InvocationUsage(
                call_id=tool_invocation.call_id,
                source="multi_agent_tool",
                status=tool_invocation.status.value,
                provider=None,
                model=None,
                task_id=tool_invocation.task_id,
                attempt=tool_invocation.attempt,
                role=tool_invocation.role,
                tool_name=tool_invocation.tool_name,
                total_tokens=None,
                cost_cny=tool_invocation.actual_cny if cost_known else None,
                usage_known=True,
                cost_known=cost_known,
                result_reference=tool_invocation.result_reference,
            )
        return tuple(rows.values())

    def summary_for_run(self, run_id: UUID) -> UsageSummary:
        rows = self.list_for_run(run_id)
        model_rows = tuple(row for row in rows if row.source.endswith("model"))
        tool_rows = tuple(row for row in rows if row.source == "multi_agent_tool")
        return UsageSummary(
            call_count=len(rows),
            model_call_count=len(model_rows),
            tool_call_count=len(tool_rows),
            known_tokens=sum(row.total_tokens or 0 for row in model_rows),
            known_cost_cny=sum(
                (row.cost_cny for row in rows if row.cost_cny is not None),
                Decimal("0"),
            ),
            has_unknown_usage=any(not row.usage_known for row in model_rows),
            has_unknown_cost=any(not row.cost_known for row in rows),
        )
