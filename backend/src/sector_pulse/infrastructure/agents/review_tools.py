"""Bounded aidynamic-agent tools for deterministic and independent review."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from aidynamic_agent.tools.base import Tool, ToolResult

from sector_pulse.application.orchestration.editorial_context import BoundReviewContext
from sector_pulse.application.orchestration.review_tools import (
    CheckDraftRulesService,
    SubmitReviewService,
)
from sector_pulse.domain.writing.editorial import (
    DraftRulesArtifact,
    IndependentReviewArtifact,
    ReviewSubmission,
)
from sector_pulse.storage.ports.writing import (
    DraftRulesRepositoryPort,
    IndependentReviewRepositoryPort,
)


class CheckDraftRulesTool(Tool):
    name = "check_draft_rules"
    description = "Run server-owned deterministic checks for the pinned draft version."
    tags = ["A4", "deterministic", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {"draft_artifact_id": {"type": "string", "format": "uuid"}},
        "required": ["draft_artifact_id"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: CheckDraftRulesService,
        *,
        rules: DraftRulesRepositoryPort,
        context: BoundReviewContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._rules = rules
        self._context = context
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"draft_artifact_id"}:
            raise ValueError("draft version and rule results are server controlled")
        identity = kwargs["draft_artifact_id"]
        if not isinstance(identity, str):
            raise ValueError("draft artifact identity must be a UUID string")
        try:
            result = self._service.check(
                context=self._context,
                draft_artifact_id=UUID(identity),
                now=self._clock(),
            )
        except (KeyError, ValueError):
            return ToolResult(content="", success=False, error="DRAFT_RULE_CHECK_INVALID")
        return self._result(result)

    def replay(self, reference: str) -> ToolResult:
        prefix = "draft-rules:"
        if not reference.startswith(prefix):
            raise ValueError("invalid draft rules reference")
        result = self._rules.get(UUID(reference[len(prefix) :]))
        if result is None:
            raise KeyError("persisted draft rules are unavailable")
        return self._result(result)

    @staticmethod
    def _result(result: DraftRulesArtifact) -> ToolResult:
        return ToolResult(
            content=json.dumps(
                {
                    "artifact_refs": [str(result.artifact_id)],
                    "draft_id": str(result.report.draft_id),
                    "draft_version": result.report.draft_version,
                    "quality_issue_count": len(result.report.quality_issues),
                    "governance_status": result.report.governance.status,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            metadata={"result_reference": f"draft-rules:{result.artifact_id}"},
        )


class SubmitReviewTool(Tool):
    name = "submit_review"
    description = "Submit an independent review of the exact pinned draft and rules report."
    tags = ["A4", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "draft_artifact_id": {"type": "string", "format": "uuid"},
            "rules_artifact_id": {"type": "string", "format": "uuid"},
            "submission": {"type": "object"},
        },
        "required": ["draft_artifact_id", "rules_artifact_id", "submission"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: SubmitReviewService,
        *,
        reviews: IndependentReviewRepositoryPort,
        context: BoundReviewContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._reviews = reviews
        self._context = context
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        required = {"draft_artifact_id", "rules_artifact_id", "submission"}
        if set(kwargs) != required:
            raise ValueError("review identity and draft version are server controlled")
        draft_id = kwargs["draft_artifact_id"]
        rules_id = kwargs["rules_artifact_id"]
        submission = kwargs["submission"]
        if not isinstance(draft_id, str) or not isinstance(rules_id, str):
            raise ValueError("review artifact identities must be UUID strings")
        if not isinstance(submission, dict):
            raise ValueError("review submission must be an object")
        try:
            result = self._service.submit(
                context=self._context,
                draft_artifact_id=UUID(draft_id),
                rules_artifact_id=UUID(rules_id),
                submission=ReviewSubmission.model_validate(submission),
                now=self._clock(),
            )
        except (KeyError, ValueError):
            return ToolResult(content="", success=False, error="REVIEW_SUBMISSION_INVALID")
        return self._result(result)

    def replay(self, reference: str) -> ToolResult:
        prefix = "independent-review:"
        if not reference.startswith(prefix):
            raise ValueError("invalid independent review reference")
        result = self._reviews.get(UUID(reference[len(prefix) :]))
        if result is None:
            raise KeyError("persisted independent review is unavailable")
        return self._result(result)

    @staticmethod
    def _result(result: IndependentReviewArtifact) -> ToolResult:
        return ToolResult(
            content=json.dumps(
                {
                    "artifact_refs": [str(result.artifact_id)],
                    "draft_id": result.report.draft_id,
                    "draft_version": result.report.draft_version,
                    "decision": result.report.decision.value,
                    "issue_count": len(result.report.issues),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            metadata={
                "result_reference": f"independent-review:{result.artifact_id}"
            },
        )


__all__ = ["CheckDraftRulesTool", "SubmitReviewTool"]
