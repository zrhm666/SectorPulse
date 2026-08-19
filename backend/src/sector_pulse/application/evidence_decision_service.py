from datetime import UTC, datetime

from sector_pulse.domain.article import ArticleDraft
from sector_pulse.domain.editing import EvidenceDecision, EvidenceDecisionKind
from sector_pulse.storage.governance_repository import SQLiteGovernanceRepository


class EvidenceDecisionService:
    def __init__(self, repository: SQLiteGovernanceRepository) -> None:
        self._repository = repository

    def record(
        self,
        draft: ArticleDraft,
        source_id: str,
        decision: str,
        reason: str,
        *,
        actor: str,
    ) -> set[str]:
        if source_id not in {source.source_id for source in draft.sources}:
            raise ValueError("source is not bound to draft")
        kind = EvidenceDecisionKind(decision)
        affected = tuple(
            section.section_id for section in draft.sections if source_id in section.source_ids
        )
        self._repository.save_evidence_decision(
            EvidenceDecision(
                run_id=draft.run_id, draft_id=draft.draft_id, draft_version=draft.version,
                source_id=source_id, decision=kind, reason=reason,
                affected_section_ids=affected, created_at=datetime.now(UTC),
            )
        )
        return set(affected)
