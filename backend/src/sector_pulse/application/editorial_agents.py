from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import uuid4

from sector_pulse.domain.article import ArticleDraft, ArticleOutline, ArticleSection
from sector_pulse.domain.attribution import SectorAnalysisCard
from sector_pulse.domain.llm import LLMRequest, LLMStatus
from sector_pulse.domain.review import ReviewReport
from sector_pulse.ports.llm import LLMPort


async def run_editorial_agent(
    cards: Sequence[SectorAnalysisCard], llm: LLMPort, prompt: Any
) -> ArticleOutline:
    valid = tuple(cards[:6])
    if len(valid) < 3:
        raise ValueError("at least 3 analysis cards are required")
    request = LLMRequest[
        ArticleOutline
    ](
        agent_name="editorial",
        model="fixture-high",
        prompt_id=getattr(prompt, "prompt_id", "editorial"),
        prompt_version=getattr(prompt, "version", "1"),
        system_prompt=getattr(prompt, "system", ""),
        user_payload={"cards": [card.model_dump(mode="json") for card in valid]},
        response_model=ArticleOutline,
        fixture_key="editorial-outline",
    )
    result = await llm.generate_structured(request)
    if result.status is LLMStatus.SUCCESS and result.data is not None:
        return cast(ArticleOutline, result.data)
    selected = tuple(card.sector_id for card in valid[:6])
    return ArticleOutline(
        outline_id=uuid4(),
        run_id=valid[0].run_id,
        sector_ids=selected,
        order_reasons={sector_id: "确定性综合热度排序" for sector_id in selected},
        title_directions=("今日板块异动与消息观察",),
        thesis="围绕板块表现、新闻线索和证据边界进行审慎观察。",
        section_character_budgets={sector_id: 220 for sector_id in selected},
        excluded_sector_reasons={},
    )


async def run_writing_agent(
    outline: ArticleOutline,
    cards: Mapping[str, SectorAnalysisCard],
    llm: LLMPort,
    prompt: Any,
) -> ArticleDraft | None:
    request = LLMRequest[
        ArticleDraft
    ](
        agent_name="writing",
        model="fixture-high",
        prompt_id=getattr(prompt, "prompt_id", "writing"),
        prompt_version=getattr(prompt, "version", "1"),
        system_prompt=getattr(prompt, "system", ""),
        user_payload={"outline": outline.model_dump(mode="json"), "cards": {
            key: value.model_dump(mode="json") for key, value in cards.items()
        }},
        response_model=ArticleDraft,
        fixture_key="article-draft",
    )
    result = await llm.generate_structured(request)
    return result.data if result.status is LLMStatus.SUCCESS else None


async def run_review_agent(
    draft: ArticleDraft, cards: Mapping[str, SectorAnalysisCard], llm: LLMPort, prompt: Any
) -> ReviewReport | None:
    request = LLMRequest[
        ReviewReport
    ](
        agent_name="review",
        model="fixture-review",
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
