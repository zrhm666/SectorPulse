from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from sector_pulse.application.invocations import (
    InvocationSink,
    build_invocation,
    noop_invocation_sink,
)
from sector_pulse.domain.article import (
    ArticleDraft,
    ArticleOutline,
    ArticleSection,
    ArticleSource,
    DraftStatus,
)
from sector_pulse.domain.attribution import SectorAnalysisCard
from sector_pulse.domain.llm import LLMRequest, LLMStatus
from sector_pulse.domain.review import ReviewReport
from sector_pulse.ports.llm import LLMPort


class ArticleDraftCandidate(BaseModel):
    """LLM 写作候选；终态规则由审校完成后统一执行。"""

    model_config = ConfigDict(frozen=True)
    draft_id: UUID
    run_id: UUID
    version: int = Field(ge=1)
    status: DraftStatus
    titles: tuple[str, ...]
    introduction: str
    sections: tuple[ArticleSection, ...]
    conclusion: str
    risk_notice: str
    sources: tuple[ArticleSource, ...]
    character_count: int = Field(ge=0)


async def run_editorial_agent(
    cards: Sequence[SectorAnalysisCard],
    llm: LLMPort,
    prompt: Any,
    invocation_sink: InvocationSink = noop_invocation_sink,
    model: str = "fixture",
) -> tuple[ArticleOutline, bool]:
    valid = tuple(cards[:6])
    if len(valid) < 3:
        raise ValueError("at least 3 analysis cards are required")
    request = LLMRequest[
        ArticleOutline
    ](
        agent_name="editorial",
        model=model,
        prompt_id=getattr(prompt, "prompt_id", "editorial"),
        prompt_version=getattr(prompt, "version", "1"),
        system_prompt=getattr(prompt, "system", ""),
        user_payload={"cards": [card.model_dump(mode="json") for card in valid]},
        response_model=ArticleOutline,
        fixture_key="editorial-outline",
    )
    result = await llm.generate_structured(request)
    invocation_sink(
        build_invocation(
            valid[0].run_id,
            "editorial",
            request,
            result,
            getattr(llm, "provider_id", "unknown"),
        )
    )
    if result.status is LLMStatus.SUCCESS and result.data is not None:
        return cast(ArticleOutline, result.data), False
    selected = tuple(card.sector_id for card in valid[:6])
    return (
        ArticleOutline(
            outline_id=uuid4(),
            run_id=valid[0].run_id,
            sector_ids=selected,
            order_reasons={sector_id: "确定性综合热度排序" for sector_id in selected},
            title_directions=("今日板块异动与消息观察",),
            thesis="围绕板块表现、新闻线索和证据边界进行审慎观察。",
            section_character_budgets={sector_id: 220 for sector_id in selected},
            excluded_sector_reasons={},
        ),
        True,
    )


async def run_writing_agent(
    outline: ArticleOutline,
    cards: Mapping[str, SectorAnalysisCard],
    llm: LLMPort,
    prompt: Any,
    invocation_sink: InvocationSink = noop_invocation_sink,
    model: str = "fixture",
    verified_sources: Sequence[ArticleSource] | None = None,
) -> ArticleDraft | None:
    request = LLMRequest[ArticleDraftCandidate](
        agent_name="writing",
        model=model,
        prompt_id=getattr(prompt, "prompt_id", "writing"),
        prompt_version=getattr(prompt, "version", "1"),
        system_prompt=getattr(prompt, "system", ""),
        user_payload={
            "outline": outline.model_dump(mode="json"),
            "cards": {
                key: value.model_dump(mode="json") for key, value in cards.items()
            },
            "verified_sources": [
                source.model_dump(mode="json") for source in verified_sources or ()
            ],
        },
        response_model=ArticleDraftCandidate,
        fixture_key="article-draft",
    )
    result = await llm.generate_structured(request)
    invocation_sink(
        build_invocation(
            outline.run_id,
            "writing",
            request,
            result,
            getattr(llm, "provider_id", "unknown"),
        )
    )
    if result.status is not LLMStatus.SUCCESS or result.data is None:
        return None
    candidate = cast(ArticleDraftCandidate, result.data)
    payload = candidate.model_dump()
    # LLM 只能生成候选稿，不能自行越过审校进入 ready 终态。
    payload["status"] = DraftStatus.UNREVIEWED
    if verified_sources is not None:
        # 来源由持久化证据确定，禁止模型遗漏或生成未经验证的来源。
        payload["sources"] = tuple(verified_sources)
    return ArticleDraft.model_validate(payload)


async def run_review_agent(
    draft: ArticleDraft,
    cards: Mapping[str, SectorAnalysisCard],
    llm: LLMPort,
    prompt: Any,
    invocation_sink: InvocationSink = noop_invocation_sink,
    model: str = "fixture",
) -> ReviewReport | None:
    request = LLMRequest[
        ReviewReport
    ](
        agent_name="review",
        model=model,
        prompt_id=getattr(prompt, "prompt_id", "review"),
        prompt_version=getattr(prompt, "version", "1"),
        system_prompt=getattr(prompt, "system", ""),
        user_payload={"draft": draft.model_dump(mode="json"), "cards": {
            key: value.model_dump(mode="json") for key, value in cards.items()
        }},
        response_model=ReviewReport,
        fixture_key=f"review:{draft.version}",
    )
    result = await llm.generate_structured(request)
    invocation_sink(
        build_invocation(
            draft.run_id,
            "review",
            request,
            result,
            getattr(llm, "provider_id", "unknown"),
        )
    )
    return result.data if result.status is LLMStatus.SUCCESS else None


def revise_sections(
    draft: ArticleDraft, replacements: Mapping[str, ArticleSection]
) -> ArticleDraft:
    """只替换审核指定的区块，保留其他区块和草稿历史。"""
    sections = tuple(replacements.get(section.section_id, section) for section in draft.sections)
    character_count = len(draft.introduction) + len(draft.conclusion) + sum(
        len(section.body) for section in sections
    )
    return draft.model_copy(
        update={
            "version": draft.version + 1,
            "sections": sections,
            "character_count": character_count,
        }
    )
