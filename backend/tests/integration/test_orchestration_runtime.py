import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("aidynamic_agent")


def test_run_starter_uses_server_config_for_root_budget_deadline_and_lease(tmp_path):
    from sector_pulse.application.orchestration.runtime import OrchestrationRunStarter
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.orchestration.models import TaskStatus
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "runtime-start.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    config = load_llm_config(Path("config/llm.yaml"))
    now = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)
    run_id, task_id = uuid4(), uuid4()

    root = OrchestrationRunStarter(repository, config).start(
        run_id=run_id,
        task_id=task_id,
        worker_id="root-worker",
        goal="full analysis",
        now=now,
    )
    state = repository.load(run_id)
    assert state is not None
    assert state.limits == config.orchestration_budget_limits()
    assert state.deadline.timestamp() - now.timestamp() == config.orchestration_timeout_seconds
    assert root.task_id == task_id
    assert root.role == "A0"
    assert root.scope == "full analysis"
    assert root.status is TaskStatus.RUNNING
    assert root.lease_expires_at == state.deadline


@pytest.mark.asyncio
async def test_runtime_t16_creates_real_child_with_server_bound_context(tmp_path):
    from aidynamic_agent.core.message import FinishReason, TextBlock, ToolUseBlock
    from aidynamic_agent.llm.base import LLMResponse
    from aidynamic_agent.tools.base import Tool, ToolResult
    from sector_pulse.application.orchestration.controls import (
        ArtifactContent,
        CompletionGoal,
        RequiredArtifactsFinalizationPolicy,
    )
    from sector_pulse.application.orchestration.runtime import OrchestrationRunStarter
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.orchestration.models import ArtifactRef, TaskStatus
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.agents.runtime import ParentAgentRuntime
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database = SQLiteDatabase(tmp_path / "parent-runtime.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    config = load_llm_config(Path("config/llm.yaml"))
    now = datetime.now(UTC)
    run_id, root_id = uuid4(), uuid4()
    OrchestrationRunStarter(repository, config).start(
        run_id=run_id,
        task_id=root_id,
        worker_id="root-worker",
        goal="full analysis",
        now=now,
    )
    input_artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root_id,
        kind="candidate_selection",
        reference="selection:3",
    )
    current = repository.load(run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "artifacts": (input_artifact,),
            }
        ),
        current.revision,
        "selection.confirmed",
    )

    class Reader:
        def read(self, artifact, *, max_chars):
            return ArtifactContent(summary=artifact.reference).bounded(max_chars)

    class NamedTool(Tool):
        name = "submit_analysis"
        description = "fixture business tool"
        parameters = {"type": "object", "properties": {}}

        def __init__(self, context):
            super().__init__()
            self.bound = context

        async def execute(self, **kwargs):
            TaskCoordinator(repository, run_id).submit_artifact(
                ArtifactRef(
                    artifact_id=uuid4(),
                    task_id=self.bound.task_id,
                    attempt=self.bound.attempt,
                    kind="sector_analysis",
                    reference=f"sector-analysis:{uuid4()}",
                ),
                worker_id=self.bound.worker_id,
            )
            return ToolResult(content="analysis submitted")

    class Endpoint:
        def __init__(self, role):
            self.role = role
            self.calls = 0

        async def create(self, *args, **kwargs):
            self.calls += 1
            if self.role is AgentRole.A0 and self.calls == 1:
                return LLMResponse(
                    content=[
                        ToolUseBlock(
                            tool_call_id="delegate-a2",
                            tool_name="delegate",
                            tool_input={
                                "role": "A2",
                                "goal": "research sector 1",
                                "scope": "industry:1",
                                "artifact_refs": [str(input_artifact.artifact_id)],
                            },
                        )
                    ],
                    model="fixture-high",
                    stop_reason=FinishReason.TOOL_USE,
                    usage={"total_tokens": 5},
                )
            if self.role is AgentRole.A2 and self.calls == 1:
                return LLMResponse(
                    content=[
                        ToolUseBlock(
                            tool_call_id="submit-a2",
                            tool_name="submit_analysis",
                            tool_input={},
                        )
                    ],
                    model="fixture-low",
                    stop_reason=FinishReason.TOOL_USE,
                    usage={"total_tokens": 5},
                )
            text = "child complete" if self.role is AgentRole.A2 else "parent complete"
            return LLMResponse(
                content=[TextBlock(text=text)],
                model="fixture",
                stop_reason=FinishReason.END_TURN,
                usage={"total_tokens": 5},
            )

    tool_contexts = []

    def build_submit_analysis(context):
        tool_contexts.append(context)
        return NamedTool(context)

    runtime = ParentAgentRuntime(
        repository=repository,
        run_id=run_id,
        root_task_id=root_id,
        root_attempt=1,
        root_worker_id="root-worker",
        config=config,
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_builder=lambda role, configured: Endpoint(role),
        business_tool_builders={"submit_analysis": build_submit_analysis},
        tool_reserved_cny={
            "delegate": 0,
            "inspect_artifacts": 0,
            "inspect_tasks": 0,
            "request_selection": 0,
            "request_finish": 0,
            "submit_analysis": 0,
        },
        artifact_reader=Reader(),
        finalization_policy=RequiredArtifactsFinalizationPolicy(
            goal=CompletionGoal.FULL_ANALYSIS,
            required_analysis_scopes=("industry:1",),
            is_current=lambda artifact: True,
        ),
        selection_version=3,
    )
    result = await runtime.run("coordinate the analysis")
    assert result.text == "parent complete"
    state = repository.load(run_id)
    child = next(task for task in state.tasks if task.parent_id == root_id)
    assert child.role == "A2"
    assert child.scope == "industry:1"
    assert child.input_artifact_ids == (input_artifact.artifact_id,)
    assert child.selection_version == 3
    assert child.status is TaskStatus.COMPLETED
    assert child.worker_id is None
    assert [item.role for item in state.ledger.reservations] == ["A0", "A2", "A2", "A0"]
    assert len(tool_contexts) == 1
    assert tool_contexts[0].task_id == child.task_id
    assert tool_contexts[0].scope == "industry:1"
    assert tool_contexts[0].input_artifact_ids == (input_artifact.artifact_id,)
    assert tool_contexts[0].selection_version == 3
    delegated_call = next(
        item for item in state.ledger.tool_invocations if item.tool_name == "delegate"
    )
    assert delegated_call.task_id == root_id
    assert delegated_call.result_reference == f"task:{child.task_id}"
    submitted_call = next(
        item for item in state.ledger.tool_invocations if item.tool_name == "submit_analysis"
    )
    assert submitted_call.task_id == child.task_id


