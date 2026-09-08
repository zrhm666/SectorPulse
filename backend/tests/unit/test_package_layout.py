"""Guard the approved package boundaries during backend reorganization."""

import ast
import importlib
import socket
from pathlib import Path

import pytest
import sector_pulse

ROOT = Path(sector_pulse.__file__).parent


def test_application_modules_are_grouped() -> None:
    assert {p.name for p in (ROOT / "application").glob("*.py")} <= {
        "__init__.py"
    }


def test_web_modules_have_explicit_responsibilities() -> None:
    assert {p.name for p in (ROOT / "web").glob("*.py")} == {
        "__init__.py", "app.py", "server.py", "dependencies.py", "errors.py"
    }


def test_storage_root_contains_only_shared_infrastructure() -> None:
    assert {p.name for p in (ROOT / "storage").glob("*.py")} == {
        "__init__.py", "database_config.py", "database_runtime.py",
        "runtime_bundle.py", "ports.py",
    }


def test_reorganized_modules_import_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbid_connect(*args: object, **kwargs: object) -> None:
        pytest.fail("Importing a backend module must not connect to external services")

    monkeypatch.setattr(socket.socket, "connect", forbid_connect)
    for layer in ("application", "storage", "web"):
        for file in sorted((ROOT / layer).rglob("*.py")):
            relative = file.relative_to(ROOT).with_suffix("")
            parts = relative.parts[:-1] if file.name == "__init__.py" else relative.parts
            module = importlib.import_module("sector_pulse." + ".".join(parts))
            assert Path(module.__file__).resolve() == file.resolve()
    importlib.import_module("sector_pulse.cli")
    importlib.import_module("sector_pulse.web.server")


def test_domain_does_not_depend_on_application_storage_or_web() -> None:
    forbidden = (
        "sector_pulse.application", "sector_pulse.storage", "sector_pulse.web"
    )
    for file in (ROOT / "domain").rglob("*.py"):
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden), file
            elif isinstance(node, ast.Import):
                assert not any(alias.name.startswith(forbidden) for alias in node.names), file
