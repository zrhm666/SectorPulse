from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import ValidationError

from sector_pulse.application.orchestration.commands import MultiAgentRunCommands
from sector_pulse.application.runs.run_commands import RunCommandService
from sector_pulse.application.runs.run_queries import RunQueryService
from sector_pulse.infrastructure.llm.fixture_resources import load_default_fixture_input
from sector_pulse.web.events.progress_bus import ProgressBus
from sector_pulse.web.schemas.runs import (
    NewRunRequest,
    NewRunResponse,
    RunCandidateItem,
    RunDetail,
    RunSelectionAcceptedResponse,
    RunSelectionConfirmRequest,
    RunSelectionProposalResponse,
    RunSummary,
)
from sector_pulse.web.services.run_service import ProviderUnavailable

LEGACY_RETRY_MESSAGE = "该运行由旧引擎创建，无法重试为多 Agent 运行；请新建一次运行"


def build_runs_review_router(
    *,
    commands: RunCommandService | MultiAgentRunCommands,
    queries: RunQueryService,
    bus: ProgressBus,
) -> APIRouter:
    router = APIRouter(tags=["runs", "review"])

    def _retryable(detail: RunDetail | RunSummary) -> RunDetail | RunSummary:
        """Clear the retry flag when the wired engine is not the one that can retry.

        `execution_engine` says how a run was made; whether retry works depends on
        the engine that would do the retrying, which is `commands`. A historical run
        therefore loses the flag here rather than offering a button that 409s.
        """
        if detail.execution_engine == "legacy" and commands.execution_engine != "legacy":
            return detail.model_copy(update={"retryable": False})
        return detail

    @router.get("/api/fixture-input")
    async def fixture_input() -> dict[str, Any]:
        return load_default_fixture_input()

    @router.get("/api/runs")
    async def list_runs() -> list[Any]:
        return [_retryable(item) for item in queries.list()]

    @router.post("/api/runs", response_model=NewRunResponse, status_code=200)
    async def create_run(req: NewRunRequest) -> NewRunResponse:
        try:
            run_id = commands.create(
                req.input_json,
                req.provider,
                selection_policy=req.selection_policy,
            )
        except ProviderUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return NewRunResponse(
            run_id=run_id,
            execution_engine=commands.execution_engine,
        )

    @router.get("/api/runs/{run_id}")
    async def get_run(run_id: UUID) -> dict[str, Any]:
        detail = queries.detail(run_id)
        if detail is None:
            raise HTTPException(404, "run not found")
        return _retryable(detail).model_dump(mode="json")

    @router.get(
        "/api/runs/{run_id}/selection", response_model=RunSelectionProposalResponse
    )
    async def get_run_selection(run_id: UUID) -> RunSelectionProposalResponse:
        if not isinstance(commands, MultiAgentRunCommands):
            raise HTTPException(404, "candidate proposal not found")
        try:
            proposal, artifact, selection_version, attempt = commands.candidate_proposal(run_id)
        except KeyError as exc:
            raise HTTPException(404, "candidate proposal not found") from exc
        return RunSelectionProposalResponse(
            run_id=run_id,
            proposal_id=proposal.proposal_id,
            proposal_artifact_id=artifact.artifact_id,
            selection_version=selection_version,
            attempt=attempt,
            items=tuple(
                RunCandidateItem(
                    sector_id=item.provider_sector_id,
                    sector_kind=item.kind.value,
                    name=item.name,
                    rank=item.rank,
                    score=str(item.score),
                    explanation=item.explanation,
                )
                for item in proposal.items
            ),
        )

    @router.put(
        "/api/runs/{run_id}/selection",
        response_model=RunSelectionAcceptedResponse,
        status_code=202,
    )
    async def confirm_run_selection(
        run_id: UUID, req: RunSelectionConfirmRequest
    ) -> RunSelectionAcceptedResponse:
        if not isinstance(commands, MultiAgentRunCommands):
            raise HTTPException(404, "candidate proposal not found")
        try:
            next_attempt = await commands.confirm_selection(
                run_id=run_id,
                proposal_id=req.proposal_id,
                sector_ids=req.sector_ids,
                expected_selection_version=req.expected_selection_version,
                expected_attempt=req.expected_attempt,
            )
        except KeyError as exc:
            raise HTTPException(404, "candidate proposal not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RunSelectionAcceptedResponse(run_id=run_id, next_attempt=next_attempt)

    @router.get("/api/runs/{run_id}/events")
    async def run_events(run_id: UUID) -> StreamingResponse:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")

        async def event_stream() -> AsyncIterator[str]:
            async for event in bus.subscribe(run_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.post("/api/runs/{run_id}/retry", response_model=NewRunResponse)
    async def retry_run(run_id: UUID) -> NewRunResponse:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        try:
            new_run_id = commands.retry(run_id)
        except ProviderUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyError as exc:
            # The multi-agent engine only retries a run it owns; a historical row has
            # no snapshot to rebuild from, so report the migration rather than 500.
            raise HTTPException(409, LEGACY_RETRY_MESSAGE) from exc
        return NewRunResponse(
            run_id=new_run_id,
            execution_engine=commands.execution_engine,
        )

    @router.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: UUID) -> dict[str, bool]:
        if not commands.cancel(run_id):
            raise HTTPException(404, "run not found or not running")
        return {"cancelled": True}

    @router.get("/api/runs/{run_id}/radar")
    async def get_radar(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.radar(run_id)

    @router.get("/api/runs/{run_id}/agent-trace")
    async def get_agent_trace(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.agent_trace(run_id)

    @router.get("/api/runs/{run_id}/tasks")
    async def get_tasks(run_id: UUID) -> dict[str, Any]:
        detail = queries.detail(run_id)
        if detail is None:
            raise HTTPException(404, "run not found")
        if detail.execution_engine == "legacy":
            return {
                "recording": "not_recorded",
                "tasks": [],
                "artifacts": [],
                "tool_invocations": [],
                "model_calls": [],
                "budget": {},
            }
        trace = queries.agent_trace(run_id)
        return {
            "recording": "recorded",
            "tasks": trace.get("tasks", []),
            "artifacts": trace.get("artifacts", []),
            "tool_invocations": trace.get("tool_invocations", []),
            "model_calls": trace.get("model_calls", []),
            "budget": trace.get("budget", {}),
        }

    @router.get("/api/runs/{run_id}/draft")
    async def get_draft(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.draft(run_id)

    @router.get("/api/runs/{run_id}/draft.md")
    async def get_draft_md(run_id: UUID) -> PlainTextResponse:
        body = queries.markdown(run_id)
        if body is None:
            raise HTTPException(404, "draft not ready")
        return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")

    @router.get("/api/runs/{run_id}/draft.txt")
    async def get_draft_txt(run_id: UUID) -> PlainTextResponse:
        body = queries.text(run_id)
        if body is None:
            raise HTTPException(404, "draft not ready")
        return PlainTextResponse(body, media_type="text/plain; charset=utf-8")

    @router.get("/api/runs/{run_id}/evidence")
    async def get_evidence(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.evidence(run_id)

    @router.get("/api/runs/{run_id}/review")
    async def get_review(run_id: UUID) -> dict[str, Any]:
        if queries.detail(run_id) is None:
            raise HTTPException(404, "run not found")
        return queries.review(run_id)

    return router
