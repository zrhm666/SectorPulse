import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from aidynamic_agent.tools.base import Tool, ToolResult

from sector_pulse.application.orchestration.editorial_context import (
    BoundEditorialContext,
    BoundRevisionContext,
)
from sector_pulse.application.orchestration.editorial_tools import (
    SubmitDraftService,
    SubmitOutlineService,
    SubmitRevisionService,
)
from sector_pulse.application.writing.revision_agent import RevisionChanges
from sector_pulse.domain.writing.editorial import (
    ArticleDraftSubmission,
    ArticleOutlineSubmission,
    EditorialDraftArtifact,
    EditorialOutlineArtifact,
)
from sector_pulse.storage.ports.writing import (
    EditorialDraftRepositoryPort,
    EditorialOutlineRepositoryPort,
)


class SubmitOutlineTool(Tool):
    name = "submit_outline"
    description = "Validate and persist an outline for the server-bound editorial context."
    tags = ["A3", "deterministic", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {"submission": ArticleOutlineSubmission.model_json_schema()},
        "required": ["submission"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: SubmitOutlineService,
        *,
        outlines: EditorialOutlineRepositoryPort,
        context: BoundEditorialContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._outlines = outlines
        self._context = context
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"submission"}:
            raise ValueError("run, task, selection and identity are server controlled")
        payload = kwargs["submission"]
        if not isinstance(payload, dict):
            raise ValueError("outline submission must be an object")
        try:
            outline = self._service.submit(
                context=self._context,
                submission=ArticleOutlineSubmission.model_validate(payload),
                now=self._clock(),
            )
        except (KeyError, ValueError) as exc:
            return ToolResult(
                content=f"OUTLINE_SUBMISSION_INVALID: {str(exc)[:500]}",
                success=False,
                error="OUTLINE_SUBMISSION_INVALID",
            )
        return self._result(outline)

    def replay(self, reference: str) -> ToolResult:
        prefix = "article-outline:"
        if not reference.startswith(prefix):
            raise ValueError("invalid article outline reference")
        outline = self._outlines.get(UUID(reference[len(prefix) :]))
        if outline is None:
            raise KeyError("persisted article outline is unavailable")
        return self._result(outline)

    @staticmethod
    def _result(outline: EditorialOutlineArtifact) -> ToolResult:
        return ToolResult(
            content=json.dumps(
                {
                    "artifact_refs": [str(outline.outline_id)],
                    "sector_ids": outline.outline.sector_ids,
                    "title_directions": outline.outline.title_directions,
                    "thesis": outline.outline.thesis,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            metadata={"result_reference": f"article-outline:{outline.outline_id}"},
        )


class SubmitDraftTool(Tool):
    name = "submit_draft"
    description = "Validate and persist a draft for one authorized outline."
    tags = ["A3", "deterministic", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "outline_artifact_id": {"type": "string", "format": "uuid"},
            "submission": ArticleDraftSubmission.model_json_schema(),
        },
        "required": ["outline_artifact_id", "submission"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: SubmitDraftService,
        *,
        drafts: EditorialDraftRepositoryPort,
        context: BoundEditorialContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._drafts = drafts
        self._context = context
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"outline_artifact_id", "submission"}:
            raise ValueError("draft identity, version, status and sources are server controlled")
        identity = kwargs["outline_artifact_id"]
        payload = kwargs["submission"]
        if not isinstance(identity, str) or not isinstance(payload, dict):
            raise ValueError("invalid draft submission")
        try:
            draft = self._service.submit(
                context=self._context,
                outline_artifact_id=UUID(identity),
                submission=ArticleDraftSubmission.model_validate(payload),
                now=self._clock(),
            )
        except (KeyError, ValueError) as exc:
            return ToolResult(
                content=f"DRAFT_SUBMISSION_INVALID: {str(exc)[:500]}",
                success=False,
                error="DRAFT_SUBMISSION_INVALID",
            )
        return self._draft_result(draft)

    def replay(self, reference: str) -> ToolResult:
        prefix = "article-draft:"
        if not reference.startswith(prefix):
            raise ValueError("invalid article draft reference")
        draft = self._drafts.get(UUID(reference[len(prefix) :]))
        if draft is None:
            raise KeyError("persisted article draft is unavailable")
        return self._draft_result(draft)

    @staticmethod
    def _draft_result(draft: EditorialDraftArtifact) -> ToolResult:
        return ToolResult(
            content=json.dumps(
                {
                    "artifact_refs": [str(draft.artifact_id)],
                    "draft_id": str(draft.draft.draft_id),
                    "version": draft.draft.version,
                    "status": draft.draft.status.value.lower(),
                    "section_ids": [item.section_id for item in draft.draft.sections],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            metadata={"result_reference": f"article-draft:{draft.artifact_id}"},
        )


class SubmitRevisionTool(Tool):
    name = "submit_revision"
    description = "Persist one scope-limited revision of the exact reviewed draft."
    tags = ["A3", "deterministic", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "base_draft_artifact_id": {"type": "string", "format": "uuid"},
            "review_artifact_id": {"type": "string", "format": "uuid"},
            "changes": {"type": "object"},
        },
        "required": ["base_draft_artifact_id", "review_artifact_id", "changes"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        service: SubmitRevisionService,
        *,
        drafts: EditorialDraftRepositoryPort,
        context: BoundRevisionContext,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._drafts = drafts
        self._context = context
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, **kwargs: object) -> ToolResult:
        required = {"base_draft_artifact_id", "review_artifact_id", "changes"}
        if set(kwargs) != required:
            raise ValueError("revision version, round, identity and status are server controlled")
        base_id = kwargs["base_draft_artifact_id"]
        review_id = kwargs["review_artifact_id"]
        changes = kwargs["changes"]
        if not isinstance(base_id, str) or not isinstance(review_id, str):
            raise ValueError("revision artifact identities must be UUID strings")
        if not isinstance(changes, dict):
            raise ValueError("revision changes must be an object")
        try:
            result = self._service.submit(
                context=self._context,
                base_draft_artifact_id=UUID(base_id),
                review_artifact_id=UUID(review_id),
                changes=RevisionChanges.model_validate(changes),
                now=self._clock(),
            )
        except (KeyError, ValueError):
            return ToolResult(content="", success=False, error="REVISION_SUBMISSION_INVALID")
        return SubmitDraftTool._draft_result(result)

    def replay(self, reference: str) -> ToolResult:
        prefix = "article-draft:"
        if not reference.startswith(prefix):
            raise ValueError("invalid revised draft reference")
        result = self._drafts.get(UUID(reference[len(prefix) :]))
        if result is None:
            raise KeyError("persisted revised draft is unavailable")
        return SubmitDraftTool._draft_result(result)


__all__ = ["SubmitDraftTool", "SubmitOutlineTool", "SubmitRevisionTool"]
