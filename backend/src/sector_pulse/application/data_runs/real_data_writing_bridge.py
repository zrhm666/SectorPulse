from typing import cast
from uuid import UUID

from sector_pulse.application.writing.attribution_gate import (
    build_attribution_context,
    evaluate_attribution_gate,
)
from sector_pulse.application.writing.phase1b_pipeline import Phase1BRequest
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.news_retrieval import SectorEventLink
from sector_pulse.domain.real_data_run import RealDataCandidate, RealDataRunStatus
from sector_pulse.domain.time import AnalysisMode, AnalysisRun
from sector_pulse.storage.database_runtime import Database
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.runtime_bundle import RuntimeStorageBundle
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.evidence_repository import SQLiteEvidenceRepository
from sector_pulse.storage.sqlite.market_snapshot_repository import SQLiteMarketSnapshotRepository
from sector_pulse.storage.sqlite.news_repository import SQLiteNewsRepository
from sector_pulse.storage.sqlite.news_retrieval_repository import SQLiteNewsRetrievalRepository
from sector_pulse.storage.sqlite.real_data_run_repository import SQLiteRealDataRunRepository


class RealDataRunNotReady(ValueError):
    pass


class RealDataBridgeIncomplete(ValueError):
    pass


def select_requested_candidates(
    candidates: list[RealDataCandidate], selected_sector_ids: tuple[str, ...] | None
) -> list[RealDataCandidate]:
    if selected_sector_ids is None:
        return candidates
    if not 3 <= len(selected_sector_ids) <= 12:
        raise RealDataBridgeIncomplete("CANDIDATE_SELECTION_INVALID")
    selected = set(selected_sector_ids)
    if len(selected) != len(selected_sector_ids):
        raise RealDataBridgeIncomplete("CANDIDATE_SELECTION_INVALID")
    available = {candidate.sector_id for candidate in candidates}
    if not selected.issubset(available):
        raise RealDataBridgeIncomplete("CANDIDATE_SELECTION_INVALID")
    return [candidate for candidate in candidates if candidate.sector_id in selected]


def build_phase1b_request(
    database: Database,
    run_id: UUID,
    storage: RuntimeStorageBundle | None = None,
    *,
    selected_sector_ids: tuple[str, ...] | None = None,
) -> Phase1BRequest:
    if isinstance(database, PostgresDatabase) and storage is None:
        raise ValueError("PostgreSQL bridge requires configured runtime storage")
    sqlite_database = database if isinstance(database, SQLiteDatabase) else None
    if storage is None and sqlite_database is None:
        raise ValueError("runtime storage is required")
    runs = (
        storage.real_data_runs
        if storage is not None
        else SQLiteRealDataRunRepository(cast(SQLiteDatabase, sqlite_database))
    )
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
    snapshots = (
        storage.market_snapshots
        if storage is not None
        else SQLiteMarketSnapshotRepository(cast(SQLiteDatabase, sqlite_database))
    )
    industry = snapshots.get(run_id, SectorKind.INDUSTRY)
    concept = snapshots.get(run_id, SectorKind.CONCEPT)
    if industry is None or concept is None:
        raise RealDataBridgeIncomplete("REAL_DATA_BRIDGE_INCOMPLETE")

    candidates = select_requested_candidates(
        runs.get_candidates(run_id), selected_sector_ids
    )
    evidence = (
        storage.evidence
        if storage is not None
        else SQLiteEvidenceRepository(cast(SQLiteDatabase, sqlite_database))
    )
    all_packs = evidence.list_for_run(run_id)
    pack_by_sector = {pack.sector_id: pack for pack in all_packs}
    packs = [
        pack_by_sector[candidate.sector_id]
        for candidate in candidates
        if candidate.sector_id in pack_by_sector
    ]
    if len(candidates) < 3 or len(packs) < len(candidates):
        raise RealDataBridgeIncomplete("REAL_DATA_BRIDGE_INCOMPLETE")
    event_ids = tuple(dict.fromkeys(event_id for pack in packs for event_id in pack.event_ids))
    news = (
        storage.news
        if storage is not None
        else SQLiteNewsRepository(cast(SQLiteDatabase, sqlite_database))
    )
    events = news.get_events(event_ids)
    documents = news.get_documents(
        tuple(dict.fromkeys(document_id for event in events for document_id in event.document_ids))
    )
    retrieval = (
        storage.news_retrieval
        if storage is not None
        else SQLiteNewsRetrievalRepository(cast(SQLiteDatabase, sqlite_database))
    )
    links = retrieval.list_links(run_id)
    links_by_sector: dict[str, list[SectorEventLink]] = {}
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
