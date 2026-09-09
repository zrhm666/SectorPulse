"""Deterministic article checks; findings are metadata, never appended to prose."""

import re
from collections.abc import Mapping

from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.review.review import IssueSeverity, ReviewIssue
from sector_pulse.domain.writing.article import ArticleDraft
from sector_pulse.domain.writing.attribution import SectorAnalysisCard

WORKFLOW_MARKER = re.compile(r"[（(]\s*已(?:复核|审核)\s*[）)]")


def sector_subject(card: SectorAnalysisCard) -> str:
    if card.sector_name and card.sector_name.strip():
        return card.sector_name.strip()
    kind = "行业" if card.sector_kind == SectorKind.INDUSTRY else "概念"
    return f"{kind}板块〔{card.sector_id}〕"


def draft_quality_issues(
    draft: ArticleDraft, cards: Mapping[str, SectorAnalysisCard]
) -> tuple[ReviewIssue, ...]:
    issues: list[ReviewIssue] = []

    def add(code: str, message: str, section_id: str | None = None) -> None:
        issues.append(
            ReviewIssue(
                issue_id=f"quality:{code}:{section_id or 'global'}",
                severity=IssueSeverity.WARNING,
                code=code,
                message=message,
                section_id=section_id,
                suggested_fix=message,
            )
        )

    seen_sectors: set[str] = set()
    seen_sections: set[str] = set()
    for section in draft.sections:
        card = cards.get(section.sector_id)
        if (
            card is None
            or card.run_id != draft.run_id
            or section.sector_id in seen_sectors
            or section.section_id in seen_sections
        ):
            add("SECTION_IDENTITY_INVALID", "章节必须唯一对应本次分析板块。", section.section_id)
        else:
            subject = sector_subject(card)
            first_sentence = re.split(r"[。！？!?\n]", section.body.strip(), maxsplit=1)[0]
            if subject not in section.heading or subject not in first_sentence:
                add(
                    "SECTOR_SUBJECT_MISSING",
                    f"标题及正文第一句须明确主体：{subject}。",
                    section.section_id,
                )
        seen_sectors.add(section.sector_id)
        seen_sections.add(section.section_id)
        if WORKFLOW_MARKER.search(section.heading + section.body):
            add(
                "WORKFLOW_MARKER_IN_ARTICLE",
                "移除文章中的系统审核标记，状态只保存在审核记录。",
                section.section_id,
            )
    global_text = "\n".join(
        (*draft.titles, draft.introduction, draft.conclusion, draft.risk_notice)
    )
    if WORKFLOW_MARKER.search(global_text):
        add("WORKFLOW_MARKER_IN_ARTICLE", "移除文章中的系统审核标记，状态只保存在审核记录。")
    return tuple(issues)
