"""Server-bound deterministic checks and independent review persistence."""

import hashlib
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.data_tools import require_live_task_owner
from sector_pulse.application.orchestration.editorial_context import BoundReviewContext
from sector_pulse.application.review.governance_service import GovernanceService
from sector_pulse.application.writing.draft_quality import draft_quality_issues
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.domain.review.review import (
    IssueSeverity,
    ReviewDecision,
    ReviewIssue,
    ReviewReport,
)
from sector_pulse.domain.writing.editorial import (
    DraftRulesArtifact,
    DraftRulesReport,
    IndependentReviewArtifact,
    ReviewSubmission,
)
from sector_pulse.ports.orchestration import SnapshotRepository, TransactionSession
from sector_pulse.storage.ports.writing import DraftRulesRepositoryPort


class DraftRulesPersistence:
    def __init__(self, result: DraftRulesArtifact) -> None:
        self.result = result

    def write(self, session: TransactionSession, artifact: object) -> None:
        del artifact
        item = self.result
        session.execute(
            "INSERT INTO draft_rules_artifacts (artifact_id, run_id, task_id, attempt, "
            "draft_artifact_id, draft_id, draft_version, input_fingerprint, payload_json, "
            "created_at) VALUES (:artifact_id, :run_id, :task_id, :attempt, "
            ":draft_artifact_id, :draft_id, :draft_version, :input_fingerprint, "
            ":payload_json, :created_at)",
            {
                "artifact_id": str(item.artifact_id),
                "run_id": str(item.run_id),
                "task_id": str(item.task_id),
                "attempt": item.attempt,
                "draft_artifact_id": str(item.draft_artifact_id),
                "draft_id": str(item.report.draft_id),
                "draft_version": item.report.draft_version,
                "input_fingerprint": item.input_fingerprint,
                "payload_json": item.model_dump_json(),
                "created_at": item.created_at.isoformat(),
            },
        )

    def exists(self, session: TransactionSession, artifact: object) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM draft_rules_artifacts WHERE artifact_id=:artifact_id",
                {"artifact_id": str(self.result.artifact_id)},
            )
        )


class CheckDraftRulesService:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
        governance: GovernanceService,
    ) -> None:
        self._orchestration = orchestration
        self._committer = committer
        self._governance = governance

    def check(
        self,
        *,
        context: BoundReviewContext,
        draft_artifact_id: UUID,
        now: datetime | None = None,
    ) -> DraftRulesArtifact:
        created_at = now or datetime.now(UTC)
        require_live_task_owner(
            self._orchestration,
            context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=created_at,
        )
        if context.role != "A4" or draft_artifact_id != context.draft.artifact_id:
            raise ValueError("draft artifact is not bound to this review context")
        cards = {item.card.sector_id: item.card for item in context.analyses}
        quality = draft_quality_issues(context.draft.draft, cards)
        governance = self._governance.check(context.draft.draft)
        report = DraftRulesReport(
            draft_id=context.draft.draft.draft_id,
            draft_version=context.draft.draft.version,
            quality_issues=quality,
            governance=governance,
        )
        fingerprint = hashlib.sha256(
            (
                f"{draft_artifact_id}:{context.draft.draft_hash}:"
                f"{report.model_dump_json()}"
            ).encode()
        ).hexdigest()
        artifact_id = uuid5(NAMESPACE_URL, f"draft-rules:{fingerprint}")
        result = DraftRulesArtifact(
            artifact_id=artifact_id,
            run_id=context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            draft_artifact_id=draft_artifact_id,
            input_fingerprint=fingerprint,
            report=report,
            created_at=created_at,
        )
        self._committer.commit(
            ArtifactRef(
                artifact_id=artifact_id,
                task_id=context.task_id,
                attempt=context.attempt,
                kind="draft_rules",
                reference=f"draft-rules:{artifact_id}",
            ),
            worker_id=context.worker_id,
            persistence=DraftRulesPersistence(result),
            now=created_at,
        )
        return result


class IndependentReviewPersistence:
    def __init__(self, result: IndependentReviewArtifact) -> None:
        self.result = result

    def write(self, session: TransactionSession, artifact: object) -> None:
        del artifact
        item = self.result
        session.execute(
            "INSERT INTO independent_review_artifacts (artifact_id, run_id, task_id, "
            "attempt, draft_artifact_id, rules_artifact_id, draft_id, draft_version, "
            "decision, input_fingerprint, payload_json, created_at) VALUES "
            "(:artifact_id, :run_id, :task_id, :attempt, :draft_artifact_id, "
            ":rules_artifact_id, :draft_id, :draft_version, :decision, "
            ":input_fingerprint, :payload_json, :created_at)",
            {
                "artifact_id": str(item.artifact_id),
                "run_id": str(item.run_id),
                "task_id": str(item.task_id),
                "attempt": item.attempt,
                "draft_artifact_id": str(item.draft_artifact_id),
                "rules_artifact_id": str(item.rules_artifact_id),
                "draft_id": item.report.draft_id,
                "draft_version": item.report.draft_version,
                "decision": item.report.decision.value,
                "input_fingerprint": item.input_fingerprint,
                "payload_json": item.model_dump_json(),
                "created_at": item.created_at.isoformat(),
            },
        )

    def exists(self, session: TransactionSession, artifact: object) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM independent_review_artifacts WHERE artifact_id=:artifact_id",
                {"artifact_id": str(self.result.artifact_id)},
            )
        )


