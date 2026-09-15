"""Framework Tool decorator enforcing persistent admission before side effects."""

import asyncio
import hashlib
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

from aidynamic_agent.tools.base import Tool, ToolResult

from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
from sector_pulse.domain.orchestration.models import ToolCallStatus


class BudgetedTool(Tool):
    def __init__(
        self,
        inner: Tool,
        budget: SharedToolBudget,
        *,
        task_id: UUID,
        attempt: int,
        reserved_cny: Decimal | None,
        actual_cost: Callable[[ToolResult], Decimal | None] | None = None,
        replay_resolver: Callable[[str], ToolResult] | None = None,
    ) -> None:
        super().__init__(inner.context)
        self.inner = inner
        self.budget = budget
        self.task_id = task_id
        self.attempt = attempt
        self.reserved_cny = reserved_cny
        self.actual_cost = actual_cost
        inner_replay = getattr(inner, "replay", None)
        self.replay_resolver = replay_resolver or (
            inner_replay if callable(inner_replay) else None
        )
        self.name = inner.name
        self.description = inner.description
        self.parameters = inner.parameters
        self.tags = inner.tags

    def _identity(self, kwargs: dict[str, Any]) -> tuple[str, str]:
        canonical = json.dumps(
            kwargs,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        fingerprint = hashlib.sha256(canonical).hexdigest()
        identity = f"{self.task_id}:{self.attempt}:{self.name}:{fingerprint}".encode()
        return hashlib.sha256(identity).hexdigest(), fingerprint

    async def execute(self, **kwargs: Any) -> ToolResult:
        call_id, fingerprint = self._identity(kwargs)
        admission = await asyncio.to_thread(
            self.budget.admit,
            task_id=self.task_id,
            attempt=self.attempt,
            call_id=call_id,
            tool_name=self.name,
            input_fingerprint=fingerprint,
            reserved_cny=self.reserved_cny,
        )
        if not admission.execute:
            invocation = admission.invocation
            if (
                invocation.status in {ToolCallStatus.SUCCEEDED, ToolCallStatus.FAILED}
                and invocation.result_reference
                and self.replay_resolver
            ):
                return await asyncio.to_thread(self.replay_resolver, invocation.result_reference)
            return ToolResult(
                content="",
                success=False,
                error="tool call already recorded; persisted result is not available",
                metadata={"tool_call_replayed": True},
            )

        succeeded: bool | None = None
        actual_cny: Decimal | None = None
        result_reference: str | None = None
        try:
            result = await self.inner.run(**kwargs)
            succeeded = result.success
            reference = result.metadata.get("result_reference")
            if isinstance(reference, str) and reference:
                result_reference = reference
            if self.actual_cost is not None:
                actual_cny = self.actual_cost(result)
            return result
        finally:
            await asyncio.shield(
                asyncio.to_thread(
                    self.budget.settle,
                    admission.invocation.call_id,
                    succeeded=succeeded,
                    actual_cny=actual_cny,
                    result_reference=result_reference,
                )
            )
