"""The HTTP adapters: wire format, error vocabulary, and what must never be logged.

Every test here drives an `httpx.MockTransport`, so no socket is opened and no endpoint is
configured. What is being pinned is the part the shared contract cannot reach — how a
provider's bytes become a domain result, and how a provider's failure becomes our failure:

- a batch that arrives out of order is put back in order rather than trusted;
- a response that is not the documented shape raises `ProviderResponseInvalid` instead of
  being coerced into something that looks plausible;
- a timeout is retriable and a rejected request is not, so the budget layer above never
  has to guess by matching strings;
- the API key never reaches a log record. A secret that is logged once is leaked.
"""

import base64
import hashlib
import json
import logging
import socket
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sector_pulse.infrastructure.research_library.providers import openai_compatible
from sector_pulse.ports.research_models import (
    ClaimExtractorProvider,
    EmbeddingProvider,
    NliProvider,
    OcrProvider,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    RerankerProvider,
    VisionDocumentProvider,
)

from backend.tests.contracts.test_research_model_providers import (
    CLAIM_REQUEST,
    FIGURE_CONTEXT,
    FIGURE_IMAGE,
    HYPOTHESIS,
    MEDIA_TYPE,
    PAGE_HEIGHT,
    PAGE_IMAGE,
    PAGE_NUMBER,
    PAGE_WIDTH,
    PREMISE,
    RERANK_DOCUMENTS,
    assert_claim_extractor_provider_contract,
    assert_embedding_provider_contract,
    assert_nli_provider_contract,
    assert_ocr_provider_contract,
    assert_reranker_provider_contract,
    assert_vision_provider_contract,
)

BASE_URL = "https://models.example/v1"
API_KEY = "sk-research-library-secret"
REJECTED = httpx.Response(400, json={"error": {"message": "bad request"}})


def endpoint(**overrides: Any) -> openai_compatible.ProviderEndpoint:
    values: dict[str, Any] = {
        "base_url": BASE_URL,
        "api_key": SecretStr(API_KEY),
        "model": "bge-m3",
        "provider": "models.example",
        "timeout_seconds": 12.0,
        "max_retries": 1,
    }
    values.update(overrides)
    return openai_compatible.ProviderEndpoint(**values)


def transport(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def json_handler(body: Any, *, status: int = 200) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, json=body)

    return handler


def plain_handler(text: str) -> Any:
    """A gateway that answers with HTML, which is what a misconfigured proxy looks like."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text=text, headers={"content-type": "text/html"})

    return handler


class Recording:
    """A handler that records the requests it received and replies with fixed bodies."""

    def __init__(self, *responses: Any) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []
        self._responses = list(responses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.bodies.append(json.loads(request.content))
        response = self._responses[min(len(self.requests) - 1, len(self._responses) - 1)]
        # `BaseException`, not `Exception`: a cancellation is what this helper is used to
        # simulate, and `KeyboardInterrupt` is not an `Exception`.
        if isinstance(response, BaseException):
            raise response
        return response

    @property
    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


def embedding_body(vectors: list[list[float]], *, model: str = "bge-m3") -> dict[str, Any]:
    return {
        "model": model,
        "data": [
            {"index": index, "embedding": vector} for index, vector in enumerate(vectors)
        ],
    }


def embedding_handler(*, dimension: int = 4, reverse: bool = True) -> Any:
    """An endpoint that answers once per input text.

    Fixed responses cannot serve the shared contract: the contract asks the same endpoint
    for batches of different lengths and expects the answers to follow the inputs. Deriving
    the vector from the text also makes the order assertion meaningful — a provider that
    returned its own order would be caught rather than accidentally agreeing.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        data = [
            {"index": index, "embedding": _vector_for(text, dimension)}
            for index, text in enumerate(texts)
        ]
        if reverse:
            # 反向返回是最坏的常见情况，也正是按 index 归位要挡住的那一种。
            data.reverse()
        return httpx.Response(200, json={"model": "bge-m3-2026-01", "data": data})

    return handler


def _vector_for(text: str, dimension: int) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    return [digest[index] / 255 for index in range(dimension)]


# --- embeddings ---


