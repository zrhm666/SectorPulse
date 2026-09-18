"""A2's internal-research tools: who may call them, and what they can reach (spec 15.2).

Three of the properties under test are only observable over real components:

- "Only A2" is a claim about three separate layers — the role whitelist, the tool factory and
  the acceptance service — so a test that stubs any of them proves nothing about the others.
- "Inspect before accepting" is a claim about a *retrieval audit row*, so the test has to run a
  real retrieval and then try the handles that were not in it, including handles that belong to
  another attempt of the same task.
- "Output is bounded" is a claim about text that leaves the authoritative library, so the test
  compares tool output against the corpus it published rather than against a mock.

The research library runs on the in-memory repository: there is still no SQLite implementation of
`ResearchLibraryRepositoryPort`. The orchestration side is the real SQLite database, because the
artifact the acceptance tool produces has to be committed there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

pytest.importorskip("aidynamic_agent")

from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.research_library.artifacts import AcceptInternalEvidenceService
from sector_pulse.application.research_library.cache import CorpusGeneration
from sector_pulse.application.research_library.retrieval import (
    CandidateWithdrawn,
    ResearchRetrievalService,
)
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.market.candidate import SectorCandidate
from sector_pulse.domain.market.candidate_batch import CandidateBatch, CandidateRankingStage
from sector_pulse.domain.market.candidate_selection import (
    CandidateSelection,
    CandidateSelectionMethod,
)
from sector_pulse.domain.market.market import SectorKind
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
from sector_pulse.domain.runs.time import AnalysisRun
from sector_pulse.infrastructure.agents.composition import (
    RAG_BUSINESS_TOOL_NAMES,
    RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES,
    REQUIRED_BUSINESS_TOOL_NAMES,
    A2BusinessToolFactory,
    A2ResearchLibraryServices,
    A2ToolDependencies,
    AgentBusinessToolFactory,
    CompositeBusinessToolFactory,
)
from sector_pulse.infrastructure.agents.research_library_tools import (
    AcceptInternalEvidenceTool,
    InspectResearchSourceTool,
    SearchInternalResearchTool,
)
from sector_pulse.infrastructure.agents.roles import (
    ROLE_TOOL_NAMES,
    AgentRole,
    AgentToolContext,
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
LONG_TEXT = "储能海外需求" + "长" * 600
VECTOR = (1.0, 0.0, 0.0, 0.0)
WORKER = "worker-1"
REFUSED = "REFUSED"
INTERNAL_TOOLS = (
    "search_internal_research",
    "inspect_research_source",
    "accept_internal_evidence",
)


def settings(**overrides: Any) -> RagSettings:
    base: dict[str, Any] = {
        "dense_top_k": 3,
        "bm25_top_k": 3,
        "fusion_top_k": 4,
        "rerank_top_k": 3,
        "max_candidates_per_document": 3,
        "max_candidate_text_chars": 200,
        "max_inspected_chars": 400,
    }
    return RagSettings(**(base | overrides))


@dataclass(frozen=True)
class _Doc:
    chunk_id: str
    text: str
    document_id: str = "doc_0001"
    version_id: str = "ver_0001"
    page: int = 18
    section: tuple[str, ...] = ("海外需求",)
    status: DocumentVersionStatus = DocumentVersionStatus.ACTIVE
    content_origin: ExtractionMethod = ExtractionMethod.NATIVE
    requires_verification: bool = False


class _CountingEmbedding:
    """Counts provider calls so a replay can be shown to make none."""

    def __init__(self, inner: FixtureEmbeddingProvider) -> None:
        self._inner = inner
        self.calls = 0

    @property
    def model_version(self) -> str:
        return self._inner.model_version

    def embed(self, texts: Any) -> Any:
        self.calls += 1
        return self._inner.embed(texts)


class _Batches:
    """The one candidate batch the A2 research context needs."""

    def __init__(self, batch: CandidateBatch) -> None:
        self._batch = batch

    def get(self, requested_id: UUID) -> CandidateBatch | None:
        return self._batch if requested_id == self._batch.batch_id else None


class _Selections:
    def __init__(self, selection: CandidateSelection) -> None:
        self._selection = selection

    def list_versions(self, run_id: UUID) -> list[CandidateSelection]:
        return [self._selection] if run_id == self._selection.run_id else []


class _Markets:
    def __init__(self, run: AnalysisRun) -> None:
        self._run = run

    def get_run(self, run_id: UUID) -> AnalysisRun | None:
        return self._run if run_id == self._run.run_id else None


@dataclass
class _Harness:
    """A published corpus, a live A2 task, and the three tools over them."""

    tmp_path: Any
    config: RagSettings = field(default_factory=settings)
    docs: list[_Doc] = field(default_factory=list)
    #: 工厂那条路要一份完整的 A2 研究上下文（范围、固定选择版本、候选批次工件、锁定的截止
    #: 时间）。直接构造工具的测试不需要它们，也不该被它们改变——装上就是一个候选批次工件
    #: 会一直躺在快照里，"这次 run 还没有产出工件"那几条断言就不再成立。
    a2_context: bool = False

    def __post_init__(self) -> None:
        self.database = SQLiteDatabase(self.tmp_path / "internal_tools.db")
        self.database.initialize()
        self.orchestration = SQLiteOrchestrationRepository(self.database)
        self.run_id = uuid4()
        self.root_id = uuid4()
        self.task_id = uuid4()
        self.batch_id = uuid4()
        self.batch_artifact_id = uuid4()
        root = TaskRecord(task_id=self.root_id, role="A0", scope="run")
        artifacts: tuple[ArtifactRef, ...] = ()
        scope = "industry:1"
        selection_version: int | None = None
        input_artifact_ids: tuple[UUID, ...] = ()
        if self.a2_context:
            scope = "sector:INDUSTRY:sector-1"
            selection_version = 1
            input_artifact_ids = (self.batch_artifact_id,)
            artifacts = (
                ArtifactRef(
                    artifact_id=self.batch_artifact_id,
                    task_id=self.root_id,
                    kind="candidate_batch",
                    reference=f"candidate-batch:{self.batch_id}",
                ),
            )
        self.child = TaskRecord(
            task_id=self.task_id,
            parent_id=self.root_id,
            role="A2",
            scope=scope,
            status=TaskStatus.RUNNING,
            worker_id=WORKER,
            lease_expires_at=NOW + timedelta(minutes=5),
            input_artifact_ids=input_artifact_ids,
            selection_version=selection_version,
        )
        self.snapshot = RunSnapshot(
            run_id=self.run_id,
            limits=BudgetLimits(max_tool_calls=50, max_cny=Decimal("10.00")),
            deadline=NOW + timedelta(minutes=30),
            tasks=(root, self.child),
            artifacts=artifacts,
        )
        self.orchestration.save(self.snapshot, -1, "created")
        self.batch = CandidateBatch(
            batch_id=self.batch_id,
            run_id=self.run_id,
            input_fingerprint="a" * 64,
            ranking_stage=CandidateRankingStage.NEWS_ENRICHED,
            candidate_limit=12,
            created_at=NOW,
            candidates=(
                SectorCandidate(
                    provider_sector_id="sector-1",
                    kind=SectorKind.INDUSTRY,
                    name="储能",
                    rank=1,
                    score=Decimal("0.91"),
                    reasons=("market",),
                ),
            ),
        )
        self.selection = CandidateSelection(
            run_id=self.run_id,
            version=1,
            selected_sector_ids=("sector-1", "sector-2", "sector-3"),
            method=CandidateSelectionMethod.MANUAL,
            confirmed_at=NOW,
            data_version="b" * 64,
        )
        self.market_run = AnalysisRun.create_live(NOW, self.run_id).lock_live_cutoff(NOW, NOW)

        self.repository = InMemoryResearchLibraryRepository()
        self.index = InMemoryVectorIndex()
        self.embedding = _CountingEmbedding(
            FixtureEmbeddingProvider(dimension=len(VECTOR), vectors={QUESTION: VECTOR})
        )
        self.retrieval = ResearchRetrievalService(
            repository=self.repository,
            vector_index=self.index,
            embedding_provider=self.embedding,
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
                    version_number=1,
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

    # --- 工件 ---

    def bound(self, *, attempt: int = 1) -> Any:
        from sector_pulse.application.orchestration.research_context import (
            BoundSectorResearchContext,
        )

        return BoundSectorResearchContext(
            run_id=self.run_id,
            task_id=self.task_id,
            attempt=attempt,
            worker_id=WORKER,
            sector_id="sector-1",
            sector_kind=SectorKind.INDUSTRY,
            sector_name="储能",
            selection_version=1,
            cutoff_at=NOW,
            input_artifacts=(),
        )

    def search_tool(
        self, *, attempt: int = 1, config: RagSettings | None = None
    ) -> SearchInternalResearchTool:
        return SearchInternalResearchTool(
            self.retrieval,
            repository=self.repository,
            context=self.bound(attempt=attempt),
            settings=self.config if config is None else config,
            clock=lambda: NOW,
        )

    def inspect_tool(self, *, attempt: int = 1) -> InspectResearchSourceTool:
        return InspectResearchSourceTool(
            self.service, context=self.bound(attempt=attempt), clock=lambda: NOW
        )

    def accept_tool(self, *, attempt: int = 1) -> AcceptInternalEvidenceTool:
        return AcceptInternalEvidenceTool(
            self.service, context=self.bound(attempt=attempt), clock=lambda: NOW
        )

    def agent_context(self) -> AgentToolContext:
        """The framework-side context the real A2 builders are called with."""
        return AgentToolContext(
            task_id=self.task_id,
            attempt=1,
            role=AgentRole.A2,
            scope=self.child.scope,
            worker_id=WORKER,
            input_artifact_ids=self.child.input_artifact_ids,
            selection_version=self.child.selection_version,
        )

    def a2_dependencies(self, services: A2ResearchLibraryServices) -> A2ToolDependencies:
        """The real A2 factory dependencies, over this harness's live state."""
        return A2ToolDependencies(
            orchestration=self.orchestration,
            selections=_Selections(self.selection),
            candidate_batches=_Batches(self.batch),
            market_snapshots=_Markets(self.market_run),
            news=object(),
            news_batches=object(),
            research_searches=object(),
            news_details=object(),
            evidence_inspections=object(),
            sector_analyses=object(),
            detail=object(),
            keyword_news=object(),
            research_library=services,
            clock=lambda: NOW,
        )

    def argument(self) -> dict[str, Any]:
        """A well-formed `accept_internal_evidence` argument with one claim."""
        return {
            "retrieval_id": self.retrieval_id,
            "claims": [
                {
                    "statement": "储能海外需求在 2026 年上半年改善",
                    "stance": "supporting",
                    "conflict_status": "RESOLVED",
                    "grade": "PRIMARY_SOURCE",
                    "source_refs": [
                        {
                            "document_id": self.candidate["document_id"],
                            "document_version_id": self.candidate["document_version_id"],
                            "chunk_id": self.candidate["chunk_id"],
                            "page_start": self.candidate["page_start"],
                            "page_end": self.candidate["page_end"],
                            "section_path": list(self.candidate["section_path"]),
                        }
                    ],
                }
            ],
        }

    # --- 用 ---

    def seed_audit(self, retrieval_id: str) -> None:
        """Mirror the audit the retrieval service wrote into the real database.

        The sources table has a foreign key onto `research_retrieval_audits`, and the only
        implementation that writes that table is the PostgreSQL repository.
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

    async def search(self, *, leads: bool = False) -> dict[str, Any]:
        """Run the search tool and keep its first candidate for the assertions after it."""
        tool = self.search_tool()
        result = await tool.execute(question=QUESTION, include_unverified_leads=leads)
        assert result.success, result.error
        payload = json.loads(result.content)
        self.reference = result.metadata["result_reference"]
        self.retrieval_id = payload["retrieval_id"]
        self.candidates = payload["candidates"]
        self.candidate = self.candidates[0]
        self.seed_audit(self.retrieval_id)
        return payload

    async def inspect(self, candidate_id: str | None = None, *, attempt: int = 1) -> Any:
        tool = self.inspect_tool(attempt=attempt)
        return await tool.execute(
            retrieval_id=self.retrieval_id,
            candidate_id=self.candidate["candidate_id"] if candidate_id is None else candidate_id,
        )

    # --- 读 ---

    def snapshot_now(self) -> Any:
        return self.orchestration.load(self.run_id)

    def rows(self, table: str) -> list[tuple[Any, ...]]:
        with self.database.connection() as connection:
            return list(connection.execute(f"SELECT * FROM {table}"))


# --- 检索工具 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_bounded_candidates_with_locators_and_grade(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(
        _Doc(chunk_id="chunk_1", text=CORPUS_TEXT),
        _Doc(
            chunk_id="chunk_2",
            text=SECOND_TEXT,
            document_id="doc_0002",
            version_id="ver_0002",
            page=3,
            section=("价格战",),
            content_origin=ExtractionMethod.OCR,
        ),
    )

    payload = await harness.search()

    assert payload["retrieval_id"].startswith("ret_")
    assert payload["query_fingerprint"]
    assert len(payload["candidates"]) == 2
    first = payload["candidates"][0]
    assert first["candidate_id"].startswith("cand_")
    assert first["chunk_id"]
    assert first["document_id"]
    assert first["document_version_id"]
    assert first["section_path"]
    assert first["grade"] in {"PRIMARY_SOURCE", "PARSED_STRUCTURE", "DERIVED_UNVERIFIED"}
    assert first["requires_verification"] is False
    assert first["text"]
    grades = {candidate["chunk_id"]: candidate["grade"] for candidate in payload["candidates"]}
    assert grades["chunk_1"] == "PRIMARY_SOURCE"
    assert grades["chunk_2"] == "PARSED_STRUCTURE"


@pytest.mark.asyncio
async def test_a_candidate_excerpt_is_bounded_by_the_configured_limit(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=LONG_TEXT))

    payload = await harness.search()

    excerpt = payload["candidates"][0]["text"]
    assert len(excerpt) == harness.config.max_candidate_text_chars
    assert LONG_TEXT.startswith(excerpt)


@pytest.mark.asyncio
async def test_the_tool_bounds_its_own_excerpt_when_the_service_would_not(tmp_path):
    """工具自己的上限，不是借服务的那一份。

    检索服务按自己那份配置截断，工具按自己那份再截一次——两处用的是两个设置对象时，输出
    仍不得超过工具声明的那一档，否则"这份输出不会超过多少"就只是服务的承诺。
    """
    harness = _Harness(
        tmp_path, config=settings(max_candidate_text_chars=600, max_inspected_chars=1200)
    )
    harness.publish(_Doc(chunk_id="chunk_1", text=LONG_TEXT))
    assert len(LONG_TEXT) > 600  # 服务那一段放得比工具宽，截断只可能来自工具

    result = await harness.search_tool(config=settings(max_candidate_text_chars=200)).execute(
        question=QUESTION
    )

    assert result.success, result.error
    excerpt = json.loads(result.content)["candidates"][0]["text"]
    assert len(excerpt) == 200
    assert LONG_TEXT.startswith(excerpt)


@pytest.mark.asyncio
async def test_a_lead_is_returned_only_when_the_caller_asked_for_leads(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    harness.publish(
        _Doc(
            chunk_id="chunk_lead",
            text=SECOND_TEXT,
            document_id="doc_0002",
            version_id="ver_0002",
            requires_verification=True,
        )
    )

    assert [candidate["chunk_id"] for candidate in (await harness.search())["candidates"]] == [
        "chunk_1"
    ]
    with_leads = (await harness.search(leads=True))["candidates"]
    lead = next(candidate for candidate in with_leads if candidate["chunk_id"] == "chunk_lead")
    assert lead["requires_verification"] is True
    assert lead["grade"] == "DERIVED_UNVERIFIED"


@pytest.mark.asyncio
async def test_search_refuses_the_identity_and_the_scope_the_server_already_bound(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    tool = harness.search_tool()

    for name in (
        "run_id",
        "task_id",
        "attempt",
        "attempt_id",
        "role",
        "worker_id",
        "sector",
        "sector_id",
        "selection_version",
        "collection",
        "top_k",
        "cutoff_at",
    ):
        with pytest.raises(ValueError, match="server controlled"):
            await tool.execute(question=QUESTION, **{name: "anything"})

    with pytest.raises(ValueError, match="question"):
        await tool.execute()


@pytest.mark.asyncio
async def test_search_refuses_a_query_it_cannot_turn_into_a_retrieval_request(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    tool = harness.search_tool()

    with pytest.raises(ValueError):
        await tool.execute(question="   ")
    with pytest.raises(ValueError):
        await tool.execute(question=QUESTION, document_types=["not_a_document_type"])
    with pytest.raises(ValueError):
        await tool.execute(question=QUESTION, time_range={"from": "2026-09-01", "to": "2026-01-01"})
    with pytest.raises(ValueError):
        await tool.execute(question=QUESTION, companies="储能")


@pytest.mark.asyncio
async def test_search_output_carries_no_object_key_address_or_credential(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))

    payload = await harness.search()
    content = json.dumps(payload, ensure_ascii=False)

    for forbidden in ("minio", "s3://", "http", "bucket", "object_key", "endpoint", "secret"):
        assert forbidden not in content


# --- 原文查看 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_inspect_returns_a_bounded_excerpt_of_the_authoritative_text(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=LONG_TEXT, page=7, section=("海外需求", "欧洲")))
    await harness.search()

    result = await harness.inspect()

    assert result.success, result.error
    payload = json.loads(result.content)
    assert payload["chunk_id"] == "chunk_1"
    assert payload["document_id"] == "doc_0001"
    assert payload["document_version_id"] == "ver_0001"
    assert payload["page_start"] == 7
    assert payload["section_path"] == ["海外需求", "欧洲"]
    assert payload["truncated"] is True
    assert payload["grade"] == "PRIMARY_SOURCE"
    assert LONG_TEXT.startswith(payload["text"])
    assert len(payload["text"]) == harness.config.max_inspected_chars
    # 查看放出的是原文，比检索摘要宽一档，但仍然是截断过的。
    assert len(payload["text"]) > harness.config.max_candidate_text_chars


@pytest.mark.asyncio
async def test_inspect_reports_the_grade_the_inspected_content_supports(tmp_path):
    """查看放出的等级跟着内容走，不是一个常数。

    一页 OCR 解析出来的是 `PARSED_STRUCTURE`，一条待核验是 `DERIVED_UNVERIFIED`：模型看到的
    等级与它随后能提交的等级必须是同一个来源算出来的，否则"不得高于内容所支持"就无从遵守。
    """
    harness = _Harness(tmp_path)
    harness.publish(
        _Doc(chunk_id="chunk_1", text=CORPUS_TEXT, content_origin=ExtractionMethod.OCR),
        _Doc(
            chunk_id="chunk_lead",
            text=SECOND_TEXT,
            document_id="doc_0002",
            version_id="ver_0002",
            requires_verification=True,
        ),
    )
    await harness.search(leads=True)
    by_chunk = {
        candidate["chunk_id"]: candidate["candidate_id"] for candidate in harness.candidates
    }

    scanned = await harness.inspect(by_chunk["chunk_1"])
    lead = await harness.inspect(by_chunk["chunk_lead"])

    assert scanned.success, scanned.error
    assert json.loads(scanned.content)["grade"] == "PARSED_STRUCTURE"
    assert json.loads(scanned.content)["requires_verification"] is False
    assert lead.success, lead.error
    assert json.loads(lead.content)["grade"] == "DERIVED_UNVERIFIED"
    assert json.loads(lead.content)["requires_verification"] is True


@pytest.mark.asyncio
async def test_inspect_refuses_a_handle_this_attempt_never_retrieved(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(
        _Doc(chunk_id="chunk_1", text=CORPUS_TEXT),
        _Doc(chunk_id="chunk_2", text=SECOND_TEXT, document_id="doc_0002", version_id="ver_0002"),
    )
    first = await harness.search()
    first_retrieval = first["retrieval_id"]
    first_candidate = first["candidates"][0]["candidate_id"]
    second = await harness.search()
    second_candidate = second["candidates"][0]["candidate_id"]
    assert second_candidate != first_candidate

    arbitrary = await harness.inspect("chunk_1")
    assert not arbitrary.success
    assert "was not returned by retrieval" in (arbitrary.error or "")
    assert arbitrary.content == ""

    # 第二次检索的句柄配第一次的 retrieval_id：两边都是真实的句柄，合起来不是任何一次
    # 检索发出过的候选。
    crossed = await harness.inspect_tool().execute(
        retrieval_id=first_retrieval, candidate_id=second_candidate
    )
    assert not crossed.success
    assert "was not returned by retrieval" in (crossed.error or "")
    assert CORPUS_TEXT not in crossed.content


@pytest.mark.asyncio
async def test_inspect_refuses_a_retrieval_that_belongs_to_another_attempt(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    await harness.search()

    result = await harness.inspect(attempt=2)

    assert not result.success
    assert "belongs to" in (result.error or "")
    assert result.content == ""


@pytest.mark.asyncio
async def test_inspect_refuses_the_identity_and_the_scope_the_server_already_bound(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    await harness.search()
    tool = harness.inspect_tool()

    for name in ("run_id", "task_id", "attempt", "role", "worker_id", "sector", "limit"):
        with pytest.raises(ValueError, match="server controlled"):
            await tool.execute(
                retrieval_id=harness.retrieval_id, candidate_id="cand_x", **{name: "anything"}
            )

    with pytest.raises(ValueError, match="server controlled"):
        await tool.execute(candidate_id="cand_x")


@pytest.mark.asyncio
async def test_inspect_output_carries_no_object_key_address_or_credential(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    await harness.search()

    result = await harness.inspect()

    for forbidden in ("minio", "s3://", "http", "bucket", "object_key", "endpoint", "secret"):
        assert forbidden not in result.content


# --- 证据接纳 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_refuses_a_claim_whose_source_was_never_inspected(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    await harness.search()

    result = await harness.accept_tool().execute(**harness.argument())

    assert not result.success
    assert "was never inspected" in (result.error or "")
    assert result.content == ""
    assert harness.snapshot_now().artifacts == ()
    assert harness.rows("internal_research_evidence") == []


@pytest.mark.asyncio
async def test_accept_commits_the_artifact_a3_a4_read_and_names_it(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    await harness.search()
    inspected = await harness.inspect()
    assert inspected.success, inspected.error

    result = await harness.accept_tool().execute(**harness.argument())

    assert result.success, result.error
    payload = json.loads(result.content)
    reference = payload["artifact_ref"]
    assert reference.startswith("internal-research-evidence:")
    artifact = harness.snapshot_now().artifacts[0]
    assert artifact.reference == reference
    assert artifact.kind == "internal_research_evidence"
    assert artifact.task_id == harness.task_id
    assert artifact.attempt == 1
    assert len(harness.rows("internal_research_evidence")) == 1
    assert len(harness.rows("internal_research_evidence_sources")) == 1


@pytest.mark.asyncio
async def test_accept_refuses_a_grade_the_inspected_content_cannot_support(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT, content_origin=ExtractionMethod.OCR))
    await harness.search()
    await harness.inspect()
    argument = harness.argument()
    argument["claims"][0]["grade"] = "PRIMARY_SOURCE"

    result = await harness.accept_tool().execute(**argument)

    assert not result.success
    assert "is stronger than the inspected content justifies" in (result.error or "")
    assert harness.snapshot_now().artifacts == ()


@pytest.mark.asyncio
async def test_accept_refuses_an_unresolved_claim_that_carries_one_side(tmp_path):
    """一条 UNRESOLVED 必须带双方，两层各挡一次。

    走的是框架入口 `run`，不是 `execute`：一条只有一边的 UNRESOLVED 在领域模型那一层就
    不成立，模型该看到的是"这条事实缺了一边"，而不是一次崩溃。同一段被引用两遍能过领域
    校验（确实有两条引用），但过不了接纳服务——那不是两个来源，是同一段话说了两次。
    """
    harness = _Harness(tmp_path)
    harness.publish(
        _Doc(chunk_id="chunk_1", text=CORPUS_TEXT),
        _Doc(chunk_id="chunk_2", text=SECOND_TEXT, document_id="doc_0002", version_id="ver_0002"),
    )
    await harness.search()
    await harness.inspect(harness.candidate["candidate_id"])
    tool = harness.accept_tool()
    argument = harness.argument()
    argument["claims"][0]["conflict_status"] = "UNRESOLVED"
    both_sides = argument["claims"][0]["source_refs"]

    one_side = await tool.run(**argument)
    assert not one_side.success
    assert "both conflicting facts" in (one_side.error or "")

    argument["claims"][0]["source_refs"] = [*both_sides, *both_sides]
    same_passage_twice = await tool.run(**argument)
    assert not same_passage_twice.success
    assert "both conflicting facts" in (same_passage_twice.error or "")
    assert harness.snapshot_now().artifacts == ()


@pytest.mark.asyncio
async def test_accept_refuses_the_identity_and_the_scope_the_server_already_bound(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    await harness.search()
    tool = harness.accept_tool()

    for name in ("run_id", "task_id", "attempt", "role", "worker_id", "sector", "evidence_id"):
        with pytest.raises(ValueError, match="server controlled"):
            await tool.execute(**harness.argument(), **{name: "anything"})

    with pytest.raises(ValueError, match="server controlled"):
        await tool.execute(claims=harness.argument()["claims"])


@pytest.mark.asyncio
async def test_accept_refuses_a_retrieval_that_belongs_to_another_attempt(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    await harness.search()

    result = await harness.accept_tool(attempt=2).execute(**harness.argument())

    assert not result.success
    assert "belongs to" in (result.error or "")
    assert harness.snapshot_now().artifacts == ()


# --- 重放 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_re_reads_the_library_instead_of_running_the_providers_again(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(
        _Doc(chunk_id="chunk_1", text=CORPUS_TEXT),
        _Doc(chunk_id="chunk_2", text=SECOND_TEXT, document_id="doc_0002", version_id="ver_0002"),
    )
    payload = await harness.search()
    calls = harness.embedding.calls

    replayed = harness.search_tool().replay(harness.reference)

    assert harness.embedding.calls == calls
    assert json.loads(replayed.content) == payload


@pytest.mark.asyncio
async def test_replay_refuses_a_candidate_the_library_has_since_withdrawn(tmp_path):
    """重放也要重新问一次"这条候选现在还作数吗"。

    审计记的是**当时**的结果；资料在那之后被软删除，`search` 的 `filter_active_hits` 与
    `inspect` 的 `CandidateWithdrawn` 都已经拒绝它了。重放若照着审计把正文重新递出去，
    被撤回的内容就多了一条只属于重放的通道——而且是模型直接能走的那一条。
    """
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    await harness.search()

    harness.repository.soft_delete_document("doc_0001", now=NOW, retention_days=30)

    with pytest.raises(CandidateWithdrawn):
        harness.search_tool().replay(harness.reference)


@pytest.mark.asyncio
async def test_accept_replay_names_only_an_artifact_this_run_committed(tmp_path):
    harness = _Harness(tmp_path)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    await harness.search()
    await harness.inspect()
    accepted = await harness.accept_tool().execute(**harness.argument())
    reference = json.loads(accepted.content)["artifact_ref"]
    tool = harness.accept_tool()

    replayed = tool.replay(reference)
    assert replayed.success
    assert json.loads(replayed.content)["artifact_ref"] == reference

    with pytest.raises(KeyError):
        tool.replay(f"internal-research-evidence:{uuid4()}")


# --- 组合契约 ---------------------------------------------------------------


class _NamedTool:
    """A placeholder tool for the names a factory is expected to provide."""

    def __init__(self, name: str) -> None:
        self.name = name


def _a2_dependencies(services: A2ResearchLibraryServices | None) -> A2ToolDependencies:
    return A2ToolDependencies(
        orchestration=object(),
        selections=object(),
        candidate_batches=object(),
        market_snapshots=object(),
        news=object(),
        news_batches=object(),
        research_searches=object(),
        news_details=object(),
        evidence_inspections=object(),
        sector_analyses=object(),
        detail=object(),
        keyword_news=object(),
        research_library=services,
    )


def test_the_a2_factory_exposes_the_internal_research_tools_only_when_rag_is_wired(tmp_path):
    harness = _Harness(tmp_path)
    services = A2ResearchLibraryServices(
        retrieval=harness.retrieval,
        repository=harness.repository,
        settings=harness.config,
    )

    without = A2BusinessToolFactory(_a2_dependencies(None)).build(
        run_id=harness.run_id, provider="fixture"
    )
    with_rag = A2BusinessToolFactory(_a2_dependencies(services)).build(
        run_id=harness.run_id, provider="fixture"
    )

    assert set(without) == {
        "search_news",
        "read_news_detail",
        "inspect_evidence",
        "submit_analysis",
    }
    assert set(with_rag) == set(without) | set(INTERNAL_TOOLS)


def test_the_runtime_contract_requires_the_rag_tools_only_when_rag_is_expected():
    # RAG 那一组钉在名字上，不是钉在"它与自己一致"上：`web/dependencies.py` 用它报工具价，
    # 少一个名字，一份缺接纳工具的部署就会被当成完整的部署放行。
    assert set(INTERNAL_TOOLS) == RAG_BUSINESS_TOOL_NAMES
    assert RAG_BUSINESS_TOOL_NAMES.isdisjoint(REQUIRED_BUSINESS_TOOL_NAMES)
    # 右边写死那三个名字，不从 `RAG_BUSINESS_TOOL_NAMES` 反推：`RAG_ENABLED_REQUIRED_…` 就是
    # 用这两个集合的并集定义的，拿它去比自己的定义式，对任何取值都成立，包括三件工具全丢。
    assert REQUIRED_BUSINESS_TOOL_NAMES | {
        "search_internal_research",
        "inspect_research_source",
        "accept_internal_evidence",
    } == RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES
    # 原先这里还有一条 `set(INTERNAL_TOOLS) | REQUIRED == RAG_ENABLED_REQUIRED`：一旦上面
    # 那条把 `INTERNAL_TOOLS` 钉在了生产常量上，它就退化成"契约等于契约自己的定义式"，
    # 删掉不减少任何覆盖。

    def builders(names: Any) -> Any:
        return {name: (lambda context, name=name: _NamedTool(name)) for name in names}

    without_rag = AgentBusinessToolFactory(
        builders(REQUIRED_BUSINESS_TOOL_NAMES), required_names=REQUIRED_BUSINESS_TOOL_NAMES
    )
    with_rag = AgentBusinessToolFactory(
        builders(REQUIRED_BUSINESS_TOOL_NAMES | RAG_BUSINESS_TOOL_NAMES),
        required_names=RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES,
    )

    def build(factory: CompositeBusinessToolFactory) -> set[str]:
        return set(factory.build(run_id=uuid4(), provider="fixture"))

    # RAG 关闭：契约就是原来那一份，多一个名字都会被拒绝。
    assert build(CompositeBusinessToolFactory(without_rag)) == set(REQUIRED_BUSINESS_TOOL_NAMES)
    # RAG 打开但只接了一半：拒绝，而不是静默退化成"没有那三件工具"。
    with pytest.raises(ValueError, match="missing business tools"):
        build(
            CompositeBusinessToolFactory(
                without_rag, required_names=RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES
            )
        )
    assert build(
        CompositeBusinessToolFactory(
            with_rag, required_names=RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES
        )
    ) == set(RAG_ENABLED_REQUIRED_BUSINESS_TOOL_NAMES)


@pytest.mark.asyncio
async def test_the_factory_gives_a2_one_ledger_so_inspect_then_accept_commits(tmp_path):
    """工厂那条路跑一遍：检索 → 查看 → 接纳。

    三件工具各建一次，但 `inspect` 记下的台账与 `accept` 认的台账必须是同一本——否则 A2
    会先被允许查看，然后在接纳时被告知"从没查看过"。直接构造工具的测试证明不了这件事，它
    绕过了组合，而组合才是部署时真实发生的那一次装配。
    """
    harness = _Harness(tmp_path, a2_context=True)
    harness.publish(_Doc(chunk_id="chunk_1", text=CORPUS_TEXT))
    services = A2ResearchLibraryServices(
        retrieval=harness.retrieval,
        repository=harness.repository,
        settings=harness.config,
    )
    builders = A2BusinessToolFactory(harness.a2_dependencies(services)).build(
        run_id=harness.run_id, provider="fixture"
    )
    context = harness.agent_context()
    search = builders["search_internal_research"](context)
    inspect = builders["inspect_research_source"](context)
    accept = builders["accept_internal_evidence"](context)

    found = await search.execute(question=QUESTION)
    assert found.success, found.error
    payload = json.loads(found.content)
    candidate = payload["candidates"][0]
    harness.seed_audit(payload["retrieval_id"])

    seen = await inspect.execute(
        retrieval_id=payload["retrieval_id"], candidate_id=candidate["candidate_id"]
    )
    assert seen.success, seen.error

    committed = await accept.execute(
        retrieval_id=payload["retrieval_id"],
        claims=[
            {
                "statement": "储能海外需求在 2026 年上半年改善",
                "stance": "supporting",
                "conflict_status": "RESOLVED",
                "grade": "PRIMARY_SOURCE",
                "source_refs": [
                    {
                        "document_id": candidate["document_id"],
                        "document_version_id": candidate["document_version_id"],
                        "chunk_id": candidate["chunk_id"],
                        "page_start": candidate["page_start"],
                        "page_end": candidate["page_end"],
                        "section_path": list(candidate["section_path"]),
                    }
                ],
            }
        ],
    )

    assert committed.success, committed.error
    reference = json.loads(committed.content)["artifact_ref"]
    assert reference.startswith("internal-research-evidence:")
    assert reference in {artifact.reference for artifact in harness.snapshot_now().artifacts}
    assert len(harness.rows("internal_research_evidence")) == 1


def test_only_a2_lists_the_internal_research_tools():
    for role in AgentRole:
        listed = ROLE_TOOL_NAMES[role]
        if role is AgentRole.A2:
            assert set(INTERNAL_TOOLS) <= listed
        else:
            assert set(INTERNAL_TOOLS).isdisjoint(listed), role
