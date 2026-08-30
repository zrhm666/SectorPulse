from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.llm import AgentInvocation, LLMStatus, MoneyCny, TokenUsage
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresAgentInvocationRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save(self, invocations: Sequence[AgentInvocation]) -> None:
        with self._database.start().begin() as connection:
            for invocation in invocations:
                connection.execute(
                    text(
                        """INSERT INTO agent_invocations
                        (invocation_id, run_id, stage, provider_id, model, prompt_id,
                         prompt_version, input_hash, output_hash, status, prompt_tokens,
                         completion_tokens, total_tokens, estimated_cost_cny, error_code)
                        VALUES (:invocation_id, :run_id, :stage, :provider_id, :model,
                         :prompt_id, :prompt_version, :input_hash, :output_hash, :status,
                         :prompt_tokens, :completion_tokens, :total_tokens,
                         :estimated_cost_cny, :error_code)
                        ON CONFLICT (invocation_id) DO UPDATE SET status = EXCLUDED.status,
                         output_hash = EXCLUDED.output_hash, error_code = EXCLUDED.error_code"""
                    ),
                    {
                        "invocation_id": str(invocation.invocation_id),
                        "run_id": str(invocation.run_id),
                        "stage": invocation.stage, "provider_id": invocation.provider_id,
                        "model": invocation.model, "prompt_id": invocation.prompt_id,
                        "prompt_version": invocation.prompt_version,
                        "input_hash": invocation.input_hash,
                        "output_hash": invocation.output_hash, "status": invocation.status.value,
                        "prompt_tokens": invocation.usage.prompt_tokens,
                        "completion_tokens": invocation.usage.completion_tokens,
                        "total_tokens": invocation.usage.total_tokens,
                        "estimated_cost_cny": str(invocation.estimated_cost_cny.amount),
                        "error_code": invocation.error_code,
                    },
                )

    def list_for_run(self, run_id: UUID) -> list[AgentInvocation]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text(
                    "SELECT invocation_id, run_id, stage, provider_id, model, prompt_id, "
                    "prompt_version, input_hash, output_hash, status, prompt_tokens, "
                    "completion_tokens, total_tokens, estimated_cost_cny, error_code "
                    "FROM agent_invocations WHERE run_id = :run_id ORDER BY invocation_id"
                ),
                {"run_id": str(run_id)},
            )
            rows = result.fetchall()
        return [
            AgentInvocation(
                invocation_id=UUID(row[0]), run_id=UUID(row[1]), stage=row[2],
                provider_id=row[3], model=row[4], prompt_id=row[5], prompt_version=row[6],
                input_hash=row[7], output_hash=row[8], status=LLMStatus(row[9]),
                usage=TokenUsage(
                    prompt_tokens=row[10], completion_tokens=row[11], total_tokens=row[12]
                ),
                estimated_cost_cny=MoneyCny(amount=Decimal(row[13])), error_code=row[14],
            )
            for row in rows
        ]