def test_every_http_adapter_declares_the_port_it_implements() -> None:
    client = transport(json_handler({}))
    try:
        assert isinstance(
            openai_compatible.OpenAICompatibleEmbeddingProvider(endpoint(), client=client),
            EmbeddingProvider,
        )
        assert isinstance(
            openai_compatible.OpenAICompatibleRerankerProvider(endpoint(), client=client),
            RerankerProvider,
        )
        assert isinstance(
            openai_compatible.OpenAICompatibleNliProvider(endpoint(), client=client), NliProvider
        )
        assert isinstance(
            openai_compatible.OpenAICompatibleClaimExtractorProvider(endpoint(), client=client),
            ClaimExtractorProvider,
        )
        assert isinstance(
            openai_compatible.OpenAICompatibleOcrProvider(endpoint(), client=client), OcrProvider
        )
        assert isinstance(
            openai_compatible.OpenAICompatibleVisionDocumentProvider(endpoint(), client=client),
            VisionDocumentProvider,
        )
    finally:
        client.close()


def test_the_http_embedding_provider_satisfies_the_contract() -> None:
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(embedding_handler())
    )
    assert_embedding_provider_contract(provider)


def test_an_out_of_order_batch_is_put_back_in_order() -> None:
    """Providers do return their own order. Trusting it attributes one text's vector to another."""
    recorder = Recording(
        httpx.Response(
            200,
            json={
                "model": "bge-m3",
                "data": [
                    {"index": 2, "embedding": [3.0]},
                    {"index": 0, "embedding": [1.0]},
                    {"index": 1, "embedding": [2.0]},
                ],
            },
        )
    )
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(recorder)
    )
    assert provider.embed(("a", "b", "c")).vectors == ((1.0,), (2.0,), (3.0,))


def test_the_embedding_request_names_the_configured_model_and_carries_the_texts() -> None:
    recorder = Recording(httpx.Response(200, json=embedding_body([[0.1, 0.2]])))
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(recorder)
    )
    provider.embed(("海外需求回暖",))

    assert recorder.paths == ["/v1/embeddings"]
    assert recorder.bodies[0] == {"model": "bge-m3", "input": ["海外需求回暖"]}
    assert recorder.requests[0].headers["authorization"] == f"Bearer {API_KEY}"


def test_the_model_version_in_the_result_is_the_one_that_answered() -> None:
    """A provider that quietly serves another revision must not be recorded as the one asked for."""
    recorder = Recording(
        httpx.Response(200, json=embedding_body([[0.1]], model="bge-m3-2026-01"))
    )
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(recorder)
    )
    assert provider.embed(("文本",)).model_version == "bge-m3-2026-01"


@pytest.mark.parametrize(
    "body",
    [
        {"model": "bge-m3", "data": []},
        {"model": "bge-m3", "data": [{"index": 0, "embedding": [0.1]}]},
        {"model": "bge-m3", "data": [{"index": 0, "embedding": []}]},
        {"model": "bge-m3", "data": [{"index": 0, "embedding": "0.1"}]},
        {"model": "bge-m3", "data": [{"index": 0, "embedding": [0.1, True]}]},
        {
            "model": "bge-m3",
            "data": [{"index": 0, "embedding": [0.1, 0.2]}, {"index": 0, "embedding": [0.3, 0.4]}],
        },
        {
            "model": "bge-m3",
            "data": [{"index": 5, "embedding": [0.1]}, {"index": 0, "embedding": [0.2]}],
        },
        {"model": "bge-m3", "data": [{"embedding": [0.1]}, {"index": 0, "embedding": [0.2]}]},
        {"model": "bge-m3", "data": "not a list"},
        {"model": "bge-m3"},
    ],
)
def test_a_malformed_embedding_response_is_refused_not_coerced(body: dict[str, Any]) -> None:
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(json_handler(body))
    )
    with pytest.raises(ProviderResponseInvalid):
        provider.embed(("a", "b"))


# --- rerank ---


def test_the_http_reranker_satisfies_the_contract() -> None:
    body = {
        "model": "bge-reranker-v2",
        "results": [
            {"index": index, "relevance_score": 1.0 - index / 10}
            for index in range(len(RERANK_DOCUMENTS))
        ],
    }
    provider = openai_compatible.OpenAICompatibleRerankerProvider(
        endpoint(model="bge-reranker-v2"), client=transport(json_handler(body))
    )
    assert_reranker_provider_contract(provider)


