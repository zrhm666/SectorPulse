"""Guard the approved package boundaries during backend reorganization."""

from pathlib import Path

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
