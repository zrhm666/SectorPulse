"""Programmatic evidence inspection for one server-bound A2 task."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sector_pulse.application.data_runs.candidate_selection import build_evidence_pack
from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.data_tools import require_live_task_owner
from sector_pulse.application.orchestration.research_context import BoundSectorResearchContext
from sector_pulse.application.writing.agent_validation import (
    AgentOutputViolation,
    validate_analysis_card,
)
from sector_pulse.application.writing.attribution_gate import (
    build_attribution_context,
    evaluate_attribution_gate,
)
from sector_pulse.domain.news.evidence import EvidenceLevel
from sector_pulse.domain.news.research import NewsDetailSnapshot, ResearchSearchBatch
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.domain.writing.research import (
    EvidenceDocumentView,
    EvidenceInspectionReport,
    SectorAnalysisArtifact,
    SectorAnalysisSubmission,
)
from sector_pulse.ports.orchestration import SnapshotRepository, TransactionSession
from sector_pulse.storage.ports.market import (
    CandidateBatchRepositoryPort,
    MarketSnapshotRepositoryPort,
)
from sector_pulse.storage.ports.news import (
    NewsBatchRepositoryPort,
    NewsDetailSnapshotRepositoryPort,
    NewsRepositoryPort,
    ResearchSearchRepositoryPort,
)
from sector_pulse.storage.ports.writing import EvidenceInspectionRepositoryPort


def evidence_inspection_artifact_id(report: EvidenceInspectionReport) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"evidence-inspection-artifact:{report.report_id}:{report.task_id}:{report.attempt}",
    )


def sector_analysis_artifact_id(analysis: SectorAnalysisArtifact) -> UUID:
    return uuid5(NAMESPACE_URL, f"sector-analysis-artifact:{analysis.analysis_id}")


class EvidenceInspectionPersistence:
    def __init__(self, report: EvidenceInspectionReport) -> None:
        self._report = report

    def write(self, session: TransactionSession, artifact: object) -> None:
        del artifact
        report = self._report
        session.execute(
            "INSERT INTO evidence_inspection_reports (report_id, run_id, task_id, attempt, "
            "sector_id, sector_kind, selection_version, input_fingerprint, artifact_ids_json, "
            "context_json, gate_json, document_views_json, payload_json, created_at) VALUES "
            "(:report_id, :run_id, :task_id, :attempt, :sector_id, :sector_kind, "
            ":selection_version, :input_fingerprint, :artifact_ids_json, :context_json, "
            ":gate_json, :document_views_json, :payload_json, :created_at)",
            {
                "report_id": str(report.report_id),
                "run_id": str(report.run_id),
                "task_id": str(report.task_id),
                "attempt": report.attempt,
                "sector_id": report.sector_id,
                "sector_kind": report.context.sector_kind.value,
                "selection_version": report.selection_version,
                "input_fingerprint": report.input_fingerprint,
                "artifact_ids_json": json.dumps(
                    [str(item) for item in report.input_artifact_ids]
                ),
                "context_json": report.context.model_dump_json(),
                "gate_json": report.gate.model_dump_json(),
                "document_views_json": json.dumps(
                    [item.model_dump(mode="json") for item in report.document_views],
                    ensure_ascii=False,
                ),
                "payload_json": report.model_dump_json(),
                "created_at": report.created_at.isoformat(),
            },
        )

    def exists(self, session: TransactionSession, artifact: object) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM evidence_inspection_reports WHERE report_id=:report_id",
                {"report_id": str(self._report.report_id)},
            )
        )


class InspectSectorEvidenceService:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
        candidate_batches: CandidateBatchRepositoryPort,
        market_snapshots: MarketSnapshotRepositoryPort,
        news: NewsRepositoryPort,
        research_searches: ResearchSearchRepositoryPort,
        news_details: NewsDetailSnapshotRepositoryPort,
        news_batches: NewsBatchRepositoryPort | None = None,
    ) -> None:
        self._orchestration = orchestration
        self._committer = committer
        self._candidate_batches = candidate_batches
        self._market_snapshots = market_snapshots
        self._news = news
        self._research_searches = research_searches
        self._news_details = news_details
        self._news_batches = news_batches

    def inspect(
        self,
        *,
        context: BoundSectorResearchContext,
        artifact_ids: tuple[UUID, ...],
        now: datetime | None = None,
    ) -> EvidenceInspectionReport:
        created_at = now or datetime.now(UTC)
        require_live_task_owner(
            self._orchestration,
            context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=created_at,
        )
        if not artifact_ids or len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("inspection requires unique artifact IDs")
        state = self._orchestration.load(context.run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        artifacts = {item.artifact_id: item for item in state.artifacts}
        authorized = {item.artifact_id for item in context.input_artifacts}
        authorized.update(
            item.artifact_id
            for item in state.artifacts
            if item.task_id == context.task_id and item.attempt == context.attempt
        )
        if any(item not in authorized or item not in artifacts for item in artifact_ids):
            raise ValueError("artifact is not authorized for this research task")
        selected = tuple(artifacts[item] for item in artifact_ids)
        if any(
            item.kind not in {"candidate_batch", "news_batch", "research_search", "news_detail"}
            for item in selected
        ):
            raise ValueError("artifact kind is not authorized for evidence inspection")

        candidate_artifacts = tuple(
            item for item in context.input_artifacts if item.kind == "candidate_batch"
        )
        if len(candidate_artifacts) != 1:
            raise ValueError("inspection requires one pinned candidate batch")
        if candidate_artifacts[0].artifact_id not in artifact_ids:
            raise ValueError("inspection must include the pinned candidate batch")
        prefix = "candidate-batch:"
        candidate_ref = candidate_artifacts[0].reference
        if not candidate_ref.startswith(prefix):
            raise ValueError("candidate batch reference is invalid")
        candidate_batch = self._candidate_batches.get(UUID(candidate_ref[len(prefix) :]))
        if candidate_batch is None or candidate_batch.run_id != context.run_id:
            raise ValueError("candidate batch is unavailable")
        candidate = next(
            (
                item
                for item in candidate_batch.candidates
                if item.provider_sector_id == context.sector_id
                and item.kind == context.sector_kind
            ),
            None,
        )
        if candidate is None:
            raise ValueError("candidate does not match research scope")

        event_ids: set[str] = set()
        document_ids: set[str] = set()
        details: dict[str, NewsDetailSnapshot] = {}
        for artifact in selected:
            if artifact.kind == "research_search":
                batch = self._research_search(artifact, context)
                event_ids.update(batch.event_ids)
                document_ids.update(batch.document_ids)
            elif artifact.kind == "news_detail":
                detail = self._news_detail(artifact, context)
                details[detail.document_id] = detail
                document_ids.add(detail.document_id)
            elif artifact.kind == "news_batch":
                prefix = "news-batch:"
                if self._news_batches is None or not artifact.reference.startswith(prefix):
                    raise ValueError("news batch is unavailable")
                news_batch = self._news_batches.get(UUID(artifact.reference[len(prefix) :]))
                if news_batch is None or news_batch.run_id != context.run_id:
                    raise ValueError("news batch does not match current run")
                event_ids.update(news_batch.event_ids)
                document_ids.update(news_batch.document_ids)
        events = self._news.get_events(tuple(sorted(event_ids)))
        for event in events:
            document_ids.update(event.document_ids)
        documents = self._news.get_documents(tuple(sorted(document_ids)))
        snapshot = self._market_snapshots.get(context.run_id, context.sector_kind)
        run = self._market_snapshots.get_run(context.run_id)
        if snapshot is None or run is None or run.run_cutoff_at != context.cutoff_at:
            raise ValueError("pinned market snapshot is unavailable")
        pack = build_evidence_pack(candidate, (snapshot,), events, context.run_id)
        sector = next(
            item
            for item in snapshot.sectors
            if item.provider_sector_id == context.sector_id and item.kind == context.sector_kind
        )
        attribution_context = build_attribution_context(
            run,
            pack,
            sector,
            events,
            documents,
            (),
            None,
        )
        gate = evaluate_attribution_gate(attribution_context, documents, None, False)
        views = tuple(
            EvidenceDocumentView(
                document_id=document.document_id,
                title=document.title,
                publisher=document.publisher,
                citation_url=document.citation_url,
                published_at=document.published_at,
                source_grade=document.source_grade,
                use=document.use_at(context.cutoff_at),
                detail_availability=(
                    details[document.document_id].availability
                    if document.document_id in details
                    else None
                ),
                content=(
                    details[document.document_id].content
                    if document.document_id in details
                    else ""
                ),
                historical_snapshot_verified=(
                    details[document.document_id].historical_snapshot_verified
                    if document.document_id in details
                    else False
                ),
            )
            for document in sorted(documents.values(), key=lambda item: item.document_id)
        )
        ordered_ids = tuple(sorted(artifact_ids, key=str))
        fingerprint = hashlib.sha256(
            json.dumps([str(item) for item in ordered_ids], separators=(",", ":")).encode()
        ).hexdigest()
        report = EvidenceInspectionReport(
            report_id=uuid5(
                NAMESPACE_URL,
                "evidence-inspection:"
                f"{context.run_id}:{context.task_id}:{context.attempt}:{fingerprint}",
            ),
            run_id=context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            sector_id=context.sector_id,
            selection_version=context.selection_version,
            input_artifact_ids=ordered_ids,
            input_fingerprint=fingerprint,
            context=attribution_context,
            gate=gate,
            document_views=views,
            created_at=created_at,
        )
        artifact = ArtifactRef(
            artifact_id=evidence_inspection_artifact_id(report),
            task_id=context.task_id,
            attempt=context.attempt,
            kind="evidence_inspection",
            reference=f"evidence-inspection:{report.report_id}",
        )
        self._committer.commit(
            artifact,
            worker_id=context.worker_id,
            persistence=EvidenceInspectionPersistence(report),
            now=created_at,
        )
        return report

    def _research_search(
        self, artifact: ArtifactRef, context: BoundSectorResearchContext
    ) -> ResearchSearchBatch:
        prefix = "research-search:"
        if not artifact.reference.startswith(prefix):
            raise ValueError("research search reference is invalid")
        batch = self._research_searches.get(UUID(artifact.reference[len(prefix) :]))
        if (
            batch is None
            or batch.run_id != context.run_id
            or batch.task_id != context.task_id
            or batch.attempt != context.attempt
            or batch.sector_id != context.sector_id
            or batch.sector_kind != context.sector_kind
        ):
            raise ValueError("research search does not match current scope")
        return batch

    def _news_detail(
        self, artifact: ArtifactRef, context: BoundSectorResearchContext
    ) -> NewsDetailSnapshot:
        prefix = "news-detail:"
        if not artifact.reference.startswith(prefix):
            raise ValueError("news detail reference is invalid")
        detail = self._news_details.get(UUID(artifact.reference[len(prefix) :]))
        if (
            detail is None
            or detail.run_id != context.run_id
            or detail.task_id != context.task_id
            or detail.attempt != context.attempt
            or detail.sector_id != context.sector_id
            or detail.sector_kind != context.sector_kind
        ):
            raise ValueError("news detail does not match current scope")
        return detail


class SectorAnalysisPersistence:
    def __init__(self, analysis: SectorAnalysisArtifact) -> None:
        self._analysis = analysis

    def write(self, session: TransactionSession, artifact: object) -> None:
        del artifact
        analysis = self._analysis
        session.execute(
            "INSERT INTO sector_analysis_artifacts (analysis_id, run_id, task_id, attempt, "
            "sector_id, sector_kind, inspection_id, input_fingerprint, card_hash, card_json, "
            "payload_json, created_at) VALUES (:analysis_id, :run_id, :task_id, :attempt, "
            ":sector_id, :sector_kind, :inspection_id, :fingerprint, :card_hash, :card_json, "
            ":payload_json, :created_at)",
            {
                "analysis_id": str(analysis.analysis_id),
                "run_id": str(analysis.run_id),
                "task_id": str(analysis.task_id),
                "attempt": analysis.attempt,
                "sector_id": analysis.card.sector_id,
                "sector_kind": analysis.card.sector_kind.value,
                "inspection_id": str(analysis.inspection_id),
                "fingerprint": analysis.input_fingerprint,
                "card_hash": analysis.card_hash,
                "card_json": analysis.card.model_dump_json(),
                "payload_json": analysis.model_dump_json(),
                "created_at": analysis.created_at.isoformat(),
            },
        )
        for claim in analysis.card.claims:
            session.execute(
                "INSERT INTO sector_analysis_claims (analysis_id, claim_id, claim_kind, "
                "payload_json) VALUES (:analysis_id, :claim_id, :claim_kind, :payload_json)",
                {
                    "analysis_id": str(analysis.analysis_id),
                    "claim_id": claim.claim_id,
                    "claim_kind": claim.kind.value,
                    "payload_json": claim.model_dump_json(),
                },
            )

    def exists(self, session: TransactionSession, artifact: object) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM sector_analysis_artifacts WHERE analysis_id=:analysis_id",
                {"analysis_id": str(self._analysis.analysis_id)},
            )
        )


class SubmitSectorAnalysisService:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
        inspections: EvidenceInspectionRepositoryPort,
    ) -> None:
        self._orchestration = orchestration
        self._committer = committer
        self._inspections = inspections

    def submit(
        self,
        *,
        context: BoundSectorResearchContext,
        inspection_artifact_id: UUID,
        submission: SectorAnalysisSubmission,
        now: datetime | None = None,
    ) -> SectorAnalysisArtifact:
        created_at = now or datetime.now(UTC)
        require_live_task_owner(
            self._orchestration,
            context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=created_at,
        )
        state = self._orchestration.load(context.run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        artifact = next(
            (item for item in state.artifacts if item.artifact_id == inspection_artifact_id),
            None,
        )
        prefix = "evidence-inspection:"
        if artifact is None or (
            artifact.task_id != context.task_id or artifact.attempt != context.attempt
        ):
            candidates = tuple(
                item
                for item in state.artifacts
                if item.kind == "evidence_inspection"
                and item.task_id == context.task_id
                and item.attempt == context.attempt
            )
            if len(candidates) == 1:
                artifact = candidates[0]
        if (
            artifact is None
            or artifact.kind != "evidence_inspection"
            or artifact.task_id != context.task_id
            or artifact.attempt != context.attempt
            or not artifact.reference.startswith(prefix)
        ):
            raise ValueError("inspection artifact is not authorized")
        report = self._inspections.get(UUID(artifact.reference[len(prefix) :]))
        if (
            report is None
            or report.run_id != context.run_id
            or report.task_id != context.task_id
            or report.attempt != context.attempt
            or report.sector_id != context.sector_id
            or report.selection_version != context.selection_version
        ):
            raise ValueError("inspection report does not match current scope")
        if report.gate.allowed_max_level is EvidenceLevel.NO_RELIABLE_EXPLANATION:
            submission = submission.model_copy(
                update={
                    "attribution_level": EvidenceLevel.NO_RELIABLE_EXPLANATION,
                    "confidence": min(submission.confidence, Decimal("0.2")),
                    "conclusion": "现有材料不足以支持可靠归因。",
                    "supporting_evidence_ids": (),
                    "uncertainties": submission.uncertainties
                    or ("缺少可验证的直接驱动证据",),
                    "background_event_ids": (),
                    "claims": (),
                    "forbidden_inferences": submission.forbidden_inferences,
                }
            )
        from sector_pulse.domain.writing.attribution import LEVEL_RANK, SectorAnalysisCard

        if LEVEL_RANK[submission.attribution_level] > LEVEL_RANK[report.gate.allowed_max_level]:
            raise AgentOutputViolation(
                "ATTRIBUTION_LEVEL_EXCEEDED", submission.attribution_level.value
            )

        card = validate_analysis_card(
            SectorAnalysisCard(
                run_id=context.run_id,
                sector_id=context.sector_id,
                sector_kind=context.sector_kind,
                sector_name=context.sector_name,
                allowed_max_level=report.gate.allowed_max_level,
                counter_evidence=report.gate.counter_evidence,
                **submission.model_dump(),
            ),
            report.gate,
            report.context,
        )
        canonical = card.model_dump_json()
        card_hash = hashlib.sha256(canonical.encode()).hexdigest()
        fingerprint = hashlib.sha256(
            f"{report.report_id}:{card_hash}".encode()
        ).hexdigest()
        analysis = SectorAnalysisArtifact(
            analysis_id=uuid5(NAMESPACE_URL, f"sector-analysis:{context.run_id}:{fingerprint}"),
            run_id=context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            inspection_id=report.report_id,
            input_fingerprint=fingerprint,
            card_hash=card_hash,
            card=card,
            created_at=created_at,
        )
        analysis_artifact = ArtifactRef(
            artifact_id=sector_analysis_artifact_id(analysis),
            task_id=context.task_id,
            attempt=context.attempt,
            kind="sector_analysis",
            reference=f"sector-analysis:{analysis.analysis_id}",
        )
        self._committer.commit(
            analysis_artifact,
            worker_id=context.worker_id,
            persistence=SectorAnalysisPersistence(analysis),
            now=created_at,
        )
        return analysis


__all__ = [
    "EvidenceInspectionPersistence",
    "InspectSectorEvidenceService",
    "SectorAnalysisPersistence",
    "SubmitSectorAnalysisService",
]
