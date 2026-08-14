from collections.abc import Sequence

from sector_pulse.domain.llm import AgentInvocation
from sector_pulse.storage.sqlite import SQLiteDatabase


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
