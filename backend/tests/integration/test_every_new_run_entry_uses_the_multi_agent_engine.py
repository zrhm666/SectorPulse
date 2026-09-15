"""Every entry point that can start a run must reach the parent-agent engine.

One leftover path that still builds the old Phase 1B pipeline is enough to make
"there is only one engine" false in production while every other test still
passes, because the old path is only ever exercised through an explicit test
override. These checks therefore assert the *wire-up* rather than a behaviour
that either engine could satisfy.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytest.importorskip("aidynamic_agent")

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "sector_pulse"
# The whole old engine, and the only production module allowed to reach each part
# of it. Everything here hangs off the legacy run command service, whose single
# constructor call is itself listed — so one forgotten override cannot revive the
# old engine quietly. Found by walking the AST for calls, so a comment or an import
# that merely mentions a name does not count as a caller.
LEGACY_SURFACE = {
    "run_phase1b_pipeline": {"web/services/run_service.py"},
    "run_revision_agent": {"application/writing/phase1b_pipeline.py"},
    "run_agent_loop": {"application/writing/agent_runtime.py"},
    # The old single-shot structured adapter, which the framework provider replaces.
    "build_live_provider": {"web/services/run_service.py"},
    "RunCommandService": {"web/dependencies.py"},
}


def _default_router_dependencies(tmp_path):
    """The dependencies the production app wires when no test overrides anything.

    `create_app` calls this same pair with `enable_multi_agent=True` and no
    overrides, so this is the shipped configuration, not a test convenience.
    """
    from sector_pulse.config.settings import ApplicationSettings
    from sector_pulse.web.dependencies import (
        build_runtime_dependencies,
        build_web_router_dependencies,
    )

    settings = ApplicationSettings(database_path=tmp_path / "entry.db")
    runtime = build_runtime_dependencies(settings, settings.database_path, enable_multi_agent=True)
    return build_web_router_dependencies(runtime, settings)


def _call_sites(function_name: str) -> set[str]:
    """Modules that *call* `function_name`, found by walking the AST."""
    found: set[str] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name == function_name:
                found.add(path.relative_to(SOURCE_ROOT).as_posix())
    return found


def test_the_default_wire_up_starts_runs_through_the_parent_agent(tmp_path) -> None:
    from sector_pulse.application.orchestration.commands import MultiAgentRunCommands
    from sector_pulse.application.runs.run_commands import RunCommandService

    commands = _default_router_dependencies(tmp_path).commands

    assert isinstance(commands, MultiAgentRunCommands)
    # The old command service is what a legacy-phase run would have to go through.
    assert not isinstance(commands, RunCommandService)
    assert commands.execution_engine == "multi_agent"


def test_the_data_run_continuation_also_uses_the_parent_agent(tmp_path) -> None:
    """Confirming candidates on a data run must not fall back to the old writer."""
    from sector_pulse.web.services.data_run_writing_service import (
        DataRunWritingService,
        MultiAgentDataRunWritingService,
    )

    writing = _default_router_dependencies(tmp_path).writing_service

    assert isinstance(writing, MultiAgentDataRunWritingService)
    assert not isinstance(writing, DataRunWritingService)


def test_the_scheduler_hands_new_work_to_the_parent_agent(tmp_path) -> None:
    """A scheduled run must not be the one path that still builds the old pipeline.

    The assertion reads the bridge the scheduler actually runs rather than
    counting constructor calls: `build_runtime_dependencies` also builds a
    bridge, and a call-order assertion would happily pass on the wrong one.
    """
    scheduler = _default_router_dependencies(tmp_path).scheduler

    assert scheduler._bridge._multi_agent_commands is not None


def test_the_cli_refuses_to_start_a_run_without_the_parent_agent() -> None:
    """The CLI asserts the engine instead of quietly using the old one."""
    import sector_pulse.cli as cli_module

    text = Path(cli_module.__file__).read_text(encoding="utf-8")

    assert "isinstance(commands, MultiAgentRunCommands)" in text
    assert "multi-agent runtime was not enabled" in text


def test_no_production_caller_leans_on_the_legacy_default() -> None:
    """`enable_multi_agent` defaults to False, so silence here means the old engine.

    Both shipped callers pass it explicitly today; this fails the moment a new
    one forgets, instead of quietly shipping a second engine.
    """
    missing: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name != "build_runtime_dependencies":
                continue
            if not any(
                keyword.arg == "enable_multi_agent"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            ):
                missing.append(f"{path.relative_to(SOURCE_ROOT).as_posix()}:{node.lineno}")

    assert missing == []


def test_the_old_engine_is_only_reachable_from_the_legacy_creation_path() -> None:
    """Executable form of the repo-wide search this unit is required to make.

    It is not a grep: a comment or a string that merely mentions a name is not a
    call site, and this fails as soon as a new caller appears anywhere.
    """
    actual = {name: _call_sites(name) for name in LEGACY_SURFACE}

    assert actual == LEGACY_SURFACE
