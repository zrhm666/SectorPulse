"""Query-scoped claim extraction and the grouping that precedes NLI (spec 12, 13).

Nothing in this file compares two claims to each other. That is the split between this
module and Task 13's: here we decide *which claims exist* and *which pairs are worth asking
an NLI model about*, and both are decided by rules that can be checked by reading them.
Every judgement that cannot be made by reading — entailment, contradiction, which source
wins — happens after this file.

The two halves fail in opposite directions, so they are pinned in opposite directions:

- Extraction errs toward rejecting. A claim whose asserted content is not inside the span
  it cites is dropped: not repaired, not passed on. Dropping is the only honest outcome,
  because the service cannot know what the model meant, and a fabricated fact that reaches
  the resolver arrives wearing the same clothes as a real one.
- Grouping errs toward including. Two claims about the same subject and property at
  comparable times are grouped even when they look perfectly compatible, because "these
  agree" is a judgement for the NLI model rather than for a string comparison. What
  grouping does refuse is the Cartesian product: claims about different subjects or
  different properties are never paired, and that refusal is what bounds the NLI bill.

Grounding is checked against the *span* rather than the chunk, which is what makes
`source_span` load-bearing rather than decorative: a claim can name a subject that appears
somewhere in the passage and still be rejected because the span it quoted says something
else. The predicate is deliberately exempt — a property name is a normalised label
(`增长情况`), not a phrase anyone writes in a document.
"""

from __future__ import annotations

import itertools
from datetime import date
from typing import Any

from sector_pulse.application.research_library.claims import (
    ClaimExtractionService,
    group_comparable_claims,
    normalise_entity,
)
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.research_library.models import ExtractionMethod, SourceSpan
from sector_pulse.domain.research_library.retrieval import (
    ExtractedClaim,
    RetrievedCandidate,
    TimeRange,
)
from sector_pulse.ports.research_models import ClaimExtractionRequest

QUESTION = "海外储能订单的增长情况"

SOURCE = "报告显示，2026年第二季度海外储能订单同比增长85%，其中CATL占比提升至31%。"

_ids = itertools.count(1)


def _span_of(haystack: str, needle: str) -> SourceSpan:
    """The span of an exact substring, so no test hard-codes an offset."""
    start = haystack.index(needle)
    return SourceSpan(start=start, end=start + len(needle))


GOOD_SPAN = _span_of(SOURCE, "2026年第二季度海外储能订单同比增长85%")
CATL_SPAN = _span_of(SOURCE, "CATL占比提升至31%")


def _candidate(
    text: str = SOURCE, *, chunk_id: str = "chunk_1", rank: int = 1
) -> RetrievedCandidate:
    return RetrievedCandidate(
        candidate_id=f"cand_{rank}",
        retrieval_id="ret_1",
        chunk_id=chunk_id,
        document_id="doc_1",
        document_version_id="ver_1",
        text=text,
        content_origin=ExtractionMethod.NATIVE,
    )


def _claim(
    *,
    subject: str = "海外储能订单",
    predicate: str = "增长情况",
    object: str | None = "同比增长85%",
    statement: str | None = None,
    qualifiers: tuple[str, ...] = (),
    span: SourceSpan | None = None,
    chunk_id: str = "chunk_1",
    confidence: float = 0.9,
    valid_time: TimeRange | None = None,
    claim_id: str | None = None,
) -> ExtractedClaim:
    return ExtractedClaim(
        claim_id=claim_id if claim_id is not None else f"claim_{next(_ids):04d}",
        statement=statement if statement is not None else f"{subject}{object or ''}",
        subject=subject,
        predicate=predicate,
        object=object,
        qualifiers=qualifiers,
        valid_time=valid_time,
        source_chunk_id=chunk_id,
        source_span=span if span is not None else GOOD_SPAN,
        extraction_confidence=confidence,
    )


class _StubExtractor:
    """Returns whatever the test staged, including claims no source could support."""

    def __init__(self, claims: tuple[ExtractedClaim, ...] = ()) -> None:
        self.claims = claims
        self.requests: list[ClaimExtractionRequest] = []

    def extract(self, request: ClaimExtractionRequest) -> tuple[ExtractedClaim, ...]:
        self.requests.append(request)
        return self.claims


def _service(provider: _StubExtractor, **overrides: Any) -> ClaimExtractionService:
    return ClaimExtractionService(provider=provider, settings=RagSettings(**overrides))


# --- 抽取 ---


def test_a_statement_the_span_cannot_support_is_dropped_rather_than_repaired() -> None:
    """The plan's named case: a claim whose span quotes something else entirely."""
    provider = _StubExtractor((_claim(span=CATL_SPAN),))

    assert _service(provider).extract(QUESTION, [_candidate()]) == ()


def test_an_object_that_contradicts_the_span_is_dropped() -> None:
    provider = _StubExtractor((_claim(object="同比下降30%"),))

    assert _service(provider).extract(QUESTION, [_candidate()]) == ()


def test_a_qualifier_the_span_does_not_contain_is_dropped() -> None:
    provider = _StubExtractor((_claim(qualifiers=("北美市场",)),))

    assert _service(provider).extract(QUESTION, [_candidate()]) == ()


