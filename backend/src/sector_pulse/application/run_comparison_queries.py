"""Query persisted run state only; shared news metadata is explicitly not historical text."""

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from sector_pulse.application.run_comparison_diff import compare_kinds, document_membership
from sector_pulse.application.run_comparison_models import (
    CandidateCounts,
    ComparisonWarning,
    CurrentNewsMetadata,
    EvidenceComparisonPage,
    EvidenceComparisonRow,
    EvidenceLinkView,
    KindComparison,
    MembershipFilter,
    NewsComparisonPage,
    NewsComparisonRow,
    NewsCounts,
    NewsCoverage,
    Provider,
    RunComparisonView,
    RunMode,
    RunOption,
    RunOptionPage,
)
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.news import NewsDocument
from sector_pulse.domain.news_retrieval import SectorEventLink
from sector_pulse.domain.quality import QualityStatus
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunStatus
from sector_pulse.storage.runtime_bundle import RuntimeStorageBundle


class ComparisonNotFoundError(ValueError):
    pass


class ComparisonConflictError(ValueError):
    pass


class ComparisonInputError(ValueError):
    pass


def _pagination(offset: int, limit: int) -> None:
    if offset < 0 or not 1 <= limit <= 100:
        raise ComparisonInputError("分页范围无效：每页应为 1–100 条。")


def _option(run: RealDataRun) -> RunOption:
    assert run.request.lookback_hours is not None
    return RunOption(
        run_id=run.run_id,
        provider=run.provider,
        mode=run.request.mode,
        status=run.status,
        requested_at=run.request.requested_at,
        cutoff_at=run.cutoff_at,
        finished_at=run.finished_at,
        lookback_hours=run.request.lookback_hours,
        precandidate_limit=run.request.precandidate_limit,
        final_candidate_limit=run.request.final_candidate_limit,
        error_code=run.error_code,
    )


def _coverage(ids: set[str]) -> NewsCoverage:
    return NewsCoverage(lineage="RECORDED" if ids else "UNVERIFIABLE", recorded_count=len(ids))


def _news_counts(base: set[str], compare: set[str]) -> NewsCounts | None:
    if not base or not compare:
        return None
    return NewsCounts(
        both=len(base & compare), only_base=len(base - compare), only_compare=len(compare - base)
    )


def _metadata(document: NewsDocument | None) -> CurrentNewsMetadata | None:
    if document is None:
        return None
    url = document.citation_url
    try:
        parsed = urlsplit(url or "")
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            url = None
    except ValueError:
        url = None
    return CurrentNewsMetadata(
        title=document.title,
        source_id=document.source_id,
        publisher=document.publisher,
        summary=document.summary,
        citation_url=url,
        published_at=document.published_at,
    )


def _link_view(link: SectorEventLink | None) -> EvidenceLinkView | None:
    if link is None:
        return None
    return EvidenceLinkView(
        relation_type=link.relation_type,
        mapping_confidence=link.mapping_confidence,
        mapping_reason=link.mapping_reason,
        rule_version=link.rule_version,
    )


def _run_warnings(base: RealDataRun, compare: RealDataRun) -> list[ComparisonWarning]:
    warnings: list[ComparisonWarning] = []
    for side, run in (("BASE", base), ("COMPARE", compare)):
        typed_side: Literal["BASE", "COMPARE"] = "BASE" if side == "BASE" else "COMPARE"
        if (
            run.status != RealDataRunStatus.READY_FOR_ATTRIBUTION
            or run.error_code
            or run.quality.downgrade_reasons
            or run.quality.cutoff_violation_count
            or any(
                quality != QualityStatus.NORMAL
                for quality in (
                    *run.quality.market_quality.values(),
                    *run.quality.news_quality.values(),
                )
            )
        ):
            warnings.append(
                ComparisonWarning(
                    code="RUN_PARTIAL",
                    side=typed_side,
                    message="运行存在失败或质量降级，仅比较当前留存数据，不代表完整采集。",
                )
            )
        if run.cutoff_at is None:
            warnings.append(
                ComparisonWarning(
                    code="CUTOFF_MISSING",
                    side=typed_side,
                    message="运行未保存数据截点，无法核验完整时间边界。",
                )
            )
    if base.request.lookback_hours != compare.request.lookback_hours:
        warnings.append(
            ComparisonWarning(
                code="NEWS_WINDOW_DIFF",
                message="两次新闻回溯窗口不同，留存数量不能直接解释为新闻热度变化。",
            )
        )
    if (base.request.precandidate_limit, base.request.final_candidate_limit) != (
        compare.request.precandidate_limit,
        compare.request.final_candidate_limit,
    ):
        warnings.append(
            ComparisonWarning(
                code="CANDIDATE_LIMIT_DIFF",
                message="两次候选数量上限不同，入选关系可能受到筛选范围影响。",
            )
        )
    if base.cutoff_at and compare.cutoff_at and compare.cutoff_at < base.cutoff_at:
        warnings.append(ComparisonWarning(code="REVERSED_TIME", message="对照时间早于基准。"))
    return warnings


