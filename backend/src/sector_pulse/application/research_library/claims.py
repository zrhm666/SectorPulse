"""查询期事实抽取，以及进入 NLI 之前的分组（规格 12、13）。

这一层做两件事，两件事的失败方向相反，因此写法也相反。

**抽取宁可拒绝。** 模型返回的一条事实，只有在它引用的切片正文里**真的找得到**的时候
才算数：主体、宾语、每一个限定词都必须出现在 `source_span` 圈出来的那一段里，置信度必须
够。任何一条不满足的事实被丢掉，而不是被修补、被传给下游。丢掉是唯一诚实的结果——这一层
无法知道模型想说什么，而一条编出来的事实到了裁决器那里，和一条真事实穿着同样的衣服。
比对的是**片段**而不是整块切片，这正是 `source_span` 从"装饰"变成"有承重作用"的地方：
一条事实可以把主体写对、却把出处指向别处，那它引用的那一段并不支持它。

谓词不在比对之列。`增长情况` 这样的属性名是被归一出来的标签，不是谁会在报告里写下的
句子；要求它在原文里出现，等于要求原文按我们的字段表说话。

**分组宁可纳入。** 主体归一后相同、属性相同、时间可比较的两条事实会被分到一组，哪怕
它们看起来完全一致——"这两条说的是同一件事"是 NLI 该下的判断，不是字符串比较该下的
判断。这一层拒绝的是笛卡尔积：主体不同或属性不同的两条事实永远不会被配成一对，而正是
这条拒绝把 NLI 的账单限制住了。

时间可比较**不是**分组键的一部分，因为它描述的是两条事实之间的关系，而不是单条事实的
属性：把时间塞进键里，要么让季度不同但其实同属一句结论的两条事实彻底失联，要么对每组
做一遍两两判断从而退回笛卡尔积。这里把"时间可比较"当成一条边，组是它的连通分量：Q1 与
Q2 不重叠，一条覆盖全年的第三条事实会把它们连成一组，而不是取决于谁先被抽出来。

别名表由调用方注入。`CATL` 与 `宁德时代` 是不是同一个实体，不是这一层能发明的事，写死
一张表只会让资料库里真实存在的第三种写法永远配不上。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence

from pydantic import Field
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.research_library.models import Record, SourceSpan
from sector_pulse.domain.research_library.retrieval import (
    ExtractedClaim,
    RetrievedCandidate,
    TimeRange,
)
from sector_pulse.ports.research_models import (
    ClaimExtractionRequest,
    ClaimExtractorProvider,
    ClaimSourceChunk,
)

__all__ = [
    "ClaimExtractionService",
    "ComparableClaimGroup",
    "group_comparable_claims",
    "normalise_entity",
]

#: 分组前的字段数下限：一条事实没有可比的对象，就不是"可比较组"，也不该占一个组的位置。
MIN_COMPARABLE_CLAIMS = 2


def normalise_entity(value: str) -> str:
    """把一个名字折成它的键：NFKC、去掉所有空白、大小写折叠。

    全角与半角、大小写、以及 PDF 提取时插在词中间的空格，都是同一个名字的几种写法；
    不折叠的话，`ＣＡＴＬ` 和 `CATL` 会被当成两个主体，各自去和别的说法配组。折叠只做
    这些机械的替换，不做任何别名推断。
    """
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


class ComparableClaimGroup(Record):
    """一组可以送去问 NLI 的事实。

    `subject_key` / `predicate_key` 是归一后的键，不是给人看的名字：拿它们当展示文案会
    让文档里原本的写法（大小写、全角）在界面上消失。展示用的名字在原始的事实里。
    """

    subject_key: str = Field(min_length=1)
    predicate_key: str = Field(min_length=1)
    claims: tuple[ExtractedClaim, ...] = Field(min_length=MIN_COMPARABLE_CLAIMS)

    @property
    def claim_ids(self) -> tuple[str, ...]:
        return tuple(claim.claim_id for claim in self.claims)


def _span_is_inside(span: SourceSpan, length: int) -> bool:
    """片段必须落在切片正文之内。

    Python 的切片对越界是静默截断的，因此"取出来的那段文字里有主体"这句话，在一个
    `end` 超出正文的片段上也可能成立——那已经不是在核对出处，而是在核对一段被截短的
    投影。
    """
    return span.start < span.end <= length


def _asserted_components(claim: ExtractedClaim) -> tuple[str, ...]:
    """这条事实在原文里主张了哪些字面内容。

    谓词不在其中（见模块说明）。主体、宾语与限定词都在：这三者加起来就是"这段话说了
    什么"，而其中任何一个凭空出现的字，都说明这条事实不是从这一段读出来的。
    """
    parts = [claim.subject, *(claim.qualifiers)]
    if claim.object:
        parts.append(claim.object)
    return tuple(part for part in parts if part.strip())


def _is_grounded(claim: ExtractedClaim, span_text: str) -> bool:
    haystack = normalise_entity(span_text)
    return all(normalise_entity(part) in haystack for part in _asserted_components(claim))


def _key_of(subject: str, aliases: Mapping[str, str]) -> str:
    key = normalise_entity(subject)
    alias = aliases.get(key)
    return key if alias is None else normalise_entity(alias)


def _time_comparable(left: TimeRange | None, right: TimeRange | None) -> bool:
    """规格 13 的"时间范围重叠或存在可比较关系"。

    一侧没有时间就认为可比较：一个没有说自己管哪一段时间的事实，不因此就不再是关于
    那一段时间的，把它排除掉只会让"没有标注时间"变成躲避比对的写法。两侧都有时间时
    要求闭区间相交；完全错开的两个窗口说的是两件不同的事，让它们进入 NLI 只会换来一个
    昂贵的 `NOT_CONFLICT`。
    """
    if left is None or right is None:
        return True
    return left.start <= right.end and right.start <= left.end


def _components(bucket: Sequence[ExtractedClaim]) -> list[list[ExtractedClaim]]:
    """把一组候选按"时间可比较"拆成连通分量，保持原有次序。

    用连通分量而不是依次就近归并：就近归并的结果取决于输入顺序，而输入顺序来自模型的
    输出顺序——那意味着同一批事实换个顺序抽出来会得到不同的组，进而得到不同的裁决。
    """
    remaining = list(range(len(bucket)))
    components: list[list[ExtractedClaim]] = []
    while remaining:
        seed = remaining.pop(0)
        reached = [seed]
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            opened: list[int] = []
            kept: list[int] = []
            for index in remaining:
                destination = (
                    opened
                    if _time_comparable(bucket[current].valid_time, bucket[index].valid_time)
                    else kept
                )
                destination.append(index)
            reached.extend(opened)
            frontier.extend(opened)
            remaining = kept
        components.append([bucket[index] for index in sorted(reached)])
    return components


def group_comparable_claims(
    claims: Sequence[ExtractedClaim], *, aliases: Mapping[str, str] | None = None
) -> tuple[ComparableClaimGroup, ...]:
    """按规格 13 把事实归组；只有两条以上的组会被返回。

    返回顺序是主体第一次出现的顺序，组内是事实到达的顺序。两者都是稳定的，因为审计里
    "第几组、组里第几条"是会被引用的位置。
    """
    resolved = {normalise_entity(name): canonical for name, canonical in (aliases or {}).items()}
    buckets: dict[tuple[str, str], list[ExtractedClaim]] = {}
    order: list[tuple[str, str]] = []
    for claim in claims:
        key = (_key_of(claim.subject, resolved), normalise_entity(claim.predicate))
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(claim)

    groups: list[ComparableClaimGroup] = []
    for subject_key, predicate_key in order:
        for component in _components(buckets[(subject_key, predicate_key)]):
            if len(component) >= MIN_COMPARABLE_CLAIMS:
                groups.append(
                    ComparableClaimGroup(
                        subject_key=subject_key,
                        predicate_key=predicate_key,
                        claims=tuple(component),
                    )
                )
    return tuple(groups)


class ClaimExtractionService:
    """规格 12 的查询期事实抽取。"""

    def __init__(self, *, provider: ClaimExtractorProvider, settings: RagSettings) -> None:
        self._provider = provider
        self._settings = settings

    def extract(
        self, question: str, candidates: Sequence[RetrievedCandidate]
    ) -> tuple[ExtractedClaim, ...]:
        """从这一次检索的候选里抽出与问题有关的事实。

        没有候选就不调用 Provider：一个空的抽取请求既没有意义，也会白白花掉一次调用
        预算。返回的事实**不属于任何持久化结构**——按规格 12，抽取结果默认只属于当前
        检索运行，只有最终被采用或进入冲突判断的那些才随审计保存，那是 Task 15 的事。
        这个类因此不持有任何仓储，写不进去是它的结构性质，不是它的自我约束。
        """
        if not candidates:
            return ()
        request = ClaimExtractionRequest(
            question=question,
            chunks=tuple(
                ClaimSourceChunk(chunk_id=candidate.chunk_id, text=candidate.text)
                for candidate in candidates
            ),
        )
        texts = {chunk.chunk_id: chunk.text for chunk in request.chunks}

        accepted: dict[str, ExtractedClaim] = {}
        for claim in self._provider.extract(request):
            text = texts.get(claim.source_chunk_id)
            if text is None:
                # 引用了没送过去的切片：这段原文在这个进程里不存在，无法核对。
                continue
            if not _span_is_inside(claim.source_span, len(text)):
                continue
            if not _is_grounded(claim, text[claim.source_span.start : claim.source_span.end]):
                continue
            if claim.extraction_confidence < self._settings.min_claim_confidence:
                continue
            # 同一个 claim_id 出现两次，会让一条事实同时属于两个组，从而和自己冲突；
            # 保留先到的那一条，因为抽取顺序本身就是相关性顺序。
            accepted.setdefault(claim.claim_id, claim)
        return tuple(accepted.values())
