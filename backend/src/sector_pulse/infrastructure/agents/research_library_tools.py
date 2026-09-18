"""A2 的内部研究三件工具（规格 15.2）。

三件工具都拿在服务端绑定的 `BoundSectorResearchContext` 上：跑哪个 run、哪个任务、哪一次
尝试、哪个板块，一个都不由模型填。模型能表达的只有"问什么"与"看了哪一段"，其余参数一律
**拒绝**而不是忽略——忽略一个 `sector` 会让一次越界的检索看起来像一次正常调用。

有界是这三件工具共同的形状，边界都落在交出内容的那一层：候选摘要被
`max_candidate_text_chars` 截断，原文查看被 `max_inspected_chars` 截断，一次接纳的条数有上限。
这里再截一次不是重复：上限来自服务配置，而"这份输出不会超过多少"是工具自己的承诺。

不接受的对象：对象键、下载地址、存储凭证，以及这一次任务没检索过的切片。`inspect` 只认
当前任务这次尝试里检索过、且被那次审计记下来的候选句柄；拿一个别处的 chunk ID 过来，得到
的是"这次检索没有发出过这个句柄"，而不是一段原文。

重放（`replay`）走的是权威库而不是 Provider：一次重复的检索不该再问一次 Embedding 与
Reranker，而候选的正文本来就在权威库里。审计里记的只有句柄与定位（规格 20.1），所以重放
时按句柄回库取正文——取不到就如实报错，不编一段。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from aidynamic_agent.tools.base import Tool, ToolResult

from sector_pulse.application.orchestration.research_context import BoundSectorResearchContext
from sector_pulse.application.research_library.artifacts import (
    EVIDENCE_ACCEPTING_ROLE,
    AcceptInternalEvidenceService,
    EvidenceAcceptanceDenied,
    EvidenceGradeMismatch,
    LocatorMismatch,
    SourceWithdrawn,
    UninspectedSource,
    UnsupportedDeterministicClaim,
)
from sector_pulse.application.research_library.conflicts import evidence_grade
from sector_pulse.application.research_library.retrieval import (
    CandidateWithdrawn,
    ResearchRetrievalService,
    RetrievalAccessDenied,
    RetrievalContext,
    RetrievalNotFound,
    UnknownCandidate,
)
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.domain.research_library.models import DocumentType, DocumentVersionStatus
from sector_pulse.domain.research_library.retrieval import (
    InternalEvidence,
    InternalEvidenceClaim,
    RetrievalQuery,
    RetrievedCandidate,
    TimeRange,
)
from sector_pulse.storage.ports.research_library import ResearchLibraryRepositoryPort

__all__ = [
    "AcceptInternalEvidenceTool",
    "InspectResearchSourceTool",
    "SearchInternalResearchTool",
]

#: 结果引用的三段前缀。句柄与定位都在引用里，正文一个都不在。
SEARCH_REFERENCE_PREFIX = "internal-research-search:"
SOURCE_REFERENCE_PREFIX = "internal-research-source:"
EVIDENCE_REFERENCE_PREFIX = "internal-research-evidence:"

_SEARCH_ARGUMENTS = frozenset(
    {"question", "companies", "document_types", "time_range", "include_unverified_leads"}
)
_INSPECT_ARGUMENTS = frozenset({"retrieval_id", "candidate_id"})
_ACCEPT_ARGUMENTS = frozenset({"retrieval_id", "claims"})

#: 模型能一次带进来的量。上限写在工具自己的 schema 里，也写在这里：schema 约束的是会填
#: 参数的模型，这里约束的是所有调用方。
MAX_QUESTION_CHARS = 300
MAX_COMPANIES = 8
MAX_DOCUMENT_TYPES = 4
MAX_CLAIMS = 12

_SERVER_CONTROLLED = (
    "run, task, attempt, role, worker, sector and library scope are server controlled"
)


def _retrieval_context(context: BoundSectorResearchContext) -> RetrievalContext:
    """把服务端绑定上下文投影成一次检索的身份。

    角色写成常量而不是字面量：接纳服务要求的角色与这里声明的角色必须是同一个值，否则
    "A2 检索、A2 接纳"会变成两处各自维护的说法。
    """
    return RetrievalContext(
        run_id=str(context.run_id),
        task_id=str(context.task_id),
        attempt_id=context.attempt,
        role=EVIDENCE_ACCEPTING_ROLE,
    )


def _retrieval_query(kwargs: Mapping[str, object], *, sector: str) -> RetrievalQuery:
    """把模型给的键翻成一次检索请求。

    板块取自绑定上下文，不取自参数：规格 11.1 的请求里有 `sector`，而能填它的只有服务端。
    """
    question = kwargs.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be non-empty text")
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"question must fit in {MAX_QUESTION_CHARS} characters")
    companies = kwargs.get("companies", ())
    if not isinstance(companies, (list, tuple)) or len(companies) > MAX_COMPANIES:
        raise ValueError(f"companies must be a list of at most {MAX_COMPANIES} names")
    if any(not isinstance(company, str) or not company.strip() for company in companies):
        raise ValueError("companies must be non-empty text")
    document_types = kwargs.get("document_types", ())
    if not isinstance(document_types, (list, tuple)) or len(document_types) > MAX_DOCUMENT_TYPES:
        raise ValueError(f"document_types must be a list of at most {MAX_DOCUMENT_TYPES} values")
    try:
        types = tuple(DocumentType(value) for value in document_types)
    except ValueError as exc:
        raise ValueError("document_types contains an unknown document type") from exc
    leads = kwargs.get("include_unverified_leads", False)
    if not isinstance(leads, bool):
        raise ValueError("include_unverified_leads must be a boolean")
    window = kwargs.get("time_range")
    if window is not None and not isinstance(window, Mapping):
        raise ValueError("time_range must be an object with from and to")
    return RetrievalQuery(
        question=question,
        sector=sector,
        companies=tuple(companies),
        document_types=types,
        time_range=None if window is None else TimeRange.model_validate(window),
        include_unverified_leads=leads,
    )


def _candidate_payload(candidate: RetrievedCandidate, *, limit: int) -> dict[str, Any]:
    """一条候选的安全摘要：定位、等级与有界正文。

    等级是**推出来**的（规格 14 第 5 条），不是模型自己说的：待核验一律降到最低一档，
    不论它的正文出自原生解析还是 OCR。
    """
    return {
        "candidate_id": candidate.candidate_id,
        "chunk_id": candidate.chunk_id,
        "document_id": candidate.document_id,
        "document_version_id": candidate.document_version_id,
        "page_start": candidate.page_start,
        "page_end": candidate.page_end,
        "section_path": list(candidate.section_path),
        "grade": evidence_grade(
            content_origin=candidate.content_origin,
            requires_verification=candidate.requires_verification,
        ).value,
        "requires_verification": candidate.requires_verification,
        "text": candidate.text[:limit],
    }


class SearchInternalResearchTool(Tool):
    """受控的内部资料库检索：候选、定位、等级，正文有界。"""

    name = "search_internal_research"
    description = (
        "Search the internal research library for the current server-bound sector. "
        "Returns bounded candidate excerpts with their locators and evidence grade."
    )
    tags = ["A2", "internal_research", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "minLength": 2, "maxLength": MAX_QUESTION_CHARS},
            "companies": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 64},
                "maxItems": MAX_COMPANIES,
            },
            "document_types": {
                "type": "array",
                "items": {"type": "string", "enum": [item.value for item in DocumentType]},
                "maxItems": MAX_DOCUMENT_TYPES,
            },
            "time_range": {
                "type": "object",
                "properties": {
                    "from": {"type": "string", "format": "date"},
                    "to": {"type": "string", "format": "date"},
                },
                "required": ["from", "to"],
                "additionalProperties": False,
            },
            "include_unverified_leads": {"type": "boolean"},
        },
        "required": ["question"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: ResearchRetrievalService,
        *,
        repository: ResearchLibraryRepositoryPort,
        context: BoundSectorResearchContext,
        settings: RagSettings,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._repository = repository
        self._context = context
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) - _SEARCH_ARGUMENTS:
            raise ValueError(_SERVER_CONTROLLED)
        if "question" not in kwargs:
            raise ValueError("question is required")
        query = _retrieval_query(kwargs, sector=self._context.sector_name)
        outcome = self._service.search(_retrieval_context(self._context), query)
        return self._result(outcome.retrieval_id, outcome.query_fingerprint, outcome.candidates)

    def replay(self, reference: str) -> ToolResult:
        """按审计回库重放：句柄与定位来自审计，正文来自权威库。

        正文读的是**现在**的权威库，所以"这条候选现在还作数吗"必须在这一次读的时候重新问
        一遍。审计记的是当时的结果；从那以后资料可能被软删除、被新版本取代、或者被清理。
        `inspect` 每次都会问（`CandidateWithdrawn`），重放问的是同一个问题——答案记在审计
        里，不等于它今天还成立。少了这一问，被撤回的正文会沿着重放继续递给模型，而其他每
        一条读路径都已经拒绝它了。
        """
        if not reference.startswith(SEARCH_REFERENCE_PREFIX):
            raise ValueError("invalid internal research search reference")
        retrieval_id = reference[len(SEARCH_REFERENCE_PREFIX) :]
        audit = self._repository.get_retrieval_audit(retrieval_id)
        if audit is None:
            raise KeyError("persisted retrieval is unavailable")
        entries = [(str(entry["chunk_id"]), entry) for entry in audit.returned_evidence]
        chunks = {}
        for chunk_id, _ in entries:
            chunk = self._repository.get_chunk(chunk_id)
            if chunk is None:
                raise KeyError("persisted retrieval candidate is unavailable")
            chunks[chunk_id] = chunk
        # 状态一次问完，不按候选各问一遍：同一次检索的候选通常落在少数几个版本里。
        statuses = self._repository.load_version_statuses(
            [chunk.document_version_id for chunk in chunks.values()]
        )
        candidates: list[RetrievedCandidate] = []
        for chunk_id, entry in entries:
            chunk = chunks[chunk_id]
            if statuses.get(chunk.document_version_id) is not DocumentVersionStatus.ACTIVE:
                raise CandidateWithdrawn(
                    f"replayed candidate {chunk_id!r} belongs to version "
                    f"{chunk.document_version_id!r}, which is no longer ACTIVE"
                )
            candidates.append(
                RetrievedCandidate.model_validate(
                    {**entry, "retrieval_id": retrieval_id, "text": chunk.content}
                )
            )
        return self._result(retrieval_id, audit.query_fingerprint, tuple(candidates))

    def _result(
        self,
        retrieval_id: str,
        query_fingerprint: str,
        candidates: tuple[RetrievedCandidate, ...],
    ) -> ToolResult:
        limit = self._settings.max_candidate_text_chars
        return ToolResult(
            content=json.dumps(
                {
                    "retrieval_id": retrieval_id,
                    "query_fingerprint": query_fingerprint,
                    "candidates": [
                        _candidate_payload(candidate, limit=limit) for candidate in candidates
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            metadata={"result_reference": f"{SEARCH_REFERENCE_PREFIX}{retrieval_id}"},
        )


class InspectResearchSourceTool(Tool):
    """查看当前任务检索过的候选原文；不认别处的 chunk ID。"""

    name = "inspect_research_source"
    description = (
        "Read a bounded excerpt of one candidate this task retrieved from the internal "
        "research library. The candidate must come from the retrieval id you were given."
    )
    tags = ["A2", "internal_research", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "retrieval_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "candidate_id": {"type": "string", "minLength": 1, "maxLength": 128},
        },
        "required": ["retrieval_id", "candidate_id"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: AcceptInternalEvidenceService,
        *,
        context: BoundSectorResearchContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._context = context
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != _INSPECT_ARGUMENTS:
            raise ValueError(_SERVER_CONTROLLED)
        retrieval_id = _identifier(kwargs["retrieval_id"], "retrieval_id")
        candidate_id = _identifier(kwargs["candidate_id"], "candidate_id")
        return self._inspect(retrieval_id, candidate_id)

    def replay(self, reference: str) -> ToolResult:
        """重放一次查看：不花 Provider 调用，也不越过账本。

        `inspect` 本身是幂等的（账本按 `(run, task, attempt, retrieval, chunk)` 记账），
        因此重放走的就是原路径——它读的是权威库，不是某次网络往返。
        """
        if not reference.startswith(SOURCE_REFERENCE_PREFIX):
            raise ValueError("invalid internal research source reference")
        parts = reference[len(SOURCE_REFERENCE_PREFIX) :].split(":", 1)
        if len(parts) != 2:
            raise ValueError("invalid internal research source reference")
        return self._inspect(parts[0], parts[1])

    def _inspect(self, retrieval_id: str, candidate_id: str) -> ToolResult:
        try:
            inspection = self._service.inspect(
                _retrieval_context(self._context), retrieval_id, candidate_id
            )
        except (
            RetrievalAccessDenied,
            RetrievalNotFound,
            UnknownCandidate,
            CandidateWithdrawn,
        ) as exc:
            return ToolResult(content="", success=False, error=str(exc))
        return ToolResult(
            content=json.dumps(
                {
                    "retrieval_id": inspection.retrieval_id,
                    "candidate_id": inspection.candidate_id,
                    "chunk_id": inspection.chunk_id,
                    "document_id": inspection.document_id,
                    "document_version_id": inspection.document_version_id,
                    "page_start": inspection.page_start,
                    "page_end": inspection.page_end,
                    "section_path": list(inspection.section_path),
                    "parent_texts": list(inspection.parent_texts),
                    "grade": evidence_grade(
                        content_origin=inspection.content_origin,
                        requires_verification=inspection.requires_verification,
                    ).value,
                    "requires_verification": inspection.requires_verification,
                    "truncated": inspection.truncated,
                    "text": inspection.text,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            metadata={
                "result_reference": f"{SOURCE_REFERENCE_PREFIX}{retrieval_id}:{candidate_id}"
            },
        )


class AcceptInternalEvidenceTool(Tool):
    """接纳一份内部证据，交出 A3/A4 读得到的 `ArtifactRef`。"""

    name = "accept_internal_evidence"
    description = (
        "Submit accepted internal research evidence for this run. Every source you cite must "
        "have been inspected first, and its grade must not be stronger than that content "
        "supports."
    )
    tags = ["A2", "internal_research", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "retrieval_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "claims": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_CLAIMS,
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string", "minLength": 1, "maxLength": 500},
                        "stance": {
                            "type": "string",
                            "enum": ["supporting", "opposing", "neutral"],
                        },
                        "conflict_status": {
                            "type": "string",
                            "enum": ["RESOLVED", "NOT_CONFLICT", "UNRESOLVED", "CHECK_FAILED"],
                        },
                        "grade": {
                            "type": "string",
                            "enum": ["PRIMARY_SOURCE", "PARSED_STRUCTURE", "DERIVED_UNVERIFIED"],
                        },
                        "requires_verification": {"type": "boolean"},
                        "qualifiers": {"type": "array", "items": {"type": "string"}},
                        "source_refs": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 6,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "document_id": {"type": "string", "minLength": 1},
                                    "document_version_id": {"type": "string", "minLength": 1},
                                    "chunk_id": {"type": "string", "minLength": 1},
                                    "page_start": {"type": "integer", "minimum": 1},
                                    "page_end": {"type": "integer", "minimum": 1},
                                    "section_path": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": [
                                    "document_id",
                                    "document_version_id",
                                    "chunk_id",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["statement", "conflict_status", "grade", "source_refs"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["retrieval_id", "claims"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: AcceptInternalEvidenceService,
        *,
        context: BoundSectorResearchContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._context = context
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != _ACCEPT_ARGUMENTS:
            raise ValueError(_SERVER_CONTROLLED)
        retrieval_id = _identifier(kwargs["retrieval_id"], "retrieval_id")
        evidence = _internal_evidence(retrieval_id, kwargs["claims"])
        try:
            artifact = self._service.accept(
                _retrieval_context(self._context),
                worker_id=self._context.worker_id,
                evidence=evidence,
            )
        except (
            EvidenceAcceptanceDenied,
            RetrievalAccessDenied,
            UninspectedSource,
            LocatorMismatch,
            SourceWithdrawn,
            EvidenceGradeMismatch,
            UnsupportedDeterministicClaim,
        ) as exc:
            return ToolResult(content="", success=False, error=str(exc))
        return self._result(artifact)

    def replay(self, reference: str) -> ToolResult:
        """重放一次接纳：只认这次 run 真的提交过的那一份 Artifact。

        接纳是写操作，重放不能重写一遍——重复提交会撞上"duplicate artifact ID"，而被拒绝
        的那一次看起来像一次成功的重放。因此这里回快照核对效果还在不在。
        """
        artifact = self._service.accepted_artifact(reference)
        if artifact is None:
            raise KeyError("persisted internal research evidence is unavailable")
        return self._result(artifact)

    @staticmethod
    def _result(artifact: ArtifactRef) -> ToolResult:
        return ToolResult(
            content=json.dumps(
                {
                    "artifact_ref": artifact.reference,
                    "artifact_id": str(artifact.artifact_id),
                    "kind": artifact.kind,
                    "task_id": str(artifact.task_id),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            metadata={"result_reference": artifact.reference},
        )


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _internal_evidence(retrieval_id: str, claims: object) -> InternalEvidence:
    """把模型提交的载荷翻成领域模型。

    校验交给领域模型（`InternalEvidence` 与自己那一串校验器），这里只多做一件事：把一次
    载荷错误报成**一句话**，而不是把整段 payload 抄进错误消息里——工具的错误会进日志。
    """
    if not isinstance(claims, (list, tuple)) or not claims:
        raise ValueError("claims must be a non-empty list")
    if len(claims) > MAX_CLAIMS:
        raise ValueError(f"at most {MAX_CLAIMS} claims may be submitted at once")
    if any(not isinstance(claim, Mapping) for claim in claims):
        raise ValueError("every claim must be an object")
    try:
        return InternalEvidence(
            retrieval_id=retrieval_id,
            claims=tuple(InternalEvidenceClaim.model_validate(claim) for claim in claims),
        )
    except ValueError as exc:
        raise ValueError(f"the submitted claims are not a valid evidence payload: {exc}") from exc