@pytest.mark.asyncio
async def test_real_framework_runs_two_isolated_a2_research_traces_without_legacy_runtimes(
    tmp_path, monkeypatch
):
    from aidynamic_agent.core.message import FinishReason, TextBlock, ToolUseBlock
    from aidynamic_agent.llm.base import LLMResponse
    from aidynamic_agent.tools.base import Tool, ToolResult
    from sector_pulse.application.orchestration.controls import (
        ArtifactContent,
        CompletionGoal,
        RequiredArtifactsFinalizationPolicy,
    )
    from sector_pulse.application.orchestration.runtime import OrchestrationRunStarter
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.application.writing import agent_runner, attribution_agents
    from sector_pulse.application.writing.agent_runtime import AgentRuntime
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.orchestration.models import ArtifactRef, TaskStatus
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.agents.runtime import ParentAgentRuntime
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    def legacy_called(*args, **kwargs):
        raise AssertionError("legacy agent runtime must not be called")

    monkeypatch.setattr(attribution_agents, "run_attribution_agents", legacy_called)
    monkeypatch.setattr(AgentRuntime, "run", legacy_called)
    monkeypatch.setattr(agent_runner, "run_agent_loop", legacy_called)

    database = SQLiteDatabase(tmp_path / "a2-framework-trace.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    config = load_llm_config(Path("config/llm.yaml"))
    run_id, root_id = uuid4(), uuid4()
    OrchestrationRunStarter(repository, config).start(
        run_id=run_id,
        task_id=root_id,
        worker_id="root-worker",
        goal="research",
        now=datetime.now(UTC),
    )
    selection = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root_id,
        kind="candidate_selection",
        reference="selection:9",
    )
    current = repository.load(run_id)
    repository.save(
        current.model_copy(
            update={"revision": current.revision + 1, "artifacts": (selection,)}
        ),
        current.revision,
        "selection.confirmed",
    )

    class Reader:
        def read(self, artifact, *, max_chars):
            return ArtifactContent(summary=artifact.reference).bounded(max_chars)

    traces = {
        "sector:INDUSTRY:1": [],
        "sector:INDUSTRY:2": [],
    }
    reports = {}
    analyses = {}
    documents = {"sector:INDUSTRY:2": "document-2"}

    class TraceTool(Tool):
        description = "server-bound trace fixture"
        parameters = {"type": "object", "additionalProperties": True}

        def __init__(self, name, context):
            super().__init__()
            self.name = name
            self.context_data = context

        async def execute(self, **kwargs):
            scope = self.context_data.scope
            traces[scope].append(self.name)
            if self.name == "inspect_evidence":
                report_id = uuid4()
                reports[scope] = report_id
                return ToolResult(
                    content=f'{{"artifact_refs":["{report_id}"]}}',
                    metadata={"result_reference": f"evidence-inspection:{report_id}"},
                )
            if self.name == "search_news":
                return ToolResult(
                    content=f'{{"document_ids":["{documents[scope]}"]}}',
                    metadata={"result_reference": f"research-search:{uuid4()}"},
                )
            if self.name == "read_news_detail":
                return ToolResult(
                    content='{"availability":"available"}',
                    metadata={"result_reference": f"news-detail:{uuid4()}"},
                )
            if self.name == "submit_analysis" and not kwargs["submission"]["legal"]:
                return ToolResult(content="", success=False, error="UNKNOWN_EVIDENCE_ID")
            if self.name == "submit_analysis":
                analysis_id = uuid4()
                analyses[scope] = analysis_id
                TaskCoordinator(repository, run_id).submit_artifact(
                    ArtifactRef(
                        artifact_id=analysis_id,
                        task_id=self.context_data.task_id,
                        attempt=self.context_data.attempt,
                        kind="sector_analysis",
                        reference=f"sector-analysis:{analysis_id}",
                    ),
                    worker_id=self.context_data.worker_id,
                )
                return ToolResult(
                    content=f'{{"artifact_refs":["{analysis_id}"]}}',
                    metadata={"result_reference": f"sector-analysis:{analysis_id}"},
                )
            raise AssertionError(f"unexpected tool: {self.name}")

    child_number = 0
    active_children = 0
    max_active_children = 0

    class ScriptedEndpoint:
        def __init__(self, role, scope=None):
            self.role = role
            self.scope = scope
            self.calls = 0

        async def create(self, *args, **kwargs):
            nonlocal active_children
            self.calls += 1
            if self.role is AgentRole.A0:
                if self.calls <= 2:
                    sector_id = self.calls
                    return LLMResponse(
                        content=[
                            ToolUseBlock(
                                tool_call_id=f"delegate-{sector_id}",
                                tool_name="delegate",
                                tool_input={
                                    "role": "A2",
                                    "goal": f"research sector {sector_id}",
                                    "scope": f"sector:INDUSTRY:{sector_id}",
                                    "artifact_refs": [str(selection.artifact_id)],
                                },
                            )
                        ],
                        model="fixture-high",
                        stop_reason=FinishReason.TOOL_USE,
                        usage={"total_tokens": 5},
                    )
                return LLMResponse(
                    content=[TextBlock(text="research children complete")],
                    model="fixture-high",
                    stop_reason=FinishReason.END_TURN,
                    usage={"total_tokens": 5},
                )

            sequence = (
                ("inspect_evidence", "submit_analysis", "submit_analysis")
                if self.scope == "sector:INDUSTRY:1"
                else (
                    "inspect_evidence",
                    "search_news",
                    "read_news_detail",
                    "inspect_evidence",
                    "submit_analysis",
                    "submit_analysis",
                )
            )
            if self.calls <= len(sequence):
                name = sequence[self.calls - 1]
                if name == "inspect_evidence":
                    inputs = {"artifact_ids": [str(selection.artifact_id), str(uuid4())]}
                elif name == "search_news":
                    inputs = {"query": "sector catalyst"}
                elif name == "read_news_detail":
                    inputs = {"document_id": documents[self.scope]}
                else:
                    inputs = {
                        "inspection_artifact_id": str(reports[self.scope]),
                        "submission": {"legal": self.calls == len(sequence)},
                    }
                return LLMResponse(
                    content=[
                        ToolUseBlock(
                            tool_call_id=f"{self.scope}-{self.calls}",
                            tool_name=name,
                            tool_input=inputs,
                        )
                    ],
                    model="fixture-low",
                    stop_reason=FinishReason.TOOL_USE,
                    usage={"total_tokens": 5},
                )
            active_children -= 1
            return LLMResponse(
                content=[TextBlock(text=f"{self.scope} complete")],
                model="fixture-low",
                stop_reason=FinishReason.END_TURN,
                usage={"total_tokens": 5},
            )

    child_scopes = iter(("sector:INDUSTRY:1", "sector:INDUSTRY:2"))

    def provider_builder(role, configured):
        nonlocal active_children, child_number, max_active_children
        if role is AgentRole.A2:
            child_number += 1
            active_children += 1
            max_active_children = max(max_active_children, active_children)
            return ScriptedEndpoint(role, next(child_scopes))
        return ScriptedEndpoint(role)

    def build(name):
        return lambda context: TraceTool(name, context)

    runtime = ParentAgentRuntime(
        repository=repository,
        run_id=run_id,
        root_task_id=root_id,
        root_attempt=1,
        root_worker_id="root-worker",
        config=config,
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_builder=provider_builder,
        business_tool_builders={
            name: build(name)
            for name in (
                "search_news",
                "read_news_detail",
                "inspect_evidence",
                "submit_analysis",
            )
        },
        tool_reserved_cny={
            name: 0
            for name in (
                "delegate",
                "inspect_artifacts",
                "inspect_tasks",
                "request_selection",
                "request_finish",
                "search_news",
                "read_news_detail",
                "inspect_evidence",
                "submit_analysis",
            )
        },
        artifact_reader=Reader(),
        finalization_policy=RequiredArtifactsFinalizationPolicy(
            goal=CompletionGoal.RESEARCH,
            required_analysis_scopes=("sector:INDUSTRY:1", "sector:INDUSTRY:2"),
            is_current=lambda artifact: True,
        ),
        selection_version=9,
    )
    result = await runtime.run("coordinate sector research")

    assert result.text == "research children complete"
    assert traces["sector:INDUSTRY:1"] == [
        "inspect_evidence",
        "submit_analysis",
        "submit_analysis",
    ]
    assert traces["sector:INDUSTRY:2"] == [
        "inspect_evidence",
        "search_news",
        "read_news_detail",
        "inspect_evidence",
        "submit_analysis",
        "submit_analysis",
    ]
    state = repository.load(run_id)
    children = [task for task in state.tasks if task.parent_id == root_id]
    assert child_number == 2
    assert max_active_children <= 2
    assert active_children == 0
    assert {task.scope for task in children} == set(traces)
    assert all(task.status is TaskStatus.COMPLETED for task in children)
    tasks_by_id = {task.task_id: task for task in state.tasks}
    assert {
        tasks_by_id[item.task_id].scope
        for item in state.artifacts
        if item.kind == "sector_analysis"
    } == set(traces)
    assert len(analyses) == 2
    calls_by_scope = {
        task.scope: [
            call.tool_name
            for call in state.ledger.tool_invocations
            if call.task_id == task.task_id
        ]
        for task in children
    }
    assert calls_by_scope == traces


