"""Accepted internal evidence: what A2 may hand to A3/A4, and what it may not (spec 15.2, 19).

This is the boundary where something a model produced becomes something the rest of the pipeline
is allowed to quote. Four properties are only observable over real components:

- The business rows (`internal_research_evidence`, `internal_research_evidence_sources`), the
  `ArtifactRef` and the orchestration event have to commit in one transaction, and the only way to
  see that is to make one of them fail and then look for the others.
- "Inspect before accepting" is a claim about what happened *earlier in the attempt*, so it needs a
  server-side record of inspections; a test that hands the service a citation cannot distinguish
  "inspected" from "returned by search".
- The evidence grade is a *derived* fact (spec 14 rule 5, `conflicts.evidence_grade`), so a test has
  to compare what was declared against what the inspected content actually justifies.
- The locator written to the sources table has to be the one the inspection handed out, not the one
  the caller typed, or the row would locate a page nobody read.

The SQLite database is the real one (migrations included), because the foreign key to
`research_retrieval_audits` and the check constraints on the sources table are part of the contract.
The research library itself runs on the in-memory repository: there is no SQLite implementation of
`ResearchLibraryRepositoryPort` yet, so the audit row the retrieval service produces is mirrored
into SQLite by `seed_audit`, which copies the record the service actually wrote rather than
inventing one.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.tasks import TaskOwnershipError
from sector_pulse.application.research_library.artifacts import (
    AcceptInternalEvidenceService,
    EvidenceAcceptanceDenied,
    EvidenceGradeMismatch,
    InspectedSource,
    LocatorMismatch,
    SourceWithdrawn,
    UninspectedSource,
    UnsupportedDeterministicClaim,
)
from sector_pulse.application.research_library.cache import CorpusGeneration
from sector_pulse.application.research_library.retrieval import (
    ResearchRetrievalService,
    RetrievalAccessDenied,
    RetrievalContext,
    SourceInspection,
)
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.orchestration.models import (
    ArtifactRef,
    BudgetLimits,
    RunSnapshot,
    TaskRecord,
    TaskStatus,
)
from sector_pulse.domain.research_library.models import (
    ChunkType,
    DocumentType,
    DocumentVersionStatus,
    ExtractionMethod,
    ResearchChunk,
    ResearchDocument,
    ResearchDocumentVersion,
    SourceLocator,
)
from sector_pulse.domain.research_library.retrieval import (
    ClaimStance,
    ConflictStatus,
    EvidenceGrade,
    EvidenceSourceRef,
    InternalEvidence,
    InternalEvidenceClaim,
    RetrievalQuery,
)
from sector_pulse.infrastructure.research_library.providers.fixture import (
    FixtureEmbeddingProvider,
    FixtureRerankerProvider,
)
from sector_pulse.infrastructure.research_library.vector.memory import InMemoryVectorIndex
from sector_pulse.ports.vector_index import VectorRecord
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

from backend.tests.research_library_fakes import InMemoryResearchLibraryRepository

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
PUBLISHED = date(2026, 6, 1)
GENERATION = "gen_2026_09_18"
QUESTION = "储能海外需求"
CORPUS_TEXT = "储能海外需求在 2026 年上半年同比增长 42%，欧洲市场贡献了主要增量，美国市场持平。"
SECOND_TEXT = "储能海外需求的价格战集中在 2025 年下半年，主要厂商毛利率下滑 3 个百分点。"
VECTOR = (1.0, 0.0, 0.0, 0.0)
WORKER = "worker-1"
KIND = "internal_research_evidence"


def settings(**overrides: Any) -> RagSettings:
    base: dict[str, Any] = {
        "dense_top_k": 3,
        "bm25_top_k": 3,
        "fusion_top_k": 4,
        "rerank_top_k": 3,
        "max_candidates_per_document": 3,
        "duplicate_overlap_ratio": 0.8,
        "max_candidate_text_chars": 200,
        "max_inspected_chars": 400,
        "max_parent_expansion_chunks": 2,
    }
    return RagSettings(**(base | overrides))


@dataclass(frozen=True)
class _Doc:
    chunk_id: str
    text: str
    document_id: str = "doc_0001"
    version_id: str = "ver_0001"
    version_number: int = 1
    page: int = 18
    section: tuple[str, ...] = ("海外需求",)
    status: DocumentVersionStatus = DocumentVersionStatus.ACTIVE
    content_origin: ExtractionMethod = ExtractionMethod.NATIVE
    requires_verification: bool = False


@dataclass
class _Harness:
    """A published corpus, a live A2 task, and the acceptance service over both."""

    tmp_path: Any
    lease: timedelta = timedelta(minutes=5)
    worker_id: str = WORKER
    config: RagSettings = field(default_factory=settings)
    docs: list[_Doc] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.database = SQLiteDatabase(self.tmp_path / "internal_evidence.db")
        self.database.initialize()
        self.orchestration = SQLiteOrchestrationRepository(self.database)
        self.run_id = uuid4()
        self.root_id = uuid4()
        self.task_id = uuid4()
        root = TaskRecord(task_id=self.root_id, role="A0", scope="run")
        self.child = TaskRecord(
            task_id=self.task_id,
            parent_id=self.root_id,
            role="A2",
            scope="industry:1",
            status=TaskStatus.RUNNING,
            worker_id=self.worker_id,
            lease_expires_at=NOW + self.lease,
        )
        self.snapshot = RunSnapshot(
            run_id=self.run_id,
            limits=BudgetLimits(max_tool_calls=50, max_cny=Decimal("10.00")),
            deadline=NOW + timedelta(minutes=30),
            tasks=(root, self.child),
        )
        self.orchestration.save(self.snapshot, -1, "created")

        self.repository = InMemoryResearchLibraryRepository()
        self.index = InMemoryVectorIndex()
        self.retrieval = ResearchRetrievalService(
            repository=self.repository,
            vector_index=self.index,
            embedding_provider=FixtureEmbeddingProvider(
                dimension=len(VECTOR), vectors={QUESTION: VECTOR}
            ),
            reranker=FixtureRerankerProvider(),
            settings=self.config,
            corpus_generation=CorpusGeneration(self.repository),
            clock=lambda: NOW,
        )
        self.committer = AtomicArtifactCommitter(self.orchestration, self.run_id)
        self.service = AcceptInternalEvidenceService(
            retrieval=self.retrieval,
            repository=self.repository,
            committer=self.committer,
            clock=lambda: NOW,
        )

    # --- 语料 ---

    def publish(self, *docs: _Doc) -> None:
        self.docs.extend(docs)
        for document_id in dict.fromkeys(doc.document_id for doc in self.docs):
            if self.repository.get_document(document_id) is not None:
                continue
            self.repository.create_document(
                ResearchDocument(
                    document_id=document_id,
                    title=f"{document_id} 标题",
                    document_type=DocumentType.REPORT,
                    source_weight=Decimal("0.5"),
                    created_at=NOW,
                )
            )
        for version_id in dict.fromkeys(doc.version_id for doc in self.docs):
            group = [doc for doc in self.docs if doc.version_id == version_id]
            head = group[0]
            if self.repository.get_version(version_id) is not None:
                continue
            self.repository.create_version(
                ResearchDocumentVersion(
                    document_version_id=version_id,
                    document_id=head.document_id,
                    version_number=head.version_number,
                    status=head.status,
                    published_at=NOW if head.status is DocumentVersionStatus.ACTIVE else None,
                    uploaded_at=NOW,
                    original_file_hash=f"hash_{version_id}",
                    index_generation=GENERATION,
                    expected_chunk_count=len(group),
                    indexed_at=NOW,
                )
            )
            self.repository.append_chunks(tuple(self._chunk(doc) for doc in group))
        records = [
            self._record(doc) for doc in self.docs if doc.status is DocumentVersionStatus.ACTIVE
        ]
        if records:
            self.index.stage(generation=GENERATION, records=records)
            self.index.publish(generation=GENERATION)

    def _chunk(self, doc: _Doc) -> ResearchChunk:
        return ResearchChunk(
            chunk_id=doc.chunk_id,
            document_id=doc.document_id,
            document_version_id=doc.version_id,
            chunk_type=ChunkType.TEXT,
            content=doc.text,
            content_hash=f"hash_{doc.chunk_id}",
            source=SourceLocator(page_start=doc.page, page_end=doc.page, section_path=doc.section),
            content_origin=doc.content_origin,
            requires_verification=doc.requires_verification,
            created_at=NOW,
        )

    def _record(self, doc: _Doc) -> VectorRecord:
        return VectorRecord(
            chunk_id=doc.chunk_id,
            document_id=doc.document_id,
            document_version_id=doc.version_id,
            chunk_type=ChunkType.TEXT,
            document_type=DocumentType.REPORT,
            published_at=datetime(PUBLISHED.year, PUBLISHED.month, PUBLISHED.day, tzinfo=UTC),
            content_origin=doc.content_origin,
            content=doc.text,
            dense_vector=VECTOR,
        )

    # --- 上下文 ---

    def context(self, *, role: str = "A2", attempt_id: int = 1) -> RetrievalContext:
        return RetrievalContext(
            run_id=str(self.run_id), task_id=str(self.task_id), attempt_id=attempt_id, role=role
        )

    # --- 用 ---

    def search(self, context: RetrievalContext, *, leads: bool = False) -> Any:
        return self.retrieval.search(
            context, RetrievalQuery(question=QUESTION, include_unverified_leads=leads)
        )

    def seed_audit(self, retrieval_id: str) -> None:
        """把这次检索的审计行写进 SQLite。

        来源是检索服务自己写进内存仓库的那一条，因此字段与生产一致；只有一个实现能把它
        落进 SQL 的地方——PostgreSQL 仓库——而这里跑的是 SQLite。来源表的外键指着这张表，
        所以它必须在。
        """
        audit = self.repository.get_retrieval_audit(retrieval_id)
        assert audit is not None, "every search must leave an audit record behind"
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO research_retrieval_audits (retrieval_id, run_id, task_id, "
                "attempt_id, role, question, query_fingerprint, filters_json, corpus_generation, "
                "provider_versions_json, returned_evidence_json, created_at) VALUES "
                "(:retrieval_id, :run_id, :task_id, :attempt_id, :role, :question, "
                ":query_fingerprint, :filters, :corpus_generation, :versions, :returned, "
                ":created_at)",
                {
                    "retrieval_id": audit.retrieval_id,
                    "run_id": audit.run_id,
                    "task_id": audit.task_id,
                    "attempt_id": audit.attempt_id,
                    "role": audit.role,
                    "question": audit.question,
                    "query_fingerprint": audit.query_fingerprint,
                    "filters": json.dumps(audit.filters, ensure_ascii=False),
                    "corpus_generation": audit.corpus_generation,
                    "versions": json.dumps(audit.provider_versions, ensure_ascii=False),
                    "returned": json.dumps(
                        [dict(entry) for entry in audit.returned_evidence], ensure_ascii=False
                    ),
                    "created_at": audit.created_at.isoformat(),
                },
            )

    def inspect(self, context: RetrievalContext, retrieval_id: str, candidate_id: str) -> Any:
        return self.service.inspect(context, retrieval_id, candidate_id)

    def candidate(self, context: RetrievalContext, index: int = 0, *, leads: bool = False) -> Any:
        outcome = self.search(context, leads=leads)
        self.seed_audit(outcome.retrieval_id)
        return outcome.retrieval_id, outcome.candidates[index]

    def source(self, inspection: Any) -> EvidenceSourceRef:
        return EvidenceSourceRef(
            document_id=inspection.document_id,
            document_version_id=inspection.document_version_id,
            chunk_id=inspection.chunk_id,
            page_start=inspection.page_start,
            page_end=inspection.page_end,
            section_path=inspection.section_path,
        )

    # --- 读 ---

    def rows(self, table: str, columns: str = "*") -> list[tuple[Any, ...]]:
        with self.database.connection() as connection:
            return list(connection.execute(f"SELECT {columns} FROM {table}"))

    def evidence_rows(self) -> list[tuple[Any, ...]]:
        return self.rows(
            "internal_research_evidence",
            "evidence_id, run_id, task_id, artifact_ref, retrieval_id, claim_id, statement, "
            "stance, conflict_status, grade, requires_verification, qualifiers_json, created_at",
        )

    def source_rows(self) -> list[tuple[Any, ...]]:
        return self.rows(
            "internal_research_evidence_sources",
            "evidence_id, source_order, document_id, document_version_id, chunk_id, "
            "page_start, page_end, section_path_json",
        )

    def events(self) -> list[tuple[int, str]]:
        return self.orchestration.events(self.run_id)

    def artifacts(self) -> tuple[ArtifactRef, ...]:
        loaded = self.orchestration.load(self.run_id)
        assert loaded is not None
        return loaded.artifacts


def harness(tmp_path: Any, *docs: _Doc, **kwargs: Any) -> _Harness:
    built = _Harness(tmp_path=tmp_path, **kwargs)
    built.publish(*(docs or (_Doc(chunk_id="c_1", text=CORPUS_TEXT),)))
    return built


def claim(
    *,
    statement: str = "海外储能需求在第二季度改善",
    stance: ClaimStance = ClaimStance.SUPPORTING,
    conflict_status: ConflictStatus = ConflictStatus.RESOLVED,
    grade: EvidenceGrade = EvidenceGrade.PRIMARY_SOURCE,
    requires_verification: bool = False,
    sources: Sequence[EvidenceSourceRef] = (),
    qualifiers: Sequence[str] = (),
) -> InternalEvidenceClaim:
    return InternalEvidenceClaim(
        statement=statement,
        stance=stance,
        conflict_status=conflict_status,
        source_refs=tuple(sources),
        grade=grade,
        requires_verification=requires_verification,
        qualifiers=tuple(qualifiers),
    )


def evidence(retrieval_id: str, *claims: InternalEvidenceClaim) -> InternalEvidence:
    return InternalEvidence(retrieval_id=retrieval_id, claims=tuple(claims))


def accepted(
    harness_: _Harness,
    *,
    context: RetrievalContext | None = None,
    index: int = 0,
    leads: bool = False,
) -> tuple[RetrievalContext, str, SourceInspection, EvidenceSourceRef]:
    """Search, inspect the first candidate, and build its source ref."""
    context = context or harness_.context()
    retrieval_id, candidate = harness_.candidate(context, index, leads=leads)
    inspection = harness_.inspect(context, retrieval_id, candidate.candidate_id)
    return context, retrieval_id, inspection, harness_.source(inspection)


# --- 接纳一条证据留下了什么 --------------------------------------------------


def test_accepting_evidence_returns_an_artifact_of_the_declared_kind(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, inspection, source = accepted(harness_)

    artifact = harness_.service.accept(
        context,
        worker_id=WORKER,
        evidence=evidence(retrieval_id, claim(sources=[source])),
    )

    assert artifact.kind == KIND
    assert artifact.task_id == harness_.task_id
    assert artifact.attempt == 1
    assert artifact.reference.startswith("internal-research-evidence:")
    assert artifact in harness_.artifacts()


def test_the_claim_and_its_sources_are_written_with_the_identity_of_the_run(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, inspection, source = accepted(harness_)

    artifact = harness_.service.accept(
        context,
        worker_id=WORKER,
        evidence=evidence(
            retrieval_id,
            claim(
                statement="海外储能需求在第二季度改善",
                stance=ClaimStance.SUPPORTING,
                conflict_status=ConflictStatus.RESOLVED,
                qualifiers=["口径：同比"],
                sources=[source],
            ),
        ),
    )

    rows = harness_.evidence_rows()
    assert len(rows) == 1
    (
        evidence_id,
        run_id,
        task_id,
        artifact_ref,
        stored_retrieval_id,
        _claim_id,
        statement,
        stance,
        conflict_status,
        grade,
        requires_verification,
        qualifiers_json,
        created_at,
    ) = rows[0]
    assert (run_id, task_id) == (str(harness_.run_id), str(harness_.task_id))
    assert artifact_ref == artifact.reference
    assert stored_retrieval_id == retrieval_id
    assert statement == "海外储能需求在第二季度改善"
    assert stance == "supporting"
    assert conflict_status == "RESOLVED"
    assert grade == "PRIMARY_SOURCE"
    assert requires_verification == 0
    assert json.loads(qualifiers_json) == ["口径：同比"]
    assert created_at == NOW.isoformat()

    sources = harness_.source_rows()
    assert len(sources) == 1
    assert sources[0][0] == evidence_id
    assert sources[0][1] == 0


def test_the_source_row_locates_what_the_inspection_handed_out_not_what_was_typed(
    tmp_path: Any,
) -> None:
    harness_ = harness(tmp_path, _Doc(chunk_id="c_1", text=CORPUS_TEXT, page=18))
    context, retrieval_id, inspection, source = accepted(harness_)

    harness_.service.accept(
        context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
    )

    (
        _evidence_id,
        source_order,
        document_id,
        document_version_id,
        chunk_id,
        page_start,
        page_end,
        section_path_json,
    ) = harness_.source_rows()[0]
    assert (document_id, document_version_id, chunk_id) == (
        inspection.document_id,
        inspection.document_version_id,
        inspection.chunk_id,
    )
    assert (page_start, page_end) == (18, 18)
    assert json.loads(section_path_json) == ["海外需求"]
    assert source_order == 0


def test_two_claims_share_one_artifact_and_keep_their_own_order(tmp_path: Any) -> None:
    harness_ = harness(
        tmp_path,
        _Doc(chunk_id="c_1", text=CORPUS_TEXT, page=18, section=("海外需求", "欧洲")),
        _Doc(chunk_id="c_2", text=SECOND_TEXT, page=19, section=("海外需求", "欧洲")),
    )
    context = harness_.context()
    outcome = harness_.search(context)
    harness_.seed_audit(outcome.retrieval_id)
    first = harness_.inspect(context, outcome.retrieval_id, outcome.candidates[0].candidate_id)
    second = harness_.inspect(context, outcome.retrieval_id, outcome.candidates[1].candidate_id)

    artifact = harness_.service.accept(
        context,
        worker_id=WORKER,
        evidence=evidence(
            outcome.retrieval_id,
            claim(sources=[harness_.source(first)]),
            claim(statement="价格战集中在 2025 年下半年", sources=[harness_.source(second)]),
        ),
    )

    rows = harness_.evidence_rows()
    assert len(rows) == 2
    assert {row[3] for row in rows} == {artifact.reference}
    assert len({row[0] for row in rows}) == 2, "each claim gets its own evidence id"
    sources = harness_.source_rows()
    assert sorted(row[1] for row in sources) == [0, 0], "source_order restarts per claim"
    assert {row[0] for row in sources} == {row[0] for row in rows}


def test_the_retrieval_that_produced_the_evidence_is_recorded_on_every_claim(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    harness_.service.accept(
        context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
    )

    assert {row[4] for row in harness_.evidence_rows()} == {retrieval_id}


def test_accepting_the_same_evidence_twice_is_refused_rather_than_stored_twice(
    tmp_path: Any,
) -> None:
    """证据的身份由内容决定，不由一次计数器决定：同样的接纳再来一次是重放，不是新证据。"""
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)
    payload = evidence(retrieval_id, claim(sources=[source]))

    harness_.service.accept(context, worker_id=WORKER, evidence=payload)
    with pytest.raises(ValueError, match="duplicate artifact ID"):
        harness_.service.accept(context, worker_id=WORKER, evidence=payload)

    assert len(harness_.evidence_rows()) == 1
    assert len(harness_.artifacts()) == 1


def test_the_artifact_and_the_event_arrive_in_the_same_commit(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    harness_.service.accept(
        context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
    )

    assert len(harness_.artifacts()) == 1
    assert harness_.evidence_rows()
    events = harness_.events()
    assert [event for _revision, event in events] == [
        "created",
        f"artifact.committed:{harness_.artifacts()[0].artifact_id}",
    ]


def test_the_orchestration_snapshot_never_carries_the_document_body(tmp_path: Any) -> None:
    """规格 15.2：快照里放的是 ArtifactRef，不是证据本身，更不是被引用的正文。"""
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    harness_.service.accept(
        context,
        worker_id=WORKER,
        evidence=evidence(retrieval_id, claim(sources=[source])),
    )

    loaded = harness_.orchestration.load(harness_.run_id)
    assert loaded is not None
    written = json.dumps(loaded.model_dump(mode="json"), ensure_ascii=False)
    assert CORPUS_TEXT not in written
    assert CORPUS_TEXT[:12] not in written
    assert len(written) < 6000


def test_the_inspection_ledger_keeps_locators_and_not_text(tmp_path: Any) -> None:
    """账本记的是"这一段被看过、它的定位是什么"，不是正文。

    留住正文等于把已经离开检索的那一份内容再存一份，而它没有保留期：进程活着，它就活着。
    """
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, _source = accepted(harness_)

    ledger = harness_.service.inspected_sources
    assert ledger, "an inspection must be remembered, or acceptance could not require one"
    assert all(isinstance(entry, InspectedSource) for entry in ledger)
    written = json.dumps([entry.model_dump(mode="json") for entry in ledger], ensure_ascii=False)
    assert CORPUS_TEXT not in written
    assert CORPUS_TEXT[:12] not in written


def test_neither_the_evidence_rows_nor_the_sources_keep_the_document_body(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    harness_.service.accept(
        context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
    )

    written = json.dumps(
        {
            "evidence": [list(row) for row in harness_.evidence_rows()],
            "sources": [list(row) for row in harness_.source_rows()],
        },
        ensure_ascii=False,
    )
    assert CORPUS_TEXT not in written
    assert CORPUS_TEXT[:12] not in written


# --- 谁能接纳、什么时候能接纳 ------------------------------------------------


def test_a_role_that_is_not_a2_cannot_accept_internal_evidence(tmp_path: Any) -> None:
    """规格 15：A2 是唯一具有内部检索权限的专业 Agent，A3/A4 只能读它接纳的证据。"""
    harness_ = harness(tmp_path)
    a2 = harness_.context()
    retrieval_id, _candidate = harness_.candidate(a2)
    inspection = harness_.inspect(a2, retrieval_id, _candidate.candidate_id)
    source = harness_.source(inspection)

    with pytest.raises(EvidenceAcceptanceDenied, match="A2"):
        harness_.service.accept(
            harness_.context(role="A3"),
            worker_id=WORKER,
            evidence=evidence(retrieval_id, claim(sources=[source])),
        )

    assert harness_.evidence_rows() == []


def test_a_role_that_is_not_a2_cannot_inspect_either(tmp_path: Any) -> None:
    """查看原文也是 A2 的权限。只挡住接纳，等于把原文的读口留给了所有角色。"""
    harness_ = harness(tmp_path)
    context = harness_.context()
    retrieval_id, candidate = harness_.candidate(context)

    with pytest.raises(EvidenceAcceptanceDenied, match="A2"):
        harness_.service.inspect(harness_.context(role="A4"), retrieval_id, candidate.candidate_id)

    assert harness_.service.inspected_sources == ()


def test_evidence_from_another_run_is_refused(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)
    other = RetrievalContext(
        run_id=str(uuid4()), task_id=str(harness_.task_id), attempt_id=1, role="A2"
    )

    with pytest.raises(RetrievalAccessDenied):
        harness_.service.accept(
            other, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
        )

    assert harness_.evidence_rows() == []


def test_evidence_from_another_task_is_refused(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)
    other = RetrievalContext(
        run_id=str(harness_.run_id), task_id=str(uuid4()), attempt_id=1, role="A2"
    )

    with pytest.raises(RetrievalAccessDenied):
        harness_.service.accept(
            other, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
        )

    assert harness_.evidence_rows() == []


def test_a_retrieval_from_an_earlier_attempt_cannot_be_accepted(tmp_path: Any) -> None:
    """规格 19：旧 attempt 的迟到结果全部拒绝——包括一份在它上面提取出来的证据。"""
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    with pytest.raises((RetrievalAccessDenied, UninspectedSource)):
        harness_.service.accept(
            harness_.context(attempt_id=2),
            worker_id=WORKER,
            evidence=evidence(retrieval_id, claim(sources=[source])),
        )

    assert harness_.evidence_rows() == []


def test_an_inspection_from_an_earlier_attempt_does_not_satisfy_the_retry(tmp_path: Any) -> None:
    """重试会重新检索，但模型可能把上一轮写过的那条引用原样再交一次。

    这条引用在重试里没有落脚点：它是**上一次检索**的查看记录，而重试拿到的是另一次检索。
    即使重试又召回了同一段，那一段也得在这一轮重新被看过——前提（问题、预算、语料）可能已经
    不同，"上一轮看过"不是这一轮读过原文的依据。
    """
    harness_ = harness(tmp_path)
    first = harness_.context()
    first_retrieval, candidate = harness_.candidate(first)
    inspection = harness_.inspect(first, first_retrieval, candidate.candidate_id)
    source = harness_.source(inspection)

    retry = harness_.context(attempt_id=2)
    retry_retrieval, again = harness_.candidate(retry)
    assert again.chunk_id == inspection.chunk_id, "the retry found the same passage again"

    with pytest.raises(UninspectedSource, match=inspection.chunk_id):
        harness_.service.accept(
            retry, worker_id=WORKER, evidence=evidence(retry_retrieval, claim(sources=[source]))
        )

    assert harness_.evidence_rows() == []


def test_an_attempt_that_stopped_owning_the_task_cannot_commit(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)
    current = harness_.orchestration.load(harness_.run_id)
    assert current is not None
    advanced = current.model_copy(
        update={
            "revision": current.revision + 1,
            "tasks": tuple(
                task.model_copy(update={"attempt": task.attempt + 1})
                if task.task_id == harness_.task_id
                else task
                for task in current.tasks
            ),
        }
    )
    harness_.orchestration.save(advanced, current.revision, "retried")

    with pytest.raises(TaskOwnershipError, match="stale task attempt"):
        harness_.service.accept(
            context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
        )

    assert harness_.evidence_rows() == []


def test_an_expired_lease_cannot_commit_evidence(tmp_path: Any) -> None:
    harness_ = harness(tmp_path, lease=timedelta(seconds=-1))
    context, retrieval_id, _inspection, source = accepted(harness_)

    with pytest.raises(TaskOwnershipError, match="lease"):
        harness_.service.accept(
            context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
        )

    assert harness_.evidence_rows() == []


def test_a_worker_that_does_not_own_the_task_cannot_commit_evidence(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    with pytest.raises(TaskOwnershipError, match="own"):
        harness_.service.accept(
            context, worker_id="worker-9", evidence=evidence(retrieval_id, claim(sources=[source]))
        )

    assert harness_.evidence_rows() == []


# --- 伪造的引用与没看过的候选 -------------------------------------------------


def test_a_chunk_that_was_never_returned_is_refused(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, inspection, _source = accepted(harness_)
    forged = EvidenceSourceRef(
        document_id=inspection.document_id,
        document_version_id=inspection.document_version_id,
        chunk_id="c_never_returned",
    )

    with pytest.raises(UninspectedSource, match="c_never_returned"):
        harness_.service.accept(
            context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[forged]))
        )

    assert harness_.evidence_rows() == []


def test_a_returned_candidate_that_was_never_inspected_cannot_be_adopted(tmp_path: Any) -> None:
    """规格 15.2：A2 必须先 inspect 再接纳。检索结果里的摘要是线索，不是读过的原文。"""
    harness_ = harness(
        tmp_path,
        _Doc(chunk_id="c_1", text=CORPUS_TEXT),
        _Doc(chunk_id="c_2", text=SECOND_TEXT, page=19),
    )
    context = harness_.context()
    outcome = harness_.search(context)
    harness_.seed_audit(outcome.retrieval_id)
    inspected = outcome.candidates[0]
    unread = next(
        candidate for candidate in outcome.candidates if candidate.chunk_id != inspected.chunk_id
    )
    harness_.inspect(context, outcome.retrieval_id, inspected.candidate_id)

    with pytest.raises(UninspectedSource, match=unread.chunk_id):
        harness_.service.accept(
            context,
            worker_id=WORKER,
            evidence=evidence(
                outcome.retrieval_id,
                claim(
                    sources=[
                        EvidenceSourceRef(
                            document_id=unread.document_id,
                            document_version_id=unread.document_version_id,
                            chunk_id=unread.chunk_id,
                        )
                    ]
                ),
            ),
        )

    assert harness_.evidence_rows() == []


def test_a_citation_that_moves_the_page_range_is_refused(tmp_path: Any) -> None:
    harness_ = harness(tmp_path, _Doc(chunk_id="c_1", text=CORPUS_TEXT, page=18))
    context, retrieval_id, _inspection, source = accepted(harness_)
    shifted = source.model_copy(update={"page_start": 4, "page_end": 4})

    with pytest.raises(LocatorMismatch, match="page"):
        harness_.service.accept(
            context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[shifted]))
        )

    assert harness_.evidence_rows() == []


def test_a_citation_that_names_another_version_is_refused(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)
    rewritten = source.model_copy(update={"document_version_id": "ver_0002"})

    with pytest.raises(LocatorMismatch):
        harness_.service.accept(
            context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[rewritten]))
        )

    assert harness_.evidence_rows() == []


def test_a_citation_that_widens_the_section_path_is_refused(tmp_path: Any) -> None:
    harness_ = harness(tmp_path, _Doc(chunk_id="c_1", text=CORPUS_TEXT, section=("海外需求",)))
    context, retrieval_id, _inspection, source = accepted(harness_)
    widened = source.model_copy(update={"section_path": ("海外需求", "欧洲市场")})

    with pytest.raises(LocatorMismatch):
        harness_.service.accept(
            context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[widened]))
        )

    assert harness_.evidence_rows() == []


def test_a_citation_that_adds_a_locator_the_inspection_never_handed_out_is_refused(
    tmp_path: Any,
) -> None:
    """出处只能带查看时真的交出来的定位。

    包围盒这一列在库里，但 `SourceInspection` 不发包围盒，因此到这里只能是空的。放行一个
    没人交出来的定位，等于让引用自己声明它指到了哪一块——而没有任何东西能核对它。
    """
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)
    invented = source.model_copy(update={"bounding_boxes": ((1.0, 2.0, 3.0, 4.0),)})

    with pytest.raises(LocatorMismatch, match="bounding"):
        harness_.service.accept(
            context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[invented]))
        )

    assert harness_.evidence_rows() == []


def test_a_source_that_stopped_being_active_between_inspection_and_acceptance_is_refused(
    tmp_path: Any,
) -> None:
    """规格 16.3：删除立刻生效，已经发出的引用不能变成绕过它的通道。"""
    harness_ = harness(
        tmp_path,
        _Doc(chunk_id="c_1", text=CORPUS_TEXT, version_id="ver_0001"),
        _Doc(
            chunk_id="c_9",
            text=SECOND_TEXT,
            version_id="ver_0002",
            version_number=2,
            status=DocumentVersionStatus.PROCESSING,
            page=19,
        ),
    )
    context, retrieval_id, _inspection, source = accepted(harness_)
    harness_.repository.activate_version(
        "ver_0002", expected_status=DocumentVersionStatus.PROCESSING
    )

    with pytest.raises(SourceWithdrawn, match="ACTIVE"):
        harness_.service.accept(
            context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
        )

    assert harness_.evidence_rows() == []


def test_a_source_in_a_deleted_document_is_refused(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)
    harness_.repository.soft_delete_document("doc_0001", now=NOW, retention_days=30)

    with pytest.raises(SourceWithdrawn, match="deleted"):
        harness_.service.accept(
            context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
        )

    assert harness_.evidence_rows() == []


# --- 等级与冲突状态：不许声称自己没挣到的东西 --------------------------------


def test_a_grade_the_content_does_not_justify_is_refused(tmp_path: Any) -> None:
    """规格 14 第 5 条：等级是从内容来源推出来的，不是申报出来的。

    OCR 出来的文字申报成原生文本，等于在一场按证据质量排序的裁决里悄悄升了一档。
    """
    harness_ = harness(
        tmp_path,
        _Doc(chunk_id="c_1", text=CORPUS_TEXT, content_origin=ExtractionMethod.OCR),
    )
    context, retrieval_id, _inspection, source = accepted(harness_)

    with pytest.raises(EvidenceGradeMismatch, match="PRIMARY_SOURCE"):
        harness_.service.accept(
            context,
            worker_id=WORKER,
            evidence=evidence(
                retrieval_id,
                claim(
                    grade=EvidenceGrade.PRIMARY_SOURCE,
                    sources=[source],
                ),
            ),
        )

    assert harness_.evidence_rows() == []


def test_content_marked_for_verification_cannot_be_declared_a_primary_source(
    tmp_path: Any,
) -> None:
    """待核验的内容要 A2 明确索取才会被检索出来，而它一路都只能是线索。"""
    harness_ = harness(
        tmp_path,
        _Doc(chunk_id="c_1", text=CORPUS_TEXT, requires_verification=True),
    )
    context, retrieval_id, _inspection, source = accepted(harness_, leads=True)

    with pytest.raises(EvidenceGradeMismatch, match="DERIVED_UNVERIFIED"):
        harness_.service.accept(
            context,
            worker_id=WORKER,
            evidence=evidence(
                retrieval_id,
                claim(
                    grade=EvidenceGrade.PRIMARY_SOURCE,
                    requires_verification=False,
                    sources=[source],
                ),
            ),
        )

    assert harness_.evidence_rows() == []


def test_content_marked_for_verification_is_accepted_when_it_says_so(tmp_path: Any) -> None:
    harness_ = harness(tmp_path, _Doc(chunk_id="c_1", text=CORPUS_TEXT, requires_verification=True))
    context, retrieval_id, _inspection, source = accepted(harness_, leads=True)

    harness_.service.accept(
        context,
        worker_id=WORKER,
        evidence=evidence(
            retrieval_id,
            claim(
                grade=EvidenceGrade.DERIVED_UNVERIFIED,
                requires_verification=True,
                sources=[source],
            ),
        ),
    )

    row = harness_.evidence_rows()[0]
    assert (row[9], row[10]) == ("DERIVED_UNVERIFIED", 1)


def test_an_unresolved_claim_citing_the_same_chunk_twice_is_refused(tmp_path: Any) -> None:
    """规格 14：UNRESOLVED 必须保留双方事实和来源。

    只留一方的载荷根本构造不出来——`InternalEvidence` 的校验器要求至少两条 `source_refs`。
    但"至少两条"数的是列表长度，同一段话写两遍就够了，而那不是双方：一份单一来源的事实
    会被读成两条互证的事实。因此这一层数的是**不同的切片**。
    """
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    with pytest.raises(UnsupportedDeterministicClaim, match="UNRESOLVED"):
        harness_.service.accept(
            context,
            worker_id=WORKER,
            evidence=evidence(
                retrieval_id,
                claim(conflict_status=ConflictStatus.UNRESOLVED, sources=[source, source]),
            ),
        )

    assert harness_.evidence_rows() == []


def test_an_unresolved_claim_with_two_inspected_sources_is_accepted(tmp_path: Any) -> None:
    harness_ = harness(
        tmp_path,
        _Doc(chunk_id="c_1", text=CORPUS_TEXT, page=18),
        _Doc(chunk_id="c_2", text=SECOND_TEXT, page=19),
    )
    context = harness_.context()
    outcome = harness_.search(context)
    harness_.seed_audit(outcome.retrieval_id)
    sources = [
        harness_.source(harness_.inspect(context, outcome.retrieval_id, candidate.candidate_id))
        for candidate in outcome.candidates
    ]

    harness_.service.accept(
        context,
        worker_id=WORKER,
        evidence=evidence(
            outcome.retrieval_id,
            claim(conflict_status=ConflictStatus.UNRESOLVED, sources=sources),
        ),
    )

    assert len(harness_.source_rows()) == 2
    assert harness_.evidence_rows()[0][8] == "UNRESOLVED"


def test_an_unresolved_claim_marked_for_verification_may_keep_one_side(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    harness_.service.accept(
        context,
        worker_id=WORKER,
        evidence=evidence(
            retrieval_id,
            claim(
                conflict_status=ConflictStatus.UNRESOLVED,
                requires_verification=True,
                grade=EvidenceGrade.DERIVED_UNVERIFIED,
                sources=[source],
            ),
        ),
    )

    assert harness_.evidence_rows()[0][8] == "UNRESOLVED"


def test_a_check_that_did_not_finish_cannot_be_recorded_as_settled(tmp_path: Any) -> None:
    """Task 13 把"检查没做成"与"检查做完了，没有冲突"分得很开。

    一份 CHECK_FAILED 的证据不带核验标记地交出去，读到它的人只会看到一条被接纳的事实。
    """
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    with pytest.raises(UnsupportedDeterministicClaim, match="CHECK_FAILED"):
        harness_.service.accept(
            context,
            worker_id=WORKER,
            evidence=evidence(
                retrieval_id,
                claim(conflict_status=ConflictStatus.CHECK_FAILED, sources=[source]),
            ),
        )

    assert harness_.evidence_rows() == []


def test_a_check_that_did_not_finish_is_accepted_once_it_carries_the_flag(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    harness_.service.accept(
        context,
        worker_id=WORKER,
        evidence=evidence(
            retrieval_id,
            claim(
                conflict_status=ConflictStatus.CHECK_FAILED,
                requires_verification=True,
                grade=EvidenceGrade.DERIVED_UNVERIFIED,
                sources=[source],
            ),
        ),
    )

    assert harness_.evidence_rows()[0][8] == "CHECK_FAILED"


def test_an_acceptance_without_any_claim_is_refused(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, _source = accepted(harness_)

    with pytest.raises(EvidenceAcceptanceDenied, match="claim"):
        harness_.service.accept(context, worker_id=WORKER, evidence=evidence(retrieval_id))

    assert harness_.evidence_rows() == []
    assert harness_.artifacts() == ()


# --- 原子性 -------------------------------------------------------------------


def test_an_audit_that_is_not_in_the_store_takes_the_whole_acceptance_with_it(
    tmp_path: Any,
) -> None:
    """业务行、ArtifactRef 与事件在同一个事务里：外键挡住的那一次，什么也不该留下。"""
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)
    with harness_.database.transaction() as connection:
        connection.execute(
            "DELETE FROM research_retrieval_audits WHERE retrieval_id=:id", {"id": retrieval_id}
        )

    with pytest.raises(Exception) as raised:
        harness_.service.accept(
            context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
        )

    assert "FOREIGN KEY" in str(raised.value).upper()
    assert harness_.evidence_rows() == []
    assert harness_.artifacts() == ()


def test_a_row_the_database_rejects_takes_the_earlier_claims_with_it(tmp_path: Any) -> None:
    """第二条事实被库里的 CHECK 拦下时，第一条已经写进去的行必须一起消失。

    一份只写了一半的证据比没有证据更糟：它看上去是一条完整的事实，而它的另一半不见了。
    出处的每一种偏差都能在上层拦住，所以这里用一条**库能拦而这一层不管**的坏数据——空白
    事实——把事务边界逼出来：`min_length=1` 放它进来，`length(trim(statement)) > 0` 拦它
    出去，而走到那里时第一条事实的正文与出处都已经写过了。
    """
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    with pytest.raises(Exception) as raised:
        harness_.service.accept(
            context,
            worker_id=WORKER,
            evidence=evidence(
                retrieval_id,
                claim(sources=[source]),
                claim(statement=" ", sources=[source]),
            ),
        )

    assert "CHECK" in str(raised.value).upper()
    assert harness_.evidence_rows() == []
    assert harness_.source_rows() == []
    assert harness_.artifacts() == ()


def test_an_attempt_number_that_cannot_belong_to_a_task_is_refused(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    a2 = harness_.context()
    retrieval_id, candidate = harness_.candidate(a2)
    inspection = harness_.inspect(a2, retrieval_id, candidate.candidate_id)

    with pytest.raises(EvidenceAcceptanceDenied, match="attempt"):
        harness_.service.accept(
            harness_.context(attempt_id=0),
            worker_id=WORKER,
            evidence=evidence(retrieval_id, claim(sources=[harness_.source(inspection)])),
        )

    assert harness_.evidence_rows() == []


def test_the_task_id_in_the_context_must_be_the_task_that_owns_the_run(tmp_path: Any) -> None:
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    with pytest.raises(EvidenceAcceptanceDenied, match="task"):
        harness_.service.accept(
            RetrievalContext(
                run_id=str(harness_.run_id), task_id="not-a-uuid", attempt_id=1, role="A2"
            ),
            worker_id=WORKER,
            evidence=evidence(retrieval_id, claim(sources=[source])),
        )

    assert harness_.evidence_rows() == []


def test_the_artifact_id_is_derived_from_the_run_and_the_payload(tmp_path: Any) -> None:
    """身份来自内容：同一个 run 里同样的证据得到同一个 ID，所以重放只会撞上自己。"""
    harness_ = harness(tmp_path)
    context, retrieval_id, _inspection, source = accepted(harness_)

    artifact = harness_.service.accept(
        context, worker_id=WORKER, evidence=evidence(retrieval_id, claim(sources=[source]))
    )

    assert UUID(str(artifact.artifact_id)).version == 5
    assert artifact.reference == f"internal-research-evidence:{artifact.artifact_id}"


def test_a_retrieval_under_another_retrieval_cannot_be_cited(tmp_path: Any) -> None:
    """看过的是哪一次检索的哪一段：另一次检索里出现过同一个切片，不算这一次看过。"""
    harness_ = harness(tmp_path)
    context = harness_.context()
    first = harness_.search(context)
    harness_.seed_audit(first.retrieval_id)
    inspection = harness_.inspect(context, first.retrieval_id, first.candidates[0].candidate_id)
    source = harness_.source(inspection)
    with harness_.database.transaction() as connection:
        connection.execute("DELETE FROM research_retrieval_audits")

    second = harness_.search(context)
    harness_.seed_audit(second.retrieval_id)
    assert second.retrieval_id != first.retrieval_id

    with pytest.raises(UninspectedSource, match=inspection.chunk_id):
        harness_.service.accept(
            context,
            worker_id=WORKER,
            evidence=evidence(second.retrieval_id, claim(sources=[source])),
        )

    assert harness_.evidence_rows() == []


# --- 等级取所引来源里最弱的一档 ------------------------------------------------


def test_a_claim_leaning_on_a_weaker_source_cannot_claim_the_stronger_grade(
    tmp_path: Any,
) -> None:
    """一条事实同时踩着原生文本和一页 OCR 时，它挣到的是两档里低的那一档。

    取最强的那个，等于用最体面的那一份来源替整条事实背书。
    """
    harness_ = harness(
        tmp_path,
        _Doc(chunk_id="c_1", text=CORPUS_TEXT, page=18),
        _Doc(
            chunk_id="c_2",
            text=SECOND_TEXT,
            page=19,
            content_origin=ExtractionMethod.OCR,
        ),
    )
    context = harness_.context()
    outcome = harness_.search(context)
    harness_.seed_audit(outcome.retrieval_id)
    sources = [
        harness_.source(harness_.inspect(context, outcome.retrieval_id, candidate.candidate_id))
        for candidate in outcome.candidates
    ]

    with pytest.raises(EvidenceGradeMismatch, match="PARSED_STRUCTURE"):
        harness_.service.accept(
            context,
            worker_id=WORKER,
            evidence=evidence(
                outcome.retrieval_id,
                claim(grade=EvidenceGrade.PRIMARY_SOURCE, sources=sources),
            ),
        )
    assert harness_.evidence_rows() == []

    harness_.service.accept(
        context,
        worker_id=WORKER,
        evidence=evidence(
            outcome.retrieval_id,
            claim(grade=EvidenceGrade.PARSED_STRUCTURE, sources=sources),
        ),
    )
    assert harness_.evidence_rows()[0][9] == "PARSED_STRUCTURE"


def test_content_that_needs_verification_must_say_so_on_the_claim(tmp_path: Any) -> None:
    """等级被压低只是结果，标记本身也要跟着走：A3/A4 看的是标记。"""
    harness_ = harness(tmp_path, _Doc(chunk_id="c_1", text=CORPUS_TEXT, requires_verification=True))
    context, retrieval_id, _inspection, source = accepted(harness_, leads=True)

    with pytest.raises(EvidenceGradeMismatch, match="requires_verification"):
        harness_.service.accept(
            context,
            worker_id=WORKER,
            evidence=evidence(
                retrieval_id,
                claim(grade=EvidenceGrade.DERIVED_UNVERIFIED, sources=[source]),
            ),
        )

    assert harness_.evidence_rows() == []
