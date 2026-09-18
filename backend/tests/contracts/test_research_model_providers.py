"""One contract, two adapters — the six model providers of Task 5.

Spec 6 makes every model behind the research library pluggable: embeddings, reranking,
NLI, claim extraction, OCR and vision. The rules that hold for *any* adapter are asserted
once, in the `assert_*_provider_contract` bodies below, and both the offline fixture
adapters (the offline gate) and the HTTP adapters (driven by `httpx.MockTransport`) run
exactly the same bodies.

What is being pinned here is the part a caller cannot check for itself:

- a batch comes back in the order it was sent — the third vector belongs to the third
  text, and a provider that returns its own order silently attributes one document's
  meaning to another;
- every score belongs to the document at the same index;
- a claim cites a chunk that was actually sent, because a claim citing an unsent chunk is
  a citation to nothing;
- every result names the provider and model version that produced it. Those names end up
  in evidence grades and audit rows, where "unknown" is not an acceptable value.

The fixture adapters never open a socket and the HTTP adapters are handed a
`MockTransport`, so nothing in this file touches the network.
"""

import pytest
from sector_pulse.domain.research_library.retrieval import NliRelation
from sector_pulse.infrastructure.research_library.providers import fixture
from sector_pulse.ports.research_models import (
    ClaimExtractionRequest,
    ClaimExtractorProvider,
    ClaimSourceChunk,
    EmbeddingProvider,
    NliProvider,
    OcrProvider,
    ProviderNotConfigured,
    ProviderResponseInvalid,
    RerankerProvider,
    VisionDocumentProvider,
)

# --- the inputs every adapter is asked about ---
#
# Both test files use these same values, so a difference in behaviour between the fixture
# and the HTTP adapter shows up as a contract failure rather than as two happy paths that
# were never compared.

EMBEDDING_TEXTS = ("海外需求回暖", "欧洲市场库存下降", "宁德时代产能扩张")
ORDER_TEXTS = ("alpha 需求", "beta 产能")
QUERY = "欧洲市场库存"
RERANK_DOCUMENTS = (
    "2026 年一季度欧洲市场库存在渠道端下降 12%",
    "宁德时代宣布在匈牙利扩建电芯产能",
    "人民币对欧元汇率波动加大",
)
PREMISE = "公司公告显示 2026 年一季度欧洲市场库存同比下降 12%。"
HYPOTHESIS = "2026 年一季度欧洲市场库存下降。"
PAGE_NUMBER = 7
PAGE_WIDTH = 1240
PAGE_HEIGHT = 1754
PAGE_IMAGE = b"\x89PNG\r\n\x1a\n" + b"page-7" * 8
FIGURE_IMAGE = b"\x89PNG\r\n\x1a\n" + b"figure-3" * 8
MEDIA_TYPE = "image/png"
FIGURE_CONTEXT = "图 3 2026 年一季度欧洲储能装机"
QUESTION = "2026 年一季度欧洲市场库存发生了什么变化？"
SOURCE_CHUNKS = (
    ClaimSourceChunk(chunk_id="chunk_a", text="2026 年一季度欧洲市场库存同比下降 12%。"),
    ClaimSourceChunk(chunk_id="chunk_b", text="同期欧洲储能装机同比增长 30%。"),
)
CLAIM_REQUEST = ClaimExtractionRequest(question=QUESTION, chunks=SOURCE_CHUNKS)
#: 抽取器只在这些块里找事实：任何指向别处的 claim 都是凭空引用。
SOURCE_CHUNK_IDS = frozenset(chunk.chunk_id for chunk in SOURCE_CHUNKS)


# --- the contract bodies ---


def assert_embedding_provider_contract(provider: EmbeddingProvider) -> None:
    batch = provider.embed(EMBEDDING_TEXTS)
    assert len(batch.vectors) == len(EMBEDDING_TEXTS)
    assert batch.dimension > 0
    assert all(len(vector) == batch.dimension for vector in batch.vectors)
    assert batch.provider.strip()
    assert batch.model_version.strip()

    first, second = provider.embed(ORDER_TEXTS).vectors
    swapped_first, swapped_second = provider.embed(tuple(reversed(ORDER_TEXTS))).vectors
    assert (first, second) == (swapped_second, swapped_first), (
        "a batch must come back in the order it was sent"
    )


