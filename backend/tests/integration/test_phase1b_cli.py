from sector_pulse.cli import app
from typer.testing import CliRunner


def test_cli_lists_phase1b_command() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "phase1b-draft" in result.stdout
