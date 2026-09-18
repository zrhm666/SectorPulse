"""真实 Provider 的冒烟测试（Task 20 Step 5）。

这一份**只回答一个问题**：这几类端点按我们写的那套提示词与 JSON 形状，真的能跑通吗？
它不测检索质量——那是黄金集与 `evaluation/test_research_rag_golden.py` 的事。冒烟测试在这里
花真钱，因此它要做到三件事：

1. **离线绝不运行。** 标记是 `live_rag`，`--run-live-rag` 与 `.live-rag-consent` 都在才跑
   （见 `backend/tests/conftest.py`）。它不落在 `live` 这个名字下面，因此行情那一份同意书
   不会把它捎带进来。
2. **预算是有闸的，不是有注释的。** 每一次真实调用都在调用**之前**从一个模块级的预算里扣数，
   扣不动就断言失败。上限与 deadline 写在下面，不读配置文件——一份可以被环境改大的预算不是
   预算，而这份测试的读者要能一眼看到它最多花多少钱。
3. **语料是自己编的。** 正文、查询、PDF 全在测试里生成，不碰生产数据，也不读仓库外的文件。

**已知的接线缺口（与 E138 同一条）：** 仓库里还没有生产级的 RAG 装配器，因此每类 Provider 的
端点参数没有配置归属。这里用 `SECTOR_PULSE_RAG_<KIND>_PROVIDER` / `_MODEL`（`load_rag_settings`
真的会读的那两个键）配上一个 base URL 与 key——base URL 与 key 取自仓库里唯一那处已配置的
OpenAI 兼容端点（`SECTOR_PULSE_LLM_BASE_URL` / `SECTOR_PULSE_LLM_API_KEY`）。这不是一套新配置
面，而是一个还没有归属的值暂时用现有那一处；装配器落地时它应当有自己的键，届时这一份也跟着改。
未配置时逐项 `pytest.skip`，并在原因里点名缺的是哪个键。
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from sector_pulse.infrastructure.research_library.providers.openai_compatible import (
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleNliProvider,
    OpenAICompatibleOcrProvider,
    OpenAICompatibleRerankerProvider,
    OpenAICompatibleVisionDocumentProvider,
)
from sector_pulse.ports.research_models import NliRelation

from backend.tests.research_library_live_support import endpoint_for

pytestmark = pytest.mark.live_rag

#: 整份冒烟套件的硬上限。用例数与调用数的对应关系是：Embedding 1、Reranker 1、NLI 2、
#: OCR 1、Vision 1，共 6 次；留 2 次余量给重试之外的手工排查，但绝不允许无声地涨上去。
MAX_CALLS = 8

#: 整份套件的墙钟上限。Provider 端超时是逐次生效的，一个卡住的端点会让"每次 60 秒"累成十几分钟，
#: 因此这一档管的是套件整体。
DEADLINE_SECONDS = 600.0

#: OCR 那一页上唯一的字母数字记号。中文 OCR 的分词方式各家不同，字母数字串是唯一能稳定
#: 断言的形状——它不该被"词"的切法改掉。
PAGE_TOKEN = "SP2049"

#: OCR 与视觉用同一页渲染，尺寸固定，产物可复现。
PAGE_WIDTH = 595
PAGE_HEIGHT = 842
PAGE_DPI = 150


@dataclass
class Budget:
    """真实调用的预算。扣数发生在调用之前，扣不动的那一次不会发出去。"""

    max_calls: int = MAX_CALLS
    deadline_seconds: float = DEADLINE_SECONDS
    started: float = field(default_factory=time.monotonic)
    calls: int = 0

    @contextmanager
    def spend(self, what: str) -> Iterator[None]:
        if self.calls + 1 > self.max_calls:
            raise AssertionError(
                f"this suite is capped at {self.max_calls} real provider calls; "
                f"the {what} call would be number {self.calls + 1}"
            )
        elapsed = time.monotonic() - self.started
        if elapsed > self.deadline_seconds:
            raise AssertionError(
                f"this suite is capped at {self.deadline_seconds:.0f}s; "
                f"the {what} call would start at {elapsed:.0f}s"
            )
        self.calls += 1
        yield


@pytest.fixture(scope="module")
def budget() -> Budget:
    return Budget()


@pytest.fixture(scope="module")
def page_png() -> tuple[bytes, int, int]:
    """一页我们自己画的 PDF 渲染成的 PNG：OCR 读它，是一页真实文字，不是语料库里的东西。"""
    pymupdf = pytest.importorskip("pymupdf", reason="the 'rag' extra is not installed")
    document = pymupdf.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((72, 96), "储能行业产能跟踪", fontname="china-s", fontsize=20.0)
    page.insert_text((72, 132), f"报告编号 {PAGE_TOKEN}", fontname="china-s", fontsize=12.0)
    page.insert_text(
        (72, 168), "二线厂商的产能利用率在过去一个季度上升。", fontname="china-s", fontsize=12.0
    )
    pixmap = page.get_pixmap(dpi=PAGE_DPI)
    painted = (pixmap.tobytes("png"), int(pixmap.width), int(pixmap.height))
    document.close()
    return painted


@pytest.fixture(scope="module")
def chart_png() -> bytes:
    """一张自己画的条形图。视觉那一档要的是一张真的图，不是一页文字。"""
    pymupdf = pytest.importorskip("pymupdf", reason="the 'rag' extra is not installed")
    document = pymupdf.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((72, 96), "海外订单金额（亿元）", fontname="china-s", fontsize=16.0)
    for index, (label, height) in enumerate(
        (("2026Q1", 118.0), ("2026Q2", 157.0)), start=1
    ):
        left = 72.0 + index * 90.0
        page.draw_rect(pymupdf.Rect(left, 600.0 - height, left + 60.0, 600.0), color=(0, 0, 1))
        page.insert_text((left, 620), label, fontname="china-s", fontsize=10.0)
    painted = page.get_pixmap(dpi=PAGE_DPI).tobytes("png")
    document.close()
    return painted


def test_the_embedding_dimension_is_the_one_the_collection_was_built_with(budget: Budget) -> None:
    """维度对不上，Milvus 建集合时就该失败；但那时看到的是"上传失败"，不是"模型不对"。"""
    configured = os.environ.get("SECTOR_PULSE_RAG_EMBEDDING_DIMENSION")
    if not configured:
        pytest.skip(
            "SECTOR_PULSE_RAG_EMBEDDING_DIMENSION is unset; the collection dimension is unknown"
        )
    provider = OpenAICompatibleEmbeddingProvider(endpoint_for("embedding"))
    texts = ("储能行业 2026 年中期策略", "二线厂商的产能利用率承压", "国内大储招标量创下历史新高")
    with budget.spend("embedding"):
        batch = provider.embed(texts)
    # 顺序是契约的一部分：向量的下标就是输入文本的下标，错位不会报错，只会悄悄检索到别的段落。
    assert len(batch.vectors) == len(texts)
    assert batch.dimension == int(configured)
    assert batch.provider
    assert batch.model_version


def test_the_reranker_scores_every_document_it_was_given(budget: Budget) -> None:
    provider = OpenAICompatibleRerankerProvider(endpoint_for("reranker"))
    documents = (
        "二线厂商的产能利用率在过去一个季度上升。",
        "电解液价格环比上涨百分之六。",
        "公司发布股份回购公告，拟回购金额不超过两亿元。",
    )
    with budget.spend("reranker"):
        result = provider.rerank(query="二线厂商的产能利用率怎么变？", documents=documents)
    assert len(result.scores) == len(documents)
    # 分数的量纲由端点决定（可能是 logits，不一定是 0..1），因此这里只要求它是个有限的实数。
    assert all(isinstance(score, float) for score in result.scores)
    assert sorted(result.best_order()) == list(range(len(documents)))
    # 三份内容完全不同的文档拿到三个一模一样的分数，说明这个端点没有在重排。
    assert len(set(result.scores)) > 1, result.scores


def test_nli_calls_a_contradiction_a_contradiction(budget: Budget) -> None:
    """这一条是冲突裁决的地基：把相反的两句判成 ENTAILMENT 的模型会让 UNCERTAIN 变成谎话。"""
    provider = OpenAICompatibleNliProvider(endpoint_for("nli"))
    premise = "调研结论：二线厂商的产能利用率在过去一个季度上升。"
    with budget.spend("nli"):
        contradiction = provider.classify(
            premise=premise, hypothesis="调研结论：二线厂商的产能利用率在过去一个季度没有上升。"
        )
    with budget.spend("nli"):
        entailment = provider.classify(
            premise=premise, hypothesis="二线厂商的产能利用率上升了。"
        )
    assert contradiction.relation is NliRelation.CONTRADICTION
    assert entailment.relation is NliRelation.ENTAILMENT
    floor = float(os.environ.get("SECTOR_PULSE_RAG_MIN_NLI_CONFIDENCE", "0.7"))
    assert contradiction.confidence >= floor, contradiction
    assert entailment.confidence >= floor, entailment


def test_ocr_reads_one_page_of_our_own_pdf(
    budget: Budget, page_png: tuple[bytes, int, int]
) -> None:
    image, width, height = page_png
    provider = OpenAICompatibleOcrProvider(endpoint_for("ocr"))
    with budget.spend("ocr"):
        page = provider.recognize_page(
            page_number=1, page_image=image, width=width, height=height
        )
    assert page.page_number == 1
    assert page.words
    joined = "".join(word.text for word in page.words).upper().replace("-", "").replace(" ", "")
    assert PAGE_TOKEN in joined, page.text
    # 坐标是 0..1 的相对值，原点在左上角——解析器的版面规则按这个量纲算行距与字号。返回像素
    # 坐标的端点不会报错，只会让版面规则算出一堆荒谬的数值。
    for word in page.words:
        for coordinate in word.bounding_box:
            assert 0.0 <= coordinate <= 1.0, word
    floor = float(os.environ.get("SECTOR_PULSE_RAG_MIN_OCR_CONFIDENCE", "0.6"))
    assert page.confidence >= floor, page


def test_vision_describes_a_chart_when_it_is_configured(budget: Budget, chart_png: bytes) -> None:
    """Vision 是可选的一档：没有配就跳过，配了就必须回一份通过校验的描述。"""
    provider = OpenAICompatibleVisionDocumentProvider(endpoint_for("vision"))
    with budget.spend("vision"):
        description = provider.describe(
            image=chart_png, media_type="image/png", context="海外订单金额的季度对比图"
        )
    assert len(description.description.strip()) >= 8, description
    assert description.provider
    assert description.model_version


def test_the_smoke_suite_stayed_inside_its_budget(budget: Budget) -> None:
    """放在最后：它是这一份自己的账单。跳过的用例不扣数，因此这条的期望是"至多"。"""
    assert budget.calls <= MAX_CALLS, budget.calls
