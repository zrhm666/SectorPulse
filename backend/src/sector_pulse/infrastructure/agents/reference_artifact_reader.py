"""Safe metadata-only reader for persisted orchestration artifact references."""

from collections.abc import Sequence

from sector_pulse.application.orchestration.controls import ArtifactContent
from sector_pulse.application.research_library.artifacts import EVIDENCE_ARTIFACT_KIND
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.domain.research_library.retrieval import (
    AcceptedEvidenceClaim,
    EvidenceSourceRef,
)
from sector_pulse.storage.ports.research_library import AcceptedEvidenceRepositoryPort

#: 一份证据一次最多铺开多少条事实。渲染出来的每一行都是要进模型的上下文，铺不下时说清楚
#: 还有多少条没铺，而不是让最后一行断在半句话上。
MAX_RENDERED_CLAIMS = 20


class ReferenceArtifactReader:
    """把 ArtifactRef 读成模型能用的内容。

    默认只回元数据：没有专门读取端的 kind 一律如此。**已接纳的内部证据**是唯一有内容的
    kind——它的内容不在 MinIO 里，而在权威库那两张证据表里，读取端就是为它接进来的。

    渲染出来的东西刻意只有三样：证据句柄、事实本身、以及它站着的定位。正文、对象键、内部
    下载地址都不出现：A3/A4 要判断的是"这条事实有没有出处、冲突解决了没有、版本还在不在"，
    而不是把原文再读一遍——原文属于 A2 的检索侧，规格 15.2 把它留在那里。
    """

    def __init__(self, *, evidence: AcceptedEvidenceRepositoryPort | None = None) -> None:
        self._evidence = evidence

    def read(self, artifact: ArtifactRef, *, max_chars: int) -> ArtifactContent:
        claims = self._accepted_claims(artifact)
        if claims is None:
            return ArtifactContent(
                summary=f"{artifact.kind}: {artifact.reference}",
                data={
                    "artifact_id": str(artifact.artifact_id),
                    "kind": artifact.kind,
                    "reference": artifact.reference,
                },
            )
        return ArtifactContent(
            summary=_render(claims, max_chars=max_chars),
            data={
                "artifact_id": str(artifact.artifact_id),
                "kind": artifact.kind,
                "reference": artifact.reference,
                "claims": [_claim_data(claim) for claim in claims[:MAX_RENDERED_CLAIMS]],
                "claims_truncated": len(claims) > MAX_RENDERED_CLAIMS,
            },
        )

    def _accepted_claims(self, artifact: ArtifactRef) -> tuple[AcceptedEvidenceClaim, ...] | None:
        """这份 Artifact 里的已接纳证据；不是这种 kind、或者没接读取端时返回 None。"""
        if self._evidence is None or artifact.kind != EVIDENCE_ARTIFACT_KIND:
            return None
        return self._evidence.get_accepted_evidence((artifact.reference,))


def _locator(reference: EvidenceSourceRef) -> str:
    page = (
        f"p{reference.page_start}"
        if reference.page_end in {None, reference.page_start}
        else f"p{reference.page_start}-{reference.page_end}"
    )
    section = "/".join(reference.section_path)
    parts = (
        f"doc={reference.document_id}",
        f"version={reference.document_version_id}",
        f"chunk={reference.chunk_id}",
        page,
    )
    return " ".join((*parts, f"section={section}")) if section else " ".join(parts)


def _claim_lines(index: int, claim: AcceptedEvidenceClaim) -> list[str]:
    item = claim.claim
    head = (
        f"[{index}] cite={claim.evidence_id} grade={item.grade.value} "
        f"conflict={item.conflict_status.value} "
        f"requires_verification={'yes' if item.requires_verification else 'no'}"
        + (f" qualifiers={','.join(item.qualifiers)}" if item.qualifiers else "")
    )
    lines = [head, f"    fact: {item.statement}"]
    lines.extend(f"    source: {_locator(reference)}" for reference in item.source_refs)
    return lines


def _render(claims: Sequence[AcceptedEvidenceClaim], *, max_chars: int) -> str:
    lines = [f"internal research evidence: {len(claims)} claim(s)"]
    shown = 0
    for position, claim in enumerate(claims, start=1):
        if position > MAX_RENDERED_CLAIMS:
            break
        block = _claim_lines(position, claim)
        if len("\n".join((*lines, *block))) > max_chars:
            break
        lines.extend(block)
        shown += 1
    if shown < len(claims):
        lines.append(f"... {len(claims) - shown} further claim(s) omitted for length")
    return "\n".join(lines)


def _claim_data(claim: AcceptedEvidenceClaim) -> dict[str, object]:
    item = claim.claim
    return {
        "evidence_id": claim.evidence_id,
        "statement": item.statement,
        "stance": item.stance.value,
        "grade": item.grade.value,
        "conflict_status": item.conflict_status.value,
        "requires_verification": item.requires_verification,
        "qualifiers": list(item.qualifiers),
        "source_refs": [
            {
                "document_id": reference.document_id,
                "document_version_id": reference.document_version_id,
                "chunk_id": reference.chunk_id,
                "page_start": reference.page_start,
                "page_end": reference.page_end,
                "section_path": list(reference.section_path),
            }
            for reference in item.source_refs
        ],
    }