@pytest.mark.asyncio
async def test_real_framework_runs_a3_a4_revision_loop_without_legacy_agents(
    tmp_path, monkeypatch
):
    from aidynamic_agent.core.message import FinishReason, TextBlock, ToolUseBlock
    from aidynamic_agent.llm.base import LLMResponse
    from aidynamic_agent.tools.base import Tool, ToolResult
    from sector_pulse.application.orchestration.controls import (
        ArtifactContent,
        CompletionGoal,
        RequiredArtifactsFinalizationPolicy,
    )
    from sector_pulse.application.orchestration.runtime import OrchestrationRunStarter
    from sector_pulse.application.orchestration.tasks import TaskCoordinator
    from sector_pulse.application.writing import editorial_agents, revision_agent
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.domain.orchestration.models import ArtifactRef, TaskRecord, TaskStatus
    from sector_pulse.infrastructure.agents.roles import AgentRole
    from sector_pulse.infrastructure.agents.runtime import ParentAgentRuntime
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import (
        SQLiteOrchestrationRepository,
    )

    def legacy_called(*args, **kwargs):
        raise AssertionError("legacy editorial agent must not be called")

    monkeypatch.setattr(editorial_agents, "run_editorial_agent", legacy_called)
    monkeypatch.setattr(editorial_agents, "run_writing_agent", legacy_called)
    monkeypatch.setattr(editorial_agents, "run_review_agent", legacy_called)
    monkeypatch.setattr(revision_agent, "run_revision_agent", legacy_called)

    database = SQLiteDatabase(tmp_path / "a3-a4-framework-trace.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    config = load_llm_config(Path("config/llm.yaml"))
    run_id, root_id = uuid4(), uuid4()
    OrchestrationRunStarter(repository, config).start(
        run_id=run_id,
        task_id=root_id,
        worker_id="root-worker",
        goal="full_analysis",
        now=datetime.now(UTC),
    )
    selection = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root_id,
        kind="candidate_selection",
        reference="selection:12",
    )
    research_tasks = tuple(
        TaskRecord(
            task_id=uuid4(),
            parent_id=root_id,
            role="A2",
            scope=f"sector:INDUSTRY:{index}",
            status=TaskStatus.COMPLETED,
        )
        for index in range(1, 4)
    )
    analyses = tuple(
        ArtifactRef(
            artifact_id=uuid4(),
            task_id=task.task_id,
            kind="sector_analysis",
            reference=f"sector-analysis:{uuid4()}",
        )
        for task in research_tasks
    )
    unrelated = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root_id,
        kind="candidate_proposal",
        reference=f"candidate-proposal:{uuid4()}",
    )
    current = repository.load(run_id)
    repository.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "tasks": (*current.tasks, *research_tasks),
                "artifacts": (selection, *analyses, unrelated),
            }
        ),
        current.revision,
        "research.ready",
    )

    class Reader:
        def read(self, artifact, *, max_chars):
            return ArtifactContent(summary=artifact.reference).bounded(max_chars)

    draft_id = uuid4()
    values = {}
    traces = {}

    class TraceTool(Tool):
        description = "server-bound editorial trace fixture"
        parameters = {"type": "object", "additionalProperties": True}

        def __init__(self, name, context):
            super().__init__()
            self.name = name
            self.bound = context

        async def execute(self, **kwargs):
            traces.setdefault(self.bound.scope, []).append(self.name)
            if self.name == "submit_draft" and kwargs.get("fail_once"):
                return ToolResult(content="fix the draft", success=False, error="DRAFT_INVALID")
            if self.name == "submit_review" and kwargs.get("decision") == "PASS_INVALID":
                return ToolResult(content="", success=False, error="PROGRAM_FINDINGS")
            artifact_id = uuid4()
            if self.name == "submit_outline":
                key, kind, prefix = "outline", "article_outline", "article-outline"
            elif self.name == "submit_draft":
                key, kind, prefix = "draft_v1", "article_draft", "article-draft"
            elif self.name == "check_draft_rules":
                version = (
                    2
                    if "review:" in self.bound.scope and self.bound.scope.endswith(":2")
                    else 1
                )
                key, kind, prefix = f"rules_v{version}", "draft_rules", "draft-rules"
            elif self.name == "submit_review":
                version = 2 if self.bound.scope.endswith(":2") else 1
                key = f"review_v{version}"
                kind, prefix = "independent_review", "independent-review"
            elif self.name == "submit_revision":
                key, kind, prefix = "draft_v2", "article_draft", "article-draft"
            else:
                raise AssertionError(f"unexpected tool: {self.name}")
            values[key] = artifact_id
            TaskCoordinator(repository, run_id).submit_artifact(
                ArtifactRef(
                    artifact_id=artifact_id,
                    task_id=self.bound.task_id,
                    attempt=self.bound.attempt,
                    kind=kind,
                    reference=f"{prefix}:{artifact_id}",
                ),
                worker_id=self.bound.worker_id,
            )
            payload = {"artifact_refs": [str(artifact_id)]}
            if kind == "article_draft":
                payload.update(draft_id=str(draft_id), version=2 if key == "draft_v2" else 1)
            return ToolResult(
                content=json.dumps(payload),
                metadata={"result_reference": f"{prefix}:{artifact_id}"},
            )

    role_instances = {AgentRole.A3: 0, AgentRole.A4: 0}
    specialist_prompts = []

    class ScriptedEndpoint:
        def __init__(self, role, instance=0):
            self.role = role
            self.instance = instance
            self.calls = 0

        def tool_response(self, name, inputs):
            return LLMResponse(
                content=[
                    ToolUseBlock(
                        tool_call_id=f"{self.role.value}-{self.instance}-{self.calls}",
                        tool_name=name,
                        tool_input=inputs,
                    )
                ],
                model="fixture-editorial",
                stop_reason=FinishReason.TOOL_USE,
                usage={"total_tokens": 5},
            )

        async def create(self, *args, **kwargs):
            self.calls += 1
            if self.role is AgentRole.A3 and self.calls == 1:
                specialist_prompts.append(args[0][-1].content[0].text)
            if self.role is AgentRole.A0:
                if self.calls == 1:
                    return self.tool_response(
                        "delegate",
                        {
                            "role": "A3",
                            "goal": "write initial article",
                            "scope": f"article:{run_id}",
                            "artifact_refs": [
                                str(selection.artifact_id),
                                *(str(item.artifact_id) for item in analyses),
                                str(unrelated.artifact_id),
                            ],
                        },
                    )
                if self.calls == 2:
                    return self.tool_response(
                        "delegate",
                        {
                            "role": "A4",
                            "goal": "independently review v1",
                            "scope": "review:model-invented-id",
                            "artifact_refs": [str(values["draft_v1"])],
                        },
                    )
                if self.calls == 3:
                    return self.tool_response(
                        "delegate",
                        {
                            "role": "A3",
                            "goal": "revise only reviewed passages",
                            "scope": f"revision:{draft_id}:1",
                            "artifact_refs": [
                                str(values["draft_v1"]),
                                str(values["review_v1"]),
                            ],
                        },
                    )
                if self.calls == 4:
                    return self.tool_response(
                        "delegate",
                        {
                            "role": "A4",
                            "goal": "independently review v2",
                            "scope": f"review:{draft_id}:2",
                            "artifact_refs": [str(values["draft_v2"])],
                        },
                    )
                if self.calls == 5:
                    return self.tool_response(
                        "request_finish",
                        {
                                "artifact_refs": [
                                str(selection.artifact_id),
                                *(str(item.artifact_id) for item in analyses),
                                str(values["draft_v2"]),
                                str(values["rules_v2"]),
                                str(values["review_v2"]),
                            ]
                        },
                    )
                return LLMResponse(
                    content=[TextBlock(text="editorial review complete")],
                    model="fixture-editorial",
                    stop_reason=FinishReason.END_TURN,
                    usage={"total_tokens": 5},
                )

            if self.role is AgentRole.A3 and self.instance == 1:
                sequence = {
                    1: ("skill", {"operation": "load", "name": "analysis-writing"}),
                    2: ("submit_outline", {}),
                    3: ("submit_draft", {"fail_once": True}),
                    5: ("submit_draft", {}),
                }
            elif self.role is AgentRole.A3:
                sequence = (
                    ("skill", {"operation": "load", "name": "analysis-writing"}),
                    ("submit_revision", {}),
                )
            elif self.role is AgentRole.A4 and self.instance == 1:
                sequence = (
                    ("skill", {"operation": "load", "name": "independent-review"}),
                    ("check_draft_rules", {}),
                    ("submit_review", {"decision": "PASS_INVALID"}),
                    ("submit_review", {"decision": "REVISE"}),
                )
            else:
                sequence = (
                    ("skill", {"operation": "load", "name": "independent-review"}),
                    ("check_draft_rules", {}),
                    ("submit_review", {"decision": "PASS"}),
                )
            if isinstance(sequence, dict) and self.calls in sequence:
                name, inputs = sequence[self.calls]
                return self.tool_response(name, inputs)
            if not isinstance(sequence, dict) and self.calls <= len(sequence):
                name, inputs = sequence[self.calls - 1]
                return self.tool_response(name, inputs)
            return LLMResponse(
                content=[TextBlock(text=f"{self.role.value} complete")],
                model="fixture-editorial",
                stop_reason=FinishReason.END_TURN,
                usage={"total_tokens": 5},
            )

    def provider_builder(role, configured):
        del configured
        if role in role_instances:
            role_instances[role] += 1
            return ScriptedEndpoint(role, role_instances[role])
        return ScriptedEndpoint(role)

    def build(name):
        return lambda context: TraceTool(name, context)

    runtime = ParentAgentRuntime(
        repository=repository,
        run_id=run_id,
        root_task_id=root_id,
        root_attempt=1,
        root_worker_id="root-worker",
        config=config,
        prompt_registry=PromptRegistry(Path("config/prompts")),
        provider_builder=provider_builder,
        business_tool_builders={
            name: build(name)
            for name in (
                "submit_outline",
                "submit_draft",
                "submit_revision",
                "check_draft_rules",
                "submit_review",
            )
        },
        tool_reserved_cny={
            name: 0
            for name in (
                "delegate",
                "inspect_artifacts",
                "inspect_tasks",
                "request_selection",
                "request_finish",
                "submit_outline",
                "submit_draft",
                "submit_revision",
                "check_draft_rules",
                "submit_review",
                "skill",
            )
        },
        artifact_reader=Reader(),
        finalization_policy=RequiredArtifactsFinalizationPolicy(
            goal=CompletionGoal.FULL_ANALYSIS,
            required_analysis_scopes=tuple(item.scope for item in research_tasks),
            is_current=lambda artifact: artifact.artifact_id
            in {
                selection.artifact_id,
                *(item.artifact_id for item in analyses),
                values.get("draft_v2"),
                values.get("rules_v2"),
                values.get("review_v2"),
            },
        ),
        selection_version=12,
        review_scope_resolver=lambda artifact_id: (
            f"review:{draft_id}:2"
            if artifact_id == values.get("draft_v2")
            else f"review:{draft_id}:1"
        ),
    )
    result = await runtime.run("coordinate writing and independent review")

    assert result.text == "editorial review complete"
    assert traces[f"article:{run_id}"] == [
        "submit_outline",
        "submit_draft",
        "submit_draft",
    ]
    initial_writer_prompt = json.loads(specialist_prompts[0])
    assert initial_writer_prompt["authoritative_sector_ids"] == ["1", "2", "3"]
    assert traces[f"review:{draft_id}:1"] == [
        "check_draft_rules",
        "submit_review",
        "submit_review",
    ]
    assert traces[f"revision:{draft_id}:1"] == ["submit_revision"]
    assert traces[f"review:{draft_id}:2"] == ["check_draft_rules", "submit_review"]
    state = repository.load(run_id)
    children = [item for item in state.tasks if item.role in {"A3", "A4"}]
    assert all(item.status is TaskStatus.COMPLETED for item in children)
    initial_writer = next(item for item in children if item.scope == f"article:{run_id}")
    assert set(initial_writer.input_artifact_ids) == {
        selection.artifact_id,
        *(item.artifact_id for item in analyses),
    }
    assert state.tasks[0].status is TaskStatus.WAITING_USER_REVIEW
    assert not any(item.kind in {"approval", "revocation"} for item in state.artifacts)
    assert {item.role for item in state.ledger.reservations} >= {"A0", "A3", "A4"}
    assert {item.role for item in state.ledger.tool_invocations} >= {"A0", "A3", "A4"}
    first_review_task = next(
        item for item in children if item.scope == f"review:{draft_id}:1"
    )
    first_review_calls = [
        item
        for item in state.ledger.tool_invocations
        if item.task_id == first_review_task.task_id
    ]
    assert [item.tool_name for item in first_review_calls] == [
        "skill",
        "check_draft_rules",
        "submit_review",
        "submit_review",
    ]
    assert [item.status.value for item in first_review_calls] == [
        "succeeded",
        "succeeded",
        "failed",
        "succeeded",
    ]
    assert all(item.attempt == 1 and item.role == "A4" for item in first_review_calls)
