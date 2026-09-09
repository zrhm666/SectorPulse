"""Pure historical repair preview. No persistence, LLM calls, or inferred sector names."""

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from sector_pulse.domain.review.editing import DraftPatch
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
from sector_pulse.domain.writing.attribution import AttributionContext, SectorAnalysisCard
from sector_pulse.storage.ports.review import DraftEditRepositoryPort

GENERIC_HEADING = re.compile(r"^(\s*)板块[一二三四五六七八九十\d]+(?=\s*[:：、])")
FIRST_REFERENCE = re.compile(r"^(\s*)(?:该行业板块|该概念板块|该板块)")
SYSTEM_TAIL = re.compile(r"(?:\s*[（(]已(?:复核|审核)[）)])+\s*$")


def _replace_subject(pattern: re.Pattern[str], text: str, name: str) -> str:
    return pattern.sub(lambda match: match[1] + name, text, count=1)


@dataclass(frozen=True)
class RepairChange:
    path: str
    before: str
    after: str


@dataclass(frozen=True)
class DraftRepairPreview:
    before: ArticleDraft
    after: ArticleDraft | None
    changes: tuple[RepairChange, ...]
    unresolved_section_ids: tuple[str, ...]


def repair_preview_hash(preview: DraftRepairPreview) -> str:
    payload = {
        "before": preview.before.model_dump(mode="json"),
        "after": preview.after.model_dump(mode="json") if preview.after else None,
        "changes": [(c.path, c.before, c.after) for c in preview.changes],
        "unresolved": preview.unresolved_section_ids,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def apply_draft_repair(
    preview: DraftRepairPreview,
    repository: DraftEditRepositoryPort,
    *,
    expected_preview_hash: str,
    actor: str,
) -> ArticleDraft:
    if not actor.strip() or repair_preview_hash(preview) != expected_preview_hash:
        raise ValueError("repair preview confirmation does not match")
    current = repository.latest_version(preview.before.draft_id)
    if current != preview.before:
        raise ValueError("repair preview is stale")
    if preview.after is None:
        return current
    operations = tuple(
        DraftPatch(
            path=change.path,
            old_value_hash=hashlib.sha256(change.before.encode()).hexdigest(),
            value=change.after,
        )
        for change in preview.changes
    )
    return repository.apply_patch(
        current.draft_id,
        current.version,
        operations,
        actor=f"draft-identity-repair:{actor.strip()}",
    )


def preview_draft_repair(
    draft: ArticleDraft,
    identities: Sequence[AttributionContext | SectorAnalysisCard],
    *,
    expected_version: int,
    confirmed_system_markers: bool = False,
) -> DraftRepairPreview:
    if draft.version != expected_version:
        raise ValueError("draft version does not match preview target")
    by_id: dict[str, list[AttributionContext | SectorAnalysisCard]] = {}
    for identity in identities:
        if identity.run_id == draft.run_id:
            by_id.setdefault(identity.sector_id, []).append(identity)
    changes: list[RepairChange] = []
    unresolved: list[str] = []
    sections = []
    for section in draft.sections:
        matches = by_id.get(section.sector_id, [])
        name = (matches[0].sector_name or "").strip() if len(matches) == 1 else ""
        heading, body = section.heading, section.body
        if name:
            heading = _replace_subject(GENERIC_HEADING, heading, name)
            body = _replace_subject(FIRST_REFERENCE, body, name)
        else:
            unresolved.append(section.section_id)
        if confirmed_system_markers:
            body = SYSTEM_TAIL.sub("", body)
        for field, before, after in (
            ("heading", section.heading, heading),
            ("body", section.body, body),
        ):
            if before != after:
                changes.append(
                    RepairChange(f"sections/{section.section_id}/{field}", before, after)
                )
        sections.append(
            section.model_copy(
                update={
                    "heading": heading,
                    "body": body,
                    "character_count": len(body),
                }
            )
            if heading != section.heading or body != section.body
            else section
        )
    candidate = None
    if changes:
        payload = draft.model_dump()
        payload.update(
            version=draft.version + 1,
            status=DraftStatus.UNREVIEWED,
            sections=[s.model_dump() for s in sections],
            character_count=len(draft.introduction)
            + len(draft.conclusion)
            + sum(len(s.body) for s in sections),
        )
        candidate = ArticleDraft.model_validate(payload)
    return DraftRepairPreview(draft, candidate, tuple(changes), tuple(unresolved))
