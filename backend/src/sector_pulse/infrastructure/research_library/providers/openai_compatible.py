"""OpenAI-compatible 的模型适配器：Embedding、Rerank、NLI、事实抽取、OCR 与视觉。

与 `infrastructure/llm/openai_compatible.py` 是两套东西，不是同一套的两份：那个服务于
Agent 的结构化对话（异步、按 agent 计价、有 prompt 注册表），这里服务于摄取与检索的
批处理调用（同步、按 Provider 独立计价、没有对话历史）。共用一个客户端会让"Embedding
的超时"和"NLI 的超时"变成同一个数字，而这个数字在两边该是不同的：Embedding 是批量高并发，
NLI 是单次且金额更高（规格 21 的独立配置）。

这一层只做三件事，做完就交给上层：

1. **把请求发出去**，并在超时与 5xx 上按配置重试。重试只针对"同一份请求再问一次可能就
   成了"的失败；4xx 是请求本身的问题，重试只是把同一个错误再问一遍，还多花一次钱。
2. **把响应翻译成域模型**，形状不对就抛 `ProviderResponseInvalid`，绝不"能解析多少算多少"。
   一个字段读错的置信度会以证据的身份进入报告，那时已经没人看得出它是坏的。
3. **保证顺序**：批量接口返回的顺序是 Provider 说了算的，而向量的语义就是它对应的那段
   文本。按 `index` 归位是这一层不可省略的职责。

同步而不是异步：Task 5 的端口就是同步的，摄取是一条本地 CPU 密集（解析、切片）与网络
调用交替的流水线，把其中一半改成 async 只会把线程池的问题散布到每一层。

密钥只出现在请求头里，不进日志。日志记的是路径、Provider、模型和状态码——这些足够定位
一次故障，而正文和密钥一样敏感。
"""

import base64
import hashlib
import json
import logging
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from sector_pulse.domain.research_library.models import SourceSpan
from sector_pulse.domain.research_library.retrieval import (
    ClaimStance,
    ExtractedClaim,
    NliRelation,
    TimeRange,
)
from sector_pulse.ports.research_models import (
    ClaimExtractionRequest,
    EmbeddingBatch,
    NliVerdict,
    OcrPage,
    OcrWord,
    ProviderRejected,
    ProviderResponseInvalid,
    ProviderTimeout,
    ProviderUnavailable,
    RerankResult,
    VisualDescription,
)

#: 重试的等待是翻倍的：2、4、8 秒。第一次失败多半是瞬时拥塞，第八次还在失败就不是拥塞。
RETRY_BACKOFF_SECONDS = 2.0

#: 页面图像的媒体类型是我们自己决定的：这些图由我们渲染或裁剪，不由上传方给。
PAGE_IMAGE_MEDIA_TYPE = "image/png"

NLI_INSTRUCTION = (
    "判断 hypothesis 与 premise 的关系。只输出一个 JSON 对象，不要输出任何其他文字："
    '{"relation": "ENTAILMENT"|"CONTRADICTION"|"NEUTRAL"|"UNCERTAIN", "confidence": 0..1}。'
    "ENTAILMENT 表示 premise 支持 hypothesis，CONTRADICTION 表示两者不能同时成立，"
    "NEUTRAL 表示两者无关。信息不足时必须返回 UNCERTAIN，不要猜。"
)

CLAIM_INSTRUCTION = (
    "从每个片段中抽取只回答 question 的事实。只输出一个 JSON 对象，不要输出任何其他文字："
    '{"claims": [{"statement": "完整句子", "subject": "主体", "predicate": "关系", '
    '"object": "客体或 null", "qualifiers": ["限定条件"], '
    '"valid_time": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"} 或 null, '
    '"source_chunk_id": "片段 id", "source_span": {"start": 0, "end": 10}, '
    '"extraction_confidence": 0..1, "stance": "supporting"|"opposing"|"neutral"}]}。'
    "source_chunk_id 必须是给出的片段 id 之一，source_span 是 statement 在该片段文本里的"
    "字符区间。没有相关事实时返回空数组，不要为了凑数而编造。"
)

OCR_INSTRUCTION = (
    "逐词读出这一页的文字。只输出一个 JSON 对象，不要输出任何其他文字："
    '{"words": [{"text": "词", "box": [x0, y0, x1, y1], "confidence": 0..1}], '
    '"confidence": 0..1}。'
    "坐标是 0..1 的相对值，原点在左上角。看不清的字不要猜，宁可少写一个词。"
)

