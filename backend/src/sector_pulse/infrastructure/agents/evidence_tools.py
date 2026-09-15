"""aidynamic-agent adapters for programmatic evidence inspection."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from aidynamic_agent.tools.base import Tool, ToolResult

from sector_pulse.application.orchestration.evidence_tools import (
    InspectSectorEvidenceService,
    SubmitSectorAnalysisService,
    evidence_inspection_artifact_id,
    sector_analysis_artifact_id,
)
from sector_pulse.application.orchestration.research_context import BoundSectorResearchContext
from sector_pulse.application.writing.agent_validation import AgentOutputViolation
from sector_pulse.domain.writing.research import (
    EvidenceInspectionReport,
    SectorAnalysisArtifact,
    SectorAnalysisSubmission,
)
from sector_pulse.storage.ports.writing import (
    EvidenceInspectionRepositoryPort,
    SectorAnalysisRepositoryPort,
)


class InspectEvidenceTool(Tool):
    name = "inspect_evidence"
    description = "Apply deterministic evidence and attribution gates to authorized artifacts."
    tags = ["A2", "deterministic", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "artifact_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "minItems": 1,
                "uniqueItems": True,
            }
        },
        "required": ["artifact_ids"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: InspectSectorEvidenceService,
        *,
        reports: EvidenceInspectionRepositoryPort,
        context: BoundSectorResearchContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._reports = reports
        self._context = context
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"artifact_ids"}:
            raise ValueError("scope, identity and gate inputs are server controlled")
        values = kwargs["artifact_ids"]
        if not isinstance(values, list) or not values:
            raise ValueError("artifact_ids must be a non-empty list")
        artifact_ids = tuple(UUID(item) for item in values if isinstance(item, str))
        if len(artifact_ids) != len(values):
            raise ValueError("artifact_ids must contain UUID strings")
        report = self._service.inspect(
            context=self._context,
            artifact_ids=artifact_ids,
            now=self._clock(),
        )
        return self._result(report)

    def replay(self, reference: str) -> ToolResult:
        prefix = "evidence-inspection:"
        if not reference.startswith(prefix):
            raise ValueError("invalid evidence inspection reference")
        report = self._reports.get(UUID(reference[len(prefix) :]))
        if report is None:
            raise KeyError("persisted evidence inspection is unavailable")
        return self._result(report)

    @staticmethod
    def _result(report: EvidenceInspectionReport) -> ToolResult:
        return ToolResult(
            content=json.dumps(
                {
                    "artifact_refs": [str(evidence_inspection_artifact_id(report))],
                    "sector_id": report.sector_id,
                    "allowed_max_level": report.gate.allowed_max_level.value.lower(),
                    "gate_reasons": report.gate.reasons,
                    "eligible_evidence_ids": report.gate.eligible_evidence_ids,
                    "excluded_evidence_ids": report.gate.excluded_evidence_ids,
                    "counter_evidence": report.gate.counter_evidence,
                    "document_ids": [item.document_id for item in report.document_views],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            metadata={
                "result_reference": f"evidence-inspection:{report.report_id}"
            },
        )


class SubmitAnalysisTool(Tool):
    name = "submit_analysis"
    description = "Validate and persist one sector analysis against an inspection report."
    tags = ["A2", "deterministic", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "inspection_artifact_id": {"type": "string", "format": "uuid"},
            "submission": {"type": "object"},
        },
        "required": ["inspection_artifact_id", "submission"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: SubmitSectorAnalysisService,
        *,
        analyses: SectorAnalysisRepositoryPort,
        context: BoundSectorResearchContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._analyses = analyses
        self._context = context
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"inspection_artifact_id", "submission"}:
            raise ValueError("run, task, scope, identity and gate are server controlled")
        identity = kwargs["inspection_artifact_id"]
        payload = kwargs["submission"]
        if not isinstance(identity, str) or not isinstance(payload, dict):
            raise ValueError("invalid analysis submission")
        try:
            analysis = self._service.submit(
                context=self._context,
                inspection_artifact_id=UUID(identity),
                submission=SectorAnalysisSubmission.model_validate(payload),
                now=self._clock(),
            )
        except AgentOutputViolation as exc:
            return ToolResult(
                content="",
                success=False,
                error=exc.code,
                metadata={"validation_location": exc.location},
            )
        except (KeyError, ValueError):
            return ToolResult(
                content="",
                success=False,
                error="ANALYSIS_SUBMISSION_INVALID",
            )
        return self._result(analysis)

    def replay(self, reference: str) -> ToolResult:
        prefix = "sector-analysis:"
        if not reference.startswith(prefix):
            raise ValueError("invalid sector analysis reference")
        analysis = self._analyses.get(UUID(reference[len(prefix) :]))
        if analysis is None:
            raise KeyError("persisted sector analysis is unavailable")
        return self._result(analysis)

    @staticmethod
    def _result(analysis: SectorAnalysisArtifact) -> ToolResult:
        return ToolResult(
            content=json.dumps(
                {
                    "artifact_refs": [str(sector_analysis_artifact_id(analysis))],
                    "sector_id": analysis.card.sector_id,
                    "attribution_level": analysis.card.attribution_level.value.lower(),
                    "confidence": str(analysis.card.confidence),
                    "supporting_evidence_ids": analysis.card.supporting_evidence_ids,
                    "claim_ids": [claim.claim_id for claim in analysis.card.claims],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            metadata={"result_reference": f"sector-analysis:{analysis.analysis_id}"},
        )
__all__ = ["InspectEvidenceTool", "SubmitAnalysisTool"]
