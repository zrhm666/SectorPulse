"""A2 接纳内部证据：模型说的话在什么条件下变成别人可以引用的事实（规格 15.2、19）。

A2 检索的内部资料不会自动成为证据。它要先 `inspect` 一段原文，再把它写成一条带出处的事实
提交上来；中间那一步才是这个模块存在的原因。检索给的是**候选摘要**——有界的、为了让人判断
"要不要读这一篇"而截出来的片段；只有 `inspect` 返回的定位（切片、页码、章节）才代表这一段的
原文被取出过来看过。因此接纳时校验的不是"这个切片存在吗"——它当然存在，整个语料都在
——而是"**这一段，在这条证据的这一次尝试里，被看过吗**"。

四类东西在这里被挡住：

**凭想象写出来的出处。** 出处必须能在本次尝试的查看台账里逐字段对上：切片、版本、页码
区间、章节路径。台账只记定位，**不记正文**：正文留在权威库里，由切片 ID 指回去；把看过的
那一段再存一份，等于给一份随时可被删除的资料配了一份不受删除影响、也没有保留期的副本。
台账活在进程内存里，这也是对的——它描述的是"这一次尝试做过什么"，而尝试随进程一起死。

**等级与标记只能往低了说。** 规格 14 第 5 条把等级定义为从内容来源推出的结论：一页 OCR
申报成原生文本，是在一场按证据质量排序的裁决里悄悄升了一档。一条事实引用几份来源时，它挣到
的是其中**最低**的那一档——取最高的那一档，等于让最体面的那一份来源替整条事实背书。反过来，
自愿申报得比应得的更低是保守，不是撒谎，因此允许。

**没做完的检查不许当成做完了。** `CHECK_FAILED` 与"检查做完了，没有冲突"是两个结论，
`UNRESOLVED` 必须带着双方**不同的**切片一起留下——数列表长度是不够的，同一段话写两遍就能
把这条规则绕过去。

**身份由内容决定。** 同一个 run 里同样的证据得到同一个 ID，所以重放撞上的是自己（`duplicate
artifact ID`），而不是留下第二份看起来一样的证据。

落库与入编排快照在同一次事务里由 `AtomicArtifactCommitter` 完成：业务行、`ArtifactRef` 与事件
一起提交或一起回滚。一份只写了一半的证据比没有证据更糟——它看上去是一条完整的事实，而它的
另一半不见了。快照里放的只有 `ArtifactRef`，正文与证据本体都不进去（规格 15.2）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.research_library.conflicts import evidence_grade, weakest_grade
from sector_pulse.application.research_library.retrieval import (
    ResearchRetrievalService,
    RetrievalAccessDenied,
    RetrievalContext,
    SourceInspection,
)
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.domain.research_library.models import (
    DocumentVersionStatus,
    ExtractionMethod,
    Record,
)
from sector_pulse.domain.research_library.retrieval import (
    ClaimStance,
    ConflictStatus,
    EvidenceGrade,
    EvidenceSourceRef,
    InternalEvidence,
    InternalEvidenceClaim,
)
from sector_pulse.ports.orchestration import ArtifactPersistence, TransactionSession
from sector_pulse.storage.ports.research_library import ResearchLibraryRepositoryPort

__all__ = [
    "EVIDENCE_ARTIFACT_KIND",
    "AcceptInternalEvidenceService",
    "EvidenceAcceptanceDenied",
    "EvidenceGradeMismatch",
    "InspectedSource",
    "LocatorMismatch",
    "SourceWithdrawn",
    "UninspectedSource",
    "UnsupportedDeterministicClaim",
]

#: 规格 15.2 的 Artifact kind。Artifact 的 kind 是裸字符串，这里只此一处定义。
EVIDENCE_ARTIFACT_KIND = "internal_research_evidence"

#: 唯一具有内部检索权限并因此可以接纳内部证据的角色（规格 15）。
EVIDENCE_ACCEPTING_ROLE = "A2"

#: 等级从强到弱的次序。与 `conflicts._GRADE_RANK` 相反方向的排序在这里**不**另立一份：
#: 比较一律通过 `weakest_grade` 做，这里只用来判断"申报得比应得的更高"。
_GRADE_ORDER: Mapping[EvidenceGrade, int] = {
    EvidenceGrade.DERIVED_UNVERIFIED: 0,
    EvidenceGrade.PARSED_STRUCTURE: 1,
    EvidenceGrade.PRIMARY_SOURCE: 2,
}

#: 承载证据身份的命名空间。固定值：换掉它意味着同一个 run 里同样的证据会得到新 ID。
_NAMESPACE = UUID("8f2b7c41-6a3d-4e58-9b17-2c5e4d0a7f93")

_LOCATOR_FIELDS = ("document_id", "document_version_id", "page_start", "page_end", "section_path")


class EvidenceAcceptanceDenied(ValueError):
    """这次接纳从根上就不成立：角色不对、尝试号不可能、载荷里没有事实。"""


class UninspectedSource(ValueError):
    """出处指向一段本次尝试没有查看过的原文。"""


class LocatorMismatch(ValueError):
    """出处里的定位与查看时得到的定位不一致。"""


class SourceWithdrawn(ValueError):
    """查看时还在架的那一版，在接纳之前被替换或删除。"""


class EvidenceGradeMismatch(ValueError):
    """申报的证据质量高于所引内容能支撑的档位。"""


class UnsupportedDeterministicClaim(ValueError):
    """冲突状态与随行的出处不匹配：判不了的和没查成的都必须看得出来。"""


class InspectedSource(Record):
    """台账里的一条：一次 `inspect` 交出过的定位。

    刻意**没有**正文，也没有 `candidate_id`。要记的是一个可以被核对的最小事实——"这一段的
    这一版、这一页、这一节，在这次尝试里被取出过来看过"——而 `candidate_id` 是候选本身的
    句柄，它在审计里，在这里只会多一个可能对不上的副本。
    """

    retrieval_id: str
    chunk_id: str
    document_id: str
    document_version_id: str
    page_start: int | None = None
    page_end: int | None = None
    section_path: tuple[str, ...] = ()
    content_origin: ExtractionMethod
    requires_verification: bool = False

    def located_as(self, reference: EvidenceSourceRef) -> str | None:
        """返回第一处对不上的定位字段名，全部对上时返回 None。"""
        for name in _LOCATOR_FIELDS:
            if getattr(self, name) != getattr(reference, name):
                return name
        return None

    def grade(self) -> EvidenceGrade:
        """这份内容本身应得的等级。"""
        return evidence_grade(
            content_origin=self.content_origin,
            requires_verification=self.requires_verification,
        )


class _EvidenceTables(ArtifactPersistence):
    """把一份接纳写进 `internal_research_evidence` 与 `..._sources`。

    迁移 035 已经在 Task 3 建立这两张表并冻结；这个类只写它们，不碰它们。

    每条事实连同它的出处一起写，父行先落、子行随即跟上。真正保证"要么都在、要么都不在"的
    不是这个顺序，而是 `AtomicArtifactCommitter` 的那一次事务；顺序只让回滚要撤掉的东西
    看起来就是它写下去的那一批。
    """

    def __init__(
        self, groups: Sequence[tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]]
    ) -> None:
        self._groups = tuple((claim, tuple(group)) for claim, group in groups)

    def write(self, session: TransactionSession, artifact: ArtifactRef) -> None:
        for claim, sources in self._groups:
            session.execute(
                "INSERT INTO internal_research_evidence (evidence_id, run_id, task_id, "
                "artifact_ref, retrieval_id, claim_id, statement, stance, conflict_status, "
                "grade, requires_verification, qualifiers_json, created_at) VALUES "
                "(:evidence_id, :run_id, :task_id, :artifact_ref, :retrieval_id, :claim_id, "
                ":statement, :stance, :conflict_status, :grade, :requires_verification, "
                ":qualifiers_json, :created_at)",
                dict(claim),
            )
            for source in sources:
                session.execute(
                    "INSERT INTO internal_research_evidence_sources (evidence_id, source_order, "
                    "document_id, document_version_id, chunk_id, page_start, page_end, "
                    "section_path_json, bounding_boxes_json) VALUES "
                    "(:evidence_id, :source_order, :document_id, :document_version_id, "
                    ":chunk_id, :page_start, :page_end, :section_path_json, "
                    ":bounding_boxes_json)",
                    dict(source),
                )

    def exists(self, session: TransactionSession, artifact: ArtifactRef) -> bool:
        """业务行必须真的在事务里可见，且一条不少。

        只数事实而不数出处是不够的：一份少了一条出处的证据仍然会通过，而它引用的那一段
        原文从审计里消失了。
        """
        claims = session.rows(
            "SELECT COUNT(*) FROM internal_research_evidence WHERE artifact_ref=:ref",
            {"ref": artifact.reference},
        )
        written = session.rows(
            "SELECT COUNT(*) FROM internal_research_evidence_sources WHERE evidence_id IN "
            "(SELECT evidence_id FROM internal_research_evidence WHERE artifact_ref=:ref)",
            {"ref": artifact.reference},
        )
        expected = sum(len(group) for _claim, group in self._groups)
        return bool(claims[0][0] == len(self._groups) and written[0][0] == expected)


class AcceptInternalEvidenceService:
    """A2 的两步：先 `inspect`，再 `accept`。

    两个方法在同一个对象上，是因为台账是它们之间唯一的联系：接纳时能核对的只有这个对象
    记下的查看记录。拆成两个对象就得把台账搬到一个更长寿的地方，而它描述的是"这一次尝试
    做过什么"——尝试结束了，它就该跟着结束。
    """

    def __init__(
        self,
        *,
        retrieval: ResearchRetrievalService,
        repository: ResearchLibraryRepositoryPort,
        committer: AtomicArtifactCommitter,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._repository = repository
        self._committer = committer
        self._clock = clock or (lambda: datetime.now(UTC))
        self._inspected: dict[tuple[str, str, int, str, str], InspectedSource] = {}

    @property
    def inspected_sources(self) -> tuple[InspectedSource, ...]:
        """本次尝试查看过的定位。测试与排查用；接纳只从它里面取。"""
        return tuple(self._inspected.values())

    def accepted_artifact(self, reference: str) -> ArtifactRef | None:
        """这次 run 里已经提交过的那一份证据 Artifact，按引用找。

        给重放用：接纳是写，重放不能重写一遍——重复提交会撞上"duplicate artifact ID"，而
        被拒绝的那一次看起来像一次成功的重放。回快照核对效果还在不在，是这里唯一能给的
        诚实答案。
        """
        state = self._committer.repository.load(self._committer.run_id)
        if state is None:
            return None
        return next(
            (
                artifact
                for artifact in state.artifacts
                if artifact.kind == EVIDENCE_ARTIFACT_KIND and artifact.reference == reference
            ),
            None,
        )

    def inspect(
        self, context: RetrievalContext, retrieval_id: str, candidate_id: str
    ) -> SourceInspection:
        """查看一段原文，并把它记进台账。

        角色在这里就挡住：只有 A2 有内部检索权限（规格 15），A3/A4 读的是 A2 接纳的证据。
        """
        self._require_a2(context)
        inspection = self._retrieval.inspect(context, retrieval_id, candidate_id)
        self._inspected[self._key(context, retrieval_id, inspection.chunk_id)] = InspectedSource(
            retrieval_id=retrieval_id,
            chunk_id=inspection.chunk_id,
            document_id=inspection.document_id,
            document_version_id=inspection.document_version_id,
            page_start=inspection.page_start,
            page_end=inspection.page_end,
            section_path=inspection.section_path,
            content_origin=inspection.content_origin,
            requires_verification=inspection.requires_verification,
        )
        return inspection

    def accept(
        self, context: RetrievalContext, *, worker_id: str, evidence: InternalEvidence
    ) -> ArtifactRef:
        """接纳一份内部证据，返回 A3/A4 用来读取它的 `ArtifactRef`。"""
        self._require_a2(context)
        if context.attempt_id < 1:
            raise EvidenceAcceptanceDenied(
                f"attempt {context.attempt_id} cannot belong to a task; an artifact records "
                f"the attempt that produced it"
            )
        task_id = self._task_id(context)
        self._require_current_retrieval(context, evidence.retrieval_id)
        if not evidence.claims:
            raise EvidenceAcceptanceDenied(
                "an evidence artifact must carry at least one claim; an empty one would be "
                "read downstream as 'A2 found nothing' rather than as a mistake"
            )

        claim_rows: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        payload = self._payload(context, evidence)
        artifact_id = uuid5(_NAMESPACE, _digest(payload))
        reference = f"internal-research-evidence:{artifact_id}"
        for index, claim in enumerate(evidence.claims):
            located = self._verified_sources(context, evidence.retrieval_id, claim)
            self._require_grade(claim, located)
            self._require_conflict_metadata(claim, located)
            digest = _digest(claim.model_dump(mode="json"))
            evidence_id = str(uuid5(_NAMESPACE, f"claim/{artifact_id}/{index}/{digest}"))
            claim_rows.append(
                (
                    self._claim_row(
                        evidence_id=evidence_id,
                        context=context,
                        task_id=task_id,
                        reference=reference,
                        retrieval_id=evidence.retrieval_id,
                        claim=claim,
                    ),
                    [
                        self._source_row(evidence_id=evidence_id, order=order, reference=source)
                        for order, source in enumerate(claim.source_refs)
                    ],
                )
            )

        artifact = ArtifactRef(
            artifact_id=artifact_id,
            task_id=task_id,
            attempt=context.attempt_id,
            kind=EVIDENCE_ARTIFACT_KIND,
            reference=reference,
        )
        return self._committer.commit(
            artifact,
            worker_id=worker_id,
            persistence=_EvidenceTables(claim_rows),
            now=self._clock(),
        )

    # --- 授权 ---------------------------------------------------------------

    @staticmethod
    def _require_a2(context: RetrievalContext) -> None:
        if context.role != EVIDENCE_ACCEPTING_ROLE:
            raise EvidenceAcceptanceDenied(
                f"role {context.role!r} may not handle internal research evidence; only "
                f"{EVIDENCE_ACCEPTING_ROLE} may retrieve it and accept it"
            )

    @staticmethod
    def _task_id(context: RetrievalContext) -> UUID:
        try:
            return UUID(context.task_id)
        except ValueError as exc:
            raise EvidenceAcceptanceDenied(
                f"task {context.task_id!r} is not an orchestration task ID"
            ) from exc

    def _require_current_retrieval(self, context: RetrievalContext, retrieval_id: str) -> None:
        """这次检索必须属于调用方自己的 run、任务与尝试。

        规格 19：旧 attempt 的迟到结果全部拒绝。一份在上一轮基础上提取出来的证据，它的前提
        ——问题、预算、语料——可能已经不同，接纳它等于让上一轮悄悄替这一轮说话。
        """
        audit = self._repository.get_retrieval_audit(retrieval_id)
        if audit is None:
            raise EvidenceAcceptanceDenied(f"no retrieval is recorded under {retrieval_id!r}")
        if (audit.run_id, audit.task_id, audit.attempt_id) != (
            context.run_id,
            context.task_id,
            context.attempt_id,
        ):
            raise RetrievalAccessDenied(
                f"retrieval {retrieval_id!r} belongs to run {audit.run_id!r} task "
                f"{audit.task_id!r} attempt {audit.attempt_id}, not to task "
                f"{context.task_id!r} attempt {context.attempt_id}"
            )

    # --- 出处 ---------------------------------------------------------------

    def _verified_sources(
        self, context: RetrievalContext, retrieval_id: str, claim: InternalEvidenceClaim
    ) -> tuple[InspectedSource, ...]:
        located: list[InspectedSource] = []
        for reference in claim.source_refs:
            entry = self._inspected.get(self._key(context, retrieval_id, reference.chunk_id))
            if entry is None:
                raise UninspectedSource(
                    f"chunk {reference.chunk_id!r} was never inspected in this attempt of "
                    f"{context.task_id!r}; a candidate that was returned by search has not "
                    f"been read, and a chunk from elsewhere in the corpus was never offered"
                )
            moved = entry.located_as(reference)
            if moved is not None:
                raise LocatorMismatch(
                    f"the citation moves {moved} to {getattr(reference, moved)!r}, but this "
                    f"chunk was inspected as {getattr(entry, moved)!r}"
                )
            if reference.bounding_boxes:
                raise LocatorMismatch(
                    "the inspection did not hand out bounding boxes for this chunk; a "
                    "citation may only carry locators that were actually handed out"
                )
            self._require_in_force(entry)
            located.append(entry)
        return tuple(located)

    def _require_in_force(self, entry: InspectedSource) -> None:
        """查看时在架的那一版，接纳时还得在架。

        规格 16.3：删除立刻生效，已经发出的引用不能变成绕过它的通道。一份在查看之后被
        替换或删除的资料，它的原文已经从语料里退出，而这条证据是照着它写的。
        """
        document = self._repository.get_document(entry.document_id)
        if document is None or document.deleted_at is not None:
            raise SourceWithdrawn(
                f"document {entry.document_id!r} is deleted; evidence written against it may "
                f"not be accepted"
            )
        statuses = self._repository.load_version_statuses([entry.document_version_id])
        if statuses.get(entry.document_version_id) is not DocumentVersionStatus.ACTIVE:
            raise SourceWithdrawn(
                f"version {entry.document_version_id!r} is no longer ACTIVE; it was replaced "
                f"between the inspection and the acceptance"
            )

    # --- 等级与冲突状态 ------------------------------------------------------

    @staticmethod
    def _require_grade(claim: InternalEvidenceClaim, located: Sequence[InspectedSource]) -> None:
        """规格 14 第 5 条：等级是推出来的，只能往低了说。

        申报得更高，等于用一份内容扛起它挣不到的信用；申报得更低只是保守，而保守不需要
        被拦住。
        """
        available = weakest_grade([entry.grade() for entry in located])
        if _GRADE_ORDER[claim.grade] > _GRADE_ORDER[available]:
            raise EvidenceGradeMismatch(
                f"grade {claim.grade} is stronger than the inspected content justifies; at "
                f"most {available} is available for these sources"
            )
        if (
            any(entry.requires_verification for entry in located)
            and not claim.requires_verification
        ):
            raise EvidenceGradeMismatch(
                "the cited content requires_verification; the claim must carry the flag, not "
                "only the lowered grade"
            )

    @staticmethod
    def _require_conflict_metadata(
        claim: InternalEvidenceClaim, located: Sequence[InspectedSource]
    ) -> None:
        """判不了的和没查成的，都必须看得出来。"""
        if claim.conflict_status is ConflictStatus.CHECK_FAILED and not claim.requires_verification:
            raise UnsupportedDeterministicClaim(
                "a CHECK_FAILED conflict means the check did not finish; recording it as a "
                "settled claim would read to everyone downstream as 'there is no conflict'"
            )
        if claim.conflict_status is not ConflictStatus.UNRESOLVED:
            return
        if claim.requires_verification:
            return
        if len({entry.chunk_id for entry in located}) < 2:
            raise UnsupportedDeterministicClaim(
                "an UNRESOLVED claim must carry the sources of both conflicting facts, from "
                "two different chunks; the same passage cited twice is one side"
            )

    # --- 行 ------------------------------------------------------------------

    def _claim_row(
        self,
        *,
        evidence_id: str,
        context: RetrievalContext,
        task_id: UUID,
        reference: str,
        retrieval_id: str,
        claim: InternalEvidenceClaim,
    ) -> dict[str, Any]:
        return {
            "evidence_id": evidence_id,
            "run_id": context.run_id,
            "task_id": str(task_id),
            "artifact_ref": reference,
            "retrieval_id": retrieval_id,
            # 领域载荷里的事实没有 ID：`ExtractedClaim.claim_id` 属于抽取阶段，而这里提交的是
            # A2 采纳之后的事实。列留给将来把两者连起来的那一天，现在不编一个填进去。
            "claim_id": None,
            "statement": claim.statement,
            "stance": ClaimStance(claim.stance).value,
            "conflict_status": claim.conflict_status.value,
            "grade": claim.grade.value,
            "requires_verification": int(claim.requires_verification),
            "qualifiers_json": json.dumps(list(claim.qualifiers), ensure_ascii=False),
            "created_at": self._clock().isoformat(),
        }

    @staticmethod
    def _source_row(
        *, evidence_id: str, order: int, reference: EvidenceSourceRef
    ) -> dict[str, Any]:
        return {
            "evidence_id": evidence_id,
            "source_order": order,
            "document_id": reference.document_id,
            "document_version_id": reference.document_version_id,
            "chunk_id": reference.chunk_id,
            "page_start": reference.page_start,
            "page_end": reference.page_end,
            "section_path_json": json.dumps(list(reference.section_path), ensure_ascii=False),
            # 核对过的定位里没有包围盒（`SourceInspection` 不提供），因此到这里只能是空的；
            # `_verified_sources` 已经把非空的挡在前面。
            "bounding_boxes_json": "[]",
        }

    # --- 身份 ---------------------------------------------------------------

    @staticmethod
    def _payload(context: RetrievalContext, evidence: InternalEvidence) -> dict[str, Any]:
        return {
            "run_id": context.run_id,
            "task_id": context.task_id,
            "attempt_id": context.attempt_id,
            "retrieval_id": evidence.retrieval_id,
            "claims": [claim.model_dump(mode="json") for claim in evidence.claims],
        }

    @staticmethod
    def _key(
        context: RetrievalContext, retrieval_id: str, chunk_id: str
    ) -> tuple[str, str, int, str, str]:
        return (
            context.run_id,
            context.task_id,
            context.attempt_id,
            retrieval_id,
            chunk_id,
        )


def _digest(payload: Any) -> str:
    """载荷的规范摘要。

    `sort_keys` 与紧凑分隔符一起去掉"同样的内容、不同的字节"这件事，而 `ensure_ascii=False`
    让中文不因转义而膨胀；三者合起来保证同一个载荷永远得到同一个 ID。
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
