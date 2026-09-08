from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sector_pulse.domain.llm import (
    AgentInvocation,
    LLMStatus,
    MoneyCny,
    TokenUsage,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteAgentInvocationRepository:
    """记录每次模型调用的脱敏元数据，便于成本和失败审计。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def save(self, invocations: Sequence[AgentInvocation]) -> None:
        with self._database.transaction() as connection:
            for invocation in invocations:
                connection.execute(
                    """INSERT OR REPLACE INTO agent_invocations (
                    invocation_id, run_id, stage, provider_id, model, prompt_id,
                    prompt_version, input_hash, output_hash, status,
                    prompt_tokens, completion_tokens, total_tokens,
                    estimated_cost_cny, error_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(invocation.invocation_id), str(invocation.run_id), invocation.stage,
                        invocation.provider_id, invocation.model, invocation.prompt_id,
                        invocation.prompt_version, invocation.input_hash, invocation.output_hash,
                        invocation.status.value, invocation.usage.prompt_tokens,
                        invocation.usage.completion_tokens, invocation.usage.total_tokens,
                        str(invocation.estimated_cost_cny.amount), invocation.error_code,
                    ),
                )

    def list_for_run(self, run_id: UUID) -> list[AgentInvocation]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """SELECT invocation_id, run_id, stage, provider_id, model, prompt_id,
                   prompt_version, input_hash, output_hash, status,
                   prompt_tokens, completion_tokens, total_tokens,
                   estimated_cost_cny, error_code
                   FROM agent_invocations WHERE run_id = ? ORDER BY rowid""",
                (str(run_id),),
            ).fetchall()
        return [
            AgentInvocation(
                invocation_id=UUID(r[0]),
                run_id=UUID(r[1]),
                stage=r[2],
                provider_id=r[3],
                model=r[4],
                prompt_id=r[5],
                prompt_version=r[6],
                input_hash=r[7],
                output_hash=r[8],
                status=LLMStatus(r[9]),
                usage=TokenUsage(
                    prompt_tokens=r[10], completion_tokens=r[11], total_tokens=r[12]
                ),
                estimated_cost_cny=MoneyCny(amount=Decimal(r[13])),
                error_code=r[14],
            )
            for r in rows
        ]
