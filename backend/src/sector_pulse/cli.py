import asyncio
from datetime import UTC, datetime
from pathlib import Path

import typer

from sector_pulse.application.phase0_probe import Phase0ProbeReport, run_phase0_probe
from sector_pulse.domain.quality import QualityThresholds
from sector_pulse.infrastructure.providers.akshare.adapter import AkShareMarketDataAdapter
from sector_pulse.reporting.phase0_report import render_phase0_markdown, write_utf8_atomic

app = typer.Typer(no_args_is_help=True)


@app.command("phase0-probe")
def phase0_probe(
    output_dir: Path = typer.Option(Path("data/phase0/latest")),
    consent_file: Path = typer.Option(Path(".live-data-consent")),
):
    if not consent_file.is_file():
        raise typer.BadParameter("create .live-data-consent after reviewing provider terms")
    report = asyncio.run(
        run_phase0_probe(
            AkShareMarketDataAdapter(),
            output_dir,
            datetime.now(UTC),
            QualityThresholds(),
            120,
        )
    )
    typer.echo(report.model_dump_json(indent=2))


@app.command("render-report")
def render_report(
    input_path: Path = typer.Option(..., "--input"),
    output_path: Path = typer.Option(..., "--output"),
):
    write_utf8_atomic(
        output_path,
        render_phase0_markdown(
            Phase0ProbeReport.model_validate_json(input_path.read_text(encoding="utf-8"))
        ),
    )
    typer.echo(str(output_path))
