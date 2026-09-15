"""Framework adapters for A1 deterministic data services."""

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from aidynamic_agent.tools.base import Tool, ToolResult

from sector_pulse.application.orchestration.data_tools import (
    CollectMarketService,
    InspectDataQualityService,
    MarketCollectionContext,
    MarketCollectionRequest,
    MarketCollectionResult,
    MarketQualityPersistence,
    require_live_task_owner,
)
from sector_pulse.domain.market.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.storage.ports.market import MarketSnapshotRepositoryPort


class CollectMarketTool(Tool):
    name = "collect_market"
    description = "Collect only approved industry or concept market-data gaps."
    tags = ["A1", "server_bound", "external_data"]
    parameters = {
        "type": "object",
        "properties": {
            "kinds": {
                "type": "array",
                "items": {"type": "string", "enum": ["INDUSTRY", "CONCEPT"]},
                "minItems": 1,
                "maxItems": 2,
                "uniqueItems": True,
            }
        },
        "required": ["kinds"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: CollectMarketService,
        *,
        context: MarketCollectionContext,
        snapshots: MarketSnapshotRepositoryPort,
        clock: Callable[[], datetime] | None = None,
        max_core_skew_seconds: int = 60,
    ) -> None:
        super().__init__()
        self._service = service
        self._context = context
        self._snapshots = snapshots
        self._clock = clock or (lambda: datetime.now(UTC))
        if max_core_skew_seconds < 0:
            raise ValueError("max core skew must be non-negative")
        self._max_core_skew_seconds = max_core_skew_seconds

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"kinds"}:
            raise ValueError("run and provider identity are server controlled")
        raw_kinds = kwargs["kinds"]
        if not isinstance(raw_kinds, list) or not all(
            isinstance(item, str) for item in raw_kinds
        ):
            raise ValueError("kinds must be a list of approved market kinds")
        try:
            request = MarketCollectionRequest(
                kinds=tuple(SectorKind(item) for item in raw_kinds)
            )
        except (ValueError, TypeError) as exc:
            raise ValueError("MARKET_KINDS_INVALID") from exc
        now = self._clock()
        result: MarketCollectionResult
        if self._context.run.run_cutoff_at is None:
            if set(request.kinds) != {SectorKind.INDUSTRY, SectorKind.CONCEPT}:
                raise ValueError("initial market collection requires both core kinds")
            result = await self._service.collect_core_and_persist(
                context=self._context,
                locked_at=now,
                max_skew_seconds=self._max_core_skew_seconds,
            )
        else:
            if len(request.kinds) != 1:
                raise ValueError("one market kind is allowed per supplemental call")
            result = await self._service.collect_and_persist(
                request,
                context=self._context,
                now=now,
            )
        references = self._artifact_ids(result.results)
        content = self._content(
            {
                kind: item.data
                for kind, item in result.results.items()
                if item.data is not None
            },
            references,
        )
        if len(references) != len(result.results):
            return ToolResult(
                content=content,
                success=False,
                error="MARKET_SOURCE_UNAVAILABLE",
            )
        return ToolResult(
            content=content,
            metadata={
                "result_reference": (
                    f"market-result:{self._context.run.run_id}:{','.join(references)}"
                )
            },
        )

    def replay(self, reference: str) -> ToolResult:
        parts = reference.split(":", 2)
        if len(parts) != 3 or parts[0] != "market-result":
            raise ValueError("invalid market result reference")
        run_id = UUID(parts[1])
        if run_id != self._context.run.run_id:
            raise ValueError("market result belongs to another run")
        artifact_ids = tuple(UUID(item) for item in parts[2].split(",") if item)
        state = self._context.orchestration.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        by_id = {artifact.artifact_id: artifact for artifact in state.artifacts}
        snapshots: dict[SectorKind, SectorUniverseSnapshot] = {}
        for artifact_id in artifact_ids:
            artifact = by_id.get(artifact_id)
            if artifact is None or artifact.kind != "market_snapshot":
                raise KeyError("persisted market result is unavailable")
            ref_parts = artifact.reference.split(":", 3)
            if len(ref_parts) != 4 or UUID(ref_parts[1]) != run_id:
                raise ValueError("invalid persisted market reference")
            kind = SectorKind(ref_parts[2])
            snapshot = self._snapshots.get(run_id, kind)
            if snapshot is None or snapshot.source_version != ref_parts[3]:
                raise KeyError("persisted market result is unavailable")
            snapshots[kind] = snapshot
        return ToolResult(
            content=self._content(
                snapshots,
                tuple(str(artifact_id) for artifact_id in artifact_ids),
            )
        )

    def _artifact_ids(
        self,
        results: Mapping[SectorKind, ProviderResult[SectorUniverseSnapshot]],
    ) -> tuple[str, ...]:
        expected = {
            f"market:{self._context.run.run_id}:{kind.value}:{result.data.source_version}"
            for kind, result in results.items()
            if result.data is not None
        }
        state = self._context.orchestration.load(self._context.run.run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        return tuple(
            str(artifact.artifact_id)
            for artifact in state.artifacts
            if artifact.task_id == self._context.task_id
            and artifact.attempt == self._context.attempt
            and artifact.reference in expected
        )

    @staticmethod
    def _content(
        snapshots: dict[SectorKind, SectorUniverseSnapshot],
        references: tuple[str, ...],
    ) -> str:
        return json.dumps(
            {
                "status": "success" if snapshots else "failed",
                "artifact_refs": references,
                "summary": {
                    kind.value: {
                        "sector_count": snapshot.sector_count,
                        "available_fields": sorted(snapshot.available_fields),
                        "source_version": snapshot.source_version,
                    }
                    for kind, snapshot in snapshots.items()
                },
                "safe_error_code": None if snapshots else "MARKET_SOURCE_UNAVAILABLE",
            },
            ensure_ascii=False,
            sort_keys=True,
        )


class InspectDataQualityTool(Tool):
    name = "inspect_data_quality"
    description = "Read the server-computed quality report for a persisted market snapshot."
    tags = ["A1", "read_only", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {"artifact_ref": {"type": "string", "format": "uuid"}},
        "required": ["artifact_ref"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: InspectDataQualityService,
        *,
        context: MarketCollectionContext,
        snapshots: MarketSnapshotRepositoryPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._context = context
        self._snapshots = snapshots
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"artifact_ref"} or not isinstance(
            kwargs.get("artifact_ref"), str
        ):
            raise ValueError("quality thresholds and run identity are server controlled")
        artifact_id = UUID(str(kwargs["artifact_ref"]))
        return self._read(artifact_id)

    def replay(self, reference: str) -> ToolResult:
        prefix = "quality:"
        if not reference.startswith(prefix):
            raise ValueError("invalid quality result reference")
        return self._read(UUID(reference[len(prefix) :]))

    def _read(self, artifact_id: UUID) -> ToolResult:
        context = self._context
        require_live_task_owner(
            context.orchestration,
            context.run.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=self._clock(),
        )
        state = context.orchestration.load(context.run.run_id)
        if state is None:  # Ownership validation already guards this.
            raise KeyError("orchestration run not found")
        caller = next(item for item in state.tasks if item.task_id == context.task_id)
        artifact = next(
            (item for item in state.artifacts if item.artifact_id == artifact_id), None
        )
        if artifact is None or artifact.kind != "market_snapshot":
            raise KeyError("market snapshot artifact not found")
        source_task = next(
            (item for item in state.tasks if item.task_id == artifact.task_id), None
        )
        if source_task is None or source_task.attempt != artifact.attempt:
            raise ValueError("market snapshot artifact is stale")
        if caller.role != "A0" and artifact.task_id != caller.task_id:
            raise ValueError("market snapshot artifact is outside task scope")
        parts = artifact.reference.split(":", 3)
        if (
            len(parts) != 4
            or parts[0] != "market"
            or UUID(parts[1]) != context.run.run_id
        ):
            raise ValueError("invalid market snapshot reference")
        kind = SectorKind(parts[2])
        snapshot = self._snapshots.get(context.run.run_id, kind)
        if snapshot is None or snapshot.source_version != parts[3]:
            raise KeyError("persisted market snapshot is unavailable")
        report = self._service.inspect(
            ProviderResult(
                provider_id=snapshot.provider_id,
                capability="market.sector_universe",
                status=DataStatus.SUCCESS,
                data=snapshot,
                observed_at=snapshot.observed_at,
                collected_at=snapshot.collected_at,
                source_version=snapshot.source_version,
            )
        )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "source_artifact_id": str(artifact_id),
                    "thresholds": self._service.thresholds.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        report_id = uuid5(
            NAMESPACE_URL,
            f"market-quality:{context.run.run_id}:{fingerprint}",
        )
        context.committer.commit(
            ArtifactRef(
                artifact_id=uuid5(
                    NAMESPACE_URL,
                    f"market-quality-artifact:{report_id}:{context.task_id}:{context.attempt}",
                ),
                task_id=context.task_id,
                attempt=context.attempt,
                kind="data_quality",
                reference=f"market-quality:{report_id}",
            ),
            worker_id=context.worker_id,
            persistence=MarketQualityPersistence(
                report_id=report_id,
                run_id=context.run.run_id,
                source_artifact_id=artifact_id,
                input_fingerprint=fingerprint,
                report=report,
                created_at=self._clock(),
            ),
            now=self._clock(),
        )
        return ToolResult(
            content=json.dumps(
                {
                    "status": report.status.value,
                    "sector_count": report.sector_count,
                    "issues": report.issues,
                    "artifact_ref": str(artifact.artifact_id),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            metadata={"result_reference": f"quality:{artifact.artifact_id}"},
        )