class RunComparisonQueries:
    def __init__(self, storage: RuntimeStorageBundle) -> None:
        self._storage = storage

    def list_runs(
        self,
        *,
        provider: Provider | None = None,
        mode: RunMode | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> RunOptionPage:
        _pagination(offset, limit)
        runs, total = self._storage.real_data_runs.list_comparison_runs(
            provider=provider, mode=mode, offset=offset, limit=limit
        )
        return RunOptionPage(
            items=[_option(run) for run in runs], total=total, offset=offset, limit=limit
        )

    def _pair(self, base_id: UUID, compare_id: UUID) -> tuple[RealDataRun, RealDataRun]:
        if base_id == compare_id:
            raise ComparisonInputError("请选择两次不同的数据运行。")
        base = self._storage.real_data_runs.get_run(base_id)
        compare = self._storage.real_data_runs.get_run(compare_id)
        if base is None or compare is None:
            raise ComparisonNotFoundError("所选数据运行不存在，或仅包含内容运行。")
        if not base.status.is_terminal or not compare.status.is_terminal:
            raise ComparisonConflictError("数据采集尚未结束，请等待运行结束后再比较。")
        if base.provider != compare.provider or base.request.mode != compare.request.mode:
            raise ComparisonConflictError("请选择相同来源、相同盘中或盘后场景的运行。")
        return base, compare

    def _market(
        self,
        base_id: UUID,
        compare_id: UUID,
    ) -> tuple[list[KindComparison], list[ComparisonWarning]]:
        storage = self._storage
        return compare_kinds(
            {kind: storage.market_snapshots.get(base_id, kind) for kind in SectorKind},
            {kind: storage.market_snapshots.get(compare_id, kind) for kind in SectorKind},
            storage.real_data_runs.get_candidates(base_id),
            storage.real_data_runs.get_candidates(compare_id),
        )

    def _documents(self, run_id: UUID) -> set[str]:
        return {
            link.document_id for link in self._storage.news_retrieval.list_query_documents(run_id)
        }

    def compare(self, base_run_id: UUID, compare_run_id: UUID) -> RunComparisonView:
        base, compare = self._pair(base_run_id, compare_run_id)
        kinds, market_warnings = self._market(base_run_id, compare_run_id)
        base_ids, compare_ids = self._documents(base_run_id), self._documents(compare_run_id)
        rows = [row for group in kinds for row in group.rows]
        warnings = [*_run_warnings(base, compare), *market_warnings]
        if not base_ids or not compare_ids:
            warnings.append(
                ComparisonWarning(
                    code="NEWS_LINEAGE_UNVERIFIABLE",
                    message="至少一侧缺少新闻成员记录，新闻差异无法核验；不能视为零条新闻。",
                )
            )
        warnings.append(
            ComparisonWarning(
                code="CURRENT_NEWS_METADATA",
                message="新闻文字为当前保存的元数据，非历史正文快照；不包含已删除的历史记录。",
            )
        )
        return RunComparisonView(
            base=_option(base),
            compare=_option(compare),
            queried_at=datetime.now(UTC),
            warnings=warnings,
            kinds=kinds,
            base_news=_coverage(base_ids),
            compare_news=_coverage(compare_ids),
            news_counts=_news_counts(base_ids, compare_ids),
            candidates=CandidateCounts(
                both=sum(row.membership == "BOTH" for row in rows),
                only_base=sum(row.membership == "ONLY_BASE" for row in rows),
                only_compare=sum(row.membership == "ONLY_COMPARE" for row in rows),
                unavailable_kinds=sum(group.status != "COMPARABLE" for group in kinds),
            ),
        )

    def news(
        self,
        base_run_id: UUID,
        compare_run_id: UUID,
        *,
        membership: MembershipFilter = "ALL",
        offset: int = 0,
        limit: int = 20,
    ) -> NewsComparisonPage:
        _pagination(offset, limit)
        if membership not in {"ALL", "BOTH", "ONLY_BASE", "ONLY_COMPARE"}:
            raise ComparisonInputError("新闻成员筛选无效。")
        self._pair(base_run_id, compare_run_id)
        base_ids, compare_ids = self._documents(base_run_id), self._documents(compare_run_id)
        base_news, compare_news = _coverage(base_ids), _coverage(compare_ids)
        counts = _news_counts(base_ids, compare_ids)
        if counts is None:
            return NewsComparisonPage(
                available=False,
                reason="LINEAGE_UNVERIFIABLE",
                base_news=base_news,
                compare_news=compare_news,
                counts=None,
                total=None,
                items=[],
                offset=offset,
                limit=limit,
            )
        memberships = document_membership(base_ids, compare_ids)
        filtered = [
            key for key, value in memberships.items() if membership == "ALL" or value == membership
        ]
        page_ids = filtered[offset : offset + limit]
        documents = self._storage.news.get_documents(page_ids) if page_ids else {}
        return NewsComparisonPage(
            available=True,
            reason=None,
            base_news=base_news,
            compare_news=compare_news,
            counts=counts,
            total=len(filtered),
            items=[
                NewsComparisonRow(
                    document_id=key,
                    membership=memberships[key],
                    metadata=_metadata(documents.get(key)),
                )
                for key in page_ids
            ],
            offset=offset,
            limit=limit,
        )

    def evidence(
        self,
        base_run_id: UUID,
        compare_run_id: UUID,
        *,
        kind: SectorKind | None = None,
        sector_id: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> EvidenceComparisonPage:
        _pagination(offset, limit)
        if (kind is None) != (sector_id is None) or sector_id == "":
            raise ComparisonInputError("筛选证据时须同时提供板块类型和板块代码。")
        self._pair(base_run_id, compare_run_id)
        groups, _ = self._market(base_run_id, compare_run_id)
        allowed = {
            (group.kind, row.sector_id)
            for group in groups
            for row in group.rows
            if kind is None or (group.kind, row.sector_id) == (kind, sector_id)
        }

        def links(run_id: UUID) -> dict[tuple[SectorKind, str, str], SectorEventLink]:
            return {
                (link.sector_kind, link.sector_id, link.event_id): link
                for link in self._storage.news_retrieval.list_links(run_id)
                if (link.sector_kind, link.sector_id) in allowed
            }

        base_links, compare_links = links(base_run_id), links(compare_run_id)
        keys = sorted(base_links.keys() | compare_links.keys())
        page = keys[offset : offset + limit]
        event_ids = sorted({key[2] for key in page})
        events = (
            {event.event_id: event for event in self._storage.news.get_events(event_ids)}
            if event_ids
            else {}
        )
        return EvidenceComparisonPage(
            items=[
                EvidenceComparisonRow(
                    kind=key[0],
                    sector_id=key[1],
                    event_id=key[2],
                    membership="BOTH"
                    if key in base_links and key in compare_links
                    else "ONLY_BASE"
                    if key in base_links
                    else "ONLY_COMPARE",
                    base=_link_view(base_links.get(key)),
                    compare=_link_view(compare_links.get(key)),
                    current_event_title=events[key[2]].canonical_title
                    if key[2] in events
                    else None,
                )
                for key in page
            ],
            total=len(keys),
            offset=offset,
            limit=limit,
            unavailable_kinds=[group.kind for group in groups if group.status != "COMPARABLE"],
        )