def test_content_present_in_the_chunk_but_outside_the_span_is_still_dropped() -> None:
    """`source_span` is load-bearing: citing a narrower span must narrow the claim."""
    provider = _StubExtractor(
        (_claim(subject="CATL", object="31%", span=_span_of(SOURCE, "占比提升至31%")),)
    )

    assert _service(provider).extract(QUESTION, [_candidate()]) == ()


def test_a_span_that_runs_past_the_end_of_the_chunk_is_dropped() -> None:
    """Python slices silently truncate; a truncated span would ground any statement."""
    provider = _StubExtractor((_claim(span=SourceSpan(start=5, end=500)),))

    assert _service(provider).extract(QUESTION, [_candidate()]) == ()


def test_a_claim_citing_a_chunk_that_was_never_sent_is_dropped() -> None:
    provider = _StubExtractor((_claim(chunk_id="chunk_elsewhere"),))

    assert _service(provider).extract(QUESTION, [_candidate()]) == ()


def test_matching_survives_full_width_digits_and_letter_case() -> None:
    """全角数字与大小写是同一句话的两种打法，落在同一个键上才算归一到了一起。"""
    provider = _StubExtractor(
        (
            _claim(object="同比增长８５％"),
            _claim(subject="catl", object="31%", span=CATL_SPAN),
        )
    )

    accepted = _service(provider).extract(QUESTION, [_candidate()])

    assert [claim.object for claim in accepted] == ["同比增长８５％", "31%"]


def test_matching_survives_a_line_break_inside_the_subject() -> None:
    wrapped = "2026年第二季度海外储能\n订单同比增长85%"
    provider = _StubExtractor((_claim(span=_span_of(wrapped, "海外储能\n订单同比增长85%")),))

    accepted = _service(provider).extract(QUESTION, [_candidate(wrapped)])

    assert len(accepted) == 1


def test_several_claims_in_one_chunk_all_survive_extraction() -> None:
    provider = _StubExtractor(
        (_claim(), _claim(subject="CATL", object="31%", span=CATL_SPAN))
    )

    accepted = _service(provider).extract(QUESTION, [_candidate()])

    assert len(accepted) == 2


def test_a_chunk_that_answers_nothing_yields_no_claims() -> None:
    """An empty extraction is a conclusion, not a failure — the passage says nothing."""
    provider = _StubExtractor(())

    assert _service(provider).extract(QUESTION, [_candidate()]) == ()


def test_no_candidates_means_no_provider_call_at_all() -> None:
    provider = _StubExtractor((_claim(),))

    assert _service(provider).extract(QUESTION, []) == ()
    assert provider.requests == []


def test_the_extractor_is_given_the_question_and_the_candidate_text() -> None:
    provider = _StubExtractor((_claim(),))

    _service(provider).extract(QUESTION, [_candidate()])

    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.question == QUESTION
    assert [chunk.chunk_id for chunk in request.chunks] == ["chunk_1"]
    assert request.chunks[0].text == SOURCE


def test_a_claim_below_the_confidence_floor_is_not_offered_as_a_fact() -> None:
    provider = _StubExtractor((_claim(confidence=0.49),))

    assert _service(provider, min_claim_confidence=0.5).extract(QUESTION, [_candidate()]) == ()


def test_a_claim_exactly_at_the_confidence_floor_is_kept() -> None:
    """The floor is a floor: it excludes what is below it, not what equals it."""
    provider = _StubExtractor((_claim(confidence=0.5),))

    assert len(_service(provider, min_claim_confidence=0.5).extract(QUESTION, [_candidate()])) == 1


def test_the_same_claim_returned_twice_is_kept_once() -> None:
    """A duplicate id would put one claim in two groups and invent a conflict with itself."""
    claim = _claim()
    provider = _StubExtractor((claim, claim))

    assert len(_service(provider).extract(QUESTION, [_candidate()])) == 1


def test_claims_come_back_in_the_order_the_extractor_gave_them() -> None:
    first = _claim(subject="CATL", object="31%", span=CATL_SPAN)
    second = _claim()
    provider = _StubExtractor((first, second))

    accepted = _service(provider).extract(QUESTION, [_candidate()])

    assert [claim.claim_id for claim in accepted] == [first.claim_id, second.claim_id]


# --- 归组 ---


def test_subject_normalisation_folds_width_whitespace_and_case() -> None:
    assert normalise_entity("ＣＡＴＬ") == normalise_entity("catl")
    assert normalise_entity(" 海外储能\n订单 ") == normalise_entity("海外储能订单")


Q1 = TimeRange(start=date(2026, 1, 1), end=date(2026, 3, 31))
Q2 = TimeRange(start=date(2026, 4, 1), end=date(2026, 6, 30))
YEAR = TimeRange(start=date(2026, 1, 1), end=date(2026, 12, 31))


