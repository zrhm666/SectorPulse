from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from sector_pulse.domain.market.market import SectorSnapshot
from sector_pulse.domain.news.evidence import EvidenceLevel, EvidencePack
from sector_pulse.domain.news.news import NewsDocument, NewsEvent, NewsUse, SourceGrade
from sector_pulse.domain.news.news_retrieval import SectorEventLink
from sector_pulse.domain.runs.time import AnalysisRun
from sector_pulse.domain.writing.attribution import (
    LEVEL_RANK,
    AttributionContext,
    AttributionGateResult,
)


def build_attribution_context(
    run: AnalysisRun,
    pack: EvidencePack,
    snapshot: SectorSnapshot,
    events: Sequence[NewsEvent],
    documents: Mapping[str, NewsDocument],
    links: Sequence[SectorEventLink],
    market_move_started_at: datetime | None,
) -> AttributionContext:
    """从已持久化 EvidencePack 构建模型只读输入，并保留每个时间边界的分类。"""
    if run.run_cutoff_at is None:
        raise ValueError("attribution context requires locked cutoff")
    if (
        pack.run_id != run.run_id
        or snapshot.provider_sector_id != pack.sector_id
        or snapshot.kind != pack.sector_kind
    ):
        raise ValueError("snapshot does not match evidence pack identity")
    event_by_id = {event.event_id: event for event in events}
    event_ids = tuple(pack.event_ids)
    eligible: list[str] = []
    background: list[str] = []
    excluded: list[str] = []
    source_grades: dict[str, SourceGrade] = {}
    for event_id in event_ids:
        event = event_by_id.get(event_id)
        if event is None:
            continue
        event_documents = [
            documents[doc_id] for doc_id in event.document_ids if doc_id in documents
        ]
        uses = [document.use_at(run.run_cutoff_at) for document in event_documents]
        source_grades.update(
            {document.document_id: document.source_grade for document in event_documents}
        )
        if any(use is NewsUse.EXCLUDED for use in uses):
            excluded.append(event_id)
        elif any(use is NewsUse.EVIDENCE for use in uses):
            eligible.append(event_id)
        else:
            background.append(event_id)
    return AttributionContext(
        run_id=run.run_id,
        sector_id=pack.sector_id,
        sector_kind=pack.sector_kind,
        sector_name=snapshot.name.strip() or None,
        cutoff_at=run.run_cutoff_at,
        market_facts={
            "pct_change": snapshot.pct_change,
            "breadth_ratio": snapshot.breadth_ratio,
            "turnover_rate": snapshot.turnover_rate,
            "leader_name": snapshot.leader_name,
            "leader_pct_change": snapshot.leader_pct_change,
            "market_move_started_at": market_move_started_at.isoformat()
            if market_move_started_at
            else None,
        },
        event_ids=event_ids,
        eligible_event_ids=tuple(eligible),
        background_event_ids=tuple(background),
        excluded_event_ids=tuple(excluded),
        source_grades=source_grades,
        counter_evidence=pack.counter_evidence,
    )


def _lower(current: EvidenceLevel, proposed: EvidenceLevel) -> EvidenceLevel:
    return proposed if LEVEL_RANK[proposed] < LEVEL_RANK[current] else current


def evaluate_attribution_gate(
    context: AttributionContext,
    documents: Mapping[str, NewsDocument],
    market_move_started_at: datetime | None,
    broad_market_alternative: bool,
) -> AttributionGateResult:
    """按固定顺序只降低归因上限，程序规则优先于模型输出。"""
    maximum = EvidenceLevel.EXPLICIT_DRIVER
    reasons: list[str] = []
    if not context.eligible_event_ids:
        maximum = EvidenceLevel.NO_RELIABLE_EXPLANATION
        reasons.append("NO_ELIGIBLE_EVENT")
    eligible_documents = [
        document
        for document in documents.values()
        if document.document_id in context.source_grades
        and document.published_at is not None
    ]
    if any(document.published_at is None for document in documents.values()):
        maximum = _lower(maximum, EvidenceLevel.MARKET_ASSOCIATION)
        reasons.append("MISSING_PUBLICATION_TIME")
    if any(
        document.source_grade is SourceGrade.DISCOVERY_ONLY and document.citation_url is None
        for document in eligible_documents
    ):
        maximum = _lower(maximum, EvidenceLevel.MARKET_ASSOCIATION)
        reasons.append("DISCOVERY_ONLY_WITHOUT_CITATION")
    if market_move_started_at is not None and any(
        document.published_at is not None and document.published_at > market_move_started_at
        for document in eligible_documents
    ):
        maximum = _lower(maximum, EvidenceLevel.MARKET_ASSOCIATION)
        reasons.append("EVENT_AFTER_MARKET_MOVE")
    breadth = context.market_facts.get("breadth_ratio")
    if isinstance(breadth, Decimal) and breadth < Decimal("0.5"):
        maximum = _lower(maximum, EvidenceLevel.POSSIBLE_CATALYST)
        reasons.append("INSUFFICIENT_SECTOR_BREADTH")
    if broad_market_alternative:
        maximum = _lower(maximum, EvidenceLevel.POSSIBLE_CATALYST)
        reasons.append("BROAD_MARKET_ALTERNATIVE")
    if maximum is EvidenceLevel.EXPLICIT_DRIVER and not any(
        document.source_grade is SourceGrade.PRIMARY for document in eligible_documents
    ):
        maximum = EvidenceLevel.POSSIBLE_CATALYST
        reasons.append("NO_PRIMARY_SOURCE")
    return AttributionGateResult(
        run_id=context.run_id,
        sector_id=context.sector_id,
        allowed_max_level=maximum,
        reasons=tuple(dict.fromkeys(reasons)),
        eligible_evidence_ids=context.eligible_event_ids,
        excluded_evidence_ids=context.excluded_event_ids,
        counter_evidence=context.counter_evidence,
    )