def test_the_reranker_orders_scores_by_document_index_not_by_provider_order() -> None:
    recorder = Recording(
        httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.1},
                    {"index": 0, "relevance_score": 0.9},
                ]
            },
        )
    )
    provider = openai_compatible.OpenAICompatibleRerankerProvider(
        endpoint(), client=transport(recorder)
    )
    result = provider.rerank(query="q", documents=("first", "second"))
    assert result.scores == (0.9, 0.1)
    assert result.best_order() == (0, 1)


@pytest.mark.parametrize(
    "body",
    [
        {"results": []},
        {"results": [{"index": 0, "relevance_score": 0.5}]},
        {
            "results": [
                {"index": 0, "relevance_score": 0.5},
                {"index": 0, "relevance_score": 0.5},
            ]
        },
        {
            "results": [
                {"index": 0, "relevance_score": "high"},
                {"index": 1, "relevance_score": 0.5},
            ]
        },
        {"results": [{"index": 0}, {"index": 1, "relevance_score": 0.5}]},
        {"results": "not a list"},
    ],
)
def test_a_malformed_rerank_response_is_refused(body: dict[str, Any]) -> None:
    provider = openai_compatible.OpenAICompatibleRerankerProvider(
        endpoint(), client=transport(json_handler(body))
    )
    with pytest.raises(ProviderResponseInvalid):
        provider.rerank(query="q", documents=("a", "b"))


# --- NLI ---


def chat_body(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": "qwen3-14b",
        "choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}],
    }


def test_the_http_nli_provider_satisfies_the_contract() -> None:
    body = chat_body({"relation": "ENTAILMENT", "confidence": 0.92})
    provider = openai_compatible.OpenAICompatibleNliProvider(
        endpoint(model="qwen3-14b"), client=transport(json_handler(body))
    )
    assert_nli_provider_contract(provider)


def test_the_nli_prompt_carries_both_texts_and_forbids_guessing() -> None:
    recorder = Recording(
        httpx.Response(200, json=chat_body({"relation": "UNCERTAIN", "confidence": 0.3}))
    )
    provider = openai_compatible.OpenAICompatibleNliProvider(
        endpoint(), client=transport(recorder)
    )
    provider.classify(premise=PREMISE, hypothesis=HYPOTHESIS)

    assert recorder.paths == ["/v1/chat/completions"]
    body = recorder.bodies[0]
    assert body["model"] == "bge-m3"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    contents = " ".join(message["content"] for message in body["messages"])
    assert PREMISE in contents
    assert HYPOTHESIS in contents
    assert "UNCERTAIN" in contents


@pytest.mark.parametrize(
    "content",
    [
        '{"relation": "PROBABLY", "confidence": 0.9}',
        '{"relation": "ENTAILMENT", "confidence": 1.4}',
        '{"relation": "ENTAILMENT", "confidence": -0.1}',
        '{"relation": "ENTAILMENT", "confidence": "high"}',
        '{"relation": "ENTAILMENT"}',
        '{"confidence": 0.9}',
        "not JSON at all",
        "```json\n{\"relation\": \"ENTAILMENT\", \"confidence\": 0.9}\n```",
        "[1, 2, 3]",
    ],
)
def test_a_malformed_nli_answer_is_refused(content: str) -> None:
    """Including the fenced one: an answer wrapped in prose is an answer we cannot bound."""
    body = {"choices": [{"message": {"content": content}}]}
    provider = openai_compatible.OpenAICompatibleNliProvider(
        endpoint(), client=transport(json_handler(body))
    )
    with pytest.raises(ProviderResponseInvalid):
        provider.classify(premise=PREMISE, hypothesis=HYPOTHESIS)


# --- claims ---


def test_the_http_claim_extractor_satisfies_the_contract() -> None:
    body = chat_body(
        {
            "claims": [
                {
                    "statement": "2026 年一季度欧洲市场库存同比下降 12%。",
                    "subject": "欧洲市场库存",
                    "predicate": "同比下降",
                    "object": "12%",
                    "source_chunk_id": "chunk_a",
                    "source_span": {"start": 0, "end": 20},
                    "extraction_confidence": 0.88,
                }
            ]
        }
    )
    provider = openai_compatible.OpenAICompatibleClaimExtractorProvider(
        endpoint(), client=transport(json_handler(body))
    )
    assert_claim_extractor_provider_contract(provider, CLAIM_REQUEST)