def test_two_claims_about_one_subject_and_property_form_a_group() -> None:
    groups = group_comparable_claims(
        [
            _claim(claim_id="c1", valid_time=Q1),
            _claim(claim_id="c2", valid_time=Q1),
        ]
    )

    assert len(groups) == 1
    assert groups[0].claim_ids == ("c1", "c2")
    assert groups[0].subject_key == normalise_entity("海外储能订单")
    assert groups[0].predicate_key == normalise_entity("增长情况")


def test_a_claim_with_nothing_to_compare_against_forms_no_group() -> None:
    """A lone fact is not a conflict candidate, and NLI has nothing to be asked about it."""
    assert group_comparable_claims([_claim(claim_id="c1")]) == ()


def test_different_subjects_are_never_paired() -> None:
    """This is the "no Cartesian product" rule: it is what bounds the NLI cost."""
    groups = group_comparable_claims(
        [
            _claim(claim_id="c1", subject="海外储能订单"),
            _claim(claim_id="c2", subject="海外储能订单"),
            _claim(claim_id="c3", subject="欧洲储能订单"),
        ]
    )

    assert len(groups) == 1
    assert groups[0].claim_ids == ("c1", "c2")


def test_different_properties_are_never_paired() -> None:
    groups = group_comparable_claims(
        [
            _claim(claim_id="c1", predicate="增长情况"),
            _claim(claim_id="c2", predicate="增长情况"),
            _claim(claim_id="c3", predicate="毛利率"),
        ]
    )

    assert len(groups) == 1
    assert groups[0].claim_ids == ("c1", "c2")


def test_subjects_that_differ_only_in_width_or_case_are_one_entity() -> None:
    groups = group_comparable_claims(
        [
            _claim(claim_id="c1", subject="CATL"),
            _claim(claim_id="c2", subject="ＣＡＴＬ"),
            _claim(claim_id="c3", subject="catl"),
        ]
    )

    assert len(groups) == 1
    assert groups[0].claim_ids == ("c1", "c2", "c3")


def test_an_injected_alias_merges_two_names_for_one_entity() -> None:
    """别名表由调用方注入：哪一个名字是哪一个实体的另一面，不是这层能发明的事。"""
    groups = group_comparable_claims(
        [
            _claim(claim_id="c1", subject="CATL"),
            _claim(claim_id="c2", subject="宁德时代"),
        ],
        aliases={"catl": "宁德时代"},
    )

    assert len(groups) == 1
    assert groups[0].claim_ids == ("c1", "c2")
    assert groups[0].subject_key == normalise_entity("宁德时代")


def test_claims_whose_times_do_not_overlap_are_not_comparable() -> None:
    """规格 14 第 3 条：不同时间的事实可能不是冲突，而不同季度也确实不是。"""
    groups = group_comparable_claims(
        [
            _claim(claim_id="c1", valid_time=Q1),
            _claim(claim_id="c2", valid_time=Q2),
        ]
    )

    assert groups == ()


def test_overlapping_times_are_comparable() -> None:
    groups = group_comparable_claims(
        [
            _claim(claim_id="c1", valid_time=YEAR),
            _claim(claim_id="c2", valid_time=Q2),
        ]
    )

    assert len(groups) == 1


def test_an_undated_claim_is_comparable_with_a_dated_one() -> None:
    """One claim stating no window does not exclude itself from being about that window."""
    groups = group_comparable_claims(
        [
            _claim(claim_id="c1", valid_time=None),
            _claim(claim_id="c2", valid_time=Q1),
        ]
    )

    assert len(groups) == 1


def test_a_claim_bridging_two_disjoint_ones_merges_them_into_one_group() -> None:
    """Comparability is not transitive, so a group is a connected component.

    Q1 and Q2 do not overlap; the year overlaps both. Pairing by first fit would leave the
    two quarters in separate groups depending on input order, and the resolved conflict
    would then depend on which claim the extractor happened to emit first.
    """
    groups = group_comparable_claims(
        [
            _claim(claim_id="c1", valid_time=Q1),
            _claim(claim_id="c2", valid_time=Q2),
            _claim(claim_id="c3", valid_time=YEAR),
        ]
    )

    assert len(groups) == 1
    assert groups[0].claim_ids == ("c1", "c2", "c3")


def test_groups_appear_in_the_order_their_subjects_first_appeared() -> None:
    """海外 vs 欧洲 is deliberate: sorted order would put 欧洲 first, appearance order does not.

    The audit cites groups by position, so the order has to come from the claims rather than
    from the alphabet — otherwise the same facts in the same order would be reported under
    different numbers depending on the sort key.
    """
    groups = group_comparable_claims(
        [
            _claim(claim_id="c1", subject="海外储能订单"),
            _claim(claim_id="c2", subject="欧洲储能订单"),
            _claim(claim_id="c3", subject="海外储能订单"),
            _claim(claim_id="c4", subject="欧洲储能订单"),
        ]
    )

    assert [group.subject_key for group in groups] == [
        normalise_entity("海外储能订单"),
        normalise_entity("欧洲储能订单"),
    ]
    assert [group.claim_ids for group in groups] == [("c1", "c3"), ("c2", "c4")]


def test_nothing_is_grouped_when_there_is_nothing_to_group() -> None:
    assert group_comparable_claims([]) == ()
