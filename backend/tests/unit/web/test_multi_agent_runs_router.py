from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_runs_router_passes_selection_policy_to_multi_agent_commands():
    from sector_pulse.web.events.progress_bus import ProgressBus
    from sector_pulse.web.routers.runs import build_runs_review_router

    run_id = uuid4()

    class Commands:
        execution_engine = "multi_agent"
        call = None

        def create(self, input_json, provider, *, selection_policy):
            self.call = (input_json, provider, selection_policy)
            return run_id

        def retry(self, source):
            raise AssertionError(source)

        def cancel(self, target):
            raise AssertionError(target)

    class Queries:
        def list(self):
            return []

    commands = Commands()
    app = FastAPI()
    app.include_router(
        build_runs_review_router(commands=commands, queries=Queries(), bus=ProgressBus())
    )

    response = TestClient(app).post(
        "/api/runs",
        json={
            "provider": "fixture",
            "selection_policy": "server_default",
            "input_json": {"goal": "scheduled sector analysis"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_id": str(run_id),
        "execution_engine": "multi_agent",
    }
    assert commands.call == (
        {"goal": "scheduled sector analysis"},
        "fixture",
        "server_default",
    )


def test_runs_router_exposes_task_tree_and_budget_projection():
    from sector_pulse.web.events.progress_bus import ProgressBus
    from sector_pulse.web.routers.runs import build_runs_review_router

    run_id = uuid4()

    class Commands:
        execution_engine = "multi_agent"

    class Queries:
        def detail(self, requested):
            return SimpleNamespace(execution_engine="multi_agent") if requested == run_id else None

        def agent_trace(self, requested):
            assert requested == run_id
            return {
                "tasks": [{"role": "A0"}],
                "artifacts": [{"kind": "candidate_selection"}],
                "tool_invocations": [{"tool_name": "inspect_tasks"}],
                "model_calls": [{"call_id": "m1"}],
                "budget": {"calls": 1},
            }

    app = FastAPI()
    app.include_router(
        build_runs_review_router(commands=Commands(), queries=Queries(), bus=ProgressBus())
    )

    response = TestClient(app).get(f"/api/runs/{run_id}/tasks")

    assert response.status_code == 200
    assert response.json() == {
        "recording": "recorded",
        "tasks": [{"role": "A0"}],
        "artifacts": [{"kind": "candidate_selection"}],
        "tool_invocations": [{"tool_name": "inspect_tasks"}],
        "model_calls": [{"call_id": "m1"}],
        "budget": {"calls": 1},
    }


def test_runs_router_does_not_invent_a_task_tree_for_legacy_runs():
    from sector_pulse.web.events.progress_bus import ProgressBus
    from sector_pulse.web.routers.runs import build_runs_review_router

    run_id = uuid4()

    class Commands:
        execution_engine = "multi_agent"

    class Queries:
        def detail(self, requested):
            return SimpleNamespace(execution_engine="legacy") if requested == run_id else None

        def agent_trace(self, requested):
            raise AssertionError("legacy trace must not be reinterpreted as a task tree")

    app = FastAPI()
    app.include_router(
        build_runs_review_router(commands=Commands(), queries=Queries(), bus=ProgressBus())
    )

    response = TestClient(app).get(f"/api/runs/{run_id}/tasks")

    assert response.status_code == 200
    assert response.json() == {
        "recording": "not_recorded",
        "tasks": [],
        "artifacts": [],
        "tool_invocations": [],
        "model_calls": [],
        "budget": {},
    }
