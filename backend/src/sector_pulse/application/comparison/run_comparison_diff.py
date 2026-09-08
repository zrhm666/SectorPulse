"""Pure differences over persisted observations, never scores recomputed from live data."""

from collections.abc import Mapping, Sequence
from decimal import Decimal

from sector_pulse.application.comparison.run_comparison_models import (
    ComparisonWarning,
    KindComparison,
    Membership,
    MetricDifference,
    MetricUnit,
    MissingReason,
    SectorComparisonRow,
    SnapshotContext,
)
from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.real_data_run import RealDataCandidate


def metric_difference(
    base: Decimal | None,
    compare: Decimal | None,
    *,
    unit: MetricUnit,
    base_reason: MissingReason | None = None,
    compare_reason: MissingReason | None = None,
) -> MetricDifference:
    if base_reason is not None:
        base = None
    if compare_reason is not None:
        compare = None
    return MetricDifference(
        base=base,
        compare=compare,
        delta=None if base is None or compare is None else compare - base,
        unit=unit,
        base_reason=base_reason or ("VALUE_MISSING" if base is None else None),
        compare_reason=compare_reason or ("VALUE_MISSING" if compare is None else None),
    )


def rank_delta(base: int | None, compare: int | None) -> int | None:
    return None if base is None or compare is None else base - compare


def candidate_keys(candidates: Sequence[RealDataCandidate]) -> set[tuple[SectorKind, str]]:
    return {(item.sector_kind, item.sector_id) for item in candidates}


def document_membership(base_ids: set[str], compare_ids: set[str]) -> dict[str, Membership]:
    return {
        key: "BOTH"
        if key in base_ids and key in compare_ids
        else "ONLY_BASE"
        if key in base_ids
        else "ONLY_COMPARE"
        for key in sorted(base_ids | compare_ids)
    }


def _context(snapshot: SectorUniverseSnapshot | None) -> SnapshotContext | None:
    if snapshot is None:
        return None
    return SnapshotContext(
        provider_id=snapshot.provider_id,
        classification_version=snapshot.classification_version,
        source_version=snapshot.source_version,
        observed_at=snapshot.observed_at,
        collected_at=snapshot.collected_at,
        available_fields=sorted(snapshot.available_fields),
    )


def _observation(
    sector: SectorSnapshot | None,
    fields: frozenset[str],
    field: str,
) -> tuple[Decimal | None, MissingReason | None]:
    if sector is None:
        return None, "SECTOR_MISSING"
    if field not in fields:
        return None, "FIELD_UNDECLARED"
    value = getattr(sector, field)
    if value is None:
        return None, "VALUE_MISSING"
    return Decimal(value), None


def _sector_row(
    kind: SectorKind,
    sector_id: str,
    base_candidate: RealDataCandidate | None,
    compare_candidate: RealDataCandidate | None,
    base_sector: SectorSnapshot | None,
    compare_sector: SectorSnapshot | None,
    base_fields: frozenset[str],
    compare_fields: frozenset[str],
) -> SectorComparisonRow:
    def metric(field: str, unit: MetricUnit) -> MetricDifference:
        base, base_reason = _observation(base_sector, base_fields, field)
        compare, compare_reason = _observation(compare_sector, compare_fields, field)
        return metric_difference(
            base, compare, unit=unit, base_reason=base_reason, compare_reason=compare_reason
        )

    base_rank = base_candidate.rank if base_candidate else None
    compare_rank = compare_candidate.rank if compare_candidate else None
    return SectorComparisonRow(
        sector_id=sector_id,
        kind=kind,
        base_name=base_sector.name if base_sector and "name" in base_fields else None,
        compare_name=compare_sector.name if compare_sector and "name" in compare_fields else None,
        membership="BOTH"
        if base_candidate and compare_candidate
        else "ONLY_BASE"
        if base_candidate
        else "ONLY_COMPARE",
        base_rank=base_rank,
        compare_rank=compare_rank,
        rank_delta=rank_delta(base_rank, compare_rank),
        base_score=base_candidate.score if base_candidate else None,
        compare_score=compare_candidate.score if compare_candidate else None,
        base_leader=base_sector.leader_name
        if base_sector and "leader_name" in base_fields
        else None,
        compare_leader=compare_sector.leader_name
        if compare_sector and "leader_name" in compare_fields
        else None,
        pct_change=metric("pct_change", "percentage_points"),
        turnover_rate=metric("turnover_rate", "percentage_points"),
        advancers=metric("advancers", "count"),
        decliners=metric("decliners", "count"),
    )


