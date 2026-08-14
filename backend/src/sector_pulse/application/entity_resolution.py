from collections.abc import Mapping, Sequence
from uuid import UUID

from sector_pulse.domain.market import SectorSnapshot
from sector_pulse.domain.news import NewsDocument, NewsEvent
from sector_pulse.domain.news_retrieval import (
    MappingConfidence,
    SectorEntityConfig,
    SectorEventLink,
)


def resolve_sector_links(
    run_id: UUID,
    events: Sequence[NewsEvent],
    sectors: Sequence[SectorSnapshot],
    memberships: Mapping[str, Sequence[str]],
    entity_config: SectorEntityConfig,
    documents: Mapping[str, NewsDocument] | None = None,
) -> tuple[SectorEventLink, ...]:
    """用可审计的确定性规则把新闻事件映射到板块，不在此阶段推断因果。"""
    sector_by_id = {sector.provider_sector_id: sector for sector in sectors}
    documents = documents or {}
    links: dict[tuple[str, str], SectorEventLink] = {}
    confidence_rank = {
        MappingConfidence.LOW: 1,
        MappingConfidence.MEDIUM: 2,
        MappingConfidence.HIGH: 3,
    }
    for event in events:
        text_parts = [event.canonical_title]
        text_parts.extend(
            document.summary or document.title
            for document_id in event.document_ids
            if (document := documents.get(document_id)) is not None
        )
        text = " ".join(text_parts).casefold()
        matched: list[tuple[str, MappingConfidence, str, tuple[str, ...]]] = []
        for code, sector_ids in memberships.items():
            if code in text:
                for sector_id in sector_ids:
                    if sector_id in sector_by_id:
                        matched.append(
                            (sector_id, MappingConfidence.HIGH, f"stock_code:{code}", (code,))
                        )
        for sector_id, sector in sector_by_id.items():
            aliases = entity_config.aliases.get(sector_id, ())
            terms = entity_config.industry_terms.get(sector_id, ())
            if sector.name.casefold() in text:
                matched.append(
                    (
                        sector_id,
                        MappingConfidence.MEDIUM,
                        f"sector_name:{sector.name}",
                        (sector.name,),
                    )
                )
            for alias in aliases:
                if alias.casefold() in text:
                    matched.append(
                        (sector_id, MappingConfidence.MEDIUM, f"alias:{alias}", (alias,))
                    )
            non_ambiguous_hits = [term for term in terms if term.casefold() in text]
            if non_ambiguous_hits:
                matched.append(
                    (sector_id, MappingConfidence.LOW, "industry_term", tuple(non_ambiguous_hits))
                )
            has_ambiguous_hit = any(
                term.casefold() in text for term in entity_config.ambiguous_terms
            )
            if has_ambiguous_hit and non_ambiguous_hits:
                matched.append(
                    (
                        sector_id,
                        MappingConfidence.LOW,
                        "ambiguous_with_context",
                        tuple(non_ambiguous_hits),
                    )
                )
        for sector_id, confidence, reason, entities in matched:
            key = (event.event_id, sector_id)
            previous = links.get(key)
            is_lower_or_equal = (
                previous is not None
                and confidence_rank[previous.mapping_confidence] >= confidence_rank[confidence]
            )
            if is_lower_or_equal:
                continue
            links[key] = SectorEventLink(
                run_id=run_id,
                event_id=event.event_id,
                sector_id=sector_id,
                sector_kind=sector_by_id[sector_id].kind,
                relation_type="NEWS_MENTION",
                matched_entities=entities,
                mapping_confidence=confidence,
                mapping_reason=reason,
                rule_version=entity_config.version,
            )
    return tuple(sorted(links.values(), key=lambda item: (item.event_id, item.sector_id)))
