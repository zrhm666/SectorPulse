import json
from datetime import datetime
from uuid import UUID

from sector_pulse.domain.editing import EvidenceDecision, EvidenceDecisionKind
from sector_pulse.storage.sqlite import SQLiteDatabase


class SQLiteGovernanceRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def save_evidence_decision(self, decision: EvidenceDecision) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """INSERT INTO evidence_decisions
                (decision_id, run_id, draft_id, draft_version, source_id, decision,
                 reason, affected_section_ids_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(decision.decision_id), str(decision.run_id), str(decision.draft_id),
                    decision.draft_version, decision.source_id, decision.decision.value,
                    decision.reason, json.dumps(decision.affected_section_ids),
                    decision.created_at.isoformat(),
                ),
            )

    def list_evidence_decisions(self, draft_id: UUID) -> tuple[EvidenceDecision, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """SELECT decision_id, run_id, draft_id, draft_version, source_id,
                          decision, reason, affected_section_ids_json, created_at
                   FROM evidence_decisions WHERE draft_id = ? ORDER BY created_at""",
                (str(draft_id),),
            ).fetchall()
        return tuple(
            EvidenceDecision(
                decision_id=UUID(row[0]), run_id=UUID(row[1]), draft_id=UUID(row[2]),
                draft_version=row[3], source_id=row[4], decision=EvidenceDecisionKind(row[5]),
                reason=row[6], affected_section_ids=tuple(json.loads(row[7])),
                created_at=datetime.fromisoformat(row[8]),
            )
            for row in rows
        )
