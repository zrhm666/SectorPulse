from uuid import uuid4

import pytest
from sector_pulse.application.writing import draft_quality
from sector_pulse.domain.writing.article import ArticleDraft, ArticleSection, DraftStatus
from sector_pulse.domain.writing.attribution import SectorAnalysisCard


def sample():
    run_id = uuid4()
    card = SectorAnalysisCard(
        run_id=run_id,
        sector_id="881001",
        sector_kind="INDUSTRY",
        sector_name="文化传媒",
        allowed_max_level="NO_RELIABLE_EXPLANATION",
        attribution_level="NO_RELIABLE_EXPLANATION",
        confidence=0,
        conclusion="暂无可靠解释",
        supporting_evidence_ids=(),
        counter_evidence=(),
        uncertainties=(),
        background_event_ids=(),
        claims=(),
        forbidden_inferences=(),
    )
    section = ArticleSection(
        section_id="s1",
        sector_id=card.sector_id,
        heading="文化传媒：市场观察",
        body="文化传媒板块表现分化。暂无可靠解释。",
        claims=(),
        source_ids=(),
        character_count=24,
    )
    draft = ArticleDraft(
        draft_id=uuid4(),
        run_id=run_id,
        version=1,
        status=DraftStatus.UNREVIEWED,
        titles=("市场观察",),
        introduction="观察市场",
        sections=(section,),
        conclusion="保持审慎",
        risk_notice="不构成投资建议",
        sources=(),
        character_count=40,
    )
    return draft, {card.sector_id: card}


def test_clear_subject_is_accepted():
    draft, cards = sample()
    assert draft_quality.draft_quality_issues(draft, cards) == ()


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"heading": "板块一：观察"}, "SECTOR_SUBJECT_MISSING"),
        ({"body": "该板块表现分化。文化传媒只是后文才说明。"}, "SECTOR_SUBJECT_MISSING"),
        ({"body": "文化传媒表现分化。（已复核）（已复核）"}, "WORKFLOW_MARKER_IN_ARTICLE"),
        ({"sector_id": "unknown"}, "SECTION_IDENTITY_INVALID"),
    ],
)
def test_quality_issues_are_located(changes, code):
    draft, cards = sample()
    draft = draft.model_copy(update={"sections": (draft.sections[0].model_copy(update=changes),)})
    issues = draft_quality.draft_quality_issues(draft, cards)
    assert any(issue.code == code and issue.section_id == "s1" for issue in issues)


def test_duplicate_sector_is_rejected():
    draft, cards = sample()
    duplicate = draft.sections[0].model_copy(update={"section_id": "s2"})
    draft = draft.model_copy(update={"sections": (*draft.sections, duplicate)})
    assert any(
        i.code == "SECTION_IDENTITY_INVALID"
        for i in draft_quality.draft_quality_issues(draft, cards)
    )


def test_unknown_name_uses_traceable_subject():
    _, cards = sample()
    card = cards["881001"].model_copy(update={"sector_name": None})
    assert draft_quality.sector_subject(card) == "行业板块〔881001〕"
    assert (
        draft_quality.sector_subject(card.model_copy(update={"sector_kind": "CONCEPT"}))
        == "概念板块〔881001〕"
    )


def test_global_workflow_marker_is_not_ignored():
    draft, cards = sample()
    draft = draft.model_copy(update={"introduction": "观察市场（已审核）"})
    assert any(
        i.code == "WORKFLOW_MARKER_IN_ARTICLE" and i.section_id is None
        for i in draft_quality.draft_quality_issues(draft, cards)
    )
