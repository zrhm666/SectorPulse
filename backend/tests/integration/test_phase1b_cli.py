from sector_pulse.cli import app
from typer.testing import CliRunner


def test_cli_lists_only_the_multi_agent_command_for_new_content_runs() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "phase1b-draft" not in result.stdout
    assert "multi-agent-run" in result.stdout


def test_cli_starts_fixture_multi_agent_run(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "multi-agent-run",
            "--goal",
            "offline fixture acceptance",
            "--database-path",
            str(tmp_path / "cli.db"),
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.strip()
