"""Guard the approved package boundaries during backend reorganization."""

from pathlib import Path

import sector_pulse

ROOT = Path(sector_pulse.__file__).parent


def test_application_modules_are_grouped() -> None:
    assert {p.name for p in (ROOT / "application").glob("*.py")} <= {
        "__init__.py"
    }