def test_the_same_claim_text_always_gets_the_same_id() -> None:
    """Identity is the claim's lineage, so a retry must not mint a second claim row."""
    body = chat_body(
        {
            "claims": [
                {
                    "statement": "2026 年一季度欧洲市场库存同比下降 12%。",
                    "subject": "欧洲市场库存",
                    "predicate": "同比下降",
                    "source_chunk_id": "chunk_a",
                    "source_span": {"start": 0, "end": 20},
                    "extraction_confidence": 0.88,
                }
            ]
        }
    )
    provider = openai_compatible.OpenAICompatibleClaimExtractorProvider(
        endpoint(), client=transport(json_handler(body))
    )
    first = provider.extract(CLAIM_REQUEST)
    second = provider.extract(CLAIM_REQUEST)
    assert first[0].claim_id == second[0].claim_id


def test_claims_from_different_chunks_do_not_share_an_id() -> None:
    body = chat_body(
        {
            "claims": [
                {
                    "statement": "库存同比下降 12%。",
                    "subject": "库存",
                    "predicate": "下降",
                    "source_chunk_id": "chunk_a",
                    "source_span": {"start": 0, "end": 12},
                    "extraction_confidence": 0.8,
                },
                {
                    "statement": "库存同比下降 12%。",
                    "subject": "库存",
                    "predicate": "下降",
                    "source_chunk_id": "chunk_b",
                    "source_span": {"start": 0, "end": 12},
                    "extraction_confidence": 0.8,
                },
            ]
        }
    )
    provider = openai_compatible.OpenAICompatibleClaimExtractorProvider(
        endpoint(), client=transport(json_handler(body))
    )
    first, second = provider.extract(CLAIM_REQUEST)
    assert first.claim_id != second.claim_id


def test_a_claim_citing_an_unsent_chunk_is_refused() -> None:
    body = chat_body(
        {
            "claims": [
                {
                    "statement": "库存下降了。",
                    "subject": "库存",
                    "predicate": "下降",
                    "source_chunk_id": "chunk_invented",
                    "source_span": {"start": 0, "end": 6},
                    "extraction_confidence": 0.7,
                }
            ]
        }
    )
    provider = openai_compatible.OpenAICompatibleClaimExtractorProvider(
        endpoint(), client=transport(json_handler(body))
    )
    with pytest.raises(ProviderResponseInvalid):
        provider.extract(CLAIM_REQUEST)


@pytest.mark.parametrize(
    "claim",
    [
        {"subject": "库存", "predicate": "下降", "source_chunk_id": "chunk_a"},
        {
            "statement": " ",
            "subject": "库存",
            "predicate": "下降",
            "source_chunk_id": "chunk_a",
            "source_span": {"start": 0, "end": 6},
        },
        {
            "statement": "库存下降。",
            "subject": "库存",
            "predicate": "下降",
            "source_chunk_id": "chunk_a",
            "source_span": {"start": 0, "end": 6},
            "extraction_confidence": 1.5,
        },
        {
            "statement": "库存下降。",
            "subject": "库存",
            "predicate": "下降",
            "source_chunk_id": "chunk_a",
            "source_span": {"start": 6, "end": 6},
            "extraction_confidence": 0.5,
        },
        {
            "statement": "库存下降。",
            "subject": "库存",
            "predicate": "下降",
            "source_chunk_id": "chunk_a",
            "source_span": {"start": 0, "end": 6},
            "extraction_confidence": 0.5,
            "valid_time": {"from": "2026-01-01"},
        },
    ],
)
def test_a_malformed_claim_is_refused(claim: dict[str, Any]) -> None:
    provider = openai_compatible.OpenAICompatibleClaimExtractorProvider(
        endpoint(), client=transport(json_handler(chat_body({"claims": [claim]})))
    )
    with pytest.raises(ProviderResponseInvalid):
        provider.extract(CLAIM_REQUEST)


def test_an_empty_claim_list_is_an_answer_not_an_error() -> None:
    """'Nothing here answers the question' is a result the pipeline has to be able to receive."""
    provider = openai_compatible.OpenAICompatibleClaimExtractorProvider(
        endpoint(), client=transport(json_handler(chat_body({"claims": []})))
    )
    assert provider.extract(CLAIM_REQUEST) == ()


