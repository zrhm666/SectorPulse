from uuid import uuid4

from sector_pulse.application.evidence_decision_service import EvidenceDecisionService
from sector_pulse.domain.article import ArticleDraft, ArticleSection, ArticleSource, DraftStatus
from sector_pulse.storage.governance_repository import SQLiteGovernanceRepository
from sector_pulse.storage.sqlite import SQLiteDatabase


def test_rejecting_source_marks_only_linked_sections_for_rewrite(tmp_path):
    database = SQLiteDatabase(tmp_path / "decisions.db")
    repository = SQLiteGovernanceRepository(database)
    draft = ArticleDraft(
        draft_id=uuid4(), run_id=uuid4(), version=1, status=DraftStatus.INCOMPLETE,
        titles=("标题",), introduction="导语",
        sections=(
            ArticleSection(
                section_id="section-1", sector_id="s1", heading="一", body="一",
                claims=(), source_ids=("source-1",), character_count=1,
            ),
            ArticleSection(
                section_id="section-2", sector_id="s2", heading="二", body="二",
                claims=(), source_ids=("source-2",), character_count=1,
            ),
        ),
        conclusion="总结", risk_notice="风险",
        sources=(
            ArticleSource(source_id="source-1", title="来源"),
            ArticleSource(source_id="source-2", title="来源2"),
        ),
        character_count=8,
    )
    service = EvidenceDecisionService(repository)

    affected = service.record(draft, "source-1", "REJECT", "not relevant", actor="tester")

    assert affected == {"section-1"}