def compare_kinds(
    base_snapshots: Mapping[SectorKind, SectorUniverseSnapshot | None],
    compare_snapshots: Mapping[SectorKind, SectorUniverseSnapshot | None],
    base_candidates: Sequence[RealDataCandidate],
    compare_candidates: Sequence[RealDataCandidate],
) -> tuple[list[KindComparison], list[ComparisonWarning]]:
    groups: list[KindComparison] = []
    warnings: list[ComparisonWarning] = []
    base_by_key = {(row.sector_kind, row.sector_id): row for row in base_candidates}
    compare_by_key = {(row.sector_kind, row.sector_id): row for row in compare_candidates}
    keys = candidate_keys(base_candidates) | candidate_keys(compare_candidates)
    for kind in SectorKind:
        base, compare = base_snapshots.get(kind), compare_snapshots.get(kind)
        base_context, compare_context = _context(base), _context(compare)
        if base is None or compare is None:
            groups.append(
                KindComparison(
                    kind=kind,
                    base=base_context,
                    compare=compare_context,
                    status="UNAVAILABLE",
                    rows=[],
                )
            )
            warnings.append(
                ComparisonWarning(
                    code="SNAPSHOT_MISSING",
                    kind=kind,
                    message="该类别缺少一侧行情快照，不能计算变化。",
                )
            )
            continue
        identity = (base.provider_id, base.classification_version)
        if not all(value.strip() for value in identity) or identity != (
            compare.provider_id,
            compare.classification_version,
        ):
            groups.append(
                KindComparison(
                    kind=kind,
                    base=base_context,
                    compare=compare_context,
                    status="INCOMPATIBLE",
                    rows=[],
                )
            )
            warnings.append(
                ComparisonWarning(
                    code="CLASSIFICATION_MISMATCH",
                    kind=kind,
                    message="该类别的数据来源或分类版本不同，未配对板块。",
                )
            )
            continue
        if base.source_version != compare.source_version:
            warnings.append(
                ComparisonWarning(
                    code="SOURCE_VERSION_DIFF",
                    kind=kind,
                    message="采集程序版本不同，行情字段口径可能有差异。",
                )
            )
        for side, snapshot in (("BASE", base), ("COMPARE", compare)):
            if not snapshot.available_fields:
                warnings.append(
                    ComparisonWarning(
                        code="FIELD_SCHEMA_UNKNOWN",
                        side="BASE" if side == "BASE" else "COMPARE",
                        kind=kind,
                        message="历史快照未声明可用字段，相关数值标记为未知。",
                    )
                )
        base_sectors = {sector.provider_sector_id: sector for sector in base.sectors}
        compare_sectors = {sector.provider_sector_id: sector for sector in compare.sectors}
        rows = [
            _sector_row(
                kind,
                sector_id,
                base_by_key.get((kind, sector_id)),
                compare_by_key.get((kind, sector_id)),
                base_sectors.get(sector_id),
                compare_sectors.get(sector_id),
                base.available_fields,
                compare.available_fields,
            )
            for key_kind, sector_id in sorted(keys)
            if key_kind == kind
        ]
        rows.sort(
            key=lambda row: (
                row.compare_rank is None,
                row.compare_rank or 0,
                row.base_rank or 0,
                row.kind,
                row.sector_id,
            )
        )
        groups.append(
            KindComparison(
                kind=kind,
                base=base_context,
                compare=compare_context,
                status="COMPARABLE",
                rows=rows,
            )
        )
    return groups, warnings
