# ruff: noqa: E501
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.prompt_golden import PromptGoldenCase
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresPromptGoldenRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save(self, item: PromptGoldenCase) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO prompt_golden_cases
                    (case_id, prompt_id, prompt_version, input_hash, expected_schema,
                     result, notes, created_at)
                    VALUES (:case_id, :prompt_id, :prompt_version, :input_hash,
                     :expected_schema, :result, :notes, :created_at)
                    ON CONFLICT (prompt_id, prompt_version, input_hash) DO UPDATE SET result = EXCLUDED.result,
                     notes = EXCLUDED.notes"""
                ),
                {
                    "case_id": str(item.case_id), "prompt_id": item.prompt_id,
                    "prompt_version": item.prompt_version, "input_hash": item.input_hash,
                    "expected_schema": item.expected_schema, "result": item.result,
                    "notes": item.notes, "created_at": item.created_at.isoformat(),
                },
            )

    def list(self) -> tuple[PromptGoldenCase, ...]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text(
                    "SELECT case_id, prompt_id, prompt_version, input_hash, expected_schema, "
                    "result, notes, created_at FROM prompt_golden_cases "
                    "ORDER BY prompt_id, prompt_version, created_at"
                )
            )
            rows = result.mappings().all()
        return tuple(
            PromptGoldenCase(
                case_id=UUID(row["case_id"]), prompt_id=row["prompt_id"],
                prompt_version=row["prompt_version"], input_hash=row["input_hash"],
                expected_schema=row["expected_schema"], result=row["result"],
                notes=row["notes"], created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        )
