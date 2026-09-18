"""金标准检索评测（规格 21 的"可复现质量报告"）。

这份评测要回答的问题只有一个：**一次真实的检索，交到 A2 手里的那 12 条候选，够不够用。**
因此它不测某一条规则，而是把整条链路跑起来——上传、解析、切片、嵌入、发布、检索、查看、
接纳——然后在一份固定的语料上量一遍。

四条刻意的选择：

1. **指标由这里自己算。** 去重率尤其如此：拿检索服务自己的判据去量重复，量到的永远是
   "它的判据认为没有重复"。这里另写一份二元组覆盖率，与生产实现无关。
2. **标注按答案写，不按切片写。** `contains` 是一个只出现在目标段落里的文本标记，摄取之后
   才去权威库解析成 `chunk_id`。切片参数变了，这份标注不会变成一份悄悄失效的答案。
3. **阈值是提交进仓库的基线。** 真实 Provider 的影子结果另报，不回写这些数字——否则换一次
   模型就会悄悄把标准降低。
4. **空语料不许通过。** 一份没有摄取到东西的语料会让每一项指标都"满足"：零条标注、零条
   候选、零次泄漏。因此第一个用例先证明语料真的在那儿。

一次检索走的是 A2 的三件工具（`search_internal_research` / `inspect_research_source` /
`accept_internal_evidence`），不是服务内部对象：指标要量的是 A2 实际拿到的东西，而 A2 只有
这三条路。真实 Provider 的 `live_rag` 冒烟不在这里，在 `backend/tests/live/`，需要显式同意书。
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pymupdf
import pytest
import yaml
from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.research_context import BoundSectorResearchContext
from sector_pulse.application.research_library.artifacts import (
    AcceptInternalEvidenceService,
)
from sector_pulse.application.research_library.claims import (
    ClaimExtractionService,
    group_comparable_claims,
)
from sector_pulse.application.research_library.commands import UploadTarget
from sector_pulse.application.research_library.conflicts import (
    ClaimSource,
    ConflictContext,
    ConflictService,
)
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.orchestration.models import (
    BudgetLimits,
    RunSnapshot,
    TaskRecord,
    TaskStatus,
)
from sector_pulse.domain.research_library.models import (
    DocumentType,
    DocumentVersionStatus,
    ExtractionMethod,
    ResearchChunk,
    SourceSpan,
)
from sector_pulse.domain.research_library.retrieval import (
    ConflictStatus,
    NliRelation,
    RetrievedCandidate,
    TimeRange,
)
from sector_pulse.infrastructure.agents.research_library_tools import (
    AcceptInternalEvidenceTool,
    InspectResearchSourceTool,
    SearchInternalResearchTool,
)
from sector_pulse.infrastructure.agents.roles import ROLE_TOOL_NAMES, AgentRole
from sector_pulse.infrastructure.research_library.assets.integrity import spool_to_disk
from sector_pulse.infrastructure.research_library.parsing import build_parse_pipeline
from sector_pulse.infrastructure.research_library.providers.fixture import (
    FixtureClaimExtractorProvider,
    FixtureNliProvider,
    FixtureOcrProvider,
    claim,
    ocr_page,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

from backend.tests.research_library_stack import (
    ResearchLibraryStack,
    build_research_library_stack,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "research_library"
    / "golden_retrieval.yaml"
)

WORKER = "golden-worker"
ACTOR = "评测"
NOW = datetime(2026, 9, 18, 4, 0, tzinfo=UTC)
SECTOR = "储能"

#: 与 PDF 夹具同一套排版参数：行距固定，因此"哪一行落在哪一页"是确定的。
PDF_FONT = "china-s"
PDF_PAGE_WIDTH = 595.0
PDF_PAGE_HEIGHT = 842.0
PDF_FIRST_LINE_Y = 90.0
PDF_LINE_HEIGHT = 22.0
PDF_LINES_PER_PAGE = 28

#: 检索交出去的候选条数。计划里的 "Top-12" 就是 `rerank_top_k` 的默认值。
TOP_K = 12

#: 评测自己的去重判据。与生产的 `duplicate_overlap_ratio` 数值相同，实现独立。
DUPLICATE_COVERAGE = 0.8

#: 判定"这一句是否定"的标记。只用来区分"上升"与"没有上升"这类词面近乎重合、含义相反的
#: 一对事实：它们不是同一段话的两个副本。
NEGATION_MARKERS = ("没有", "不是", "并非", "未")

#: 等级由强到弱。只用来在两条出处之间取最低的那一档。
GRADE_STRENGTH: Mapping[str, int] = {
    "DERIVED_UNVERIFIED": 0,
    "PARSED_STRUCTURE": 1,
    "PRIMARY_SOURCE": 2,
}


# --- 夹具 ---


@dataclass(frozen=True)
class Label:
    document: str
    contains: str
    grade: int = 2


@dataclass(frozen=True)
class ClaimSpec:
    document: str
    contains: str
    statement: str
    subject: str
    predicate: str
    valid_time: TimeRange | None = None


@dataclass(frozen=True)
class QuerySpec:
    query_id: str
    question: str
    sector: str | None = None
    document_types: tuple[str, ...] = ()
    time_range: TimeRange | None = None
    relevant: tuple[Label, ...] = ()
    forbidden: tuple[Label, ...] = ()
    claims: tuple[ClaimSpec, ...] = ()


@dataclass(frozen=True)
class DocumentSpec:
    key: str
    title: str
    document_type: str
    institution: str | None
    source_weight: str
    media: str
    published_at: datetime
    bodies: tuple[str, ...]
    ocr_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class Golden:
    thresholds: Mapping[str, float]
    documents: tuple[DocumentSpec, ...]
    queries: tuple[QuerySpec, ...]


def _labels(entries: Sequence[Mapping[str, Any]] | None) -> tuple[Label, ...]:
    return tuple(
        Label(
            document=str(entry["document"]),
            contains=str(entry["contains"]),
            grade=int(entry.get("grade", 2)),
        )
        for entry in entries or ()
    )


def _window(raw: Mapping[str, Any] | None) -> TimeRange | None:
    if raw is None:
        return None
    return TimeRange.model_validate({"from": str(raw["from"]), "to": str(raw["to"])})


def load_golden(path: Path = FIXTURE_PATH) -> Golden:
    """读金标准夹具。夹具有问题就当场说出来，而不是让指标在空语料上"通过"。"""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict), "the golden fixture must be a mapping"
    documents: list[DocumentSpec] = []
    for entry in raw["documents"]:
        bodies = (
            tuple(str(version["body"]) for version in entry["versions"])
            if "versions" in entry
            else (str(entry["body"]),)
        )
        documents.append(
            DocumentSpec(
                key=str(entry["key"]),
                title=str(entry["title"]),
                document_type=str(entry["document_type"]),
                institution=entry.get("institution"),
                source_weight=str(entry.get("source_weight", "0.50")),
                media=str(entry["media"]),
                published_at=datetime.fromisoformat(str(entry["published_at"])),
                bodies=bodies,
                ocr_lines=tuple(str(line) for line in entry.get("ocr_lines", ())),
            )
        )
    # OCR 夹具按**页号**查表，而解析流水线是全局的：两份扫描件会抢同一个页号，第二份静默地
    # 读到第一份的文字。宁可现在拒绝这份夹具。
    scanned = [spec for spec in documents if spec.media == "application/pdf+scan"]
    if len(scanned) > 1:
        raise ValueError(
            f"the golden fixture declares {len(scanned)} scanned PDFs; the fixture OCR "
            "provider is keyed by page number, so only one of them can be read correctly"
        )
    queries: list[QuerySpec] = []
    for entry in raw["queries"]:
        queries.append(
            QuerySpec(
                query_id=str(entry["id"]),
                question=str(entry["question"]),
                sector=entry.get("sector"),
                document_types=tuple(str(value) for value in entry.get("document_types", ())),
                time_range=_window(entry.get("time_range")),
                relevant=_labels(entry.get("relevant")),
                forbidden=_labels(entry.get("forbidden")),
                claims=tuple(
                    ClaimSpec(
                        document=str(item["document"]),
                        contains=str(item["contains"]),
                        statement=str(item["statement"]),
                        subject=str(item["subject"]),
                        predicate=str(item["predicate"]),
                        valid_time=_window(item.get("valid_time")),
                    )
                    for item in entry.get("claims", ())
                ),
            )
        )
    if any(not spec.relevant for spec in queries):
        raise ValueError("every golden query must carry a labelled answer")
    return Golden(
        thresholds={key: float(value) for key, value in raw["thresholds"].items()},
        documents=tuple(documents),
        queries=tuple(queries),
    )


# --- PDF 字节 ---


def _pdf_document(lines: Sequence[str]) -> pymupdf.Document:
    document = pymupdf.open()
    # 固定元数据：同一份正文每次都得到同样的字节，因此 `original_file_hash` 也是同一个值。
    document.set_metadata(
        {
            "creationDate": "D:20260101000000Z",
            "modDate": "D:20260101000000Z",
            "producer": "SectorPulse golden fixture",
            "creator": "SectorPulse golden fixture",
        }
    )
    for start in range(0, max(len(lines), 1), PDF_LINES_PER_PAGE):
        page = document.new_page(width=PDF_PAGE_WIDTH, height=PDF_PAGE_HEIGHT)
        for offset, line in enumerate(lines[start : start + PDF_LINES_PER_PAGE]):
            page.insert_text(
                (72, PDF_FIRST_LINE_Y + offset * PDF_LINE_HEIGHT),
                line,
                fontname=PDF_FONT,
                fontsize=10.0,
            )
    return document


def native_pdf_bytes(lines: Sequence[str]) -> bytes:
    """有真实文字层的 PDF：任何一页都不该走到 OCR。"""
    document = _pdf_document(lines)
    payload = document.tobytes()
    document.close()
    return payload


def scanned_pdf_bytes(lines: Sequence[str]) -> bytes:
    """第 1 页有文字层，第 2 页是第 1 页的**位图**——像素里没有字。

    这就是扫描件在解析器眼里的样子：一张图，零个字符。第 2 页的正文只能由 OCR 给出，因此
    它由夹具声明（`ocr_lines`），而不是从这份 PDF 里读出来的。
    """
    document = _pdf_document(lines)
    pixmap = document[0].get_pixmap(dpi=72)
    scanned = document.new_page(width=PDF_PAGE_WIDTH, height=PDF_PAGE_HEIGHT)
    scanned.insert_image(pymupdf.Rect(0, 0, PDF_PAGE_WIDTH, PDF_PAGE_HEIGHT), pixmap=pixmap)
    payload = document.tobytes()
    document.close()
    return payload


def _payload(spec: DocumentSpec, body: str) -> tuple[bytes, str]:
    if spec.media == "application/pdf":
        return native_pdf_bytes(body.splitlines()), f"{spec.key}.pdf"
    if spec.media == "application/pdf+scan":
        return scanned_pdf_bytes(body.splitlines()), f"{spec.key}.pdf"
    if spec.media == "text/markdown":
        return body.encode("utf-8"), f"{spec.key}.md"
    return body.encode("utf-8"), f"{spec.key}.txt"


# --- 语料 ---


@dataclass
class Corpus:
    golden: Golden
    stack: ResearchLibraryStack
    document_ids: dict[str, str] = field(default_factory=dict)
    version_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def chunks(self, key: str, *, searchable_only: bool = True) -> tuple[ResearchChunk, ...]:
        """这一版**可被检索到**的切片。

        父块不在这里：规格 8 规定父块只用来展开上下文、不参与向量召回。标注落在父块上会
        永远匹配不到任何候选，而那看起来像"一条都没召回"，不像一份写错了的标注——一个
        会让 12 条标注一起变成 0 的坑。
        """
        found: list[ResearchChunk] = []
        for version_id in self.version_ids[key]:
            for chunk in self.stack.repository.list_chunks(version_id):
                if searchable_only and chunk.parent_chunk_id is None:
                    continue
                found.append(chunk)
        return tuple(found)

    def chunk_for(self, label: Label) -> ResearchChunk:
        """把一个标注解析成切片。解析不到就是夹具坏了，不是"没检索到"。"""
        for chunk in self.chunks(label.document):
            if label.contains in chunk.content:
                return chunk
        raise AssertionError(
            f"the golden fixture labels {label.contains!r} in document "
            f"{label.document!r}, but no chunk of that document contains it"
        )


def build_corpus(golden: Golden, tmp_path: Path) -> Corpus:
    """把夹具里的文档真的摄取一遍。走的是命令层，与 API 调的是同一条路径。"""
    del tmp_path  # 摄取全程在内存对象存储与内存索引上；临时目录留给调用方。
    scanned = next(
        (spec for spec in golden.documents if spec.media == "application/pdf+scan"), None
    )
    ocr = (
        FixtureOcrProvider(pages={2: ocr_page(page_number=2, lines=scanned.ocr_lines)})
        if scanned is not None and scanned.ocr_lines
        else None
    )
    stack = build_research_library_stack(parse_pipeline=build_parse_pipeline(ocr=ocr))
    corpus = Corpus(golden=golden, stack=stack)
    for spec in golden.documents:
        versions: list[str] = []
        document_id: str | None = None
        for body in spec.bodies:
            payload, filename = _payload(spec, body)
            target = (
                UploadTarget.NEW_DOCUMENT if document_id is None else UploadTarget.NEW_VERSION
            )
            with spool_to_disk(
                BytesIO(payload), max_bytes=stack.services.max_upload_bytes
            ) as spooled:
                result = stack.commands.upload(
                    spooled=spooled,
                    media_type=spec.media.replace("+scan", ""),
                    filename=filename,
                    target=target,
                    actor=ACTOR,
                    document_id=document_id,
                    title=spec.title if document_id is None else None,
                    document_type=(
                        DocumentType(spec.document_type) if document_id is None else None
                    ),
                    institution=spec.institution if document_id is None else None,
                    published_at=spec.published_at,
                    now=NOW,
                )
            document_id = result.document.document_id
            job = stack.commands.run_ingestion(result.job.job_id, worker_id=WORKER, now=NOW)
            assert job.status.value == "PUBLISHED", (spec.key, job.status, job.failure_reason)
            versions.append(result.version.document_version_id)
        assert document_id is not None
        corpus.document_ids[spec.key] = document_id
        corpus.version_ids[spec.key] = tuple(versions)
        stack.commands.set_source_weight(
            document_id, source_weight=Decimal(spec.source_weight), actor=ACTOR, now=NOW
        )
    return corpus


# --- 一次检索 ---


@dataclass(frozen=True)
class Candidate:
    """A2 实际拿到的那一份候选（工具输出，不是服务内部对象）。"""

    candidate_id: str
    chunk_id: str
    document_id: str
    document_version_id: str
    grade: str
    text: str
    section_path: tuple[str, ...] = ()
    page_start: int | None = None


@dataclass(frozen=True)
class QueryRun:
    spec: QuerySpec
    retrieval_id: str
    candidates: tuple[Candidate, ...]


@dataclass
class A2Harness:
    """A2 的三件工具，绑在一次任务尝试上。"""

    context: BoundSectorResearchContext
    search: SearchInternalResearchTool
    inspect: InspectResearchSourceTool
    accept: AcceptInternalEvidenceTool
    service: AcceptInternalEvidenceService
    run_id: Any
    database: SQLiteDatabase


def tool_call(tool: Any, **kwargs: Any) -> Any:
    """从同步用例里调一个异步工具。

    这三件工具一次真 I/O 都不 await——它们读的是权威库与内存索引——因此每次调用新开一个
    事件循环不花什么代价，换来的是整个评测的夹具都是同步的，而模块级的语料只能由同步夹具
    持有。
    """
    return asyncio.run(tool.execute(**kwargs))


def build_a2(corpus: Corpus, tmp_path: Path) -> A2Harness:
    run_id = uuid4()
    root_id = uuid4()
    task_id = uuid4()
    database = SQLiteDatabase(tmp_path / "golden-orchestration.db")
    database.initialize()
    orchestration = SQLiteOrchestrationRepository(database)
    orchestration.save(
        RunSnapshot(
            run_id=run_id,
            limits=BudgetLimits(max_tool_calls=200, max_cny=Decimal("10.00")),
            deadline=NOW.replace(year=NOW.year + 1),
            tasks=(
                TaskRecord(task_id=root_id, role="A0", scope="run"),
                TaskRecord(
                    task_id=task_id,
                    parent_id=root_id,
                    role="A2",
                    scope=f"industry:{SECTOR}",
                    status=TaskStatus.RUNNING,
                    worker_id=WORKER,
                    lease_expires_at=NOW.replace(year=NOW.year + 1),
                    selection_version=1,
                ),
            ),
        ),
        -1,
        "created",
    )
    context = BoundSectorResearchContext(
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        worker_id=WORKER,
        sector_id="industry:1",
        sector_kind=SectorKind.INDUSTRY,
        sector_name=SECTOR,
        selection_version=1,
        cutoff_at=NOW,
        input_artifacts=(),
    )
    services = corpus.stack.services
    service = AcceptInternalEvidenceService(
        retrieval=services.retrieval,
        repository=services.repository,
        committer=AtomicArtifactCommitter(orchestration, run_id),
        clock=lambda: NOW,
    )
    return A2Harness(
        context=context,
        search=SearchInternalResearchTool(
            services.retrieval,
            repository=services.repository,
            context=context,
            settings=services.settings,
            clock=lambda: NOW,
        ),
        inspect=InspectResearchSourceTool(service, context=context, clock=lambda: NOW),
        accept=AcceptInternalEvidenceTool(service, context=context, clock=lambda: NOW),
        service=service,
        run_id=run_id,
        database=database,
    )


def run_query(a2: A2Harness, spec: QuerySpec) -> QueryRun:
    arguments: dict[str, Any] = {"question": spec.question}
    if spec.document_types:
        arguments["document_types"] = list(spec.document_types)
    if spec.time_range is not None:
        arguments["time_range"] = {
            "from": spec.time_range.start.isoformat(),
            "to": spec.time_range.end.isoformat(),
        }
    result = tool_call(a2.search, **arguments)
    assert result.success, (spec.query_id, result.error)
    payload = json.loads(result.content)
    return QueryRun(
        spec=spec,
        retrieval_id=payload["retrieval_id"],
        candidates=tuple(
            Candidate(
                candidate_id=entry["candidate_id"],
                chunk_id=entry["chunk_id"],
                document_id=entry["document_id"],
                document_version_id=entry["document_version_id"],
                grade=entry["grade"],
                text=entry["text"],
                section_path=tuple(entry["section_path"]),
                page_start=entry["page_start"],
            )
            for entry in payload["candidates"]
        ),
    )


def run_all(corpus: Corpus, a2: A2Harness) -> tuple[QueryRun, ...]:
    return tuple(run_query(a2, spec) for spec in corpus.golden.queries)


# --- 指标 ---


def recall_at(run: QueryRun, relevant: set[str], k: int = TOP_K) -> float:
    returned = {candidate.chunk_id for candidate in run.candidates[:k]}
    return len(returned & relevant) / len(relevant)


def reciprocal_rank(run: QueryRun, relevant: set[str]) -> float:
    for rank, candidate in enumerate(run.candidates, start=1):
        if candidate.chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at(run: QueryRun, gains: Mapping[str, int], k: int = TOP_K) -> float:
    """2^grade - 1 作增益。"""

    def dcg(order: Sequence[int]) -> float:
        return sum(gain / math.log2(rank + 1) for rank, gain in enumerate(order, start=1))

    actual = [gains.get(candidate.chunk_id, 0) for candidate in run.candidates[:k]]
    ideal = sorted(gains.values(), reverse=True)[:k]
    best = dcg(ideal)
    return 1.0 if best == 0 else dcg(actual) / best


def _bigrams(text: str) -> frozenset[str]:
    compact = "".join(text.split())
    if len(compact) < 2:
        return frozenset({compact}) if compact else frozenset()
    return frozenset(compact[index : index + 2] for index in range(len(compact) - 1))


def _is_covered(shorter: str, longer: str) -> bool:
    """较短的一段有多大比例被较长的一段覆盖。

    与被测实现同一条判据、不同一份代码：覆盖率而不是 Jaccard，因为要抓的是包含关系。
    """
    inner = _bigrams(shorter)
    if not inner:
        return False
    return len(inner & _bigrams(longer)) / len(inner) >= DUPLICATE_COVERAGE


def _states_a_negation(text: str) -> bool:
    return any(marker in text for marker in NEGATION_MARKERS)


def _same_passage(earlier: Candidate, later: Candidate) -> bool:
    """这两条候选是不是"同一段话被交了两遍"。

    三个条件缺一不可：

    * **同一版本、同一章节。** 同一句话在两份资料里各写一遍是两个出处，合并它们等于凭空
      删掉一个来源（这是这套系统自己的判据，写在这里是因为它是"重复"的**定义**的一部分，
      不是某个实现顺手加的条件）。
    * 较短的一段被较长的一段覆盖到 `DUPLICATE_COVERAGE`。
    * **两侧的否定状态一致。** "产能利用率上升"与"产能利用率没有上升"字面几乎重合，相差
      两个字，却是两条互相矛盾的事实。把它们算成重复，会让这份指标在最重要的那个查询上
      把"矛盾"读成"冗余"——而语料里就摆着这么一对。
    """
    if earlier.document_version_id != later.document_version_id:
        return False
    if earlier.section_path != later.section_path:
        return False
    if _states_a_negation(earlier.text) != _states_a_negation(later.text):
        return False
    shorter, longer = sorted((earlier.text, later.text), key=len)
    return _is_covered(shorter, longer)


def duplicate_ratio(run: QueryRun) -> float:
    """这一次检索交出去的候选里，有几条是前面某一条的重复。"""
    if not run.candidates:
        return 0.0
    repeats = 0
    for index, candidate in enumerate(run.candidates):
        if any(_same_passage(earlier, candidate) for earlier in run.candidates[:index]):
            repeats += 1
    return repeats / len(run.candidates)


def test_the_repeat_detector_still_catches_a_real_repeat() -> None:
    """这份指标得先证明自己认得出重复，否则"没有重复"只是一个空话。

    两种情况一起断言：真正同段话多切了一刀要被认出来，而一对互相矛盾的事实不能。
    """
    passage = "报告期内行业整体产能投放节奏放缓，二线厂商的开工率出现分化。"

    def candidate(
        text: str, *, section: tuple[str, ...] = ("第一章",), version: str = "v1"
    ) -> Candidate:
        return Candidate(
            candidate_id="c",
            chunk_id="k",
            document_id="d",
            document_version_id=version,
            grade="PRIMARY_SOURCE",
            text=text,
            section_path=section,
        )

    assert _same_passage(candidate(f"第二章 产线明细\n{passage}"), candidate(passage))
    assert _same_passage(candidate(passage, version="v1"), candidate(passage, version="v1"))
    # 换个章节、换个版本：都是另一个出处。
    assert not _same_passage(candidate(passage, section=("第二章",)), candidate(passage))
    assert not _same_passage(candidate(passage, version="v2"), candidate(passage))
    # 否定状态不同的两条，是两条事实。
    assert not _same_passage(
        candidate("二线厂商的产能利用率在过去一个季度上升。"),
        candidate("二线厂商的产能利用率在过去一个季度没有上升。"),
    )
    # 无关的两段话。
    assert not _same_passage(candidate("电解液价格环比上涨百分之六。"), candidate(passage))


@dataclass(frozen=True)
class Metrics:
    recall: float
    mrr: float
    ndcg: float
    duplicates: float

    def as_dict(self) -> dict[str, float]:
        return {
            "recall@12": round(self.recall, 4),
            "mrr": round(self.mrr, 4),
            "ndcg@12": round(self.ndcg, 4),
            "duplicate_ratio": round(self.duplicates, 4),
        }


def measure(corpus: Corpus, runs: Sequence[QueryRun]) -> Metrics:
    recalls: list[float] = []
    ranks: list[float] = []
    gains: list[float] = []
    repeats: list[float] = []
    for run in runs:
        relevant = {
            corpus.chunk_for(label).chunk_id for label in run.spec.relevant if label.grade == 2
        }
        if not relevant:
            continue
        graded = {corpus.chunk_for(label).chunk_id: label.grade for label in run.spec.relevant}
        recalls.append(recall_at(run, relevant))
        ranks.append(reciprocal_rank(run, relevant))
        gains.append(ndcg_at(run, graded))
        repeats.append(duplicate_ratio(run))
    assert recalls, "no query in the golden fixture carries a graded answer"
    # 去重率取最大值而不是平均值：一个查询交出满屏重复都是不允许的，平均会把这件事抹平。
    return Metrics(
        recall=sum(recalls) / len(recalls),
        mrr=sum(ranks) / len(ranks),
        ndcg=sum(gains) / len(gains),
        duplicates=max(repeats),
    )


# --- 夹具 ---


@pytest.fixture(scope="module")
def golden() -> Golden:
    return load_golden()


@pytest.fixture(scope="module")
def corpus(golden: Golden, tmp_path_factory: pytest.TempPathFactory) -> Corpus:
    return build_corpus(golden, tmp_path_factory.mktemp("golden-corpus"))


@pytest.fixture(scope="module")
def a2(corpus: Corpus, tmp_path_factory: pytest.TempPathFactory) -> A2Harness:
    return build_a2(corpus, tmp_path_factory.mktemp("golden-a2"))


@pytest.fixture(scope="module")
def runs(corpus: Corpus, a2: A2Harness) -> tuple[QueryRun, ...]:
    return run_all(corpus, a2)


def run_of(runs: Sequence[QueryRun], query_id: str) -> QueryRun:
    for run in runs:
        if run.spec.query_id == query_id:
            return run
    raise AssertionError(f"the golden fixture has no query {query_id!r}")


# --- 语料与指标 ---


def test_the_corpus_really_is_in_the_library(corpus: Corpus) -> None:
    """空语料会让每一项指标都"满足"。因此先证明语料在那儿，而且每一版都是在架的。"""
    assert len(corpus.golden.documents) >= 10
    for spec in corpus.golden.documents:
        assert corpus.document_ids[spec.key], spec.key
        versions = corpus.version_ids[spec.key]
        statuses = corpus.stack.repository.load_version_statuses(list(versions))
        assert statuses[versions[-1]] is DocumentVersionStatus.ACTIVE, spec.key
        if len(spec.bodies) > 1:
            # 多版本的文档：旧版仍在库里，但已经不在服务集里。旧版的切片留着，正是它让
            # "零非活跃版本泄漏"这条指标有意义。
            assert statuses[versions[0]] is not DocumentVersionStatus.ACTIVE, spec.key
        # 每一版都有可召回的切片，而且父块**不在**可召回的那一批里：标注解析的就是这一批，
        # 它空了的话所有指标都会以"一条都没召回"的形式同时变成 0。
        assert corpus.chunks(spec.key), spec.key
        assert corpus.chunks(spec.key, searchable_only=False), spec.key


def test_every_query_returns_candidates(runs: Sequence[QueryRun]) -> None:
    for run in runs:
        assert run.candidates, run.spec.query_id


def test_retrieval_clears_the_committed_baseline(corpus: Corpus, runs: Sequence[QueryRun]) -> None:
    measured = measure(corpus, runs)
    thresholds = corpus.golden.thresholds
    assert measured.recall >= thresholds["recall_at_12"], measured.as_dict()
    assert measured.mrr >= thresholds["mrr"], measured.as_dict()
    assert measured.ndcg >= thresholds["ndcg_at_12"], measured.as_dict()


def test_no_query_hands_back_more_repeats_than_the_baseline(
    corpus: Corpus, runs: Sequence[QueryRun]
) -> None:
    """重复的候选不只是噪声：它占掉一个名额，而名额总共只有 12 个。

    因此这一条**逐查询**断言，而不是对平均值断言。
    """
    for run in runs:
        assert (
            duplicate_ratio(run) <= corpus.golden.thresholds["max_duplicate_ratio"]
        ), run.spec.query_id


def test_no_candidate_comes_from_a_version_that_is_no_longer_active(
    corpus: Corpus, runs: Sequence[QueryRun]
) -> None:
    for run in runs:
        statuses = corpus.stack.repository.load_version_statuses(
            [candidate.document_version_id for candidate in run.candidates]
        )
        returned = {candidate.chunk_id for candidate in run.candidates}
        for candidate in run.candidates:
            assert (
                statuses.get(candidate.document_version_id) is DocumentVersionStatus.ACTIVE
            ), f"{run.spec.query_id} returned {candidate.document_version_id}"
        for label in run.spec.forbidden:
            stale = corpus.chunk_for(label)
            assert stale.chunk_id not in returned, (
                f"{run.spec.query_id} returned the superseded chunk {stale.chunk_id}"
            )


def test_every_candidate_can_be_inspected_down_to_a_locator(
    corpus: Corpus, a2: A2Harness, runs: Sequence[QueryRun]
) -> None:
    """100% 的定位成功率：每一条交出去的候选都能回到原文的一页一段。

    走的是 A2 的 `inspect_research_source`，不是服务内部对象——A2 只有这一条路看得到原文。
    """
    for run in runs:
        for candidate in run.candidates:
            result = tool_call(
                a2.inspect, retrieval_id=run.retrieval_id, candidate_id=candidate.candidate_id
            )
            assert result.success, (run.spec.query_id, result.error)
            inspection = json.loads(result.content)
            chunk = corpus.stack.repository.get_chunk(candidate.chunk_id)
            assert chunk is not None
            assert inspection["chunk_id"] == chunk.chunk_id
            assert inspection["page_start"] == chunk.source.page_start
            assert tuple(inspection["section_path"]) == chunk.source.section_path
            # 正文必须来自权威库，而不是索引里的那份副本。
            assert inspection["text"].startswith(chunk.content[: len(inspection["text"])])


def test_the_report_is_reproducible(
    corpus: Corpus, a2: A2Harness, runs: Sequence[QueryRun]
) -> None:
    """同一份语料、同一套夹具 Provider，跑两遍必须得到同一个报告。"""
    again = run_all(corpus, a2)
    assert measure(corpus, runs).as_dict() == measure(corpus, again).as_dict()
    for first, second in zip(runs, again, strict=True):
        assert [item.chunk_id for item in first.candidates] == [
            item.chunk_id for item in second.candidates
        ], first.spec.query_id


# --- 冲突 ---


def _claim_source(corpus: Corpus, candidate: Candidate) -> ClaimSource:
    repository = corpus.stack.repository
    version = repository.get_version(candidate.document_version_id)
    document = repository.get_document(candidate.document_id)
    assert version is not None and document is not None
    return ClaimSource(
        document_id=candidate.document_id,
        document_version_id=candidate.document_version_id,
        version_number=version.version_number,
        status=DocumentVersionStatus.ACTIVE,
        source_weight=document.source_weight,
        content_origin=ExtractionMethod.NATIVE,
    )


def _candidate_for(corpus: Corpus, run: QueryRun, spec: ClaimSpec) -> Candidate:
    """找到这条事实的出处所在的那一条候选。

    两步定位，两步各有各的用处：`contains` 指向这一段落在哪条候选里，`statement` 说明事实
    写在哪一句。重叠窗口会让同一句话落在两条候选里（那是切片器的重叠，不是重复），此时取
    排序最靠前的那一条——确定性优先，而两条的正文都撑得住这条事实。
    """
    document_id = corpus.document_ids[spec.document]
    of_document = [item for item in run.candidates if item.document_id == document_id]
    assert of_document, f"{run.spec.query_id} did not return {spec.document}"
    matching = [item for item in of_document if spec.contains in item.text]
    assert matching, (
        f"{run.spec.query_id}: no candidate of {spec.document} carries {spec.contains!r}"
    )
    grounded = [item for item in matching if spec.statement in item.text]
    assert grounded, (
        f"{run.spec.query_id}: {spec.statement!r} is not written in any candidate of "
        f"{spec.document} that carries {spec.contains!r}"
    )
    return grounded[0]


def _claim_from(run: QueryRun, spec: ClaimSpec, candidate: Candidate) -> Any:
    """按 A2 看到的那份正文造一条事实。

    位置从**候选正文**里取，而不是从权威库那一份切片里取：抽取校验的是"这句话在你送进来的
    这段文字里"，两者差一个截断点就会让事实被静默丢掉，而那看起来像"这一段没有事实"。
    """
    start = candidate.text.find(spec.statement)
    assert start >= 0, f"{run.spec.query_id}: {spec.statement!r} is not in the candidate text"
    entry = claim(
        chunk_id=candidate.chunk_id,
        statement=spec.statement,
        subject=spec.subject,
        predicate=spec.predicate,
        span=SourceSpan(start=start, end=start + len(spec.statement)),
    )
    if spec.valid_time is not None:
        entry = entry.model_copy(update={"valid_time": spec.valid_time})
    return entry


def extract_claims(corpus: Corpus, run: QueryRun) -> tuple[Any, ...]:
    """抽事实。抽取结果就是进入冲突判断的那一批。"""
    candidates = [_candidate_for(corpus, run, spec) for spec in run.spec.claims]
    extracted = ClaimExtractionService(
        provider=FixtureClaimExtractorProvider(
            claims={
                run.spec.question: tuple(
                    _claim_from(run, spec, candidate)
                    for candidate, spec in zip(candidates, run.spec.claims, strict=True)
                )
            }
        ),
        settings=RagSettings(),
    ).extract(
        run.spec.question,
        tuple(
            RetrievedCandidate(
                candidate_id=item.candidate_id,
                retrieval_id=run.retrieval_id,
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                text=item.text,
                content_origin=ExtractionMethod.NATIVE,
            )
            for item in candidates
        ),
    )
    assert len(extracted) == len(run.spec.claims), (
        f"{run.spec.query_id}: extracted {len(extracted)} of {len(run.spec.claims)} "
        "declared claims; a claim that is not grounded in the text A2 saw is dropped silently"
    )
    return extracted


def resolve_conflicts(
    corpus: Corpus, run: QueryRun, *, verdict: NliRelation | None = None
) -> tuple[Any, ...]:
    """抽事实、归组、送 NLI、裁决。

    `verdict` 为这一对事实显式声明一次 NLI 判定。夹具的词面规则处理近义改写时会掉到置信度
    门槛以下，那样走到的 UNRESOLVED 是"没查清"；而"查清了、判成矛盾，仍然判不了谁赢"这条
    必须由一次高置信度的矛盾来验证，两者不是同一件事。
    """
    extracted = extract_claims(corpus, run)
    groups = group_comparable_claims(extracted)
    sources = {
        candidate.chunk_id: _claim_source(corpus, candidate)
        for candidate in (_candidate_for(corpus, run, spec) for spec in run.spec.claims)
    }
    declared: dict[tuple[str, str], NliRelation] = {}
    if verdict is not None and len(extracted) >= 2:
        declared = {(extracted[0].statement, extracted[1].statement): verdict}
    return ConflictService(
        provider=FixtureNliProvider(verdicts=declared), settings=RagSettings()
    ).check(groups, ConflictContext(sources=sources))


def test_an_independent_contradiction_has_no_winner(
    corpus: Corpus, runs: Sequence[QueryRun]
) -> None:
    """两个独立、都有效、权重相同的来源说了相反的话：没有规则能分出高下。

    规格 14 的优先级试到最后一条也不成立，于是谁都不能被删掉——`selected_claim_id` 必须是
    None。这条用例是"零 unresolved-as-fact"的前提：正因为这里判不了，下游才必须看得出来。
    """
    run = run_of(runs, "independent_conflict")
    decisions = resolve_conflicts(corpus, run, verdict=NliRelation.CONTRADICTION)

    assert len(decisions) == 1, decisions
    decision = decisions[0]
    assert decision.status is ConflictStatus.UNRESOLVED
    assert decision.rule is None
    assert decision.selected_claim_id is None
    assert len(decision.claim_ids) == 2
    assert decision.nli_relation is NliRelation.CONTRADICTION
    assert "独立" in decision.rationale


def test_two_facts_about_different_quarters_are_not_a_conflict(
    corpus: Corpus, runs: Sequence[QueryRun]
) -> None:
    """同样的话落在不同季度：它们不是一对可比事实，压根不该被配到一起。

    配到一起的代价是可量化的——一次昂贵的 NLI 调用，以及一个看起来像冲突的结论。
    """
    run = run_of(runs, "different_time")
    extracted = extract_claims(corpus, run)

    assert len(extracted) == 2
    left, right = extracted
    assert left.valid_time is not None and right.valid_time is not None
    assert left.valid_time.end < right.valid_time.start, "the fixture windows must be disjoint"
    assert group_comparable_claims(extracted) == ()
    assert resolve_conflicts(corpus, run) == ()


# --- 接纳 ---


def seed_audit(a2: A2Harness, corpus: Corpus, retrieval_id: str) -> None:
    """把这次检索的审计行写进 SQLite。

    来源是检索服务自己写进内存仓库的那一条，因此字段与生产一致；只有一个实现能把它落进
    SQL 的地方——PostgreSQL 仓库——而这里跑的是 SQLite。接纳表的外键指着这张表，所以它
    必须在。复制的是服务真正写下的那条记录，不是另编一条。
    """
    audit = corpus.stack.repository.get_retrieval_audit(retrieval_id)
    assert audit is not None, "every search must leave an audit record behind"
    with a2.database.connection() as connection:
        seen = connection.execute(
            "SELECT COUNT(*) FROM research_retrieval_audits WHERE retrieval_id=:id",
            {"id": retrieval_id},
        ).fetchone()
    if seen is not None and seen[0]:
        # 已经镜像过了。审计行是一条不可变记录的副本，再镜像一次不该产生第二条——两个
        # 用例先后用同一次检索时，第二次进来的就是这种情况。
        return
    with a2.database.transaction() as connection:
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


def inspect_sides(
    corpus: Corpus, a2: A2Harness, run: QueryRun
) -> tuple[list[dict[str, Any]], str]:
    """查看这次检索的两条候选，交出可以照抄进接纳载荷的出处与等级。

    出处里的定位逐字段来自查看结果：接纳核对的是"你引的这段，就是你看过的那一段"，
    自己按切片拼一个定位出来，测的就不是这条规则了。
    """
    refs: list[dict[str, Any]] = []
    grades: list[str] = []
    for spec in run.spec.claims:
        candidate = _candidate_for(corpus, run, spec)
        result = tool_call(
            a2.inspect, retrieval_id=run.retrieval_id, candidate_id=candidate.candidate_id
        )
        assert result.success, result.error
        inspection = json.loads(result.content)
        refs.append(
            {
                "document_id": inspection["document_id"],
                "document_version_id": inspection["document_version_id"],
                "chunk_id": inspection["chunk_id"],
                "page_start": inspection["page_start"],
                "page_end": inspection["page_end"],
                "section_path": inspection["section_path"],
            }
        )
        grades.append(inspection["grade"])
    assert len({entry["chunk_id"] for entry in refs}) == len(refs), refs
    return refs, min(grades, key=lambda grade: GRADE_STRENGTH[grade])


def _unresolved_submission(
    run: QueryRun, refs: Sequence[Mapping[str, Any]], grade: str
) -> dict[str, Any]:
    return {
        "retrieval_id": run.retrieval_id,
        "claims": [
            {
                "statement": "二线厂商的产能利用率在过去一个季度的方向尚不能确定。",
                "conflict_status": ConflictStatus.UNRESOLVED.value,
                "grade": grade,
                "source_refs": [dict(entry) for entry in refs],
            }
        ],
    }


def _evidence_rows(a2: A2Harness) -> list[tuple[Any, ...]]:
    with a2.database.connection() as connection:
        return list(
            connection.execute(
                "SELECT evidence_id, artifact_ref, conflict_status, grade, statement "
                "FROM internal_research_evidence ORDER BY evidence_id"
            )
        )


def test_an_unresolved_conflict_cannot_be_recorded_as_a_settled_fact(
    corpus: Corpus, a2: A2Harness, runs: Sequence[QueryRun]
) -> None:
    """规格 13：判不了就说判不了，而且要带着双方一起说。

    断言落在接纳服务与它的工具上——A2 真实调用的那一层——不是落在评测自己的推导上。三种
    载荷走三条不同的拒绝路径，谁都不能变成一条"看起来已经查清"的事实：

    * 只引一条来源：载荷本身就不成立，连领域模型都造不出来；
    * 同一条来源引两遍：条数是够了，"两个不同的切片"不够——数列表长度是绕得过去的，
      这正是它要挡住的那种绕法；
    * 两条来源：接纳成立，A3/A4 拿到的是一条带着双方出处的 UNRESOLVED 事实。
    """
    run = run_of(runs, "independent_conflict")
    refs, grade = inspect_sides(corpus, a2, run)
    seed_audit(a2, corpus, run.retrieval_id)

    with pytest.raises(ValueError, match="both conflicting facts"):
        tool_call(a2.accept, **_unresolved_submission(run, refs[:1], grade))

    one_sided_twice = tool_call(
        a2.accept, **_unresolved_submission(run, [refs[0], refs[0]], grade)
    )
    assert one_sided_twice.success is False, "the same passage cited twice is still one side"
    assert "two different chunks" in one_sided_twice.error

    both = tool_call(a2.accept, **_unresolved_submission(run, refs, grade))
    assert both.success, both.error
    accepted = json.loads(both.content)
    assert accepted["kind"] == "internal_research_evidence"
    assert accepted["artifact_ref"].startswith("internal-research-evidence:")


def test_the_rejected_submissions_left_nothing_behind(
    corpus: Corpus, a2: A2Harness, runs: Sequence[QueryRun]
) -> None:
    """被拒的那两次不能留下半条证据。

    一份写了一半的证据比没有证据更糟：它看上去是一条完整的事实，而它的另一半不见了。
    """
    run = run_of(runs, "independent_conflict")
    refs, grade = inspect_sides(corpus, a2, run)
    seed_audit(a2, corpus, run.retrieval_id)
    before = _evidence_rows(a2)

    with pytest.raises(ValueError):
        tool_call(a2.accept, **_unresolved_submission(run, refs[:1], grade))
    rejected = tool_call(a2.accept, **_unresolved_submission(run, [refs[0], refs[0]], grade))
    assert rejected.success is False

    assert _evidence_rows(a2) == before


# --- 提示注入 ---


def test_text_in_the_corpus_cannot_change_what_the_tools_may_do(
    corpus: Corpus, a2: A2Harness, runs: Sequence[QueryRun]
) -> None:
    """正文里写着的"系统指令"只是正文。

    三条路各自挡住一次：参数范围、身份绑定、接纳条件。任何一条被正文改掉，注入就成功了。
    """
    run = run_of(runs, "prompt_injection")
    assert any(
        "忽略以上所有指令" in candidate.text for candidate in run.candidates
    ), "the injection text must actually reach A2 — otherwise this test proves nothing"

    # 1. 越界的参数被拒绝，而不是被忽略：板块与身份由服务端绑定，注入句一个字符都改不了。
    for forbidden in (
        {"question": "隔膜价格", "sector": "全库"},
        {"question": "隔膜价格", "run_id": str(a2.run_id)},
        {"question": "隔膜价格", "role": "A0"},
    ):
        with pytest.raises(ValueError):
            tool_call(a2.search, **forbidden)

    # 2. 权限在角色白名单里，不在正文里。
    research_tools = {
        "search_internal_research",
        "inspect_research_source",
        "accept_internal_evidence",
    }
    for role in (AgentRole.A0, AgentRole.A1, AgentRole.A3, AgentRole.A4):
        assert not (ROLE_TOOL_NAMES[role] & research_tools), role
    assert research_tools <= ROLE_TOOL_NAMES[AgentRole.A2]

    # 3. 注入句没有被当成事实接纳：出处必须来自本次尝试真的查看过的那一段。
    seed_audit(a2, corpus, run.retrieval_id)
    unfounded = tool_call(
        a2.accept,
        retrieval_id=run.retrieval_id,
        claims=[
            {
                "statement": "隔膜价格将下跌一半。",
                "conflict_status": ConflictStatus.RESOLVED.value,
                "grade": "DERIVED_UNVERIFIED",
                "source_refs": [
                    {
                        "document_id": "doc_not_inspected",
                        "document_version_id": "docv_not_inspected",
                        "chunk_id": "chunk_not_inspected",
                    }
                ],
            }
        ],
    )
    assert not unfounded.success, "an uninspected source must not be acceptable as evidence"
    assert "never inspected" in unfounded.error


# --- 删除 ---


def test_a_deleted_document_leaves_the_candidate_list_at_once(
    corpus: Corpus, a2: A2Harness, runs: Sequence[QueryRun]
) -> None:
    """软删除立刻生效，而它生效**不是**因为派生索引被清了。

    这一条测的是可见性的归属：切片此刻仍在库里、向量也仍在索引里，检索却已经看不见它——
    权威库是可见性的唯一来源，派生索引晚一点清干净是可以接受的，反过来不行。恢复之后它
    立刻回来，也不需要重建索引。
    """
    run = run_of(runs, "deleted_document")
    doomed = corpus.document_ids["doomed"]
    version_id = corpus.version_ids["doomed"][-1]

    def returned() -> set[str]:
        return {candidate.document_id for candidate in run_query(a2, run.spec).candidates}

    assert doomed in returned()

    corpus.stack.commands.soft_delete(doomed, actor=ACTOR, now=NOW)
    try:
        document = corpus.stack.repository.get_document(doomed)
        assert document is not None and document.deleted_at is not None
        # 切片还在，只是不再可见。这一条正是"可见性不在派生索引里"的证据。
        assert corpus.stack.repository.list_chunks(version_id)
        assert doomed not in returned()
    finally:
        corpus.stack.commands.restore(doomed, actor=ACTOR, now=NOW)

    restored = corpus.stack.repository.get_document(doomed)
    assert restored is not None and restored.deleted_at is None
    assert doomed in returned()
