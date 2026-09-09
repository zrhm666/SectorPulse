import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sector_pulse.domain.review.review import ReviewReport
from sector_pulse.domain.writing.article import ArticleDraft
from sector_pulse.domain.writing.attribution import SectorAnalysisCard
from sector_pulse.infrastructure.llm.fixture_provider import FixtureLLMProvider


def inputs():
    run_id = uuid4()
    card = SectorAnalysisCard(
        run_id=run_id,
        sector_id="1",
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
    draft = ArticleDraft.model_validate(
        {
            "draft_id": uuid4(),
            "run_id": run_id,
            "version": 1,
            "status": "UNREVIEWED",
            "titles": ["市场观察"],
            "introduction": "市场分化",
            "conclusion": "谨慎观察",
            "risk_notice": "不构成投资建议",
            "sources": [{"source_id": "e1", "title": "来源"}],
            "character_count": 20,
            "sections": [
                {
                    "section_id": "s1",
                    "sector_id": "1",
                    "heading": "文化传媒观察",
                    "body": "文化传媒表现分化。",
                    "claims": [],
                    "source_ids": [],
                    "character_count": 10,
                }
            ],
        }
    )
    review = ReviewReport(
        review_id="r1",
        draft_id=str(draft.draft_id),
        draft_version=1,
        decision="REVISE",
        issues=(
            {
                "issue_id": "i1",
                "severity": "WARNING",
                "code": "STYLE",
                "message": "补充边界",
                "section_id": "s1",
            },
        ),
        revision_round=0,
    )
    change = {
        "sections": [
            {
                "section_id": "s1",
                "heading": "文化传媒观察",
                "body": "文化传媒表现分化，暂无可靠解释。",
                "claims": [],
                "source_ids": [],
            }
        ]
    }
    return draft, review, {"1": card}, change


def run(change, draft=None, review=None):
    from sector_pulse.application.writing.revision_agent import run_revision_agent

    original, report, cards, _ = inputs()
    draft = draft or original
    cards = {key: card.model_copy(update={"run_id": draft.run_id}) for key, card in cards.items()}
    report = review or report.model_copy(update={"draft_id": str(draft.draft_id)})
    invocations = []
    result = asyncio.run(
        run_revision_agent(
            draft,
            report,
            cards,
            FixtureLLMProvider({"revision:1": change}),
            SimpleNamespace(),
            invocation_sink=invocations.append,
        )
    )
    return result, invocations


def test_revision_changes_actual_text_and_resets_status():
    draft, review, _, change = inputs()
    result, invocations = run(change, draft, review)
    assert result.error_code is None
    assert result.draft.version == 2
    assert result.draft.draft_id == draft.draft_id
    assert result.draft.sections[0].body == "文化传媒表现分化，暂无可靠解释。"
    assert result.draft.status.value == "UNREVIEWED"
    assert result.draft.introduction == draft.introduction
    assert len(invocations) == 1
    assert invocations[0].stage == "revision"


@pytest.mark.parametrize(
    "case",
    [
        "no_change",
        "unknown_section",
        "unknown_source",
        "global_edit",
        "marker",
        "missing_subject",
        "forbidden",
        "identity",
        "claim",
    ],
)
def test_invalid_revision_never_produces_new_version(case):
    draft, review, _, change = inputs()
    section = change["sections"][0]
    if case == "no_change":
        section["body"] = draft.sections[0].body
    elif case == "unknown_section":
        section["section_id"] = "other"
    elif case == "unknown_source":
        section["source_ids"] = ["invented"]
    elif case == "global_edit":
        change["introduction"] = "不允许修改全局字段"
    elif case == "marker":
        section["body"] += "（已复核）"
    elif case == "missing_subject":
        section["body"] = "该板块表现分化。"
    elif case == "forbidden":
        section["body"] += "建议买入"
    elif case == "identity":
        change["draft_id"] = str(uuid4())
    else:
        section["claims"] = [
            {
                "claim_id": "c1",
                "kind": "ATTRIBUTION",
                "text": "文化传媒上涨",
                "evidence_ids": ["invented"],
                "attribution_level": "EXPLICIT_DRIVER",
            }
        ]
    result, _ = run(change, draft, review)
    assert result.draft is None
    assert result.error_code is not None


def test_unknown_review_claim_rejects_before_call():
    draft, review, _, change = inputs()
    issue = review.issues[0].model_copy(update={"claim_id": "missing"})
    review = review.model_copy(update={"issues": (issue,)})
    result, invocations = run(change, draft, review)
    assert result.error_code == "REVISION_SCOPE_INVALID"
    assert invocations == []


def test_source_catalog_does_not_authorize_unrelated_sector_evidence():
    draft, review, _, change = inputs()
    change["sections"][0]["claims"] = [
        {
            "claim_id": "c1",
            "kind": "NEWS_FACT",
            "text": "另一板块的证据",
            "evidence_ids": ["e1"],
        }
    ]
    result, _ = run(change, draft, review)
    assert result.draft is None
    assert result.error_code == "REVISION_INVALID"
