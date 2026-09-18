"""离线的模型 Provider：确定性、无网络，且在没有声明答案时明确失败。

这套 Fixture 服务于两件事。一是离线门禁：解析、切片、检索、NLI 的测试不能依赖真实模型
端点，否则每次跑都要钱、要网、还要接受结果会变。二是让上层逻辑真的可测——一个永远返回
同一个向量的 Embedding 会让"混合检索"退化成"验证排序函数"，所以这里的 Embedding 带真实
的相似度结构，Reranker 真的按相关性打分，NLI 真的分蕴含/矛盾/无关。

"没有声明答案时明确失败"是这套 Fixture 最重要的一条：返回空结果、返回默认置信度、返回
一个占位描述，都会让调用方以为自己拿到了一个结论。`ProviderNotConfigured` 说的是"这里
少配了一件东西"，与"Provider 说没有"是两回事，调用方分得开才可能做出正确的反应。
"""

import hashlib
import math
from collections.abc import Mapping, Sequence

from sector_pulse.domain.research_library.models import SourceSpan
from sector_pulse.domain.research_library.retrieval import (
    ClaimStance,
    ExtractedClaim,
    NliRelation,
)
from sector_pulse.ports.research_models import (
    ClaimExtractionRequest,
    EmbeddingBatch,
    NliVerdict,
    OcrPage,
    OcrWord,
    ProviderNotConfigured,
    ProviderRejected,
    ProviderResponseInvalid,
    RerankResult,
    VisualDescription,
)

FIXTURE_PROVIDER = "fixture"

#: 否定词。中文里"没有/未/不再"改变整句话的真值，NLI Fixture 靠它们区分矛盾与无关。
NEGATIONS = ("没有", "未", "不再", "不", "无", "非")

#: 图描述的默认值：一个没有图表类型的描述仍然是描述，缺的是那三个字而不是整句话。
DEFAULT_CONFIDENCE = 0.9


# --- 可复用的构造助手 ---
#
# 测试里手写 OcrWord/ExtractedClaim 的完整字段只会让每处断言都被样板淹没，而样板一多，
# 真正想断言的那一行就看不见了。


def ocr_page(
    *, page_number: int, lines: Sequence[str], confidence: float = DEFAULT_CONFIDENCE
) -> OcrPage:
    """按行造一页 OCR 结果。每行一个 word，坐标自上而下依次排开。

    真实 OCR 会给每个词一个框；这里按行给框，是因为 Fixture 要回答的问题是"这一页读到了
    什么"，而不是"每个词落在哪个像素上"。
    """
    words = tuple(
        OcrWord(
            text=line,
            bounding_box=(0.1, 0.05 + index * 0.05, 0.9, 0.1 + index * 0.05),
            confidence=confidence,
        )
        for index, line in enumerate(lines)
    )
    return OcrPage(
        page_number=page_number,
        words=words,
        provider=FIXTURE_PROVIDER,
        model_version="fixture-ocr-v1",
        confidence=confidence,
    )


def visual_description(
    *,
    description: str,
    confidence: float = DEFAULT_CONFIDENCE,
    chart_type: str | None = None,
    caption: str | None = None,
) -> VisualDescription:
    return VisualDescription(
        description=description,
        caption=caption,
        chart_type=chart_type,
        confidence=confidence,
        provider=FIXTURE_PROVIDER,
        model_version="fixture-vision-v1",
    )


def claim(
    *,
    chunk_id: str,
    statement: str,
    subject: str,
    predicate: str | None = None,
    object: str | None = None,
    span: SourceSpan | None = None,
    confidence: float = DEFAULT_CONFIDENCE,
    stance: ClaimStance = ClaimStance.SUPPORTING,
) -> ExtractedClaim:
    """造一条事实。`span` 缺省时取整段 statement 的位置，`claim_id` 由来源决定。

    与 HTTP 适配器同一条规则：ID 是这条事实的出身（哪一块、哪一段、说了什么），不是
    随机数——重试一次就换一个 ID 的话，同一件事会被记成两条。
    """
    location = span if span is not None else SourceSpan(start=0, end=max(1, len(statement)))
    return ExtractedClaim(
        claim_id=claim_id(chunk_id=chunk_id, statement=statement, span=location),
        statement=statement,
        subject=subject,
        predicate=predicate if predicate is not None else statement,
        object=object,
        source_chunk_id=chunk_id,
        source_span=location,
        extraction_confidence=confidence,
        stance=stance,
    )


