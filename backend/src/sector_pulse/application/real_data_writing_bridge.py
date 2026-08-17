from uuid import UUID

from sector_pulse.application.attribution_gate import (
    build_attribution_context,
    evaluate_attribution_gate,
)
from sector_pulse.application.phase1b_pipeline import Phase1BRequest
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.real_data_run import RealDataRunStatus
from sector_pulse.domain.time import AnalysisMode, AnalysisRun
from sector_pulse.storage.evidence_repository import SQLiteEvidenceRepository
from sector_pulse.storage.market_snapshot_repository import SQLiteMarketSnapshotRepository
from sector_pulse.storage.news_repository import SQLiteNewsRepository
from sector_pulse.storage.news_retrieval_repository import SQLiteNewsRetrievalRepository
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite import SQLiteDatabase


class RealDataRunNotReady(ValueError):
    pass


class RealDataBridgeIncomplete(ValueError):
    pass


def build_phase1b_request(database: SQLiteDatabase, run_id: UUID) -> Phase1BRequest:
    runs = SQLiteRealDataRunRepository(database)
    real_run = runs.get_run(run_id)
    if real_run is None:
        raise RealDataRunNotReady("REAL_DATA_RUN_NOT_FOUND")
    if real_run.status is not RealDataRunStatus.READY_FOR_ATTRIBUTION:
        raise RealDataRunNotReady("REAL_DATA_RUN_NOT_READY")
    if real_run.cutoff_at is None:
        raise RealDataBridgeIncomplete("REAL_DATA_BRIDGE_INCOMPLETE")

    analysis_run = AnalysisRun(
        run_id=run_id,
        mode=AnalysisMode.LIVE,
        requested_at=real_run.request.requested_at,
        run_cutoff_at=real_run.cutoff_at,
        cutoff_locked_at=real_run.cutoff_at,
    )
    snapshots = SQLiteMarketSnapshotRepository(database)
    industry = snapshots.get(run_id, SectorKind.INDUSTRY)
    concept = snapshots.get(run_id, SectorKind.CONCEPT)
    if industry is None or concept is None:
        raise RealDataBridgeIncomplete("REAL_DATA_BRIDGE_INCOMPLETE")

    candidates = runs.get_candidates(run_id)
    packs = SQLiteEvidenceRepository(database).list_for_run(run_id)
    if len(candidates) < 3 or len(packs) < len(candidates):
        raise RealDataBridgeIncomplete("REAL_DATA_BRIDGE_INCOMPLETE")
    pack_by_sector = {pack.sector_id: pack for pack in packs}
    event_ids = tuple(dict.fromkeys(event_id for pack in packs for event_id in pack.event_ids))
    news = SQLiteNewsRepository(database)
    events = news.get_events(event_ids)
    documents = news.get_documents(
        tuple(dict.fromkeys(document_id for event in events for document_id in event.document_ids))
    )
    links = SQLiteNewsRetrievalRepository(database).list_links(run_id)
    links_by_sector: dict[str, list] = {}
    for link in links:
        links_by_sector.setdefault(link.sector_id, []).append(link)

    snapshots_by_kind = {industry.kind: industry, concept.kind: concept}
    contexts = []
    gates = {}
    for candidate in candidates:
        pack = pack_by_sector.get(candidate.sector_id)
        universe = snapshots_by_kind.get(candidate.sector_kind)
        if pack is None or universe is None:
            raise RealDataBridgeIncomplete("REAL_DATA_BRIDGE_INCOMPLETE")
        sector = next(
            (item for item in universe.sectors if item.provider_sector_id == candidate.sector_id),
            None,
        )
        if sector is None:
            raise RealDataBridgeIncomplete("REAL_DATA_BRIDGE_INCOMPLETE")
        sector_events = tuple(
            event for event in events if event.event_id in pack.event_ids
        )
        context = build_attribution_context(
            analysis_run, pack, sector, sector_events, documents,
            links_by_sector.get(candidate.sector_id, ()), None,
        )
        gate = evaluate_attribution_gate(context, documents, None, False)
        contexts.append(context)
        gates[candidate.sector_id] = gate
    return Phase1BRequest(
        run_id=run_id,
        requested_at=real_run.request.requested_at,
        contexts=tuple(contexts),
        gates=gates,
    )
