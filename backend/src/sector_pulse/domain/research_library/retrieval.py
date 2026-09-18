"""检索、事实与冲突裁决的值模型。

检索请求里没有 Top-K、collection 名或任意过滤条件：召回规模由服务配置决定，
Agent 只能表达“问什么”，不能表达“多宽地捞”。这一点靠 `extra="forbid"` 在模型层
拒绝，而不是靠调用方自觉。
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from sector_pulse.domain.research_library.models import (
    BoundingBox,
    DocumentType,
    ExtractionMethod,
    Record,
    SourceSpan,
)


class ClaimStance(StrEnum):
    SUPPORTING = "supporting"
    OPPOSING = "opposing"
    NEUTRAL = "neutral"


class ConflictStatus(StrEnum):
    RESOLVED = "RESOLVED"
    NOT_CONFLICT = "NOT_CONFLICT"
    UNRESOLVED = "UNRESOLVED"
    CHECK_FAILED = "CHECK_FAILED"


class ConflictRule(StrEnum):
    """规格 14 的裁决优先级，顺序即优先级。"""

    STATUS = "STATUS"
    EXPLICIT_VERSION = "EXPLICIT_VERSION"
    EFFECTIVE_TIME = "EFFECTIVE_TIME"
    SOURCE_WEIGHT = "SOURCE_WEIGHT"
    EVIDENCE_QUALITY = "EVIDENCE_QUALITY"
    RELEVANCE = "RELEVANCE"


class NliRelation(StrEnum):
    ENTAILMENT = "ENTAILMENT"
    CONTRADICTION = "CONTRADICTION"
    NEUTRAL = "NEUTRAL"
    UNCERTAIN = "UNCERTAIN"


class EvidenceGrade(StrEnum):
    PRIMARY_SOURCE = "PRIMARY_SOURCE"
    PARSED_STRUCTURE = "PARSED_STRUCTURE"
    DERIVED_UNVERIFIED = "DERIVED_UNVERIFIED"


class TimeRange(Record):
    """闭区间日期范围；对外 JSON 使用规格里的 `from` / `to`。"""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    start: date = Field(alias="from")
    end: date = Field(alias="to")

    @model_validator(mode="after")
    def _window_is_forward(self) -> Self:
        if self.end < self.start:
            raise ValueError("time_range ends before it starts")
        return self


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str = Field(min_length=1)
    sector: str | None = None
    companies: tuple[str, ...] = ()
    document_types: tuple[DocumentType, ...] = ()
    time_range: TimeRange | None = None
    include_unverified_leads: bool = False

    @model_validator(mode="after")
    def _question_is_meaningful(self) -> Self:
        if not self.question.strip():
            raise ValueError("question must not be blank")
        return self


class RetrievedCandidate(Record):
    """一次检索中返回给 A2 的有界候选，`candidate_id` 是不透明句柄。"""

    candidate_id: str = Field(min_length=1)
    retrieval_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    section_path: tuple[str, ...] = ()
    content_origin: ExtractionMethod
    requires_verification: bool = False
    dense_score: float | None = None
    lexical_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None


class ExtractedClaim(Record):
    """查询期事实；`source_span` 必须精确落在源切片正文里。"""

    claim_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str | None = None
    valid_time: TimeRange | None = None
    qualifiers: tuple[str, ...] = ()
    source_chunk_id: str = Field(min_length=1)
    source_span: SourceSpan
    extraction_confidence: float = Field(ge=0, le=1)
    stance: ClaimStance = ClaimStance.SUPPORTING

    @model_validator(mode="after")
    def _statement_is_meaningful(self) -> Self:
        if not self.statement.strip():
            raise ValueError("statement must not be blank")
        return self


class ConflictDecision(Record):
    """一对可比较事实的裁决结果。

    `UNRESOLVED` 必须保留双方；规则无法判断时不允许悄悄选一个赢家。
    """

    status: ConflictStatus
    claim_ids: tuple[str, ...] = Field(min_length=2)
    rule: ConflictRule | None = None
    selected_claim_id: str | None = None
    nli_relation: NliRelation | None = None
    nli_confidence: float | None = Field(default=None, ge=0, le=1)
    nli_provider: str | None = None
    nli_model_version: str | None = None
    rationale: str | None = None

    @model_validator(mode="after")
    def _selection_is_explicit_and_bounded(self) -> Self:
        if self.selected_claim_id is not None and self.selected_claim_id not in self.claim_ids:
            raise ValueError("the selected claim must be one of claim_ids")
        if self.status is ConflictStatus.RESOLVED:
            if self.rule is None:
                raise ValueError("a RESOLVED conflict must name the rule that decided it")
            if self.selected_claim_id is None:
                raise ValueError("a RESOLVED conflict must select the surviving claim")
        elif self.selected_claim_id is not None:
            raise ValueError(f"a {self.status} conflict must not select a surviving claim")
        return self


class EvidenceSourceRef(Record):
    """最终证据回到原文件的最小定位集合。"""

    document_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    section_path: tuple[str, ...] = ()
    bounding_boxes: tuple[BoundingBox, ...] = ()


class RetrievedEvidence(Record):
    """一条被采用的事实及其冲突状态。"""

    evidence_id: str = Field(min_length=1)
    retrieval_id: str = Field(min_length=1)
    claim: ExtractedClaim
    source_refs: tuple[EvidenceSourceRef, ...] = Field(min_length=1)
    conflict: ConflictDecision
    grade: EvidenceGrade


class InternalEvidenceClaim(Record):
    """A2 提交的内部研究证据条目。"""

    statement: str = Field(min_length=1)
    stance: ClaimStance = ClaimStance.SUPPORTING
    conflict_status: ConflictStatus
    source_refs: tuple[EvidenceSourceRef, ...] = Field(min_length=1)
    grade: EvidenceGrade
    requires_verification: bool = False
    qualifiers: tuple[str, ...] = ()


class InternalEvidence(Record):
    """规格 15.2 的 `internal_research_evidence` Artifact 载荷。"""

    kind: Literal["internal_research_evidence"] = "internal_research_evidence"
    retrieval_id: str = Field(min_length=1)
    claims: tuple[InternalEvidenceClaim, ...] = ()

    @model_validator(mode="after")
    def _unresolved_claims_keep_their_sources(self) -> Self:
        for claim in self.claims:
            if (
                claim.conflict_status is ConflictStatus.UNRESOLVED
                and not claim.requires_verification
                and len(claim.source_refs) < 2
            ):
                raise ValueError(
                    "an UNRESOLVED claim must carry the sources of both conflicting facts"
                )
        return self


class AcceptedEvidenceClaim(Record):
    """从内部证据表读回的一条事实：引用句柄 + 内容。

    `evidence_id` 只在读的时候是一个独立字段。写入时它由接纳服务从内容算出来（规格 15.2），
    A2 无法自己指定；A3/A4 拿它当引用句柄——草稿里的 `evidence_ids` 写的就是它。

    `artifact_ref` 一并带回来，是因为下游要按"这一条属于哪一份 Artifact"分组：草稿既能引用
    某一版证据，也能引用同一 run 里的另一版，两者的可信度不由句柄本身决定。
    """

    evidence_id: str = Field(min_length=1)
    artifact_ref: str = Field(min_length=1)
    claim: InternalEvidenceClaim

    @property
    def document_version_ids(self) -> tuple[str, ...]:
        """这条事实站在哪几版原文上；定位核对按它们逐版进行。"""
        return tuple(dict.fromkeys(ref.document_version_id for ref in self.claim.source_refs))


class RetrievalAuditRecord(Record):
    """规格 20.1 的一次检索审计记录。

    记录的是“这次检索凭什么给出这个答案”：每一段召回的原始名次、被采用的来源切片、
    裁决结果、以及可核对语料版本与 provider 版本的用量。它是排查“答案看着对但来源
    错”的唯一依据，因此只追加、不覆盖。载有名次的字段刻意保持为自由 JSON：它们是
    审计痕迹而非领域决策，由 Task 14 决定最终形态。
    """

    retrieval_id: str = Field(min_length=1)
    run_id: str | None = None
    task_id: str | None = None
    attempt_id: int | None = Field(default=None, ge=0)
    role: str | None = None
    question: str = Field(min_length=1)
    query_fingerprint: str = Field(min_length=1)
    filters: dict[str, object] = Field(default_factory=dict)
    corpus_generation: str = Field(min_length=1)
    provider_versions: dict[str, str] = Field(default_factory=dict)
    dense_candidates: tuple[dict[str, object], ...] = ()
    bm25_candidates: tuple[dict[str, object], ...] = ()
    fused_candidates: tuple[dict[str, object], ...] = ()
    reranked_candidates: tuple[dict[str, object], ...] = ()
    parent_expansions: tuple[dict[str, object], ...] = ()
    claims: tuple[dict[str, object], ...] = ()
    conflicts: tuple[dict[str, object], ...] = ()
    returned_evidence: tuple[dict[str, object], ...] = ()
    duration_ms: int | None = Field(default=None, ge=0)
    provider_calls: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_cny: Decimal | None = Field(default=None, ge=0)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _question_is_meaningful(self) -> Self:
        if not self.question.strip():
            raise ValueError("an audit record must quote the question it answered")
        return self
