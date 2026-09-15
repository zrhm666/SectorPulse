import hashlib
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sector_pulse.application.data_runs.candidate_selection import (
    select_candidates,
    select_market_precandidates,
)
from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.data_tools import require_live_task_owner
from sector_pulse.domain.market.candidate_batch import CandidateBatch, CandidateRankingStage
from sector_pulse.domain.market.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.orchestration.models import ArtifactRef, RunSnapshot
from sector_pulse.ports.orchestration import SnapshotRepository, TransactionSession
from sector_pulse.storage.ports.market import MarketSnapshotRepositoryPort
from sector_pulse.storage.ports.news import NewsBatchRepositoryPort, NewsRepositoryPort


class CandidateBatchPersistence:
    def __init__(self, batch: CandidateBatch) -> None:
        self._batch = batch

    def write(self, session: TransactionSession, artifact: ArtifactRef) -> None:
        del artifact
        batch = self._batch
        session.execute(
            "INSERT INTO candidate_batches (batch_id, run_id, input_fingerprint, "
            "ranking_stage, candidate_limit, created_at) VALUES (:batch_id, :run_id, "
            ":input_fingerprint, :ranking_stage, :candidate_limit, :created_at)",
            {
                "batch_id": str(batch.batch_id),
                "run_id": str(batch.run_id),
                "input_fingerprint": batch.input_fingerprint,
                "ranking_stage": batch.ranking_stage.value,
                "candidate_limit": batch.candidate_limit,
                "created_at": batch.created_at.isoformat(),
            },
        )
        for candidate in batch.candidates:
            session.execute(
                "INSERT INTO sector_candidate_versions (batch_id, provider_sector_id, "
                "sector_kind, sector_name, rank, score, reasons_json) VALUES "
                "(:batch_id, :sector_id, :sector_kind, :sector_name, :rank, :score, "
                ":reasons_json)",
                {
                    "batch_id": str(batch.batch_id),
                    "sector_id": candidate.provider_sector_id,
                    "sector_kind": candidate.kind.value,
                    "sector_name": candidate.name,
                    "rank": candidate.rank,
                    "score": str(candidate.score),
                    "reasons_json": json.dumps(candidate.reasons, ensure_ascii=False),
                },
            )

    def exists(self, session: TransactionSession, artifact: ArtifactRef) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM candidate_batches WHERE batch_id=:batch_id",
                {"batch_id": str(self._batch.batch_id)},
            )
        )