def claim_id(*, chunk_id: str, statement: str, span: SourceSpan) -> str:
    """一条事实的身份就是它的出身。

    问模型"请给它一个 ID"会得到一个每次都不一样、也无法核对的字符串；而从来源算出来的
    ID 在重试、重放和审计里都是同一个值。
    """
    digest = hashlib.sha256(f"{chunk_id}|{span.start}|{span.end}|{statement}".encode()).hexdigest()
    return f"claim_{digest[:32]}"


# --- Embedding ---


class FixtureEmbeddingProvider:
    """确定性的 Embedding：同样文本永远同一个向量，且相似文本的余弦更高。

    做法是把文本切成字符二元组（CJK 与西文一视同仁），用 sha256 把它们散列到固定维度的
    坐标上、按符号累加、再归一化——经典的 hashing trick，没有任何随机数。它不接近任何真实
    模型的语义空间，但它保住了上层真正依赖的两条性质：确定性，和"越像越近"。
    """

    provider = FIXTURE_PROVIDER

    def __init__(
        self,
        *,
        dimension: int = 256,
        model_version: str = "fixture-embedding-v1",
        vectors: Mapping[str, tuple[float, ...]] | None = None,
    ) -> None:
        if dimension <= 0:
            raise ValueError("an embedding dimension must be positive")
        for text, vector in (vectors or {}).items():
            if len(vector) != dimension:
                raise ValueError(
                    f"the fixed vector for {text!r} has dimension {len(vector)}, not {dimension}"
                )
        self._dimension = dimension
        self._model_version = model_version
        self._vectors = dict(vectors or {})

    @property
    def model_version(self) -> str:
        return self._model_version

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        if not texts:
            raise ProviderRejected("an embedding batch must not be empty")
        vectors = tuple(self._vector(text) for text in texts)
        return EmbeddingBatch(
            vectors=vectors,
            dimension=self._dimension,
            provider=FIXTURE_PROVIDER,
            model_version=self._model_version,
        )

    def _vector(self, text: str) -> tuple[float, ...]:
        fixed = self._vectors.get(text)
        if fixed is not None:
            return fixed
        vector = [0.0] * self._dimension
        for gram in _bigrams(text):
            digest = hashlib.sha256(gram.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            # 空文本或全部抵消：给一个确定的方向，让余弦是 0 而不是未定义。
            vector[0] = 1.0
            return tuple(vector)
        return tuple(value / norm for value in vector)


def _bigrams(text: str) -> tuple[str, ...]:
    """空白归一化后的字符二元组；单字文本退化成它自己。"""
    compact = "".join(text.split())
    if len(compact) < 2:
        return (compact,) if compact else ()
    return tuple(compact[index : index + 2] for index in range(len(compact) - 1))


# --- Rerank ---


class FixtureRerankerProvider:
    """按词面重叠打分的 Reranker。

    这不是"假装的相关性"：词面重叠是一个真实存在、可解释的打分函数，而且它刻意不引入
    语义——如果检索链路上层写错了，测试会看到排序真的变了，而不是被 Fixture 的语义兜住。
    """

    provider = FIXTURE_PROVIDER
    model_version = "fixture-reranker-v1"

    def __init__(self, *, scores: Mapping[str, float] | None = None) -> None:
        self._scores = dict(scores or {})

    def rerank(self, *, query: str, documents: Sequence[str]) -> RerankResult:
        if not documents:
            raise ProviderRejected("a rerank request must carry at least one document")
        return RerankResult(
            scores=tuple(self._score(query, document) for document in documents),
            provider=FIXTURE_PROVIDER,
            model_version=self.model_version,
        )

    def _score(self, query: str, document: str) -> float:
        fixed = self._scores.get(document)
        if fixed is not None:
            return fixed
        wanted = set(_bigrams(query))
        if not wanted:
            return 0.0
        present = set(_bigrams(document))
        return len(wanted & present) / len(wanted)


# --- NLI ---


class FixtureNliProvider:
    """按词面关系判定蕴含、矛盾与无关的 NLI。

    规则只有三条，顺序即优先级：显式声明的判定最优先；假设里出现前件没有的否定词，判为
    矛盾；假设的每个二元组都能在前件里找到，判为蕴含；其余一律 UNCERTAIN。

    最后一条是刻意的：真实 NLI 模型在信息不足时会给出一个高分的中性判断，而下游的冲突
    裁决必须区分"模型说无关"与"模型没说清"——只有后者该继续找证据。
    """

    provider = FIXTURE_PROVIDER
    model_version = "fixture-nli-v1"

    def __init__(self, *, verdicts: Mapping[tuple[str, str], NliRelation] | None = None) -> None:
        self._verdicts = dict(verdicts or {})

    def classify(self, *, premise: str, hypothesis: str) -> NliVerdict:
        declared = self._verdicts.get((premise, hypothesis))
        if declared is not None:
            return self._verdict(declared, 0.99)
        overlap = self._overlap(premise, hypothesis)
        if self._contradicts(premise, hypothesis):
            return self._verdict(NliRelation.CONTRADICTION, min(0.99, 1.0 - overlap / 2))
        if overlap >= 0.5:
            return self._verdict(NliRelation.ENTAILMENT, min(0.99, 0.5 + overlap / 2))
        return self._verdict(NliRelation.UNCERTAIN, max(0.0, overlap / 2))

    def _verdict(self, relation: NliRelation, confidence: float) -> NliVerdict:
        return NliVerdict(
            relation=relation,
            confidence=confidence,
            provider=FIXTURE_PROVIDER,
            model_version=self.model_version,
        )

    @staticmethod
    def _contradicts(premise: str, hypothesis: str) -> bool:
        return _negated(hypothesis) != _negated(premise)

    @staticmethod
    def _overlap(premise: str, hypothesis: str) -> float:
        wanted = set(_bigrams(hypothesis))
        if not wanted:
            return 0.0
        return len(wanted & set(_bigrams(premise))) / len(wanted)


def _negated(text: str) -> bool:
    return any(negation in text for negation in NEGATIONS)


# --- 事实抽取 ---


class FixtureClaimExtractorProvider:
    """按问题查表的事实抽取器。

    缺省不是"抽不出事实"，而是"这个问题没有声明过答案"：抽取器返回空元组是一个合法的
    结论（这一段确实不回答这个问题），而一个没有被声明的 Fixture 给出空元组会让测试把
    "没配对"读成"确实没有事实"。两者用不同的异常分开。
    """

    provider = FIXTURE_PROVIDER
    model_version = "fixture-claim-extractor-v1"

    def __init__(self, *, claims: Mapping[str, Sequence[ExtractedClaim]]) -> None:
        self._claims = {question: tuple(items) for question, items in claims.items()}

    def extract(self, request: ClaimExtractionRequest) -> tuple[ExtractedClaim, ...]:
        if request.question not in self._claims:
            raise ProviderNotConfigured(f"no fixture declares claims for {request.question!r}")
        allowed = {chunk.chunk_id for chunk in request.chunks}
        extracted = self._claims[request.question]
        for entry in extracted:
            # 与 HTTP 适配器同一条规则：引用了没送过来的块，就是凭空引用。
            if entry.source_chunk_id not in allowed:
                raise ProviderResponseInvalid(
                    f"claim {entry.claim_id} cites {entry.source_chunk_id!r}, "
                    "which was not among the chunks that were sent"
                )
        return extracted


# --- OCR 与视觉 ---


class FixtureOcrProvider:
    """按页号查表的 OCR。页号不在表里就是没配，而不是"这一页是空的"。"""

    provider = FIXTURE_PROVIDER
    model_version = "fixture-ocr-v1"

    def __init__(self, *, pages: Mapping[int, OcrPage], default: OcrPage | None = None) -> None:
        self._pages = dict(pages)
        self._default = default

    def recognize_page(
        self, *, page_number: int, page_image: bytes, width: int, height: int
    ) -> OcrPage:
        del page_image, width, height
        page = self._pages.get(page_number, self._default)
        if page is None:
            raise ProviderNotConfigured(f"no fixture declares page {page_number}")
        return page


class FixtureVisionDocumentProvider:
    """按图片内容查表的视觉描述。

    键是图片字节的散列而不是文件名或位置：同一张图换个路径仍然是同一张图，而同一个路径
    下换一张图必须是另一段描述。
    """

    provider = FIXTURE_PROVIDER
    model_version = "fixture-vision-v1"

    def __init__(
        self,
        *,
        descriptions: Mapping[str, VisualDescription],
        default: VisualDescription | None = None,
    ) -> None:
        self._descriptions = dict(descriptions)
        self._default = default

    @classmethod
    def keyed_by_image(
        cls,
        descriptions: Mapping[bytes, VisualDescription],
        *,
        default: VisualDescription | None = None,
    ) -> "FixtureVisionDocumentProvider":
        return cls(
            descriptions={
                hashlib.sha256(image).hexdigest(): description
                for image, description in descriptions.items()
            },
            default=default,
        )

    def describe(
        self, *, image: bytes, media_type: str, context: str | None = None
    ) -> VisualDescription:
        del media_type, context
        description = self._descriptions.get(hashlib.sha256(image).hexdigest(), self._default)
        if description is None:
            raise ProviderNotConfigured("no fixture describes this image")
        return description