def assert_reranker_provider_contract(provider: RerankerProvider) -> None:
    result = provider.rerank(query=QUERY, documents=RERANK_DOCUMENTS)
    assert len(result.scores) == len(RERANK_DOCUMENTS), (
        "every document needs a score at its own index, or the score ranks the wrong text"
    )
    assert all(score == score for score in result.scores), "a NaN score would silently sort last"
    assert sorted(result.best_order()) == list(range(len(RERANK_DOCUMENTS)))
    assert result.provider.strip()
    assert result.model_version.strip()


def assert_nli_provider_contract(provider: NliProvider) -> None:
    verdict = provider.classify(premise=PREMISE, hypothesis=HYPOTHESIS)
    assert isinstance(verdict.relation, NliRelation)
    assert 0 <= verdict.confidence <= 1
    assert verdict.provider.strip()
    assert verdict.model_version.strip()


def assert_ocr_provider_contract(provider: OcrProvider) -> None:
    page = provider.recognize_page(
        page_number=PAGE_NUMBER, page_image=PAGE_IMAGE, width=PAGE_WIDTH, height=PAGE_HEIGHT
    )
    assert page.page_number == PAGE_NUMBER
    assert page.words, "a page that produced no words is a fact the caller must be told"
    assert all(word.text.strip() for word in page.words)
    assert all(0 <= word.confidence <= 1 for word in page.words)
    assert all(len(word.bounding_box) == 4 for word in page.words)
    assert 0 <= page.confidence <= 1
    assert page.provider.strip()
    assert page.model_version.strip()


def assert_vision_provider_contract(provider: VisionDocumentProvider) -> None:
    description = provider.describe(
        image=FIGURE_IMAGE, media_type=MEDIA_TYPE, context=FIGURE_CONTEXT
    )
    assert description.description.strip()
    assert 0 <= description.confidence <= 1
    assert description.provider.strip()
    assert description.model_version.strip()


def assert_claim_extractor_provider_contract(
    provider: ClaimExtractorProvider, request: ClaimExtractionRequest
) -> None:
    for claim in provider.extract(request):
        assert claim.source_chunk_id in SOURCE_CHUNK_IDS, (
            "a claim must cite a chunk that was sent; anything else is a citation to nothing"
        )
        assert claim.statement.strip()
        assert 0 <= claim.extraction_confidence <= 1
        assert claim.claim_id.strip()


# --- the reference adapter ---


def test_every_fixture_adapter_declares_the_port_it_implements() -> None:
    """`isinstance` against a runtime-checkable Protocol fails on a missing method.

    Without this, a renamed method shows up as an `AttributeError` in whichever task
    happens to call it first, instead of here.
    """
    assert isinstance(fixture.FixtureEmbeddingProvider(), EmbeddingProvider)
    assert isinstance(fixture.FixtureRerankerProvider(), RerankerProvider)
    assert isinstance(fixture.FixtureNliProvider(), NliProvider)
    assert isinstance(fixture.FixtureClaimExtractorProvider(claims={}), ClaimExtractorProvider)
    assert isinstance(fixture.FixtureOcrProvider(pages={}), OcrProvider)
    assert isinstance(
        fixture.FixtureVisionDocumentProvider.keyed_by_image({}), VisionDocumentProvider
    )


def test_the_fixture_embedding_provider_satisfies_the_contract() -> None:
    assert_embedding_provider_contract(fixture.FixtureEmbeddingProvider(dimension=64))


def test_the_fixture_reranker_satisfies_the_contract() -> None:
    assert_reranker_provider_contract(fixture.FixtureRerankerProvider())


def test_the_fixture_nli_provider_satisfies_the_contract() -> None:
    assert_nli_provider_contract(fixture.FixtureNliProvider())


def test_the_fixture_ocr_provider_satisfies_the_contract() -> None:
    assert_ocr_provider_contract(
        fixture.FixtureOcrProvider(
            pages={
                PAGE_NUMBER: fixture.ocr_page(
                    page_number=PAGE_NUMBER,
                    lines=("海外需求回暖", "欧洲市场库存下降"),
                    confidence=0.94,
                )
            }
        )
    )


def test_the_fixture_vision_provider_satisfies_the_contract() -> None:
    assert_vision_provider_contract(
        fixture.FixtureVisionDocumentProvider.keyed_by_image(
            {
                FIGURE_IMAGE: fixture.visual_description(
                    description="柱状图显示 2026 年一季度欧洲储能装机同比增长 30%。",
                    confidence=0.81,
                    chart_type="bar",
                )
            }
        )
    )