VISION_INSTRUCTION = (
    "描述这张图。只输出一个 JSON 对象，不要输出任何其他文字："
    '{"description": "忠于图面的描述", "caption": null 或图题, "chart_type": 图表类型或 null, '
    '"confidence": 0..1}。'
    "只写你在图上看到的；看不清的数值不要补，confidence 要按把握程度给。"
)


@dataclass(frozen=True)
class ProviderEndpoint:
    """一类 Provider 的装配参数。

    每类 Provider 各有一份，不复用同一个对象：端点、模型、超时和重试次数是四类不同的
    事实，共享它们会让"独立配置"只剩字面意思。
    """

    base_url: str
    api_key: SecretStr | None
    model: str
    provider: str
    timeout_seconds: float = 30.0
    max_retries: int = 2

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("a provider endpoint needs a base URL")
        if not self.model.strip():
            raise ValueError("a provider endpoint needs a model")
        if not self.provider.strip():
            raise ValueError("a provider endpoint needs a provider name")


class _HttpProvider:
    """HTTP 调用的共同部分：重试、错误翻译、JSON 解码。"""

    def __init__(
        self,
        endpoint: ProviderEndpoint,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._endpoint = endpoint
        self._base_url = endpoint.base_url.rstrip("/")
        self._client = client if client is not None else httpx.Client()
        self._sleep = sleep
        self._logger = logging.getLogger(__name__)

    @property
    def endpoint(self) -> ProviderEndpoint:
        return self._endpoint

    @property
    def timeout_seconds(self) -> float:
        """这一次调用**真正**会用的超时。

        审计里记的超时必须是这一个（见 `application/research_library/provider_calls`）：配置
        只是被交下来的参数，`_send` 用的是这里返回的值，两者不一致时该被拒绝的是装配，不是
        审计里的那个数字。
        """
        return self._endpoint.timeout_seconds

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"content-type": "application/json"}
        if self._endpoint.api_key is not None:
            headers["authorization"] = f"Bearer {self._endpoint.api_key.get_secret_value()}"
        attempts = self._endpoint.max_retries + 1
        for attempt in range(attempts):
            response = self._send(path, payload, headers)
            if response.status_code == 429 or response.status_code >= 500:
                self._logger.warning(
                    "provider call failed: path=%s provider=%s model=%s status=%s attempt=%s",
                    path,
                    self._endpoint.provider,
                    self._endpoint.model,
                    response.status_code,
                    attempt + 1,
                )
                if attempt + 1 < attempts:
                    self._sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
                    continue
                raise ProviderUnavailable(
                    f"{path} returned HTTP {response.status_code} after {attempts} attempts"
                )
            if response.status_code >= 400:
                raise ProviderRejected(f"{path} returned HTTP {response.status_code}")
            return self._json(response, path)
        # 循环要么返回要么抛出；这一行让类型检查器也知道这一点。
        raise ProviderUnavailable(f"{path} exhausted its attempts")

    def _send(self, path: str, payload: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        try:
            return self._client.post(
                f"{self._base_url}{path}",
                json=payload,
                headers=headers,
                timeout=self._endpoint.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            # 超时不在这里重试：上层（Task 14）知道这次的预算还剩多少，这里只知道超时了。
            raise ProviderTimeout(
                f"{path} timed out after {self._endpoint.timeout_seconds}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{path} failed: {type(exc).__name__}") from exc

    def _json(self, response: httpx.Response, path: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderResponseInvalid(f"{path} returned a body that is not JSON") from exc
        if not isinstance(body, dict):
            raise ProviderResponseInvalid(
                f"{path} returned {type(body).__name__}, expected an object"
            )
        return body

    def _model_version(self, body: dict[str, Any]) -> str:
        """结果里记下真正回答的那个版本，而不是我们请求的那个。

        Provider 静默换版本时，审计里看到的必须是实际服务的那一个——否则"用的哪个模型"
        这个问题在任何一次事后复盘里都答不出来。
        """
        served = body.get("model")
        if isinstance(served, str) and served.strip():
            return served
        return self._endpoint.model

    def _chat_json(self, *, system: str, user: str) -> dict[str, Any]:
        body = self._post(
            "/chat/completions",
            {
                "model": self._endpoint.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        return _message_object(body)

    def _imaged(self, *, system: str, text: str, image: bytes, media_type: str) -> dict[str, Any]:
        """带一张图的一次对话调用。图按 data URI 内联：区域图像不该落在任何可被遍历的地方。"""
        return self._chat_json(system=system, user=f"{text}\n{_image_markdown(image, media_type)}")


def _message_object(body: dict[str, Any]) -> dict[str, Any]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderResponseInvalid("the response carries no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ProviderResponseInvalid("the first choice carries no message object")
    content = message.get("content")
    if isinstance(content, list):
        # 有些服务把正文切成多块返回；合起来是格式归一化，不是放宽解析。
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    if not isinstance(content, str):
        raise ProviderResponseInvalid("the message carries no text content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        # 刻意不做"剥掉代码围栏""截取最外层花括号"这类补救：一段需要猜边界的正文，其中的
        # 置信度也就无从核对，而它接下来会以证据的身份进入报告。
        raise ProviderResponseInvalid("the message content is not JSON") from exc
    if not isinstance(parsed, dict):
        raise ProviderResponseInvalid(
            f"the message content is a {type(parsed).__name__}, expected an object"
        )
    return parsed


def _number(value: Any, *, field: str) -> float:
    """取一个有限实数。

    `bool` 单独挡掉：JSON 里的 `true` 在 Python 里是 `int` 的实例，会被静默当成 1 混进
    坐标和分数里，而那种错误没有任何外部迹象。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderResponseInvalid(f"{field} must be a number, got {type(value).__name__}")
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise ProviderResponseInvalid(f"{field} must be finite")
    return number


def _unit(value: Any, *, field: str) -> float:
    """取一个置信度：必须落在 [0, 1]。"""
    number = _number(value, field=field)
    if not 0.0 <= number <= 1.0:
        raise ProviderResponseInvalid(f"{field} must be within [0, 1], got {number}")
    return number


class OpenAICompatibleEmbeddingProvider(_HttpProvider):
    """`/embeddings`，按 `index` 归位成输入顺序。"""

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        if not texts:
            raise ProviderRejected("an embedding batch must not be empty")
        body = self._post("/embeddings", {"model": self._endpoint.model, "input": list(texts)})
        vectors = _ordered_vectors(body, expected=len(texts))
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1:
            raise ProviderResponseInvalid("the vectors in one batch have different dimensions")
        return EmbeddingBatch(
            vectors=vectors,
            dimension=dimensions.pop(),
            provider=self._endpoint.provider,
            model_version=self._model_version(body),
        )


def _ordered_vectors(body: dict[str, Any], *, expected: int) -> tuple[tuple[float, ...], ...]:
    """把一批向量按 `index` 放回输入位置。

    一个下标出现两次就意味着另一个输入没有向量——归位的前提是一一对应，所以重复与越界
    都是错误，而不是"跳过这一条"。
    """
    entries = body.get("data")
    if not isinstance(entries, list) or len(entries) != expected:
        raise ProviderResponseInvalid(
            f"expected {expected} vectors, got "
            f"{len(entries) if isinstance(entries, list) else type(entries).__name__}"
        )
    ordered: list[tuple[float, ...] | None] = [None] * expected
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ProviderResponseInvalid("an embedding entry is not an object")
        index = _index(entry.get("index", position), field="an embedding index", limit=expected)
        if ordered[index] is not None:
            raise ProviderResponseInvalid(f"an embedding index {index} appears twice")
        vector = entry.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise ProviderResponseInvalid("an embedding entry carries no vector")
        ordered[index] = tuple(_number(value, field="an embedding component") for value in vector)
    return tuple(vector for vector in ordered if vector is not None)


def _index(value: Any, *, field: str, limit: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProviderResponseInvalid(f"{field} must be an integer, got {type(value).__name__}")
    if not 0 <= value < limit:
        raise ProviderResponseInvalid(f"{field} {value} is outside 0..{limit - 1}")
    return int(value)


def _text(value: Any, *, field: str) -> str:
    """取一段非空文本。空串与缺失是同一件事：都没有信息。"""
    if not isinstance(value, str) or not value.strip():
        raise ProviderResponseInvalid(f"{field} must be a non-blank string")
    return value


def _optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field=field)


def _texts(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProviderResponseInvalid(f"{field} must be a list")
    return tuple(_text(item, field=field) for item in value)


def _stance(value: Any) -> ClaimStance:
    try:
        return ClaimStance(value)
    except ValueError as exc:
        allowed = sorted(member.value for member in ClaimStance)
        raise ProviderResponseInvalid(f"stance must be one of {allowed}, got {value!r}") from exc


def _time_range(value: Any) -> TimeRange | None:
    """日期区间要么完整要么为空。

    半个区间（只有起点）不是"从这天开始"的意思：规格 14 用区间判断两条事实是否可比，
    而一个没有终点的区间与任何区间都重叠，会把不相干的事实排到一起。
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProviderResponseInvalid("valid_time must be an object or null")
    try:
        return TimeRange.model_validate(value)
    except ValidationError as exc:
        raise ProviderResponseInvalid(f"valid_time is not a complete range: {exc}") from exc


class OpenAICompatibleRerankerProvider(_HttpProvider):
    """`/rerank`，按 `index` 归位：分数必须落在它对应的文档上。"""

    def rerank(self, *, query: str, documents: Sequence[str]) -> RerankResult:
        if not documents:
            raise ProviderRejected("a rerank request must carry at least one document")
        body = self._post(
            "/rerank",
            {"model": self._endpoint.model, "query": query, "documents": list(documents)},
        )
        entries = body.get("results")
        if not isinstance(entries, list) or len(entries) != len(documents):
            raise ProviderResponseInvalid(
                f"expected {len(documents)} rerank results, got "
                f"{len(entries) if isinstance(entries, list) else type(entries).__name__}"
            )
        ordered: list[float | None] = [None] * len(documents)
        for position, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ProviderResponseInvalid("a rerank result is not an object")
            index = _index(
                entry.get("index", position), field="a rerank index", limit=len(documents)
            )
            if ordered[index] is not None:
                raise ProviderResponseInvalid(f"a rerank index {index} appears twice")
            ordered[index] = _number(entry.get("relevance_score"), field="a relevance score")
        return RerankResult(
            scores=tuple(score for score in ordered if score is not None),
            provider=self._endpoint.provider,
            model_version=self._model_version(body),
        )


class OpenAICompatibleNliProvider(_HttpProvider):
    """用对话端点做 NLI。判定与置信度都必须落在枚举与区间内，否则整条响应作废。"""

    def classify(self, *, premise: str, hypothesis: str) -> NliVerdict:
        body = self._chat_json(
            system=NLI_INSTRUCTION,
            user=json.dumps({"premise": premise, "hypothesis": hypothesis}, ensure_ascii=False),
        )
        relation = body.get("relation")
        allowed = sorted(member.value for member in NliRelation)
        if relation not in allowed:
            raise ProviderResponseInvalid(f"relation must be one of {allowed}, got {relation!r}")
        return NliVerdict(
            relation=NliRelation(relation),
            confidence=_unit(body.get("confidence"), field="confidence"),
            provider=self._endpoint.provider,
            model_version=self._model_version(body),
        )


class OpenAICompatibleClaimExtractorProvider(_HttpProvider):
    """查询相关的结构化抽取。

    这一层挡住的只有两类错误：形状不对，和引用了没有送过来的块。至于 statement 是否真的
    出现在原文里，属于 Task 12 的核对——那需要规范化后的正文，不在这一层的视野里。
    """

    def extract(self, request: ClaimExtractionRequest) -> tuple[ExtractedClaim, ...]:
        texts = {chunk.chunk_id: chunk.text for chunk in request.chunks}
        body = self._chat_json(
            system=CLAIM_INSTRUCTION,
            user=json.dumps(
                {
                    "question": request.question,
                    "chunks": [
                        {"chunk_id": chunk.chunk_id, "text": chunk.text} for chunk in request.chunks
                    ],
                },
                ensure_ascii=False,
            ),
        )
        entries = body.get("claims")
        if not isinstance(entries, list):
            raise ProviderResponseInvalid("claims must be a list")
        return tuple(self._claim(entry, texts=texts) for entry in entries)

    def _claim(self, entry: Any, *, texts: dict[str, str]) -> ExtractedClaim:
        """每个字段都在这里验过再进域模型。

        刻意不靠 Pydantic 的 ValidationError 兜底：转述出来的错误信息说的是"字段不匹配
        某个形状"，而这里能说的是"这条事实的哪一个部分不成立"——排查一条被丢掉的事实时，
        这两句话的价值不一样。
        """
        if not isinstance(entry, dict):
            raise ProviderResponseInvalid("a claim is not an object")
        chunk_id = entry.get("source_chunk_id")
        if chunk_id not in texts:
            raise ProviderResponseInvalid(
                f"a claim cites {chunk_id!r}, which was not among the chunks that were sent"
            )
        span = _source_span(entry.get("source_span"))
        statement = _text(entry.get("statement"), field="a claim statement")
        return ExtractedClaim(
            claim_id=_claim_id(chunk_id=chunk_id, statement=statement, span=span),
            statement=statement,
            subject=_text(entry.get("subject"), field="a claim subject"),
            predicate=_text(entry.get("predicate"), field="a claim predicate"),
            object=_optional_text(entry.get("object"), field="a claim object"),
            valid_time=_time_range(entry.get("valid_time")),
            qualifiers=_texts(entry.get("qualifiers", []), field="a claim qualifier"),
            source_chunk_id=chunk_id,
            source_span=span,
            extraction_confidence=_unit(
                entry.get("extraction_confidence"), field="extraction confidence"
            ),
            stance=_stance(entry.get("stance", ClaimStance.SUPPORTING.value)),
        )


def _source_span(raw: Any) -> SourceSpan:
    if not isinstance(raw, dict):
        raise ProviderResponseInvalid("a claim carries no source span")
    start = raw.get("start")
    end = raw.get("end")
    if isinstance(start, bool) or isinstance(end, bool):
        raise ProviderResponseInvalid("a source span needs integer bounds")
    if not isinstance(start, int) or not isinstance(end, int):
        raise ProviderResponseInvalid("a source span needs integer bounds")
    try:
        return SourceSpan(start=start, end=end)
    except ValidationError as exc:
        raise ProviderResponseInvalid(f"a source span is not a valid range: {exc}") from exc


def _claim_id(*, chunk_id: str, statement: str, span: SourceSpan) -> str:
    """一条事实的身份就是它的出身。

    不问模型要 ID：模型给的随机字符串会让同一件事在重试之后变成两条记录，而 ID 的用途
    正是在重试、重放和审计里认出"这还是那一条"。
    """
    digest = hashlib.sha256(f"{chunk_id}|{span.start}|{span.end}|{statement}".encode()).hexdigest()
    return f"claim_{digest[:32]}"


class OpenAICompatibleOcrProvider(_HttpProvider):
    """按页 OCR。页码由调用方给出：Provider 看到的是图像，它不知道这是第几页。"""

    def recognize_page(
        self, *, page_number: int, page_image: bytes, width: int, height: int
    ) -> OcrPage:
        body = self._imaged(
            system=OCR_INSTRUCTION,
            text=json.dumps(
                {"width": width, "height": height, "coordinates": "relative 0..1"},
                ensure_ascii=False,
            ),
            image=page_image,
            media_type=PAGE_IMAGE_MEDIA_TYPE,
        )
        raw_words = body.get("words")
        if not isinstance(raw_words, list) or not raw_words:
            # 空页是可能的，但"读到了零个词"与"这一页没有文字"必须由调用方判断，
            # 因此这里不接受空列表：OCR 说没有文字，走的是"这一页是图片"的路径。
            raise ProviderResponseInvalid("an OCR page must carry at least one word")
        return OcrPage(
            page_number=page_number,
            words=tuple(_ocr_word(entry) for entry in raw_words),
            provider=self._endpoint.provider,
            model_version=self._model_version(body),
            confidence=_unit(body.get("confidence"), field="page confidence"),
        )


def _ocr_word(entry: Any) -> OcrWord:
    if not isinstance(entry, dict):
        raise ProviderResponseInvalid("an OCR word is not an object")
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ProviderResponseInvalid("an OCR word carries no text")
    box = entry.get("box")
    if not isinstance(box, list) or len(box) != 4:
        raise ProviderResponseInvalid("an OCR word needs a four-number box")
    return OcrWord(
        text=text,
        bounding_box=(
            _number(box[0], field="a box coordinate"),
            _number(box[1], field="a box coordinate"),
            _number(box[2], field="a box coordinate"),
            _number(box[3], field="a box coordinate"),
        ),
        confidence=_unit(entry.get("confidence"), field="word confidence"),
    )


class OpenAICompatibleVisionDocumentProvider(_HttpProvider):
    """图表与图片的结构化描述。低置信度的结论由上层按 `min_vision_confidence` 处置。"""

    def describe(
        self, *, image: bytes, media_type: str, context: str | None = None
    ) -> VisualDescription:
        body = self._imaged(
            system=VISION_INSTRUCTION,
            text=context or "（没有提供上下文）",
            image=image,
            media_type=media_type,
        )
        return VisualDescription(
            description=_text(body.get("description"), field="a vision description"),
            caption=_optional_text(body.get("caption"), field="a figure caption"),
            chart_type=_optional_text(body.get("chart_type"), field="a chart type"),
            confidence=_unit(body.get("confidence"), field="vision confidence"),
            provider=self._endpoint.provider,
            model_version=self._model_version(body),
        )


def _image_markdown(image: bytes, media_type: str) -> str:
    """把图片按 data URI 的形式附在正文里。

    这是这类端点唯一被普遍支持的传图方式；"内联"也正好符合规格 18.3 的要求——区域图像
    只在这一次调用里存在，不落在任何可被遍历的地方。
    """
    encoded = base64.b64encode(image).decode("ascii")
    return f"![image](data:{media_type};base64,{encoded})"