# --- OCR and vision ---


def test_the_http_ocr_provider_satisfies_the_contract() -> None:
    body = chat_body(
        {
            "words": [
                {"text": "海外需求回暖", "box": [0.1, 0.2, 0.4, 0.3], "confidence": 0.95},
                {"text": "库存下降", "box": [0.1, 0.4, 0.3, 0.5], "confidence": 0.88},
            ],
            "confidence": 0.91,
        }
    )
    provider = openai_compatible.OpenAICompatibleOcrProvider(
        endpoint(model="qwen3-vl"), client=transport(json_handler(body))
    )
    assert_ocr_provider_contract(provider)


def test_the_ocr_request_carries_the_page_image_and_its_size() -> None:
    recorder = Recording(
        httpx.Response(
            200,
            json=chat_body(
                {
                    "words": [{"text": "一", "box": [0, 0, 1, 1], "confidence": 0.9}],
                    "confidence": 0.9,
                }
            ),
        )
    )
    provider = openai_compatible.OpenAICompatibleOcrProvider(
        endpoint(), client=transport(recorder)
    )
    provider.recognize_page(
        page_number=PAGE_NUMBER, page_image=PAGE_IMAGE, width=PAGE_WIDTH, height=PAGE_HEIGHT
    )

    encoded = base64.b64encode(PAGE_IMAGE).decode("ascii")
    contents = " ".join(
        part if isinstance(part, str) else json.dumps(part)
        for message in recorder.bodies[0]["messages"]
        for part in (
            message["content"] if isinstance(message["content"], list) else [message["content"]]
        )
    )
    assert encoded in contents
    assert "image/png" in contents
    assert str(PAGE_WIDTH) in contents and str(PAGE_HEIGHT) in contents


@pytest.mark.parametrize(
    "payload",
    [
        {"words": [], "confidence": 0.9},
        {"words": [{"text": "一", "box": [0, 0, 1], "confidence": 0.9}], "confidence": 0.9},
        {"words": [{"text": "一", "box": [0, 0, 1, 1], "confidence": 1.2}], "confidence": 0.9},
        {"words": [{"text": " ", "box": [0, 0, 1, 1], "confidence": 0.9}], "confidence": 0.9},
        {"words": [{"text": "一", "box": [0, 0, 1, 1], "confidence": 0.9}]},
        {"confidence": 0.9},
    ],
)
def test_a_malformed_ocr_answer_is_refused(payload: dict[str, Any]) -> None:
    provider = openai_compatible.OpenAICompatibleOcrProvider(
        endpoint(), client=transport(json_handler(chat_body(payload)))
    )
    with pytest.raises(ProviderResponseInvalid):
        provider.recognize_page(
            page_number=PAGE_NUMBER, page_image=PAGE_IMAGE, width=PAGE_WIDTH, height=PAGE_HEIGHT
        )


def test_the_http_vision_provider_satisfies_the_contract() -> None:
    body = chat_body(
        {
            "description": "柱状图显示 2026 年一季度欧洲储能装机同比增长 30%。",
            "chart_type": "bar",
            "confidence": 0.77,
        }
    )
    provider = openai_compatible.OpenAICompatibleVisionDocumentProvider(
        endpoint(model="qwen3-vl"), client=transport(json_handler(body))
    )
    assert_vision_provider_contract(provider)


@pytest.mark.parametrize(
    "payload",
    [
        {"description": " ", "confidence": 0.7},
        {"confidence": 0.7},
        {"description": "一根柱子在上升。", "confidence": 2.0},
        {"description": "一根柱子在上升。"},
    ],
)
def test_a_malformed_vision_answer_is_refused(payload: dict[str, Any]) -> None:
    provider = openai_compatible.OpenAICompatibleVisionDocumentProvider(
        endpoint(), client=transport(json_handler(chat_body(payload)))
    )
    with pytest.raises(ProviderResponseInvalid):
        provider.describe(image=FIGURE_IMAGE, media_type=MEDIA_TYPE, context=FIGURE_CONTEXT)


# --- failure vocabulary ---


def test_a_timeout_is_retriable_and_does_not_silently_retry_forever() -> None:
    recorder = Recording(httpx.TimeoutException("timed out"))
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(recorder)
    )
    with pytest.raises(ProviderTimeout) as raised:
        provider.embed(("文本",))
    assert raised.value.retriable is True
    assert len(recorder.requests) == 1, "a timeout is not retried inside the adapter"


