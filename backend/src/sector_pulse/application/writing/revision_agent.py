"""Bounded, explicit revision changes; no model-controlled draft identity."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from sector_pulse.application.writing.agent_validation import validate_prohibited_language
from sector_pulse.application.writing.draft_quality import draft_quality_issues, sector_subject
from sector_pulse.application.writing.invocations import (
    InvocationSink,
    build_invocation,
    noop_invocation_sink,
)
from sector_pulse.domain.llm import LLMRequest, LLMStatus
from sector_pulse.domain.review.review import ReviewDecision, ReviewReport
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
from sector_pulse.domain.writing.attribution import LEVEL_RANK, Claim, SectorAnalysisCard
from sector_pulse.ports.llm import LLMPort


class SectionRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    section_id: str
    heading: str
    body: str
    claims: tuple[Claim, ...]
    source_ids: tuple[str, ...]


class RevisionChanges(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sections: tuple[SectionRevision, ...] = ()
    titles: tuple[str, ...] | None = None
    introduction: str | None = None
    conclusion: str | None = None
    risk_notice: str | None = None


@dataclass(frozen=True)
class RevisionResult:
    draft: ArticleDraft | None = None
    error_code: str | None = None


def _scope(draft: ArticleDraft, review: ReviewReport) -> tuple[set[str], bool]:
    if (
        review.draft_id != str(draft.draft_id)
        or review.draft_version != draft.version
        or review.decision is not ReviewDecision.REVISE
    ):
        raise ValueError("review identity or decision mismatch")
    sections = {section.section_id for section in draft.sections}
    claims: dict[str, set[str]] = {}
    for section in draft.sections:
        for claim in section.claims:
            claims.setdefault(claim.claim_id, set()).add(section.section_id)
    allowed: set[str] = set()
    global_issue = False
    for issue in review.issues:
        target = issue.section_id
        if issue.claim_id is not None:
            owners = claims.get(issue.claim_id, set())
            if len(owners) != 1 or (target is not None and target not in owners):
                raise ValueError("unknown or ambiguous claim")
            target = next(iter(owners))
        if target is not None:
            if target not in sections:
                raise ValueError("unknown section")
            allowed.add(target)
        else:
            global_issue = True
    return (sections if global_issue else allowed), global_issue


def _apply(
    draft: ArticleDraft,
    changes: RevisionChanges,
    allowed: set[str],
    global_issue: bool,
    cards: Mapping[str, SectorAnalysisCard],
) -> ArticleDraft:
    global_updates = changes.model_dump(exclude_none=True, exclude={"sections"})
    if global_updates and not global_issue:
        raise ValueError("global fields outside revision scope")
    replacements = {item.section_id: item for item in changes.sections}
    if len(replacements) != len(changes.sections) or not replacements.keys() <= allowed:
        raise ValueError("invalid section targets")
    source_ids = {source.source_id for source in draft.sources}
    sections = []
    for section in draft.sections:
        replacement = replacements.get(section.section_id)
        if replacement is None:
            sections.append(section)
            continue
        card = cards[section.sector_id]
        sector_evidence = set(card.supporting_evidence_ids) | set(card.background_event_ids)
        if not set(replacement.source_ids) <= source_ids:
            raise ValueError("unknown source")
        for claim in replacement.claims:
            validate_prohibited_language(claim.text)
            if not set(claim.evidence_ids) <= source_ids & sector_evidence:
                raise ValueError("unknown evidence")
            if (
                claim.attribution_level is not None
                and LEVEL_RANK[claim.attribution_level] > LEVEL_RANK[card.allowed_max_level]
            ):
                raise ValueError("attribution ceiling exceeded")
        sections.append(
            section.model_copy(
                update={
                    **replacement.model_dump(exclude={"section_id", "claims"}),
                    "claims": replacement.claims,
                    "source_ids": replacement.source_ids,
                    "character_count": len(replacement.body),
                }
            )
        )
    candidate = draft.model_copy(update={**global_updates, "sections": tuple(sections)})
    if (
        candidate.titles == draft.titles
        and candidate.introduction == draft.introduction
        and candidate.conclusion == draft.conclusion
        and candidate.risk_notice == draft.risk_notice
        and all(
            a.model_dump(exclude={"character_count"}) == b.model_dump(exclude={"character_count"})
            for a, b in zip(candidate.sections, draft.sections, strict=True)
        )
    ):
        raise ValueError("REVISION_NO_CHANGE")
    if draft_quality_issues(candidate, cards):
        raise ValueError("draft quality validation failed")
    for text in (
        *candidate.titles,
        candidate.introduction,
        candidate.conclusion,
        candidate.risk_notice,
        *(s.heading + "\n" + s.body for s in candidate.sections),
    ):
        validate_prohibited_language(text)
    payload = candidate.model_dump()
    payload.update(
        version=draft.version + 1,
        status=DraftStatus.UNREVIEWED,
        character_count=len(candidate.introduction)
        + len(candidate.conclusion)
        + sum(len(s.body) for s in candidate.sections),
    )
    return ArticleDraft.model_validate(payload)


async def run_revision_agent(
    draft: ArticleDraft,
    review: ReviewReport,
    cards: Mapping[str, SectorAnalysisCard],
    llm: LLMPort,
    prompt: Any,
    invocation_sink: InvocationSink = noop_invocation_sink,
    model: str = "fixture",
) -> RevisionResult:
    try:
        allowed, global_issue = _scope(draft, review)
    except ValueError:
        return RevisionResult(error_code="REVISION_SCOPE_INVALID")
    request = LLMRequest[RevisionChanges](
        agent_name="revision",
        model=model,
        prompt_id=getattr(prompt, "prompt_id", "revision"),
        prompt_version=getattr(prompt, "version", "1"),
        system_prompt=getattr(prompt, "system", ""),
        user_payload={
            "draft": draft.model_dump(mode="json"),
            "review": review.model_dump(mode="json"),
            "allowed_section_ids": sorted(allowed),
            "allow_global_changes": global_issue,
            "cards": {key: card.model_dump(mode="json") for key, card in cards.items()},
            "sector_subjects": {key: sector_subject(card) for key, card in cards.items()},
        },
        response_model=RevisionChanges,
        fixture_key=f"revision:{draft.version}",
    )
    result = await llm.generate_structured(request)
    invocation_sink(
        build_invocation(
            draft.run_id, "revision", request, result, getattr(llm, "provider_id", "unknown")
        )
    )
    if result.status is not LLMStatus.SUCCESS or result.data is None:
        return RevisionResult(error_code="REVISION_REQUEST_FAILED")
    try:
        return RevisionResult(draft=_apply(draft, result.data, allowed, global_issue, cards))
    except (ValueError, KeyError) as exc:
        code = "REVISION_NO_CHANGE" if str(exc) == "REVISION_NO_CHANGE" else "REVISION_INVALID"
        return RevisionResult(error_code=code)