def test_the_fixture_claim_extractor_satisfies_the_contract() -> None:
    assert_claim_extractor_provider_contract(
        fixture.FixtureClaimExtractorProvider(
            claims={
                QUESTION: (
                    fixture.claim(
                        chunk_id="chunk_a",
                        statement="2026 年一季度欧洲市场库存同比下降 12%。",
                        subject="欧洲市场库存",
                        predicate="同比下降",
                        object="12%",
                    ),
                )
            }
        ),
        CLAIM_REQUEST,
    )


# --- the fixture adapters' own rules ---


def test_the_fixture_embedding_provider_is_deterministic_and_similarity_bearing() -> None:
    """Deterministic so tests can rely on it, similarity-bearing so Task 11 can use it.

    A fixture that returned random vectors would make the dense half of hybrid retrieval
    untestable: the only thing it could still assert is that the ranking function sorts.
    """
    provider = fixture.FixtureEmbeddingProvider(dimension=128)
    same = provider.embed(("欧洲市场库存下降",)).vectors
    again = provider.embed(("欧洲市场库存下降",)).vectors
    assert same == again

    near, far = provider.embed(
        ("2026 年一季度欧洲市场库存下降", "宁德时代在匈牙利扩建电芯产能")
    ).vectors
    closer = provider.embed(("欧洲市场库存下降",)).vectors[0]
    assert _cosine(closer, near) > _cosine(closer, far)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_the_fixture_embedding_provider_honours_explicit_vectors() -> None:
    """A test that needs an exact vector asks for one instead of reverse-engineering one."""
    fixed = (1.0, 0.0, 0.0)
    provider = fixture.FixtureEmbeddingProvider(dimension=3, vectors={"锚点": fixed})
    assert provider.embed(("锚点",)).vectors == (fixed,)


def test_the_fixture_embedding_provider_refuses_a_vector_of_the_wrong_dimension() -> None:
    with pytest.raises(ValueError, match="dimension"):
        fixture.FixtureEmbeddingProvider(dimension=3, vectors={"锚点": (1.0, 0.0)})


def test_the_fixture_reranker_puts_the_on_topic_document_first() -> None:
    provider = fixture.FixtureRerankerProvider()
    result = provider.rerank(query=QUERY, documents=RERANK_DOCUMENTS)
    assert result.best_order()[0] == 0


def test_the_fixture_nli_provider_reads_entailment_contradiction_and_the_rest() -> None:
    """Table-driven, because Task 13's resolver is driven by exactly these cases."""
    provider = fixture.FixtureNliProvider()
    cases = (
        (PREMISE, HYPOTHESIS, NliRelation.ENTAILMENT),
        (PREMISE, "2026 年一季度欧洲市场库存没有下降。", NliRelation.CONTRADICTION),
        (PREMISE, "宁德时代在匈牙利扩建电芯产能。", NliRelation.UNCERTAIN),
    )
    for premise, hypothesis, expected in cases:
        assert provider.classify(premise=premise, hypothesis=hypothesis).relation is expected


def test_the_fixture_nli_provider_honours_explicit_verdicts() -> None:
    provider = fixture.FixtureNliProvider(verdicts={(PREMISE, HYPOTHESIS): NliRelation.NEUTRAL})
    assert provider.classify(premise=PREMISE, hypothesis=HYPOTHESIS).relation is NliRelation.NEUTRAL


def test_a_fixture_that_declares_nothing_fails_rather_than_guesses() -> None:
    """The repository's rule for fixtures: an undeclared answer is an error, not a default.

    These are the paths a caller must be able to tell apart from a real answer — a page
    nobody described and a page described as empty are different facts.
    """
    with pytest.raises(ProviderNotConfigured):
        fixture.FixtureOcrProvider(pages={}).recognize_page(
            page_number=PAGE_NUMBER, page_image=PAGE_IMAGE, width=PAGE_WIDTH, height=PAGE_HEIGHT
        )
    with pytest.raises(ProviderNotConfigured):
        fixture.FixtureVisionDocumentProvider.keyed_by_image({}).describe(
            image=FIGURE_IMAGE, media_type=MEDIA_TYPE
        )
    with pytest.raises(ProviderNotConfigured):
        fixture.FixtureClaimExtractorProvider(claims={}).extract(CLAIM_REQUEST)


def test_the_fixture_claim_extractor_refuses_a_claim_that_cites_an_unsent_chunk() -> None:
    provider = fixture.FixtureClaimExtractorProvider(
        claims={
            QUESTION: (
                fixture.claim(chunk_id="chunk_zzz", statement="库存下降了 12%。", subject="库存"),
            )
        }
    )
    with pytest.raises(ProviderResponseInvalid):
        provider.extract(CLAIM_REQUEST)
