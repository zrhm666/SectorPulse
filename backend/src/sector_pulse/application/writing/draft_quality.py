"""Deterministic article checks; findings are metadata, never appended to prose."""

import re
from collections.abc import Mapping

from sector_pulse.application.research_library.evidence_access import AcceptedEvidenceIndex
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.research_library.retrieval import ConflictStatus
from sector_pulse.domain.review.review import IssueSeverity, ReviewIssue
from sector_pulse.domain.writing.article import ArticleDraft
from sector_pulse.domain.writing.attribution import ClaimKind, SectorAnalysisCard

WORKFLOW_MARKER = re.compile(r"[（(]\s*已(?:复核|审核)\s*[）)]")

#: 规格 15.4：判不了的和没查成的冲突都不能被写成确定结论。
_OPEN_CONFLICTS = frozenset({ConflictStatus.UNRESOLVED, ConflictStatus.CHECK_FAILED})

INTERNAL_SOURCE_INACTIVE = "INTERNAL_SOURCE_INACTIVE"
UNRESOLVED_CONFLICT_STATED_AS_FACT = "UNRESOLVED_CONFLICT_STATED_AS_FACT"
UNVERIFIED_ONLY_SUPPORT = "UNVERIFIED_ONLY_SUPPORT"


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


def internal_evidence_issues(
    draft: ArticleDraft,
    cards: Mapping[str, SectorAnalysisCard],
    accepted: AcceptedEvidenceIndex,
) -> tuple[ReviewIssue, ...]:
    """规格 15.3/15.4：草稿引用内部证据时要满足的三条确定性规则。

    这三条都是**程序结论**，不是审校意见：A4 不得把它们改写成自己的判断（规格 15.4），
    A3 也不得靠措辞绕过它们。级别一律 BLOCKING——`ReviewReport` 自己就拒绝带着 BLOCKING
    问题的 PASS，因此"把未决冲突写成确定事实"不可能靠某个 Agent 点头通过。

    只看**事实级**引用，不看章节的来源清单：`section.source_ids` 是这一段读过什么，`Claim`
    的 `evidence_ids` 才是这一段拿什么当了依据；只有后者出错才会让一句话站不住。反过来，
    一条只出现在来源清单里、没有任何事实据它下结论的内部证据，不构成违规。

    "内部"引用是这样认出来的：一个不在本板块新闻事件空间里的句柄。这个判断不需要给证据 ID
    加前缀，也就不会出现"加了前缀但没登记"这种半套状态；另一边，任何凭空写出的句柄都会在
    提交时被既有的来源校验挡掉，轮不到这里。
    """
    issues: list[ReviewIssue] = []

    def add(code: str, message: str, claim_id: str) -> None:
        issues.append(
            ReviewIssue(
                issue_id=f"internal:{code}:{claim_id}",
                severity=IssueSeverity.BLOCKING,
                code=code,
                message=message,
                claim_id=claim_id,
                suggested_fix=message,
            )
        )

    for section in draft.sections:
        card = cards.get(section.sector_id)
        if card is None or card.run_id != draft.run_id:
            # 板块身份本身已经错了，这里再报一次只会把同一个问题说两遍。
            continue
        news_ids = set(card.supporting_evidence_ids) | set(card.background_event_ids)
        for claim in section.claims:
            cited = tuple(dict.fromkeys(claim.evidence_ids))
            internal = tuple(item for item in cited if item not in news_ids)
            if not internal:
                continue
            records = [accepted.get(item) for item in internal]
            if any(not accepted.is_citable(item) for item in internal):
                add(
                    INTERNAL_SOURCE_INACTIVE,
                    "引用的内部证据已失效：来源版本被替换或删除，或它已不在本次运行的已接纳证据里。",
                    claim.claim_id,
                )
            if claim.kind is ClaimKind.BACKGROUND:
                # 背景事实只说明"这件事被报道过"，不是对板块下的结论。
                continue
            if any(
                record is not None and record.claim.conflict_status in _OPEN_CONFLICTS
                for record in records
            ):
                add(
                    UNRESOLVED_CONFLICT_STATED_AS_FACT,
                    "内部证据的冲突尚未解决，必须保留双方说法与不确定语气，不得写成确定结论。",
                    claim.claim_id,
                )
            if (
                len(internal) == len(cited)
                and all(
                    record is not None and record.claim.requires_verification
                    for record in records
                )
            ):
                add(
                    UNVERIFIED_ONLY_SUPPORT,
                    "唯一依据是需要核验的内部证据，需补充已验证来源或改写为待观察的说法。",
                    claim.claim_id,
                )
    return tuple(issues)
