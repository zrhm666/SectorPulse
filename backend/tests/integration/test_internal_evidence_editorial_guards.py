"""What A3 and A4 may do with accepted internal evidence, and what they may not (spec 15.3-15.5).

Two classes of property are checked here, and they are checked differently on purpose:

- The Skill mapping is a claim about *production files*: it asserts that the two internal-research
  method documents exist, that exactly the roles the spec names can load them, and that neither
  document carries credentials, endpoints, or store operations.
- The editorial guards are claims about *deterministic findings*: a draft whose citations are no
  longer active, whose unresolved conflict reads as settled, or whose only support still awaits
  verification must produce a named finding rather than prose advice. The tests assert the code
  and the blocking behaviour, because a warning nobody must act on is not a guard.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

pytest.importorskip("aidynamic_agent")

from sector_pulse.application.orchestration.editorial_tools import SubmitDraftService
from sector_pulse.application.research_library.artifacts import EVIDENCE_ARTIFACT_KIND
from sector_pulse.application.research_library.evidence_access import AcceptedEvidenceIndex
from sector_pulse.application.writing.draft_quality import (
    INTERNAL_SOURCE_INACTIVE,
    UNRESOLVED_CONFLICT_STATED_AS_FACT,
    UNVERIFIED_ONLY_SUPPORT,
    internal_evidence_issues,
)
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.news.evidence import EvidenceLevel
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.domain.research_library.retrieval import (
    AcceptedEvidenceClaim,
    ClaimStance,
    ConflictStatus,
    EvidenceGrade,
    EvidenceSourceRef,
    InternalEvidenceClaim,
)
from sector_pulse.domain.review.review import (
    IssueSeverity,
    ReviewDecision,
    ReviewReport,
)
from sector_pulse.domain.writing.article import (
    ArticleDraft,
    ArticleSection,
    DraftStatus,
)
from sector_pulse.domain.writing.attribution import Claim, ClaimKind, SectorAnalysisCard
from sector_pulse.domain.writing.editorial import (
    ArticleDraftSubmission,
    ArticleOutline,
    ArticleSectionSubmission,
    EditorialOutlineArtifact,
)
from sector_pulse.infrastructure.agents.reference_artifact_reader import (
    MAX_RENDERED_CLAIMS,
    ReferenceArtifactReader,
)
from sector_pulse.infrastructure.agents.roles import (
    ROLE_SKILL_NAMES,
    AgentRole,
    role_skill_managers,
)
from sector_pulse.infrastructure.agents.skills import AllowedSkillManager
from sector_pulse.storage.sqlite.research_library.evidence_repository import (
    SQLiteAcceptedEvidenceRepository,
)

from backend.tests.integration import test_internal_research_evidence_artifact as corpus
from backend.tests.integration.test_orchestration_editorial_context import (
    build_editorial_context,
)
from backend.tests.integration.test_orchestration_review_tools import build_review_context

SKILLS_ROOT = Path("config/agent-skills")
RETRIEVAL_SKILL = "internal-research-retrieval"
WRITING_SKILL = "internal-evidence-writing"
INTERNAL_SKILLS = (RETRIEVAL_SKILL, WRITING_SKILL)

HANDLE = "internal-research-evidence:one"
VERSION = "ver_0001"


def load(name: str) -> str:
    manager = AllowedSkillManager(SKILLS_ROOT, allowed_names=frozenset({name}))
    text = manager.load_full_text_with_path_hint(name)
    assert text, f"{name} must be loadable from {SKILLS_ROOT}"
    return text


# --- Skill 映射 -------------------------------------------------------------


def test_only_the_roles_the_spec_names_can_load_the_internal_research_skills():
    assert ROLE_SKILL_NAMES[AgentRole.A2] >= {RETRIEVAL_SKILL}
    assert ROLE_SKILL_NAMES[AgentRole.A3] >= {WRITING_SKILL}
    assert ROLE_SKILL_NAMES[AgentRole.A4] >= {WRITING_SKILL}
    assert set(INTERNAL_SKILLS).isdisjoint(ROLE_SKILL_NAMES[AgentRole.A1])
    # A0 没有 Skill：它只做委派、选择与收尾，不写也不审。
    assert AgentRole.A0 not in ROLE_SKILL_NAMES


def test_every_mapped_skill_exists_and_is_reachable_by_its_role():
    """白名单里写着一个不存在的目录时，那个角色会静默地没有这份方法。"""
    for role, names in ROLE_SKILL_NAMES.items():
        manager = AllowedSkillManager(SKILLS_ROOT, allowed_names=names)
        assert {item["name"] for item in manager.describe_available()} == set(names), role


def test_the_retrieval_skill_teaches_the_two_uncertainty_rules_it_is_for():
    text = load(RETRIEVAL_SKILL)
    assert "unresolved" in text.lower()
    assert "grade" in text.lower()
    assert "do not" in text.lower()


def test_the_writing_skill_teaches_versions_conflicts_and_leads():
    text = load(WRITING_SKILL)
    assert "unresolved conflict" in text.lower()
    assert "requir" in text.lower()  # requires verification
    assert "version" in text.lower()


@pytest.mark.parametrize("name", INTERNAL_SKILLS)
def test_the_internal_research_skills_carry_no_credentials_or_store_operations(name):
    text = load(name)
    lowered = text.lower()
    for forbidden in (
        "minio",
        "milvus",
        "s3://",
        "http://",
        "https://",
        "bucket",
        "select ",
        "insert ",
        "password",
        "secret",
        "api_key",
        "token",
        "endpoint",
    ):
        assert forbidden not in lowered, (name, forbidden)
    # 两份都是方法，不是权限：不能说它们自己批准、发布或改变工具。
    assert "this skill supplies" in lowered


def test_one_helper_turns_the_mapping_into_managers_with_exactly_those_names():
    managers = role_skill_managers()
    assert set(managers) == set(ROLE_SKILL_NAMES)
    for role, manager in managers.items():
        names = {item["name"] for item in manager.describe_available()}
        assert names == set(ROLE_SKILL_NAMES[role]), role


def test_the_parent_runtime_hands_each_role_the_managers_the_mapping_names(tmp_path):
    """映射写对了但运行时没照它建管理器，等于没写；这里走真实构造路径核对。"""
    from sector_pulse.application.orchestration.controls import (
        CompletionGoal,
        RequiredArtifactsFinalizationPolicy,
    )
    from sector_pulse.application.orchestration.runtime import OrchestrationRunStarter
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.infrastructure.agents.runtime import ParentAgentRuntime
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "skill-wiring.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    config = load_llm_config(Path("config/llm.yaml"))
    run_id, root_id = uuid4(), uuid4()
    OrchestrationRunStarter(repository, config).start(
        run_id=run_id,
        task_id=root_id,
        worker_id="root-worker",
        goal="full analysis",
        now=datetime.now(UTC),
    )

    class Reader:
        def read(self, artifact, *, max_chars):
            raise AssertionError("this test never reads an artifact body")

    runtime = ParentAgentRuntime(
        repository=repository,
        run_id=run_id,
        root_task_id=root_id,
        root_attempt=1,
        root_worker_id="root-worker",
        config=config,
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_builder=lambda role, configured: None,
        business_tool_builders={},
        tool_reserved_cny={},
        artifact_reader=Reader(),
        finalization_policy=RequiredArtifactsFinalizationPolicy(
            goal=CompletionGoal.FULL_ANALYSIS,
            required_analysis_scopes=("industry:1",),
            is_current=lambda artifact: True,
        ),
    )

    wired = runtime.factory.skill_managers
    assert set(wired) == set(ROLE_SKILL_NAMES)
    for role, manager in wired.items():
        names = {item["name"] for item in manager.describe_available()}
        assert names == set(ROLE_SKILL_NAMES[role]), role


# --- 已接纳证据读进草稿的那条通道（规格 15.2-15.4） ---------------------------


def _accepted_evidence(tmp_path: Any, *statements: str, **claim_fields: Any) -> tuple[Any, Any]:
    """跑一次真实的接纳：检索 → 检视 → 接纳，返回（语料库, 证据 Artifact）。

    这里的行不是手写进去的，而是接纳服务写出来的——读取端要读的正是它写的那几张表。
    """
    corpus_harness = corpus.harness(tmp_path)
    context, retrieval_id, _inspection, source = corpus.accepted(corpus_harness)
    artifact = corpus_harness.service.accept(
        context,
        worker_id=corpus.WORKER,
        evidence=corpus.evidence(
            retrieval_id,
            *(
                corpus.claim(statement=text, sources=[source], **claim_fields)
                for text in statements
            ),
        ),
    )
    return corpus_harness, artifact


def test_the_reader_renders_accepted_evidence_as_locatable_facts_and_not_the_document(tmp_path):
    corpus_harness, artifact = _accepted_evidence(tmp_path, "海外储能需求在第二季度改善")

    content = ReferenceArtifactReader(
        evidence=SQLiteAcceptedEvidenceRepository(corpus_harness.database)
    ).read(artifact, max_chars=4000)

    assert "海外储能需求在第二季度改善" in content.summary
    # 定位要够 A3/A4 自己回去核对：文档、版本、分块、页码、章节路径。
    for locator in (
        "doc=doc_0001",
        "version=ver_0001",
        "chunk=c_1",
        "p18",
        "section=海外需求",
        "grade=PRIMARY_SOURCE",
        "conflict=RESOLVED",
        "requires_verification=no",
    ):
        assert locator in content.summary, locator
    assert content.summary.count("cite=") == 1

    data = dict(content.data or {})
    assert [item["statement"] for item in data["claims"]] == ["海外储能需求在第二季度改善"]
    assert data["claims_truncated"] is False

    # 正文、对象键、内部下载地址都不出现（规格 15.2）。
    rendered = (content.summary + json.dumps(data, ensure_ascii=False)).lower()
    for forbidden in (
        corpus.CORPUS_TEXT.lower(),
        "s3://",
        "minio",
        "bucket",
        "http://",
        "https://",
    ):
        assert forbidden not in rendered, forbidden


def test_a_long_evidence_artifact_is_rendered_bounded_and_says_what_it_left_out(tmp_path):
    statements = [f"第 {index} 条可核对事实" for index in range(1, MAX_RENDERED_CLAIMS + 2)]
    corpus_harness, artifact = _accepted_evidence(tmp_path, *statements)

    reader = ReferenceArtifactReader(
        evidence=SQLiteAcceptedEvidenceRepository(corpus_harness.database)
    )
    content = reader.read(artifact, max_chars=8000)

    assert content.summary.count("cite=") == MAX_RENDERED_CLAIMS
    assert "further claim(s) omitted" in content.summary
    data = dict(content.data or {})
    assert data["claims_truncated"] is True
    assert len(data["claims"]) == MAX_RENDERED_CLAIMS

    # 渲染出来的每一行都是要进模型上下文的，超了就是超了。
    assert len(reader.read(artifact, max_chars=300).summary) <= 300


def test_only_the_evidence_kind_has_content_and_only_when_a_reader_is_wired(tmp_path):
    corpus_harness, artifact = _accepted_evidence(tmp_path, "海外储能需求在第二季度改善")

    other = ArtifactRef(
        artifact_id=uuid4(),
        task_id=uuid4(),
        kind="sector_analysis",
        reference="sector-analysis:whatever",
    )
    content = ReferenceArtifactReader(
        evidence=SQLiteAcceptedEvidenceRepository(corpus_harness.database)
    ).read(other, max_chars=4000)
    assert content.summary == "sector_analysis: sector-analysis:whatever"
    assert content.data is not None
    assert "claims" not in content.data

    # 没接读取端时证据 Artifact 也只是元数据：没有内容不等于默认通过。
    bare = ReferenceArtifactReader().read(artifact, max_chars=4000)
    assert bare.data is not None
    assert "claims" not in bare.data


def _seed_version(database: Any, *, status: str = "ACTIVE", version_id: str = VERSION) -> None:
    """把版本行写进权威库。

    `research_document_versions` 由 PostgreSQL 的资料库仓库写入；SQLite 上还没有那个端口的
    实现，所以这里按迁移 035 的约束直接播种一行——"这个版本还在不在架"问的正是这张表。
    """
    with database.transaction() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO research_documents (document_id, title, document_type, "
            "created_at) VALUES (?, ?, 'report', ?)",
            ("doc_0001", "doc_0001 标题", corpus.NOW.isoformat()),
        )
        connection.execute(
            "INSERT OR REPLACE INTO research_document_versions (document_version_id, "
            "document_id, version_number, status, uploaded_at, original_file_hash, "
            "index_generation, indexed_at, expected_chunk_count) "
            "VALUES (?, 'doc_0001', 1, ?, ?, ?, ?, ?, 1)",
            (version_id, status, corpus.NOW, f"hash_{version_id}", corpus.GENERATION, corpus.NOW),
        )


def test_a_version_that_left_the_corpus_is_no_longer_active(tmp_path):
    corpus_harness, artifact = _accepted_evidence(tmp_path, "海外储能需求在第二季度改善")
    repository = SQLiteAcceptedEvidenceRepository(corpus_harness.database)
    _seed_version(corpus_harness.database)

    claims = repository.get_accepted_evidence((artifact.reference,))
    assert len(claims) == 1
    assert claims[0].document_version_ids == (VERSION,)
    # 只读被问到的那份 Artifact：别的引用和空请求都不该带回任何一行。
    assert repository.get_accepted_evidence(("internal-research-evidence:other",)) == ()
    assert repository.get_accepted_evidence(()) == ()
    assert repository.load_active_version_ids((VERSION,)) == frozenset({VERSION})

    with corpus_harness.database.transaction() as connection:
        connection.execute(
            "UPDATE research_document_versions SET status = 'SUPERSEDED' "
            "WHERE document_version_id = :version",
            {"version": VERSION},
        )
    assert repository.load_active_version_ids((VERSION,)) == frozenset()


def test_the_index_reads_the_current_attempt_and_answers_whether_a_handle_stands(tmp_path):
    corpus_harness, artifact = _accepted_evidence(tmp_path, "海外储能需求在第二季度改善")
    repository = SQLiteAcceptedEvidenceRepository(corpus_harness.database)
    _seed_version(corpus_harness.database)
    snapshot = corpus_harness.orchestration.load(corpus_harness.run_id)
    assert snapshot is not None

    index = AcceptedEvidenceIndex.load(snapshot=snapshot, repository=repository)
    evidence_id = next(iter(index.claims))
    assert index.is_citable(evidence_id)
    # 查不到就是站不住，不是"无法判断"。
    assert index.is_citable("never-accepted") is False
    assert index.cited_versions() == (VERSION,)
    stored = index.get(evidence_id)
    assert stored is not None
    assert stored.claim.statement == "海外储能需求在第二季度改善"

    # 重试推进 attempt 之后，上一轮留下的 Artifact 还在快照里，却不再是新引用的来源。
    retried = snapshot.model_copy(
        update={
            "tasks": tuple(
                item.model_copy(update={"attempt": item.attempt + 1})
                if item.task_id == artifact.task_id
                else item
                for item in snapshot.tasks
            )
        }
    )
    assert AcceptedEvidenceIndex.load(snapshot=retried, repository=repository).claims == {}


# --- 草稿里引用内部证据时的确定性结论 -----------------------------------------


def _accepted_claim(
    *,
    conflict_status: ConflictStatus = ConflictStatus.RESOLVED,
    requires_verification: bool = False,
) -> AcceptedEvidenceClaim:
    return AcceptedEvidenceClaim(
        evidence_id=HANDLE,
        artifact_ref=HANDLE,
        claim=InternalEvidenceClaim(
            statement="海外储能需求在第二季度改善",
            stance=ClaimStance.SUPPORTING,
            conflict_status=conflict_status,
            grade=EvidenceGrade.PRIMARY_SOURCE,
            requires_verification=requires_verification,
            source_refs=(
                EvidenceSourceRef(
                    document_id="doc_0001",
                    document_version_id=VERSION,
                    chunk_id="c_1",
                    page_start=18,
                    page_end=18,
                    section_path=("海外需求",),
                ),
            ),
        ),
    )


def _index(
    *claims: AcceptedEvidenceClaim,
    active: tuple[str, ...] = (VERSION,),
) -> AcceptedEvidenceIndex:
    return AcceptedEvidenceIndex(
        claims={item.evidence_id: item for item in claims},
        active_version_ids=frozenset(active),
    )


def _draft_citing(
    evidence_ids: tuple[str, ...],
    *,
    kind: ClaimKind = ClaimKind.NEWS_FACT,
) -> tuple[ArticleDraft, dict[str, SectorAnalysisCard]]:
    """一个板块的草稿，其中一条事实引用了给定句柄。"""
    run_id = uuid4()
    card = SectorAnalysisCard(
        run_id=run_id,
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        sector_name="板块一",
        allowed_max_level=EvidenceLevel.MARKET_ASSOCIATION,
        attribution_level=EvidenceLevel.MARKET_ASSOCIATION,
        confidence=Decimal("0.6"),
        conclusion="存在市场联想",
        supporting_evidence_ids=("event-1",),
        counter_evidence=(),
        uncertainties=(),
        background_event_ids=(),
        claims=(),
        forbidden_inferences=(),
    )
    draft = ArticleDraft(
        draft_id=uuid4(),
        run_id=run_id,
        version=1,
        status=DraftStatus.UNREVIEWED,
        titles=("板块一观察",),
        introduction="导语",
        sections=(
            ArticleSection(
                section_id="section-1",
                sector_id="sector-1",
                heading="板块一：证据边界内观察",
                body="板块一的需求变化需要结合已核验信息观察。",
                claims=(
                    Claim(
                        claim_id="claim-1",
                        kind=kind,
                        text="板块一的需求改善可以核对",
                        evidence_ids=evidence_ids,
                    ),
                ),
                source_ids=evidence_ids,
                character_count=21,
            ),
        ),
        conclusion="结语",
        risk_notice="市场有风险，本文不构成投资建议。",
        sources=(),
        character_count=1400,
    )
    return draft, {"sector-1": card}


def test_citing_accepted_internal_evidence_is_not_a_finding_by_itself():
    draft, cards = _draft_citing((HANDLE,))
    assert internal_evidence_issues(draft, cards, _index(_accepted_claim())) == ()


def test_a_version_that_left_the_corpus_blocks_every_citation_of_it():
    draft, cards = _draft_citing((HANDLE,))
    issues = internal_evidence_issues(draft, cards, _index(_accepted_claim(), active=()))
    assert [item.code for item in issues] == [INTERNAL_SOURCE_INACTIVE]
    assert issues[0].severity is IssueSeverity.BLOCKING
    assert issues[0].claim_id == "claim-1"


def test_a_handle_nobody_accepted_is_as_unusable_as_an_inactive_version():
    draft, cards = _draft_citing(("internal-research-evidence:never-accepted",))
    issues = internal_evidence_issues(draft, cards, _index(_accepted_claim()))
    assert [item.code for item in issues] == [INTERNAL_SOURCE_INACTIVE]


@pytest.mark.parametrize(
    "conflict_status", [ConflictStatus.UNRESOLVED, ConflictStatus.CHECK_FAILED]
)
def test_an_open_conflict_written_as_a_conclusion_is_a_blocking_finding(conflict_status):
    draft, cards = _draft_citing((HANDLE,))
    issues = internal_evidence_issues(
        draft, cards, _index(_accepted_claim(conflict_status=conflict_status))
    )
    assert [item.code for item in issues] == [UNRESOLVED_CONFLICT_STATED_AS_FACT]
    # 这不是建议：A4 拿着它连一份 PASS 的评审都构造不出来。
    with pytest.raises(ValueError, match="blocking issues"):
        ReviewReport(
            review_id="review-1",
            draft_id=str(draft.draft_id),
            draft_version=1,
            decision=ReviewDecision.PASS,
            issues=issues,
            revision_round=0,
        )


def test_a_background_claim_may_rest_on_an_unresolved_source():
    draft, cards = _draft_citing((HANDLE,), kind=ClaimKind.BACKGROUND)
    assert (
        internal_evidence_issues(
            draft, cards, _index(_accepted_claim(conflict_status=ConflictStatus.UNRESOLVED))
        )
        == ()
    )


def test_a_conclusion_resting_only_on_unverified_evidence_is_flagged():
    draft, cards = _draft_citing((HANDLE,))
    issues = internal_evidence_issues(
        draft, cards, _index(_accepted_claim(requires_verification=True))
    )
    assert [item.code for item in issues] == [UNVERIFIED_ONLY_SUPPORT]
    assert issues[0].severity is IssueSeverity.BLOCKING


def test_a_conclusion_that_also_leans_on_a_news_event_is_supported_enough():
    draft, cards = _draft_citing(("event-1", HANDLE))
    assert (
        internal_evidence_issues(
            draft, cards, _index(_accepted_claim(requires_verification=True))
        )
        == ()
    )


def test_a_draft_that_cites_no_internal_evidence_sees_no_change():
    draft, cards = _draft_citing(("event-1",))
    assert internal_evidence_issues(draft, cards, _index(_accepted_claim())) == ()
    # 空索引是常态而不是异常：没接内部资料库的运行就是这样。
    assert internal_evidence_issues(draft, cards, AcceptedEvidenceIndex()) == ()


# --- 门口那道闸：A3 提交、A4 复核 ---------------------------------------------


class _AcceptedEvidence:
    """端口的两个方法。真实行由上面那几个跑真 SQL 仓库的测试负责。"""

    def __init__(
        self, *claims: AcceptedEvidenceClaim, active: tuple[str, ...] = (VERSION,)
    ) -> None:
        self._claims = tuple(claims)
        self._active = frozenset(active)

    def get_accepted_evidence(self, artifact_references: Any) -> tuple[AcceptedEvidenceClaim, ...]:
        wanted = set(artifact_references)
        return tuple(item for item in self._claims if item.artifact_ref in wanted)

    def load_active_version_ids(self, document_version_ids: Any) -> frozenset[str]:
        del document_version_ids
        return self._active


class _Committing:
    def __init__(self, *, refuse: bool = False) -> None:
        self.refuse = refuse
        self.committed: list[ArtifactRef] = []
        self.persisted: list[Any] = []

    def commit(self, artifact: ArtifactRef, **kwargs: Any) -> ArtifactRef:
        if self.refuse:
            raise AssertionError("a refused draft must not be committed")
        self.committed.append(artifact)
        self.persisted.append(kwargs.get("persistence"))
        return artifact


class _FixtureEvent:
    def __init__(self, index: int) -> None:
        self.event_id = f"event-{index}"
        self.canonical_title = f"来源{index}"
        self.first_published_at = "2026-09-14T00:00:00+00:00"
        self.documents = (
            {
                "title": f"原文{index}",
                "publisher": "测试来源",
                "citation_url": f"https://example.test/{index}",
                "published_at": self.first_published_at,
            },
        )


class _FixtureNews:
    def get_events(self, event_ids: Any) -> tuple[_FixtureEvent, ...]:
        return tuple(_FixtureEvent(int(item.rsplit("-", 1)[1])) for item in event_ids)


def _a3_setup(tmp_path: Any) -> tuple[Any, Any, Any, Any]:
    """A3 的运行里多一份已接纳证据：快照里有它的 Artifact，端口给出那条事实。"""
    from sector_pulse.application.orchestration.editorial_context import (
        BoundEditorialContextReader,
    )

    repository, snapshot, writer, selections, analyses_port, analyses = build_editorial_context(
        tmp_path
    )
    current = repository.load(snapshot.run_id)
    assert current is not None
    researcher = next(item for item in current.tasks if item.role == "A2")
    evidence_ref = ArtifactRef(
        artifact_id=uuid4(),
        task_id=researcher.task_id,
        attempt=researcher.attempt,
        kind=EVIDENCE_ARTIFACT_KIND,
        reference=HANDLE,
    )
    outline_id = uuid4()
    outline = EditorialOutlineArtifact(
        outline_id=outline_id,
        run_id=current.run_id,
        task_id=writer.task_id,
        attempt=1,
        selection_version=1,
        input_analysis_ids=tuple(item.analysis_id for item in analyses.values()),
        input_fingerprint="a" * 64,
        outline_hash="b" * 64,
        outline=ArticleOutline(
            outline_id=outline_id,
            run_id=current.run_id,
            sector_ids=("sector-1", "sector-2", "sector-3"),
            order_reasons={f"sector-{index}": str(index) for index in range(1, 4)},
            title_directions=("方向",),
            thesis="审慎观察",
            section_character_budgets={f"sector-{index}": 360 for index in range(1, 4)},
            excluded_sector_reasons={},
        ),
        created_at=datetime.now(UTC),
    )
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "artifacts": (
                    *current.artifacts,
                    evidence_ref,
                    ArtifactRef(
                        artifact_id=outline_id,
                        task_id=writer.task_id,
                        attempt=1,
                        kind="article_outline",
                        reference=f"article-outline:{outline_id}",
                    ),
                )
            }
        ),
        current.revision,
        "evidence.accepted",
    )
    context = BoundEditorialContextReader(
        orchestration=repository,
        selections=selections,
        analyses=analyses_port,
        run_id=current.run_id,
    ).read(task_id=writer.task_id, attempt=1, worker_id="writer-worker")
    return repository, context, outline, evidence_ref


def _a3_submission(evidence_id: str | None) -> ArticleDraftSubmission:
    def claims(index: int) -> tuple[Claim, ...]:
        if evidence_id is None or index != 1:
            return ()
        return (
            Claim(
                claim_id=f"claim-{index}",
                kind=ClaimKind.NEWS_FACT,
                text=f"板块{index}的需求改善可以核对",
                evidence_ids=(evidence_id,),
            ),
        )

    return ArticleDraftSubmission(
        titles=("今日三个板块的证据观察",),
        introduction="本文仅梳理已确认板块和可核验事实。",
        sections=tuple(
            ArticleSectionSubmission(
                section_id=f"section-{index}",
                sector_id=f"sector-{index}",
                heading=f"板块{index}：证据边界内观察",
                body=f"板块{index}的市场表现需要结合已核验信息观察。" + "审慎观察" * 85,
                claims=claims(index),
                source_ids=(
                    (f"event-{index}", evidence_id)
                    if evidence_id is not None and index == 1
                    else (f"event-{index}",)
                ),
            )
            for index in range(1, 4)
        ),
        conclusion="现有证据支持有限，后续信息仍需继续核验。",
        risk_notice="市场波动较大，本文不构成投资建议。",
    )


def _submit_a3(
    tmp_path: Any, accepted: _AcceptedEvidence, *, evidence_id: str | None = HANDLE
) -> tuple[Any, _Committing]:
    repository, context, outline, _evidence_ref = _a3_setup(tmp_path)
    committer = _Committing()
    service = SubmitDraftService(
        orchestration=repository,
        committer=committer,
        outlines=type("Outlines", (), {"get": lambda self, identity: outline})(),
        news_evidence=_FixtureNews(),
        accepted_evidence=accepted,
    )
    result = service.submit(
        context=context,
        outline_artifact_id=outline.outline_id,
        submission=_a3_submission(evidence_id),
    )
    return result, committer


def test_a3_may_cite_accepted_evidence_while_its_version_is_still_active(tmp_path):
    result, committer = _submit_a3(tmp_path, _AcceptedEvidence(_accepted_claim()))

    assert [item.kind for item in committer.committed] == ["article_draft"]
    assert committer.committed[0].artifact_id == result.artifact_id
    internal = next(item for item in result.draft.sources if item.source_id == HANDLE)
    assert internal.publisher == "内部研究资料库"
    assert internal.citation_url is None
    assert "version=ver_0001" not in internal.title
    assert VERSION in internal.title
    assert result.draft.sources[-1] == internal


def test_a3_cannot_submit_a_draft_resting_on_a_version_that_left_the_corpus(tmp_path):
    repository, context, outline, _ref = _a3_setup(tmp_path)
    service = SubmitDraftService(
        orchestration=repository,
        committer=_Committing(refuse=True),
        outlines=type("Outlines", (), {"get": lambda self, identity: outline})(),
        news_evidence=_FixtureNews(),
        accepted_evidence=_AcceptedEvidence(_accepted_claim(), active=()),
    )
    with pytest.raises(ValueError, match=INTERNAL_SOURCE_INACTIVE):
        service.submit(
            context=context,
            outline_artifact_id=outline.outline_id,
            submission=_a3_submission(HANDLE),
        )


def test_a3_cannot_submit_a_draft_that_states_an_unresolved_conflict_as_settled(tmp_path):
    repository, context, outline, _ref = _a3_setup(tmp_path)
    service = SubmitDraftService(
        orchestration=repository,
        committer=_Committing(refuse=True),
        outlines=type("Outlines", (), {"get": lambda self, identity: outline})(),
        news_evidence=_FixtureNews(),
        accepted_evidence=_AcceptedEvidence(
            _accepted_claim(conflict_status=ConflictStatus.UNRESOLVED)
        ),
    )
    with pytest.raises(ValueError, match=UNRESOLVED_CONFLICT_STATED_AS_FACT):
        service.submit(
            context=context,
            outline_artifact_id=outline.outline_id,
            submission=_a3_submission(HANDLE),
        )


def test_a3_still_refuses_a_handle_that_is_not_accepted_evidence_at_all(tmp_path):
    """没接内部资料库时，凭空写出来的句柄照旧被既有的来源校验挡在门外。"""
    repository, context, outline, _ref = _a3_setup(tmp_path)
    service = SubmitDraftService(
        orchestration=repository,
        committer=_Committing(refuse=True),
        outlines=type("Outlines", (), {"get": lambda self, identity: outline})(),
        news_evidence=_FixtureNews(),
    )
    with pytest.raises(ValueError, match="unverified source"):
        service.submit(
            context=context,
            outline_artifact_id=outline.outline_id,
            submission=_a3_submission("internal-research-evidence:never-accepted"),
        )


def test_a4_sees_the_same_findings_so_it_cannot_pass_an_unsupported_assertion(tmp_path):
    from sector_pulse.application.orchestration.review_tools import CheckDraftRulesService
    from sector_pulse.application.review.governance_service import GovernanceService

    evidence_ref = ArtifactRef(
        artifact_id=uuid4(),
        task_id=uuid4(),
        attempt=1,
        kind=EVIDENCE_ARTIFACT_KIND,
        reference=HANDLE,
    )
    repository, context, _reviewer, draft, _newer = build_review_context(
        tmp_path,
        evidence_artifact=evidence_ref,
        section_claims={
            "section-1": (
                Claim(
                    claim_id="claim-1",
                    kind=ClaimKind.NEWS_FACT,
                    text="板块一的需求改善可以核对",
                    evidence_ids=(HANDLE,),
                ),
            )
        },
    )
    committer = _Committing()
    result = CheckDraftRulesService(
        orchestration=repository,
        committer=committer,
        governance=GovernanceService(),
        accepted_evidence=_AcceptedEvidence(_accepted_claim(requires_verification=True)),
    ).check(context=context, draft_artifact_id=draft.artifact_id)

    quality = result.report.quality_issues
    assert [item.code for item in quality] == [UNVERIFIED_ONLY_SUPPORT]
    assert all(item.severity is IssueSeverity.BLOCKING for item in quality)
    assert [item.kind for item in committer.committed] == ["draft_rules"]
    assert committer.committed[0].artifact_id == result.artifact_id
    # 同一条结论也进不了 PASS：这不是审校意见，是程序结论（规格 15.4）。
    with pytest.raises(ValueError, match="blocking issues"):
        ReviewReport(
            review_id="review-1",
            draft_id=str(draft.draft.draft_id),
            draft_version=1,
            decision=ReviewDecision.PASS,
            issues=quality,
            revision_round=0,
        )


def test_a4_checks_the_version_state_as_of_the_check_not_as_of_the_binding(tmp_path):
    """版本是否还在架是**此刻**的事实，所以 A4 复核时才去查，而不是绑上下文时。"""
    from sector_pulse.application.orchestration.review_tools import CheckDraftRulesService
    from sector_pulse.application.review.governance_service import GovernanceService

    evidence_ref = ArtifactRef(
        artifact_id=uuid4(),
        task_id=uuid4(),
        attempt=1,
        kind=EVIDENCE_ARTIFACT_KIND,
        reference=HANDLE,
    )
    repository, context, _reviewer, draft, _newer = build_review_context(
        tmp_path,
        evidence_artifact=evidence_ref,
        section_claims={
            "section-1": (
                Claim(
                    claim_id="claim-1",
                    kind=ClaimKind.NEWS_FACT,
                    text="板块一的需求改善可以核对",
                    evidence_ids=(HANDLE,),
                ),
            )
        },
    )
    result = CheckDraftRulesService(
        orchestration=repository,
        committer=_Committing(),
        governance=GovernanceService(),
        accepted_evidence=_AcceptedEvidence(_accepted_claim(), active=()),
    ).check(context=context, draft_artifact_id=draft.artifact_id)

    assert [item.code for item in result.report.quality_issues] == [INTERNAL_SOURCE_INACTIVE]


def test_a4_without_an_evidence_reader_reports_the_same_as_before(tmp_path):
    """没接内部资料库的部署里，A4 的确定性检查还是原来那一条路径。"""
    from sector_pulse.application.orchestration.review_tools import CheckDraftRulesService
    from sector_pulse.application.review.governance_service import GovernanceService

    repository, context, _reviewer, draft, _newer = build_review_context(tmp_path)
    result = CheckDraftRulesService(
        orchestration=repository,
        committer=_Committing(),
        governance=GovernanceService(),
    ).check(context=context, draft_artifact_id=draft.artifact_id)

    assert result.report.quality_issues == ()
    assert result.report.governance.status == "PASS"
