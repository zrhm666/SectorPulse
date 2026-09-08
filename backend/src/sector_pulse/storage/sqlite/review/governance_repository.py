import json
from datetime import datetime
from uuid import UUID

from sector_pulse.domain.review.editing import (
    EvidenceDecision,
    EvidenceDecisionKind,
    PreferenceCandidate,
    PreferenceVersion,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase


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

    def save_preference_candidate(self, candidate: PreferenceCandidate) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """INSERT INTO preference_candidates
                (candidate_id, source_patch_id, content_json, status, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (str(candidate.candidate_id), str(candidate.source_patch_id),
                 json.dumps(candidate.content), candidate.status, candidate.created_at.isoformat()),
            )

    def adopt_preference(self, candidate_id: UUID, adopted_at: datetime) -> PreferenceVersion:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT content_json FROM preference_candidates WHERE candidate_id = ?",
                (str(candidate_id),),
            ).fetchone()
            if row is None:
                raise KeyError(str(candidate_id))
            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM preference_versions"
            ).fetchone()[0]
            version = int(current) + 1
            connection.execute("UPDATE preference_versions SET active = 0 WHERE active = 1")
            connection.execute(
                """INSERT INTO preference_versions
                (version, content_json, adopted_at, active) VALUES (?, ?, ?, 1)""",
                (version, row[0], adopted_at.isoformat()),
            )
            connection.execute(
                "UPDATE preference_candidates SET status = 'ADOPTED' WHERE candidate_id = ?",
                (str(candidate_id),),
            )
        return PreferenceVersion(version=version, content=json.loads(row[0]), adopted_at=adopted_at)