def test_a_rejected_request_is_terminal_and_never_retried() -> None:
    recorder = Recording(REJECTED)
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(recorder)
    )
    with pytest.raises(ProviderRejected) as raised:
        provider.embed(("文本",))
    assert raised.value.retriable is False
    assert len(recorder.requests) == 1


def test_a_server_error_is_retried_up_to_the_configured_maximum_then_reported() -> None:
    recorder = Recording(httpx.Response(503, text="unavailable"))
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(max_retries=2), client=transport(recorder), sleep=lambda _: None
    )
    with pytest.raises(ProviderUnavailable) as raised:
        provider.embed(("文本",))
    assert raised.value.retriable is True
    assert len(recorder.requests) == 3


def test_a_rate_limited_request_is_retried_and_can_still_succeed() -> None:
    recorder = Recording(
        httpx.Response(429, text="slow down"),
        httpx.Response(200, json=embedding_body([[0.1, 0.2]])),
    )
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(max_retries=1), client=transport(recorder), sleep=lambda _: None
    )
    assert provider.embed(("文本",)).vectors == ((0.1, 0.2),)


def test_a_network_error_is_retriable() -> None:
    recorder = Recording(httpx.ConnectError("no route to host"))
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(recorder)
    )
    with pytest.raises(ProviderUnavailable) as raised:
        provider.embed(("文本",))
    assert raised.value.retriable is True


def test_a_non_json_body_is_refused_rather_than_summarized() -> None:
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(plain_handler("<html>502 Bad Gateway</html>"))
    )
    with pytest.raises(ProviderResponseInvalid):
        provider.embed(("文本",))


def test_a_cancellation_is_never_swallowed() -> None:
    """A retriable network failure must not turn a user's Ctrl-C into a provider error."""
    recorder = Recording(KeyboardInterrupt())
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(recorder)
    )
    with pytest.raises(KeyboardInterrupt):
        provider.embed(("文本",))


def test_the_api_key_never_reaches_a_log_record(caplog: pytest.LogCaptureFixture) -> None:
    recorder = Recording(httpx.Response(503, text="unavailable"))
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(recorder), sleep=lambda _: None
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderUnavailable):
        provider.embed(("文本",))
    assert caplog.records, "the adapter logs something; otherwise this test proves nothing"
    assert API_KEY not in caplog.text
    assert not any(
        isinstance(value, str) and API_KEY in value
        for record in caplog.records
        for value in vars(record).values()
    )


def test_an_empty_batch_is_refused_before_any_request_is_made() -> None:
    recorder = Recording(httpx.Response(200, json=embedding_body([[0.1]])))
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(), client=transport(recorder)
    )
    with pytest.raises(ProviderRejected):
        provider.embed(())
    assert recorder.requests == []


def test_a_client_can_be_closed_and_reused_across_calls() -> None:
    """The adapter owns no lifecycle: the caller's client decides when to close."""
    recorder = Recording(
        httpx.Response(200, json=embedding_body([[0.1]])),
        httpx.Response(200, json=embedding_body([[0.2]])),
    )
    client = transport(recorder)
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(endpoint(), client=client)
    try:
        assert provider.embed(("a",)).vectors == ((0.1,),)
        assert provider.embed(("a",)).vectors == ((0.2,),)
    finally:
        client.close()


def test_omitting_the_api_key_omits_the_authorization_header() -> None:
    """An on-premise endpoint has no key; sending an empty bearer token is a configuration lie."""
    recorder = Recording(httpx.Response(200, json=embedding_body([[0.1]])))
    provider = openai_compatible.OpenAICompatibleEmbeddingProvider(
        endpoint(api_key=None), client=transport(recorder)
    )
    provider.embed(("文本",))
    assert "authorization" not in recorder.requests[0].headers


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Any adapter built without an injected sleep must not actually wait during tests."""
    monkeypatch.setattr(openai_compatible.time, "sleep", lambda _seconds: None)
    yield


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Proof rather than intention: opening a socket fails the test that tried it.

    Every client here is built on a `MockTransport`, which is a decision someone could
    later undo without noticing. This makes the undo loud.
    """

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a provider test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    yield
