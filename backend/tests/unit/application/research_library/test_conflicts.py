"""Conflict resolution between comparable claims (spec 13, 14).

The NLI model answers exactly one question: do these two statements contradict each other?
Which of them survives is decided here, by the rules in spec 14 read in priority order, and
the table in `fixtures/research_library/nli_cases.yaml` runs every rule and every category
in spec 22.3 with no model in the loop. The verdict is an *input* to that table rather than
the thing under test, which is what makes the priority exhaustively checkable.

Two boundaries are drawn here and nowhere else:

- A failed check is not agreement. `CHECK_FAILED` is a distinct outcome from `NOT_CONFLICT`,
  because a provider outage that reads as "no conflict" would silently delete a real one.
- A ranking score is not evidence. Rerank relevance is only allowed to separate two claims
  that are not independent sources; across independent sources, a contradiction the rules
  cannot settle stays `UNRESOLVED` and keeps both claims. Otherwise the answer would depend
  on which chunk a retrieval model happened to score higher, which is a coin toss wearing a
  number.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from sector_pulse.application.research_library.claims import (
    ComparableClaimGroup,
    normalise_entity,
)
from sector_pulse.application.research_library.conflicts import (
    ClaimSource,
    ConflictContext,
    ConflictMetadata,
    ConflictPolicy,
    ConflictService,
    UnknownClaimSource,
    resolve_conflict,
)
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.research_library.models import (
    DocumentVersionStatus,
    ExtractionMethod,
    SourceSpan,
)
from sector_pulse.domain.research_library.retrieval import (
    ClaimStance,
    ConflictRule,
    ConflictStatus,
    EvidenceGrade,
    ExtractedClaim,
    NliRelation,
    TimeRange,
)
from sector_pulse.ports.research_models import (
    NliProvider,
    NliVerdict,
    ProviderTimeout,
)

FIXTURE = Path(__file__).parents[3] / "fixtures" / "research_library" / "nli_cases.yaml"
_TABLE = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
CASES = _TABLE["cases"]
SOURCE_DEFAULTS: Mapping[str, Any] = _TABLE["defaults"]

#: 规格 14 的优先级不可配置；门槛是 `RagSettings.min_nli_confidence` 的默认值。
POLICY = ConflictPolicy(min_nli_confidence=0.7)

CONTRADICTION = NliVerdict(
    relation=NliRelation.CONTRADICTION,
    confidence=0.9,
    provider="stub-nli",
    model_version="stub-1",
)


# --- 夹具装载 ---


def _time_range(raw: Mapping[str, Any] | None) -> TimeRange | None:
    if raw is None:
        return None
    return TimeRange(start=raw["from"], end=raw["to"])


def _claim(side: str, raw: Mapping[str, Any]) -> ExtractedClaim:
    statement: str = raw["statement"]
    return ExtractedClaim(
        claim_id=raw.get("claim_id", f"c_{side}"),
        statement=statement,
        subject=raw.get("subject", "海外储能订单"),
        predicate=raw.get("predicate", "增长情况"),
        object=raw.get("object"),
        valid_time=_time_range(raw.get("valid_time")),
        qualifiers=tuple(raw.get("qualifiers", ())),
        stance=ClaimStance(raw.get("stance", "supporting")),
        source_chunk_id=f"chunk_{side}",
        source_span=SourceSpan(start=0, end=len(statement)),
        extraction_confidence=raw.get("extraction_confidence", 0.9),
    )


def _source(side: str, raw: Mapping[str, Any]) -> ClaimSource:
    merged = {**SOURCE_DEFAULTS, **raw}
    return ClaimSource(
        document_id=merged["document_id"],
        document_version_id=f"{merged['document_id']}_v{merged['version_number']}",
        version_number=merged["version_number"],
        status=DocumentVersionStatus(merged["status"]),
        source_weight=Decimal(str(merged["source_weight"])),
        content_origin=ExtractionMethod(merged["content_origin"]),
        requires_verification=merged["requires_verification"],
        relevance=merged["relevance"],
    )


def _verdict(raw: Mapping[str, Any] | None) -> NliVerdict | None:
    if raw is None:
        return None
    return NliVerdict(
        relation=NliRelation(raw["relation"]),
        confidence=raw["confidence"],
        provider="stub-nli",
        model_version="stub-1",
    )


def _metadata(case: Mapping[str, Any]) -> ConflictMetadata:
    return ConflictMetadata(
        left=_source("left", case["left"].get("source") or {}),
        right=_source("right", case["right"].get("source") or {}),
        query_time_range=_time_range(case.get("query_time_range")),
        verdict=_verdict(case.get("verdict")),
    )


def _pair(case: Mapping[str, Any]) -> tuple[ExtractedClaim, ExtractedClaim]:
    return _claim("left", case["left"]), _claim("right", case["right"])


# --- 裁决表 ---


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_the_resolver_returns_the_tabled_decision(case: Mapping[str, Any]) -> None:
    left, right = _pair(case)
    expected = case["expected"]

    decision = resolve_conflict((left, right), _metadata(case), POLICY)

    assert decision.claim_ids == (left.claim_id, right.claim_id)
    assert decision.status is ConflictStatus(expected["status"])
    assert decision.rule is (None if expected["rule"] is None else ConflictRule(expected["rule"]))
    assert decision.selected_claim_id == (
        None if expected["selected"] is None else f"c_{expected['selected']}"
    )
    assert decision.nli_relation is (
        None if expected["nli_relation"] is None else NliRelation(expected["nli_relation"])
    )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_the_tabled_confidence_is_the_one_the_model_gave(case: Mapping[str, Any]) -> None:
    """门槛会把判定降级成 UNCERTAIN，但降级的是结论，不是量到的那个数。"""
    verdict = case.get("verdict")
    left, right = _pair(case)

    decision = resolve_conflict((left, right), _metadata(case), POLICY)

    assert decision.nli_confidence == (None if verdict is None else verdict["confidence"])


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_every_decision_can_be_explained_to_a_reader(case: Mapping[str, Any]) -> None:
    """审计里这一列是人与结论之间唯一的桥：空白的理由是查不动的证据。"""
    left, right = _pair(case)

    decision = resolve_conflict((left, right), _metadata(case), POLICY)

    assert decision.rationale is not None
    assert decision.rationale.strip()


def test_the_table_exercises_every_rule_and_every_status() -> None:
    """这张表是"穷举优先级"这句话的实现；删掉一行就应当在这里变红。"""
    rules = {case["expected"]["rule"] for case in CASES}
    statuses = {case["expected"]["status"] for case in CASES}

    assert rules == {rule.value for rule in ConflictRule} | {None}
    assert statuses == {status.value for status in ConflictStatus}
    assert len(CASES) == len({case["id"] for case in CASES})


# --- 出处元数据 ---


def _source_with(**overrides: Any) -> ClaimSource:
    fields: dict[str, Any] = {
        "document_id": "doc_a",
        "document_version_id": "ver_1",
        "version_number": 1,
        "status": DocumentVersionStatus.ACTIVE,
        "source_weight": Decimal("0.5"),
        "content_origin": ExtractionMethod.NATIVE,
        "requires_verification": False,
        "relevance": None,
    }
    fields.update(overrides)
    return ClaimSource(**fields)


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (ExtractionMethod.NATIVE, EvidenceGrade.PRIMARY_SOURCE),
        (ExtractionMethod.OCR, EvidenceGrade.PARSED_STRUCTURE),
        (ExtractionMethod.PARSER_DERIVED, EvidenceGrade.PARSED_STRUCTURE),
        (ExtractionMethod.VISION_DERIVED, EvidenceGrade.DERIVED_UNVERIFIED),
    ],
)
def test_the_content_origin_maps_to_its_evidence_grade(
    origin: ExtractionMethod, expected: EvidenceGrade
) -> None:
    assert _source_with(content_origin=origin).grade is expected


def test_a_lead_awaiting_verification_is_the_lowest_grade_whatever_it_came_from() -> None:
    """规格 7.9：低置信度结论只是线索，不能因为它出身好就恢复成证据。"""
    assert _source_with(requires_verification=True).grade is EvidenceGrade.DERIVED_UNVERIFIED


def test_two_versions_of_one_document_are_not_independent_sources() -> None:
    assert not _source_with().is_independent_of(
        _source_with(document_version_id="ver_2", version_number=2)
    )


def test_two_documents_are_independent_sources() -> None:
    assert _source_with().is_independent_of(
        _source_with(document_id="doc_b", document_version_id="ver_9")
    )


# --- 服务：配对与 NLI 调用 ---


class _StubNli:
    """按调用次序给出判定；队列里放一个异常就表示那一次调用失败了。"""

    def __init__(self, *outcomes: NliVerdict | Exception) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[tuple[str, str]] = []

    def classify(self, *, premise: str, hypothesis: str) -> NliVerdict:
        self.calls.append((premise, hypothesis))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _service(provider: _StubNli, **overrides: Any) -> ConflictService:
    return ConflictService(provider=provider, settings=RagSettings(**overrides))


def _claim_for(
    chunk_id: str,
    *,
    statement: str | None = None,
    stance: ClaimStance = ClaimStance.SUPPORTING,
    valid_time: TimeRange | None = None,
) -> ExtractedClaim:
    """A claim carries no version: which version a chunk came from is a property of its source."""
    text = statement if statement is not None else f"{chunk_id}的正文"
    return ExtractedClaim(
        claim_id=f"c_{chunk_id}",
        statement=text,
        subject="海外储能订单",
        predicate="增长情况",
        source_chunk_id=chunk_id,
        source_span=SourceSpan(start=0, end=len(text)),
        extraction_confidence=0.9,
        stance=stance,
        valid_time=valid_time,
    )


def _group(*claims: ExtractedClaim) -> ComparableClaimGroup:
    return ComparableClaimGroup(
        subject_key=normalise_entity(claims[0].subject),
        predicate_key=normalise_entity(claims[0].predicate),
        claims=claims,
    )


def _context(*chunk_ids: str, versions: Mapping[str, str] | None = None) -> ConflictContext:
    """Sources for the named chunks; by default each chunk is its own document and version.

    `versions` pins chunks onto a shared version, which is how "two passages of one version"
    is expressed — that relationship lives between chunks, not on either claim.
    """
    pinned = dict(versions or {})
    return ConflictContext(
        sources={
            chunk_id: (
                _source_with(document_version_id=pinned[chunk_id])
                if chunk_id in pinned
                else _source_with(
                    document_id=f"doc_{chunk_id}",
                    document_version_id=f"ver_{chunk_id}",
                )
            )
            for chunk_id in chunk_ids
        }
    )


def test_the_stub_stands_in_for_the_real_port() -> None:
    """桩必须满足 `NliProvider`：否则这些用例证明的是另一件事能不能跑。"""
    assert isinstance(_StubNli(CONTRADICTION), NliProvider)


def test_a_group_of_two_is_asked_once_and_decided_once() -> None:
    provider = _StubNli(CONTRADICTION)
    group = _group(_claim_for("a"), _claim_for("b"))

    decisions = _service(provider).check((group,), _context("a", "b"))

    assert len(decisions) == 1
    assert decisions[0].claim_ids == ("c_a", "c_b")
    assert decisions[0].nli_provider == "stub-nli"
    assert decisions[0].nli_model_version == "stub-1"


def test_decisions_come_back_in_group_order() -> None:
    provider = _StubNli(CONTRADICTION, CONTRADICTION)
    first = _group(_claim_for("a"), _claim_for("b"))
    second = _group(_claim_for("c"), _claim_for("d"))

    decisions = _service(provider).check((first, second), _context("a", "b", "c", "d"))

    assert [decision.claim_ids for decision in decisions] == [
        ("c_a", "c_b"),
        ("c_c", "c_d"),
    ]


def test_every_pair_inside_a_group_is_asked() -> None:
    """一组三条事实是三对，而不是一对：漏掉一对就是漏掉一次可能的矛盾。"""
    provider = _StubNli(CONTRADICTION, CONTRADICTION, CONTRADICTION)
    group = _group(_claim_for("a"), _claim_for("b"), _claim_for("c"))

    decisions = _service(provider).check((group,), _context("a", "b", "c"))

    assert [decision.claim_ids for decision in decisions] == [
        ("c_a", "c_b"),
        ("c_a", "c_c"),
        ("c_b", "c_c"),
    ]


def test_two_passages_of_one_version_agreeing_on_stance_are_not_asked() -> None:
    """同一版本内的两段话属于同一份来源，立场又相同：这是一条已知的代价，不是遗漏。

    同一版本自相矛盾的话不会被发现——这一点在计划里记为已知边界（规格 13 只要求对
    不同版本、或立场不同的两条事实做 NLI）。
    """
    provider = _StubNli(CONTRADICTION)
    group = _group(_claim_for("a"), _claim_for("b"))
    one_version = {"a": "ver_1", "b": "ver_1"}

    assert _service(provider).check((group,), _context("a", "b", versions=one_version)) == ()
    assert provider.calls == []


def test_two_passages_of_one_version_with_opposite_stances_are_asked() -> None:
    provider = _StubNli(CONTRADICTION)
    group = _group(
        _claim_for("a"),
        _claim_for("b", stance=ClaimStance.OPPOSING),
    )

    decisions = _service(provider).check(
        (group,), _context("a", "b", versions={"a": "ver_1", "b": "ver_1"})
    )

    assert len(provider.calls) == 1
    assert len(decisions) == 1


def test_two_versions_are_asked_even_when_the_stances_agree() -> None:
    provider = _StubNli(CONTRADICTION)
    group = _group(_claim_for("a"), _claim_for("b"))

    assert len(_service(provider).check((group,), _context("a", "b"))) == 1


def test_the_pair_is_put_to_nli_in_group_order() -> None:
    """前提与假设互换会让蕴含与矛盾互换，因此顺序必须来自事实的次序。"""
    provider = _StubNli(CONTRADICTION)
    group = _group(_claim_for("a", statement="甲说增"), _claim_for("b", statement="乙说降"))

    _service(provider).check((group,), _context("a", "b"))

    assert provider.calls == [("甲说增", "乙说降")]


def test_the_effective_time_travels_with_the_statement() -> None:
    """规格 13：NLI 的输入要带上必要的时间限定，否则两个季度会被读成互相否定。"""
    provider = _StubNli(CONTRADICTION)
    window = TimeRange(start=date(2026, 1, 1), end=date(2026, 3, 31))
    group = _group(
        _claim_for("a", statement="订单增长", valid_time=window),
        _claim_for("b", statement="订单下滑"),
    )

    _service(provider).check((group,), _context("a", "b"))

    premise, hypothesis = provider.calls[0]
    assert "订单增长" in premise
    assert "2026-01-01" in premise
    assert "2026-03-31" in premise
    assert hypothesis == "订单下滑"


def test_a_claim_with_no_window_is_quoted_without_one() -> None:
    provider = _StubNli(CONTRADICTION)
    group = _group(_claim_for("a", statement="订单增长"), _claim_for("b"))

    _service(provider).check((group,), _context("a", "b"))

    assert provider.calls[0][0] == "订单增长"


def test_a_claim_whose_source_was_never_declared_is_a_wiring_error() -> None:
    """抽取阶段已经核对过切片出处；到这里还查不到，说明调用方漏传了来源表。

    静默丢下这一对会让一次真实矛盾从审计里消失，而两条事实看上去都被处理过了。
    """
    provider = _StubNli(CONTRADICTION)
    group = _group(_claim_for("a"), _claim_for("b"))

    with pytest.raises(UnknownClaimSource):
        _service(provider).check((group,), _context("a"))


def test_a_provider_failure_fails_only_its_own_pair() -> None:
    provider = _StubNli(ProviderTimeout("no answer"), CONTRADICTION)
    first = _group(_claim_for("a"), _claim_for("b"))
    second = _group(_claim_for("c"), _claim_for("d"))

    decisions = _service(provider).check((first, second), _context("a", "b", "c", "d"))

    assert [decision.status for decision in decisions] == [
        ConflictStatus.CHECK_FAILED,
        ConflictStatus.UNRESOLVED,
    ]
    assert decisions[0].nli_relation is None


def test_a_programming_error_is_not_mistaken_for_a_provider_outage() -> None:
    """只吞 `ProviderError`。把一切都读成"这次调用没成"，会把代码缺陷写进审计当成外部故障。"""
    provider = _StubNli(ValueError("the adapter is wired wrong"))
    group = _group(_claim_for("a"), _claim_for("b"))

    with pytest.raises(ValueError):
        _service(provider).check((group,), _context("a", "b"))


def test_the_confidence_threshold_comes_from_the_settings() -> None:
    group = _group(_claim_for("a"), _claim_for("b"))
    context = ConflictContext(
        sources={
            "a": _source_with(document_id="doc_a"),
            "b": _source_with(
                document_id="doc_b",
                document_version_id="ver_b",
                status=DocumentVersionStatus.DELETED,
            ),
        }
    )
    # 状态规则本来会选出左边；判定被门槛降级成 UNCERTAIN 后就不该再有赢家。
    assert (
        _service(_StubNli(CONTRADICTION), min_nli_confidence=0.7).check((group,), context)[0].status
        is ConflictStatus.RESOLVED
    )
    assert (
        _service(_StubNli(CONTRADICTION), min_nli_confidence=0.95)
        .check((group,), context)[0]
        .status
        is ConflictStatus.UNRESOLVED
    )


def test_the_query_window_reaches_the_resolver() -> None:
    group = _group(
        _claim_for("a", valid_time=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30))),
        _claim_for("b", valid_time=TimeRange(start=date(2026, 1, 1), end=date(2026, 6, 10))),
    )
    context = ConflictContext(
        sources={
            "a": _source_with(),
            "b": _source_with(document_id="doc_b", document_version_id="ver_b"),
        },
        query_time_range=TimeRange(start=date(2026, 6, 15), end=date(2026, 6, 30)),
    )

    decision = _service(_StubNli(CONTRADICTION)).check((group,), context)[0]

    assert decision.status is ConflictStatus.RESOLVED
    assert decision.rule is ConflictRule.EFFECTIVE_TIME
    assert decision.selected_claim_id == "c_a"


def test_no_groups_means_no_provider_call_and_no_decision() -> None:
    provider = _StubNli(CONTRADICTION)

    assert _service(provider).check((), _context()) == ()
    assert provider.calls == []


def test_the_policy_is_the_only_thing_the_settings_configure() -> None:
    """规格 14 的优先级是固定的：它不能被配置成"权重优先于状态"。"""
    policy = ConflictPolicy(min_nli_confidence=0.5)

    assert policy.min_nli_confidence == 0.5
