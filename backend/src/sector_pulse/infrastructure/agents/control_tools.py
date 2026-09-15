"""Framework adapters for server-bound orchestration control services."""

import json
from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from aidynamic_agent.tools.base import Tool, ToolResult

from sector_pulse.application.orchestration.controls import (
    ArtifactInspector,
    FinalizationController,
    SelectionController,
    TaskInspector,
)


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


class InspectArtifactsTool(Tool):
    name = "inspect_artifacts"
    description = "Read bounded, role-authorized artifacts from this run."
    tags = ["read_only", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "artifact_refs": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "maxItems": 20,
            },
            "kinds": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "maxItems": 20,
            },
            "max_chars": {"type": "integer", "minimum": 1, "maximum": 4000},
        },
        "additionalProperties": False,
    }

    def __init__(self, inspector: ArtifactInspector, *, task_id: UUID, attempt: int) -> None:
        super().__init__()
        self.inspector = inspector
        self.task_id = task_id
        self.attempt = attempt

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) - {"artifact_refs", "kinds", "max_chars"}:
            raise ValueError("run and task identity are server controlled")
        raw_refs = kwargs.get("artifact_refs", [])
        raw_kinds = kwargs.get("kinds", [])
        max_chars = kwargs.get("max_chars", 2000)
        if not isinstance(raw_refs, list) or not all(isinstance(item, str) for item in raw_refs):
            raise ValueError("artifact_refs must be a list of UUIDs")
        if not isinstance(raw_kinds, list) or not all(isinstance(item, str) for item in raw_kinds):
            raise ValueError("kinds must be a list of strings")
        if not isinstance(max_chars, int) or isinstance(max_chars, bool):
            raise ValueError("max_chars must be an integer")
        results = self.inspector.inspect(
            self.task_id,
            attempt=self.attempt,
            artifact_ids=tuple(UUID(item) for item in raw_refs),
            kinds=tuple(raw_kinds),
            max_chars=max_chars,
        )
        content = json.dumps(
            [asdict(item) for item in results],
            ensure_ascii=False,
            default=_json_default,
        )
        return ToolResult(content=content, metadata={"result_reference": "inspection:artifacts"})


class InspectTasksTool(Tool):
    name = "inspect_tasks"
    description = "Read exact persisted task states and safe artifact references for this run."
    tags = ["parent_only", "read_only", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {"_": {"type": "string"}},
        "additionalProperties": False,
    }

    def __init__(self, inspector: TaskInspector, *, task_id: UUID, attempt: int) -> None:
        super().__init__()
        self.inspector = inspector
        self.task_id = task_id
        self.attempt = attempt

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) - {"_"}:
            raise ValueError("run and task identity are server controlled")
        results = self.inspector.inspect(self.task_id, attempt=self.attempt)
        content = json.dumps(
            [asdict(item) for item in results],
            ensure_ascii=False,
            default=_json_default,
        )
        return ToolResult(content=content, metadata={"result_reference": "inspection:tasks"})


class RequestSelectionTool(Tool):
    name = "request_selection"
    description = "Pause this run for user selection of a persisted candidate proposal."
    tags = ["parent_only", "interaction", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "proposal_ref": {"type": "string", "format": "uuid"},
        },
        "required": ["proposal_ref"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        controller: SelectionController,
        *,
        task_id: UUID,
        attempt: int,
        worker_id: str,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.task_id = task_id
        self.attempt = attempt
        self.worker_id = worker_id

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"proposal_ref"}:
            raise ValueError("selection and task identity are server controlled")
        proposal_ref = kwargs["proposal_ref"]
        if not isinstance(proposal_ref, str):
            raise ValueError("proposal_ref must be a UUID")
        task = self.controller.request(
            self.task_id,
            attempt=self.attempt,
            worker_id=self.worker_id,
            proposal_id=UUID(proposal_ref),
        )
        return ToolResult(
            content=json.dumps({"status": task.status.value}),
            metadata={"result_reference": f"task:{task.task_id}"},
        )


class RequestFinishTool(Tool):
    name = "request_finish"
    description = "Request policy-checked completion using persisted artifact references."
    tags = ["parent_only", "finalization", "server_bound"]
    parameters = {
        "type": "object",
        "properties": {
            "artifact_refs": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "minItems": 1,
                "maxItems": 100,
            },
        },
        "required": ["artifact_refs"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        controller: FinalizationController,
        *,
        task_id: UUID,
        attempt: int,
        worker_id: str,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.task_id = task_id
        self.attempt = attempt
        self.worker_id = worker_id

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) != {"artifact_refs"}:
            raise ValueError("completion goal and task identity are server controlled")
        raw_refs = kwargs["artifact_refs"]
        if (
            not isinstance(raw_refs, list)
            or not raw_refs
            or len(raw_refs) > 100
            or not all(isinstance(item, str) for item in raw_refs)
        ):
            raise ValueError("artifact_refs must contain 1 to 100 UUIDs")
        task = self.controller.request(
            self.task_id,
            attempt=self.attempt,
            worker_id=self.worker_id,
            artifact_ids=tuple(UUID(item) for item in raw_refs),
        )
        return ToolResult(
            content=json.dumps({"status": task.status.value}),
            metadata={"result_reference": f"task:{task.task_id}"},
        )