class SubmitReviewService:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
        rules: DraftRulesRepositoryPort,
    ) -> None:
        self._orchestration = orchestration
        self._committer = committer
        self._rules = rules

    def submit(
        self,
        *,
        context: BoundReviewContext,
        draft_artifact_id: UUID,
        rules_artifact_id: UUID,
        submission: ReviewSubmission,
        now: datetime | None = None,
    ) -> IndependentReviewArtifact:
        created_at = now or datetime.now(UTC)
        submission = ReviewSubmission.model_validate(submission.model_dump())
        require_live_task_owner(
            self._orchestration,
            context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=created_at,
        )
        if context.role != "A4" or draft_artifact_id != context.draft.artifact_id:
            raise ValueError("draft artifact is not bound to this A4 context")
        state = self._orchestration.load(context.run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        if any(
            item.kind == "independent_review"
            and item.task_id == context.task_id
            and item.attempt == context.attempt
            for item in state.artifacts
        ):
            raise ValueError("this A4 attempt already submitted a review")
        rules_ref = next(
            (item for item in state.artifacts if item.artifact_id == rules_artifact_id),
            None,
        )
        if (
            rules_ref is None
            or rules_ref.kind != "draft_rules"
            or rules_ref.task_id != context.task_id
            or rules_ref.attempt != context.attempt
        ):
            raise ValueError("rules artifact is not authorized for this A4 attempt")
        rules = self._rules.get(rules_artifact_id)
        if (
            rules is None
            or rules.run_id != context.run_id
            or rules.task_id != context.task_id
            or rules.attempt != context.attempt
            or rules.draft_artifact_id != draft_artifact_id
            or rules.report.draft_id != context.draft.draft.draft_id
            or rules.report.draft_version != context.draft.draft.version
        ):
            raise ValueError("rules report does not match the pinned draft version")

        program_issues = list(rules.report.quality_issues)
        for index, governance_issue in enumerate(rules.report.governance.issues):
            program_issues.append(
                ReviewIssue(
                    issue_id=(
                        f"governance:{governance_issue.get('code', 'UNKNOWN')}:{index}"
                    ),
                    severity=IssueSeverity.BLOCKING,
                    code=governance_issue.get("code", "GOVERNANCE_FAILURE"),
                    message=governance_issue.get("message", "governance rule failed"),
                    suggested_fix=governance_issue.get(
                        "message", "resolve governance finding"
                    ),
                )
            )
        if rules.report.governance.status != "PASS" and not program_issues:
            program_issues.append(
                ReviewIssue(
                    issue_id="governance:FAILED:global",
                    severity=IssueSeverity.BLOCKING,
                    code="GOVERNANCE_FAILURE",
                    message="governance rules did not pass",
                )
            )
        if submission.decision is ReviewDecision.PASS and program_issues:
            raise ValueError("PASS cannot override program findings")
        if submission.decision is ReviewDecision.PASS and submission.issues:
            raise ValueError("PASS review cannot contain issues")

        sections = {item.section_id: item for item in context.draft.draft.sections}
        claims = {
            claim.claim_id: section.section_id
            for section in context.draft.draft.sections
            for claim in section.claims
        }
        for review_issue in submission.issues:
            if (
                review_issue.section_id is not None
                and review_issue.section_id not in sections
            ):
                raise ValueError("review issue references an unknown section")
            if review_issue.claim_id is not None and review_issue.claim_id not in claims:
                raise ValueError("review issue references an unknown claim")
            if (
                review_issue.claim_id is not None
                and review_issue.section_id is not None
                and claims[review_issue.claim_id] != review_issue.section_id
            ):
                raise ValueError("review issue claim is outside its section")
        combined = tuple(
            {item.issue_id: item for item in (*program_issues, *submission.issues)}.values()
        )
        if submission.decision is not ReviewDecision.PASS and not combined:
            raise ValueError("non-PASS review requires an actionable issue")
        canonical = ReviewSubmission(
            decision=submission.decision,
            issues=combined,
        ).model_dump_json()
        fingerprint = hashlib.sha256(
            f"{draft_artifact_id}:{rules_artifact_id}:{canonical}".encode()
        ).hexdigest()
        artifact_id = uuid5(NAMESPACE_URL, f"independent-review:{fingerprint}")
        report = ReviewReport(
            review_id=str(artifact_id),
            draft_id=str(context.draft.draft.draft_id),
            draft_version=context.draft.draft.version,
            decision=submission.decision,
            issues=combined,
            revision_round=max(0, context.draft.draft.version - 1),
        )
        result = IndependentReviewArtifact(
            artifact_id=artifact_id,
            run_id=context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            draft_artifact_id=draft_artifact_id,
            rules_artifact_id=rules_artifact_id,
            input_fingerprint=fingerprint,
            report=report,
            created_at=created_at,
        )
        self._committer.commit(
            ArtifactRef(
                artifact_id=artifact_id,
                task_id=context.task_id,
                attempt=context.attempt,
                kind="independent_review",
                reference=f"independent-review:{artifact_id}",
            ),
            worker_id=context.worker_id,
            persistence=IndependentReviewPersistence(result),
            now=created_at,
        )
        return result


__all__ = [
    "CheckDraftRulesService",
    "DraftRulesPersistence",
    "IndependentReviewPersistence",
    "SubmitReviewService",
]
