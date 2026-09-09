# ruff: noqa: E501
from datetime import datetime
from uuid import UUID

from sector_pulse.domain.evaluation.prompt_golden import PromptGoldenCase
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLitePromptGoldenRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def save(self, item: PromptGoldenCase) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO prompt_golden_cases
                (case_id, prompt_id, prompt_version, input_hash, expected_schema,
                 result, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(item.case_id), item.prompt_id, item.prompt_version, item.input_hash,
                 item.expected_schema, item.result, item.notes, item.created_at.isoformat()),
            )

    def list(self) -> tuple[PromptGoldenCase, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT case_id, prompt_id, prompt_version, input_hash, expected_schema, result, notes, created_at FROM prompt_golden_cases ORDER BY prompt_id, prompt_version, created_at"
            ).fetchall()
        return tuple(PromptGoldenCase(case_id=UUID(r[0]), prompt_id=r[1], prompt_version=r[2], input_hash=r[3], expected_schema=r[4], result=r[5], notes=r[6], created_at=datetime.fromisoformat(r[7])) for r in rows)