class RankSectorCandidatesService:
    def __init__(
        self,
        *,
        snapshots: MarketSnapshotRepositoryPort,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
        news_batches: NewsBatchRepositoryPort | None = None,
        news: NewsRepositoryPort | None = None,
    ) -> None:
        self._snapshots = snapshots
        self._orchestration = orchestration
        self._committer = committer
        self._news_batches = news_batches
        self._news = news

    def _load_market_snapshots(
        self,
        state: RunSnapshot,
        *,
        task_id: UUID,
        attempt: int,
        market_artifact_ids: tuple[UUID, ...],
    ) -> tuple[SectorUniverseSnapshot, SectorUniverseSnapshot]:
        run_id = self._committer.run_id
        selected = tuple(
            artifact
            for artifact in state.artifacts
            if artifact.artifact_id in market_artifact_ids
        )
        if len(selected) != 2 or len(set(market_artifact_ids)) != 2:
            raise ValueError("both current market snapshot artifacts are required")
        kinds: dict[SectorKind, SectorUniverseSnapshot] = {}
        for artifact in selected:
            if (
                artifact.kind != "market_snapshot"
                or artifact.task_id != task_id
                or artifact.attempt != attempt
            ):
                raise ValueError("market snapshot artifact is outside current task")
            parts = artifact.reference.split(":", 3)
            if len(parts) != 4 or UUID(parts[1]) != run_id:
                raise ValueError("market snapshot reference is invalid")
            kind = SectorKind(parts[2])
            snapshot = self._snapshots.get(run_id, kind)
            if snapshot is None or snapshot.source_version != parts[3]:
                raise KeyError("market snapshot is unavailable")
            kinds[kind] = snapshot
        industry = kinds.get(SectorKind.INDUSTRY)
        concept = kinds.get(SectorKind.CONCEPT)
        if industry is None or concept is None:
            raise ValueError("both current market snapshot kinds are required")
        return industry, concept

    def _persist(
        self,
        batch: CandidateBatch,
        *,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        observed_at: datetime,
    ) -> CandidateBatch:
        artifact = ArtifactRef(
            artifact_id=uuid5(
                NAMESPACE_URL,
                f"candidate-artifact:{batch.batch_id}:{task_id}:{attempt}",
            ),
            task_id=task_id,
            attempt=attempt,
            kind="candidate_batch",
            reference=f"candidate-batch:{batch.batch_id}",
        )
        self._committer.commit(
            artifact,
            worker_id=worker_id,
            persistence=CandidateBatchPersistence(batch),
            now=observed_at,
        )
        return batch

    def rank_market(
        self,
        *,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        market_artifact_ids: tuple[UUID, ...],
        limit: int,
        now: datetime | None = None,
    ) -> CandidateBatch:
        observed_at = now or datetime.now(UTC)
        run_id = self._committer.run_id
        require_live_task_owner(
            self._orchestration,
            run_id,
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            now=observed_at,
        )
        if not 1 <= limit <= 50:
            raise ValueError("candidate limit is invalid")
        state = self._orchestration.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        industry, concept = self._load_market_snapshots(
            state,
            task_id=task_id,
            attempt=attempt,
            market_artifact_ids=market_artifact_ids,
        )
        fingerprint = self._fingerprint(
            market_artifact_ids=market_artifact_ids,
            news_artifact_id=None,
            limit=limit,
            stage=CandidateRankingStage.MARKET,
        )
        batch = CandidateBatch(
            batch_id=uuid5(NAMESPACE_URL, f"candidate-batch:{run_id}:{fingerprint}"),
            run_id=run_id,
            input_fingerprint=fingerprint,
            ranking_stage=CandidateRankingStage.MARKET,
            candidate_limit=limit,
            created_at=observed_at,
            candidates=select_market_precandidates(industry, concept, limit),
        )
        return self._persist(
            batch,
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            observed_at=observed_at,
        )

    def rank_news_enriched(
        self,
        *,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        market_artifact_ids: tuple[UUID, ...],
        news_artifact_id: UUID,
        limit: int,
        now: datetime | None = None,
    ) -> CandidateBatch:
        observed_at = now or datetime.now(UTC)
        run_id = self._committer.run_id
        require_live_task_owner(
            self._orchestration,
            run_id,
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            now=observed_at,
        )
        if not 1 <= limit <= 50:
            raise ValueError("candidate limit is invalid")
        if self._news_batches is None or self._news is None:
            raise RuntimeError("news ranking repositories are unavailable")
        state = self._orchestration.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        industry, concept = self._load_market_snapshots(
            state,
            task_id=task_id,
            attempt=attempt,
            market_artifact_ids=market_artifact_ids,
        )
        artifact = next(
            (item for item in state.artifacts if item.artifact_id == news_artifact_id),
            None,
        )
        if (
            artifact is None
            or artifact.kind != "news_batch"
            or artifact.task_id != task_id
            or artifact.attempt != attempt
        ):
            raise ValueError("news artifact is outside current task")
        prefix = "news-batch:"
        if not artifact.reference.startswith(prefix):
            raise ValueError("news artifact reference is invalid")
        news_batch = self._news_batches.get(UUID(artifact.reference[len(prefix) :]))
        if news_batch is None or news_batch.run_id != run_id:
            raise KeyError("news batch is unavailable")
        events = self._news.get_events(news_batch.event_ids)
        if {item.event_id for item in events} != set(news_batch.event_ids):
            raise KeyError("news batch events are unavailable")
        fingerprint = self._fingerprint(
            market_artifact_ids=market_artifact_ids,
            news_artifact_id=news_artifact_id,
            limit=limit,
            stage=CandidateRankingStage.NEWS_ENRICHED,
        )
        batch = CandidateBatch(
            batch_id=uuid5(NAMESPACE_URL, f"candidate-batch:{run_id}:{fingerprint}"),
            run_id=run_id,
            input_fingerprint=fingerprint,
            ranking_stage=CandidateRankingStage.NEWS_ENRICHED,
            candidate_limit=limit,
            created_at=observed_at,
            candidates=select_candidates(industry, concept, events, limit),
        )
        return self._persist(
            batch,
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            observed_at=observed_at,
        )

    @staticmethod
    def _fingerprint(
        *,
        market_artifact_ids: tuple[UUID, ...],
        news_artifact_id: UUID | None,
        limit: int,
        stage: CandidateRankingStage,
    ) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "market_artifact_ids": sorted(
                        str(value) for value in market_artifact_ids
                    ),
                    "news_artifact_id": (
                        str(news_artifact_id) if news_artifact_id is not None else None
                    ),
                    "limit": limit,
                    "stage": stage.value,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
