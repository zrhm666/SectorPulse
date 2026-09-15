import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_t09_submission_uses_server_identity_and_rejects_ineligible_evidence():
    from sector_pulse.application.orchestration.evidence_tools import SubmitSectorAnalysisService
    from sector_pulse.application.orchestration.research_context import (
        BoundSectorResearchContext,
    )
    from sector_pulse.application.orchestration.tasks import TaskOwnershipError
    from sector_pulse.application.writing.agent_validation import AgentOutputViolation
    from sector_pulse.domain.market.market import SectorKind
    from sector_pulse.domain.news.evidence import EvidenceLevel
    from sector_pulse.domain.news.news import SourceGrade
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.domain.writing.attribution import (
        AttributionContext,
        AttributionGateResult,
        Claim,
        ClaimKind,
    )
    from sector_pulse.domain.writing.research import (
        EvidenceInspectionReport,
        SectorAnalysisSubmission,
    )
    from sector_pulse.infrastructure.agents.evidence_tools import SubmitAnalysisTool

    now = datetime(2026, 9, 14, 6, 0, tzinfo=UTC)
    run_id, root_id, task_id, report_id = uuid4(), uuid4(), uuid4(), uuid4()
    artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=task_id,
        attempt=1,
        kind="evidence_inspection",
        reference=f"evidence-inspection:{report_id}",
    )
    root = TaskRecord(task_id=root_id, role="A0", scope="run")
    task = TaskRecord(
        task_id=task_id,
        parent_id=root_id,
        role="A2",
        scope="sector:INDUSTRY:sector-1",
        status=TaskStatus.RUNNING,
        worker_id="research-worker",
        lease_expires_at=now + timedelta(minutes=5),
        selection_version=1,
    )
    state = RunSnapshot(
        run_id=run_id,
        deadline=now + timedelta(minutes=10),
        tasks=(root, task),
        artifacts=(artifact,),
    )
    evidence_context = AttributionContext(
        run_id=run_id,
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        sector_name="文化传媒",
        cutoff_at=now,
        market_facts={"pct_change": Decimal("2.5")},
        event_ids=("event-1", "background-1", "excluded-1"),
        eligible_event_ids=("event-1",),
        background_event_ids=("background-1",),
        excluded_event_ids=("excluded-1",),
        source_grades={"doc-1": SourceGrade.PRIMARY},
        counter_evidence=("alternative",),
    )
    gate = AttributionGateResult(
        run_id=run_id,
        sector_id="sector-1",
        allowed_max_level=EvidenceLevel.MARKET_ASSOCIATION,
        reasons=("EVENT_AFTER_MARKET_MOVE",),
        eligible_evidence_ids=("event-1",),
        excluded_evidence_ids=("excluded-1",),
        counter_evidence=("alternative",),
    )
    report = EvidenceInspectionReport(
        report_id=report_id,
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        sector_id="sector-1",
        selection_version=1,
        input_artifact_ids=(uuid4(),),
        input_fingerprint="a" * 64,
        context=evidence_context,
        gate=gate,
        document_views=(),
        created_at=now,
    )

    class Orchestration:
        def load(self, identity):
            return state if identity == run_id else None

    class Reports:
        def get(self, identity):
            return report if identity == report_id else None

    class Committer:
        committed = []

        def commit(self, item, **kwargs):
            self.committed.append(item)
            return item

    context = BoundSectorResearchContext(
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        worker_id="research-worker",
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        sector_name="文化传媒",
        selection_version=1,
        cutoff_at=now,
        input_artifacts=(),
    )
    service = SubmitSectorAnalysisService(
        orchestration=Orchestration(),
        committer=Committer(),
        inspections=Reports(),
    )
    invalid = SectorAnalysisSubmission(
        attribution_level=EvidenceLevel.MARKET_ASSOCIATION,
        confidence=Decimal("0.6"),
        conclusion="存在市场联想",
        supporting_evidence_ids=("excluded-1",),
        claims=(),
    )
    with pytest.raises(AgentOutputViolation) as error:
        service.submit(
            context=context,
            inspection_artifact_id=artifact.artifact_id,
            submission=invalid,
            now=now,
        )
    assert error.value.code == "INELIGIBLE_SUPPORTING_EVIDENCE"
    assert not Committer.committed

    with pytest.raises(ValueError, match="current scope"):
        service.submit(
            context=context.model_copy(update={"sector_id": "other-sector"}),
            inspection_artifact_id=artifact.artifact_id,
            submission=invalid,
            now=now,
        )
    with pytest.raises(TaskOwnershipError, match="stale"):
        service.submit(
            context=context.model_copy(update={"attempt": 2}),
            inspection_artifact_id=artifact.artifact_id,
            submission=invalid,
            now=now,
        )
    assert not Committer.committed

    valid = invalid.model_copy(
        update={
            "supporting_evidence_ids": ("event-1",),
            "claims": (
                Claim(
                    claim_id="claim-1",
                    kind=ClaimKind.NEWS_FACT,
                    text="已发布相关政策",
                    evidence_ids=("event-1",),
                ),
            ),
        }
    )
    result = service.submit(
        context=context,
        inspection_artifact_id=artifact.artifact_id,
        submission=valid,
        now=now,
    )
    assert result.card.run_id == run_id
    assert result.card.sector_name == "文化传媒"
    assert result.card.allowed_max_level is EvidenceLevel.MARKET_ASSOCIATION

    too_strong = valid.model_copy(
        update={"attribution_level": EvidenceLevel.EXPLICIT_DRIVER}
    )
    with pytest.raises(AgentOutputViolation) as error:
        service.submit(
            context=context,
            inspection_artifact_id=artifact.artifact_id,
            submission=too_strong,
            now=now,
        )
    assert error.value.code == "ATTRIBUTION_LEVEL_EXCEEDED"

    no_context = evidence_context.model_copy(
        update={"eligible_event_ids": (), "event_ids": (), "counter_evidence": ("alternative",)}
    )
    no_gate = gate.model_copy(
        update={
            "allowed_max_level": EvidenceLevel.NO_RELIABLE_EXPLANATION,
            "reasons": ("NO_ELIGIBLE_EVENT",),
            "eligible_evidence_ids": (),
        }
    )
    report = report.model_copy(update={"context": no_context, "gate": no_gate})
    no_explanation = SectorAnalysisSubmission(
        attribution_level=EvidenceLevel.NO_RELIABLE_EXPLANATION,
        confidence=Decimal("0.2"),
        conclusion="暂无可靠解释",
        uncertainties=("缺少合格事件",),
    )
    no_result = service.submit(
        context=context,
        inspection_artifact_id=artifact.artifact_id,
        submission=no_explanation,
        now=now,
    )
    assert not no_result.card.supporting_evidence_ids
    assert no_result.card.counter_evidence == ("alternative",)
    report = report.model_copy(update={"context": evidence_context, "gate": gate})

    class Analyses:
        def get(self, identity):
            return result if identity == result.analysis_id else None

    tool = SubmitAnalysisTool(
        service,
        analyses=Analyses(),
        context=context,
        clock=lambda: now,
    )
    assert set(tool.parameters["properties"]) == {
        "inspection_artifact_id",
        "submission",
    }
    tool_result = await tool.run(
        inspection_artifact_id=str(artifact.artifact_id),
        submission=valid.model_dump(mode="json"),
    )
    assert tool_result.success
    assert json.loads(tool_result.content)["artifact_refs"] == [
        str(Committer.committed[-1].artifact_id)
    ]
    assert tool_result.metadata["result_reference"] == f"sector-analysis:{result.analysis_id}"
    assert tool.replay(tool_result.metadata["result_reference"]).content == tool_result.content
    rejected = await tool.run(
        inspection_artifact_id=str(artifact.artifact_id),
        submission=invalid.model_dump(mode="json"),
    )
    assert not rejected.success
    assert rejected.error == "INELIGIBLE_SUPPORTING_EVIDENCE"
    forged_counter = valid.model_dump(mode="json")
    forged_counter["counter_evidence"] = ["model-overwrite"]
    rejected_counter = await tool.run(
        inspection_artifact_id=str(artifact.artifact_id),
        submission=forged_counter,
    )
    assert not rejected_counter.success
    assert rejected_counter.error == "ANALYSIS_SUBMISSION_INVALID"
    injected = await tool.run(
        inspection_artifact_id=str(artifact.artifact_id),
        submission=valid.model_dump(mode="json"),
        run_id=str(run_id),
    )
    assert not injected.success
    assert "server controlled" in (injected.error or "")
