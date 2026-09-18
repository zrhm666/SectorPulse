"""冲突裁决：谁和谁矛盾，以及矛盾之后谁活下来（规格 13、14）。

NLI 只回答一个问题——这两句话是不是互相矛盾。谁活下来由这一层决定，而且顺序本身就是
答案的一部分：状态先于版本，版本先于适用时间，来源权重与证据质量再次之，相关性排在最后。
这个顺序写死在 `_decide` 的语句次序里，而不是做成一张可排序的配置表：可排序就等于允许把
"权重优先于状态"部署出去，而规格 14 说这条顺序是固定的。可配置的只有 NLI 的置信度门槛。

两条边界在这里划下，也只在里划：

**检查失败不等于没有冲突。** 一次超时或 5xx 得到的是 `CHECK_FAILED`，与 `NOT_CONFLICT`
是两个不同的结论。把前者读成后者，会让一次真实矛盾在审计里干净地消失，而且看不出它曾经
存在过——一次没做成的检查，最诚实的样子就是"没做成"。

**排序分不是证据。** 相关性只允许在同一份来源内部区分两段话，不允许在相互独立的来源
之间选出赢家。否则两份资料的胜负就取决于一个重排模型把哪一段排得靠前，而那个分数衡量的是
"像不像问题的答案"，不是"是不是真的"。

判不了就说判不了：规则分不出高下时结果是 `UNRESOLVED`，两条事实以及它们各自的出处都保留，
交给人。这一层因此永远返回双方，永远不猜。
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator, Mapping, Sequence
from decimal import Decimal

from pydantic import Field
from sector_pulse.application.research_library.claims import ComparableClaimGroup
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.research_library.models import (
    DocumentVersionStatus,
    ExtractionMethod,
    Record,
)
from sector_pulse.domain.research_library.retrieval import (
    ConflictDecision,
    ConflictRule,
    ConflictStatus,
    EvidenceGrade,
    ExtractedClaim,
    NliRelation,
    TimeRange,
)
from sector_pulse.ports.research_models import NliProvider, NliVerdict, ProviderError

__all__ = [
    "ClaimSource",
    "ConflictContext",
    "ConflictMetadata",
    "ConflictPolicy",
    "ConflictService",
    "UnknownClaimSource",
    "evidence_grade",
    "resolve_conflict",
    "weakest_grade",
]


class UnknownClaimSource(LookupError):
    """一条事实引用的切片不在这次检索的来源表里。

    与 `ClaimExtractionService` 对"引用了没送过去的切片"的处理刻意相反——那边是丢弃，
    因为那是模型的输出，可能整条都是编的；这里是抛错，因为到这一步事实已经核对过出处，
    查不到只能是调用方漏传了来源表。静默丢下这一对，一次真实矛盾会从审计里消失，而两条
    事实看上去都被处理过了。
    """


#: 规格 14 第 5 条的证据质量档位。OCR 与解析器都属于"从版式里读出来的结构"，
#: 差别在于读得准不准，而在"是不是原文"这个问题上它们是一档。
_GRADE_BY_ORIGIN: Mapping[ExtractionMethod, EvidenceGrade] = {
    ExtractionMethod.NATIVE: EvidenceGrade.PRIMARY_SOURCE,
    ExtractionMethod.OCR: EvidenceGrade.PARSED_STRUCTURE,
    ExtractionMethod.PARSER_DERIVED: EvidenceGrade.PARSED_STRUCTURE,
    ExtractionMethod.VISION_DERIVED: EvidenceGrade.DERIVED_UNVERIFIED,
}

_GRADE_RANK: Mapping[EvidenceGrade, int] = {
    EvidenceGrade.PRIMARY_SOURCE: 2,
    EvidenceGrade.PARSED_STRUCTURE: 1,
    EvidenceGrade.DERIVED_UNVERIFIED: 0,
}


def evidence_grade(
    *, content_origin: ExtractionMethod, requires_verification: bool
) -> EvidenceGrade:
    """规格 14 第 5 条的证据质量。

    待核验把它压到最低一档，**不论它出身如何**：规格 7.9 说低置信度的视觉结论只能算线索，
    而这份判定在进入这里之前已经做完了——如果它还可以因为"文本是原生的"就恢复成证据，
    那么待核验这个标记就只是一个注解，而不是一次降级。
    """
    if requires_verification:
        return EvidenceGrade.DERIVED_UNVERIFIED
    return _GRADE_BY_ORIGIN[content_origin]


def weakest_grade(grades: Sequence[EvidenceGrade]) -> EvidenceGrade:
    """一条事实同时引用几份来源时，它挣到的是其中最低的那一档。

    取最高的那一档，等于让最体面的那一份来源替整条事实背书：一条同时踩着原生文本和一页
    OCR 的结论会被读成"来自原文"。

    档位次序与 `_GRADE_RANK` 共用一处，避免"更弱"在两处各有一个定义。
    """
    if not grades:
        raise ValueError("a claim that cites no source has no evidence grade")
    return min(grades, key=lambda grade: _GRADE_RANK[grade])


class ClaimSource(Record):
    """一条事实的出处：它从哪儿来，以及那个"哪儿"有多可信。

    事实说的是**被主张了什么**，这里说的是**谁主张的、这份主张有多硬**。两者分开是因为
    裁决只在后者上做判断：一条从被删除版本里读出来的原生文本，证据质量很高，却仍然不该
    胜过一条在架版本的 OCR 结果——状态在第 1 位，证据质量在第 5 位。

    `relevance` 不设上下界：它是重排模型给出的分数，不同实现可以是相似度、logit 或排名
    倒数，这里只比较大小，不解释它的量纲。
    """

    document_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    version_number: int = Field(ge=1)
    status: DocumentVersionStatus
    source_weight: Decimal = Field(ge=0, le=1)
    content_origin: ExtractionMethod
    requires_verification: bool = False
    relevance: float | None = None

    @property
    def grade(self) -> EvidenceGrade:
        return evidence_grade(
            content_origin=self.content_origin,
            requires_verification=self.requires_verification,
        )

    def is_independent_of(self, other: ClaimSource) -> bool:
        """两份来源是否互相独立。

        以**文档**而不是版本为单位：同一份报告的新旧两版不是两个独立来源，它们是同一方
        在不同时间的说法，相关性在这两者之间的发言权由规格 14 第 2、6 条限定。
        """
        return self.document_id != other.document_id


class ConflictPolicy(Record):
    """规格 14 里可配置的那一部分——只有门槛。

    放在这里而不是散在服务里，是为了让"阈值是多少"成为一条能写进审计的事实：同一批事实
    在两个阈值下会得到不同的结论，不记下用了哪一个，事后无法解释某次裁决。
    """

    min_nli_confidence: float = Field(gt=0, le=1)


class ConflictMetadata(Record):
    """裁决一对事实所需的全部外部信息。

    `verdict is None` 表示这次检查**没有完成**（Provider 失败、超时或未配置），它不是
    "模型说没关系"。把这两种情况表达成同一个值，就是把一次没做成的检查伪装成一个结论。
    """

    left: ClaimSource
    right: ClaimSource
    query_time_range: TimeRange | None = None
    verdict: NliVerdict | None = None


class ConflictContext(Record):
    """一次冲突判断的来源表与问题时间。

    `sources` 的键是 `chunk_id`，与 `ExtractedClaim.source_chunk_id` 对上。键就是这条来源
    的身份，`ClaimSource` 里因此不再重复存一份 chunk_id——两处各存一份，迟早会出现两份
    身份不一致而没有人知道该信哪一个的情况。
    """

    sources: Mapping[str, ClaimSource] = Field(default_factory=dict)
    query_time_range: TimeRange | None = None


def _windows_are_disjoint(left: ExtractedClaim, right: ExtractedClaim) -> bool:
    """两条事实的适用时间是否完全错开。

    一侧没有时间时不算错开：没有标注时间不等于"说了另一段时间"，把它判成不相交，会让
    "不写时间"变成一种躲避比对的写法。聚合阶段（规格 13）已经用同一条判据把不相交的
    事实分到不同的组里，这里是它在下游的第二道闸。
    """
    if left.valid_time is None or right.valid_time is None:
        return False
    return (
        left.valid_time.end < right.valid_time.start or right.valid_time.end < left.valid_time.start
    )


def _matches_window(claim: ExtractedClaim, window: TimeRange) -> bool:
    """这条事实是否落在问题问的那一段时间里。

    没有适用时间的一条事实**不**匹配：规格 14 第 3 条要的是"优先匹配问题指定时间"，而一个
    没有说自己管哪一段时间的主张，无法被判定为就落在那一时间里。
    """
    if claim.valid_time is None:
        return False
    return claim.valid_time.start <= window.end and window.start <= claim.valid_time.end


def _decide(
    left: ExtractedClaim,
    right: ExtractedClaim,
    metadata: ConflictMetadata,
) -> tuple[ExtractedClaim | None, ConflictRule | None, str]:
    """规格 14 的优先级，按顺序试到第一条能分出高下的规则为止。

    只有在 NLI 已经判定两条事实矛盾之后才会走到这里：规则的职责是**选出活下来的那一条**，
    不是判断它们是否矛盾。反过来做——先按权重选赢家再问模型——会让一份高权重资料只要被
    检索到就自动胜出，而它可能压根没说同一件事。
    """
    sides = metadata.left, metadata.right
    left_source, right_source = sides

    # 1 状态：在架的资料优先于被取代、归档或删除的。
    if left_source.status is DocumentVersionStatus.ACTIVE and (
        right_source.status is not DocumentVersionStatus.ACTIVE
    ):
        return (
            left,
            ConflictRule.STATUS,
            f"左侧版本在架，右侧为 {right_source.status.value}",
        )
    if right_source.status is DocumentVersionStatus.ACTIVE and (
        left_source.status is not DocumentVersionStatus.ACTIVE
    ):
        return (
            right,
            ConflictRule.STATUS,
            f"右侧版本在架，左侧为 {left_source.status.value}",
        )

    # 2 显式版本：**同一份文档**的新版本优先。两份不同文档的版本号之间没有大小关系。
    if (
        left_source.document_id == right_source.document_id
        and left_source.version_number != right_source.version_number
    ):
        newer_is_left = left_source.version_number > right_source.version_number
        winner = left if newer_is_left else right
        high = max(left_source.version_number, right_source.version_number)
        low = min(left_source.version_number, right_source.version_number)
        return winner, ConflictRule.EXPLICIT_VERSION, f"同一份文档的 v{high} 优先于 v{low}"

    # 3 适用时间：优先匹配问题指定的那一段。
    window = metadata.query_time_range
    if window is not None:
        left_matches = _matches_window(left, window)
        right_matches = _matches_window(right, window)
        if left_matches and not right_matches:
            return left, ConflictRule.EFFECTIVE_TIME, "左侧落在问题指定的时间范围内"
        if right_matches and not left_matches:
            return right, ConflictRule.EFFECTIVE_TIME, "右侧落在问题指定的时间范围内"

    # 4 来源权重：由资料治理配置，不由 Agent 临时修改。
    if left_source.source_weight != right_source.source_weight:
        heavier_is_left = left_source.source_weight > right_source.source_weight
        winner = left if heavier_is_left else right
        return (
            winner,
            ConflictRule.SOURCE_WEIGHT,
            f"来源权重 {left_source.source_weight} 对 {right_source.source_weight}",
        )

    # 5 证据质量：原生文本优先于结构派生，结构派生优先于未经核验的派生内容。
    if left_source.grade is not right_source.grade:
        better_is_left = _GRADE_RANK[left_source.grade] > _GRADE_RANK[right_source.grade]
        winner = left if better_is_left else right
        return (
            winner,
            ConflictRule.EVIDENCE_QUALITY,
            f"证据质量 {left_source.grade.value} 对 {right_source.grade.value}",
        )

    # 6 相关性：**只在同一份来源内部**使用。跨来源使用时，这个分数衡量的是"像不像问题的
    # 答案"，而胜负要问的是"是不是真的"——两件事。规格 14 第 6 条因此禁止它单独消灭
    # 独立有效来源之间的冲突。
    if not left_source.is_independent_of(right_source) and (
        left_source.relevance != right_source.relevance
    ):
        if left_source.relevance is None or right_source.relevance is None:
            # 一侧没有排序分。"缺一个分数"不是"分数低"，据此选赢家等于用缺失的度量下结论。
            return None, None, "同一来源内部两侧的相关性缺失其一，无法比较"
        more_relevant_is_left = left_source.relevance > right_source.relevance
        winner = left if more_relevant_is_left else right
        return (
            winner,
            ConflictRule.RELEVANCE,
            f"同一份来源内部的相关性 {left_source.relevance} 对 {right_source.relevance}",
        )

    return (
        None,
        None,
        "两条来源互相独立、都有效，且没有规则能分出高下，保留双方待人工判断",
    )


def _decision(
    status: ConflictStatus,
    claim_ids: tuple[str, ...],
    metadata: ConflictMetadata,
    *,
    reason: str,
    rule: ConflictRule | None = None,
    relation: NliRelation | None = None,
    selected: str | None = None,
) -> ConflictDecision:
    """把 Provider 的署名一并带上。

    判定来自哪个 provider、哪个模型版本是审计的一部分：换一个 NLI 模型之后同一个问题可能
    得到不同的结论，不记下来就无法解释"上一次为什么判成矛盾"。
    """
    verdict = metadata.verdict
    return ConflictDecision(
        status=status,
        claim_ids=claim_ids,
        rule=rule,
        selected_claim_id=selected,
        nli_relation=relation,
        nli_confidence=None if verdict is None else verdict.confidence,
        nli_provider=None if verdict is None else verdict.provider,
        nli_model_version=None if verdict is None else verdict.model_version,
        rationale=reason,
    )


def resolve_conflict(
    pair: tuple[ExtractedClaim, ExtractedClaim],
    metadata: ConflictMetadata,
    policy: ConflictPolicy,
) -> ConflictDecision:
    """裁决一对可比事实。纯函数：判定由调用方取得，这里不碰任何 Provider。

    判定是参数而不是内部调用，这一层才可能被穷举测试——`fixtures/research_library/
    nli_cases.yaml` 的那张表把模型给出的每一种结论都当成输入喂进来，于是规格 14 的优先级
    不需要任何真实模型就能被逐条证伪。
    """
    left, right = pair
    claim_ids = (left.claim_id, right.claim_id)

    # 适用时间完全错开是**确定性**结论，不需要模型，也不该被一次失败的检查改写：两条说的
    # 不是同一段时间，无论 NLI 能不能给出答案，它们都不是互相矛盾的两条。
    if _windows_are_disjoint(left, right):
        return _decision(
            ConflictStatus.NOT_CONFLICT,
            claim_ids,
            metadata,
            rule=ConflictRule.EFFECTIVE_TIME,
            relation=None if metadata.verdict is None else metadata.verdict.relation,
            reason="两条事实的适用时间不相交，说的不是同一段时间的事",
        )

    verdict = metadata.verdict
    if verdict is None:
        return _decision(
            ConflictStatus.CHECK_FAILED,
            claim_ids,
            metadata,
            reason="NLI 判定未完成，无法判断这两条事实是否互相矛盾",
        )

    # 规格 13：低于门槛的结果**就是** UNCERTAIN，不得触发自动覆盖。降级的是结论，不是量到
    # 的那个数——原始置信度照旧写进审计，否则事后无从知道"差多少"。
    below_floor = verdict.confidence < policy.min_nli_confidence
    relation = NliRelation.UNCERTAIN if below_floor else verdict.relation

    if relation is NliRelation.ENTAILMENT:
        return _decision(
            ConflictStatus.NOT_CONFLICT,
            claim_ids,
            metadata,
            relation=relation,
            reason="NLI 判定两条事实互相蕴含，属于互相支持",
        )
    if relation is NliRelation.NEUTRAL:
        return _decision(
            ConflictStatus.NOT_CONFLICT,
            claim_ids,
            metadata,
            relation=relation,
            reason="NLI 判定两条事实互不相干，不构成矛盾",
        )
    if relation is NliRelation.UNCERTAIN:
        if below_floor:
            reason = (
                f"模型给出 {verdict.relation.value}（{verdict.confidence:.2f}），"
                f"低于阈值 {policy.min_nli_confidence:.2f}，按规格 13 记为 UNCERTAIN，"
                "不自动覆盖任何一条"
            )
        else:
            reason = "模型判定无法确定两条事实的关系，不能据此覆盖任何一条"
        return _decision(
            ConflictStatus.UNRESOLVED,
            claim_ids,
            metadata,
            relation=relation,
            reason=reason,
        )

    winner, rule, reason = _decide(left, right, metadata)
    if winner is None:
        return _decision(
            ConflictStatus.UNRESOLVED,
            claim_ids,
            metadata,
            relation=relation,
            reason=reason,
        )
    return _decision(
        ConflictStatus.RESOLVED,
        claim_ids,
        metadata,
        rule=rule,
        relation=relation,
        selected=winner.claim_id,
        reason=reason,
    )


def _nli_text(claim: ExtractedClaim) -> str:
    """规格 13：送进 NLI 的原文要带上必要的时间限定。

    不带时间的话，"第二季度同比增长85%"和"第一季度同比下滑30%"在模型眼里就是互相否定的
    两句话，而它们其实说的是不同时间段的事。时间限定补上之后，模型才有机会说"不相干"。
    """
    window = claim.valid_time
    if window is None:
        return claim.statement
    return f"{claim.statement}（适用时间：{window.start.isoformat()} 至 {window.end.isoformat()}）"


def _needs_nli(
    left: ExtractedClaim,
    right: ExtractedClaim,
    left_source: ClaimSource,
    right_source: ClaimSource,
) -> bool:
    """规格 13：这一对要不要送进 NLI。

    同一版本内的两段话立场又相同时不送——它们是同一份来源的同一段主张，代价是同一版本
    自相矛盾的话不会被发现（记为已知边界）。这不是省钱的优化：把同一段话的两半来回比对，
    换来的是一堆自己和自己矛盾的结论。
    """
    if left_source.document_version_id != right_source.document_version_id:
        return True
    return left.stance is not right.stance


def _pairs(
    claims: Sequence[ExtractedClaim],
) -> Iterator[tuple[ExtractedClaim, ExtractedClaim]]:
    """一组事实的全部两两组合，保持输入次序。"""
    return itertools.combinations(claims, 2)


def _source_of(context: ConflictContext, claim: ExtractedClaim) -> ClaimSource:
    source = context.sources.get(claim.source_chunk_id)
    if source is None:
        raise UnknownClaimSource(
            f"claim {claim.claim_id!r} cites chunk {claim.source_chunk_id!r}, "
            "which has no source metadata in this context"
        )
    return source


class ConflictService:
    """规格 13 的冲突判断服务。"""

    def __init__(self, *, provider: NliProvider, settings: RagSettings) -> None:
        self._provider = provider
        self._policy = ConflictPolicy(min_nli_confidence=settings.min_nli_confidence)

    def check(
        self, groups: Sequence[ComparableClaimGroup], context: ConflictContext
    ) -> tuple[ConflictDecision, ...]:
        """对每一组事实的两两组合给出裁决。

        一组三条事实是三对，而不是"拿第一条去比其余两条"：漏掉一对就是漏掉一次可能的
        矛盾，而哪一条是被抽出来做基准的那条，取决于模型先说了哪一句。

        一次 Provider 失败只影响它自己那一对：这对记为 `CHECK_FAILED`，其余各对照常裁决。
        整批放弃会让一次超时抹掉其余所有结论，而它们本来是可以给出的。
        """
        decisions: list[ConflictDecision] = []
        for group in groups:
            for left, right in _pairs(group.claims):
                left_source = _source_of(context, left)
                right_source = _source_of(context, right)
                if not _needs_nli(left, right, left_source, right_source):
                    continue
                decisions.append(
                    resolve_conflict(
                        (left, right),
                        ConflictMetadata(
                            left=left_source,
                            right=right_source,
                            query_time_range=context.query_time_range,
                            verdict=self._classify(left, right),
                        ),
                        self._policy,
                    )
                )
        return tuple(decisions)

    def _classify(self, left: ExtractedClaim, right: ExtractedClaim) -> NliVerdict | None:
        """问一次 NLI；问不成返回 `None`，那意味着"没做成"而不是"没关系"。"""
        try:
            return self._provider.classify(premise=_nli_text(left), hypothesis=_nli_text(right))
        except ProviderError:
            return None
