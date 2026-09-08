# ruff: noqa: E501
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.editing import (
    EvidenceDecision,
    EvidenceDecisionKind,
    PreferenceCandidate,
    PreferenceVersion,
)
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresGovernanceRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save_evidence_decision(self, decision: EvidenceDecision) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text("INSERT INTO evidence_decisions (decision_id, run_id, draft_id, draft_version, source_id, decision, "
                     "reason, affected_section_ids_json, created_at) VALUES (:decision_id, :run_id, :draft_id, :draft_version, "
                     ":source_id, :decision, :reason, :sections, :created_at)"),
                {"decision_id": str(decision.decision_id), "run_id": str(decision.run_id),
                 "draft_id": str(decision.draft_id), "draft_version": decision.draft_version,
                 "source_id": decision.source_id, "decision": decision.decision.value,
                 "reason": decision.reason, "sections": json.dumps(decision.affected_section_ids),
                 "created_at": decision.created_at.isoformat()},
            )

    def list_evidence_decisions(self, draft_id: UUID) -> tuple[EvidenceDecision, ...]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text("SELECT decision_id, run_id, draft_id, draft_version, source_id, decision, reason, "
                     "affected_section_ids_json, created_at FROM evidence_decisions WHERE draft_id = :draft_id ORDER BY created_at"),
                {"draft_id": str(draft_id)},
            )
            rows = result.fetchall()
        return tuple(EvidenceDecision(
            decision_id=UUID(row[0]), run_id=UUID(row[1]), draft_id=UUID(row[2]), draft_version=row[3],
            source_id=row[4], decision=EvidenceDecisionKind(row[5]), reason=row[6],
            affected_section_ids=tuple(json.loads(row[7])), created_at=datetime.fromisoformat(row[8]),
        ) for row in rows)

    def save_preference_candidate(self, candidate: PreferenceCandidate) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text("INSERT INTO preference_candidates (candidate_id, source_patch_id, content_json, status, created_at) "
                     "VALUES (:candidate_id, :source_patch_id, :content, :status, :created_at)"),
                {"candidate_id": str(candidate.candidate_id), "source_patch_id": str(candidate.source_patch_id),
                 "content": json.dumps(candidate.content), "status": candidate.status,
                 "created_at": candidate.created_at.isoformat()},
            )

    def adopt_preference(self, candidate_id: UUID, adopted_at: datetime) -> PreferenceVersion:
        with self._database.start().begin() as connection:
            result = connection.execute(
                text("SELECT content_json FROM preference_candidates WHERE candidate_id = :candidate_id"),
                {"candidate_id": str(candidate_id)},
            )
            row = result.first()
            if row is None:
                raise KeyError(str(candidate_id))
            result = connection.execute(text("SELECT COALESCE(MAX(version), 0) FROM preference_versions"))
            version = int(result.scalar_one()) + 1
            connection.execute(text("UPDATE preference_versions SET active = 0 WHERE active = 1"))
            connection.execute(
                text("INSERT INTO preference_versions (version, content_json, adopted_at, active) VALUES (:version, :content, :adopted_at, 1)"),
                {"version": version, "content": row[0], "adopted_at": adopted_at.isoformat()},
            )
            connection.execute(text("UPDATE preference_candidates SET status = 'ADOPTED' WHERE candidate_id = :candidate_id"),
                                     {"candidate_id": str(candidate_id)})
        return PreferenceVersion(version=version, content=json.loads(row[0]), adopted_at=adopted_at)
