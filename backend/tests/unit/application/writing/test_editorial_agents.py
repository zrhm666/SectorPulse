from uuid import uuid4

from sector_pulse.application.writing.editorial_agents import revise_sections
from sector_pulse.domain.article import ArticleDraft, ArticleSection, ArticleSource, DraftStatus
from sector_pulse.domain.attribution import Claim, ClaimKind


def section(section_id: str, body: str) -> ArticleSection:
    return ArticleSection(
        section_id=section_id,
        sector_id=section_id,
        heading=section_id,
        body=body,
        claims=(
            Claim(claim_id=f"claim-{section_id}", kind=ClaimKind.BACKGROUND, text=body),
        ),
        source_ids=(f"source-{section_id}",),
        character_count=len(body),
    )


def test_revision_changes_only_selected_sections() -> None:
    draft = ArticleDraft(
        draft_id=uuid4(),
        run_id=uuid4(),
        version=1,
        status=DraftStatus.UNREVIEWED,
        titles=("标题",),
        introduction="导语",
        sections=(section("industry-1", "旧内容1"), section("industry-2", "旧内容2")),
        conclusion="总结",
        risk_notice="风险提示",
        sources=(
            ArticleSource(source_id="source-industry-1", title="来源1"),
            ArticleSource(source_id="source-industry-2", title="来源2"),
        ),
        character_count=20,
    )
    revised = revise_sections(draft, {"industry-1": section("industry-1", "新内容1")})
    assert revised.version == 2
    assert revised.sections[0].body == "新内容1"
    assert revised.sections[1].body == "旧内容2"
