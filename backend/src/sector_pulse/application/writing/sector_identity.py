"""Restore names exclusively from typed snapshots of the source run."""

from uuid import UUID

from sector_pulse.domain.writing.attribution import AttributionContext
from sector_pulse.storage.ports.market import MarketSnapshotRepositoryPort


def restore_context_names(
    contexts: tuple[AttributionContext, ...],
    source_run_id: UUID,
    snapshots: MarketSnapshotRepositoryPort,
) -> tuple[AttributionContext, ...]:
    universes = {
        kind: snapshots.get(source_run_id, kind)
        for kind in {c.sector_kind for c in contexts if not (c.sector_name or "").strip()}
    }
    restored = []
    for context in contexts:
        if (context.sector_name or "").strip():
            restored.append(context)
            continue
        universe = universes.get(context.sector_kind)
        matches = (
            [
                s
                for s in universe.sectors
                if s.kind == context.sector_kind
                and s.provider_sector_id == context.sector_id
                and s.name.strip()
            ]
            if universe and universe.kind == context.sector_kind
            else []
        )
        restored.append(
            context.model_copy(update={"sector_name": matches[0].name.strip()})
            if len(matches) == 1
            else context
        )
    return tuple(restored)
