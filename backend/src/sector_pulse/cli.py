import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import typer

from sector_pulse.application.data_runs.phase1a2_probe import (
    Phase1A2Dependencies,
    Phase1A2Request,
    run_phase1a2_probe,
)
from sector_pulse.application.diagnostics.phase0_probe import Phase0ProbeReport, run_phase0_probe
from sector_pulse.application.diagnostics.phase1a_probe import run_phase1a_probe
from sector_pulse.application.orchestration.commands import MultiAgentRunCommands
from sector_pulse.config.llm_config import load_llm_config
from sector_pulse.config.news_config import load_entity_config
from sector_pulse.config.settings import ApplicationSettings, load_environment
from sector_pulse.domain.market.quality import QualityThresholds
from sector_pulse.infrastructure.news.akshare_adapters import (
    AkShareClsAdapter,
    AkShareCninfoAdapter,
    AkShareEastmoneyNewsAdapter,
)
from sector_pulse.infrastructure.news.rss_adapter import RssNewsAdapter
from sector_pulse.infrastructure.providers.akshare.adapter import AkShareMarketDataAdapter
from sector_pulse.infrastructure.providers.akshare.constituents import (
    AkShareSectorConstituentAdapter,
)
from sector_pulse.reporting.phase0_report import render_phase0_markdown, write_utf8_atomic
from sector_pulse.reporting.phase1a2_report import write_phase1a2_report
from sector_pulse.storage.database_runtime import initialize_database
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.web.dependencies import build_runtime_dependencies, build_web_router_dependencies

app = typer.Typer(no_args_is_help=True)


@app.command("phase0-probe")
def phase0_probe(
    output_dir: Path = typer.Option(Path("data/phase0/latest")),
    consent_file: Path = typer.Option(Path(".live-data-consent")),
) -> None:
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
) -> None:
    write_utf8_atomic(
        output_path,
        render_phase0_markdown(
            Phase0ProbeReport.model_validate_json(input_path.read_text(encoding="utf-8"))
        ),
    )
    typer.echo(str(output_path))


@app.command("phase1a-probe")
def phase1a_probe(
    output_path: Path = typer.Option(Path("data/phase1a/latest/report.json")),
    database_path: Path = typer.Option(Path("data/sector-pulse.db")),
    consent_file: Path = typer.Option(Path(".live-data-consent")),
    source_ids: list[str] = typer.Option([], "--source-id"),
) -> None:
    """手动执行行情、新闻事件、候选和证据包的 Phase 1A 垂直探测。"""
    if not consent_file.is_file():
        raise typer.BadParameter("create .live-data-consent after reviewing provider terms")
    report = asyncio.run(
        run_phase1a_probe(
            AkShareMarketDataAdapter(),
            RssNewsAdapter(),
            SQLiteDatabase(database_path),
            datetime.now(UTC),
            QualityThresholds(),
            tuple(source_ids),
        )
    )
    write_utf8_atomic(output_path, report.model_dump_json(indent=2))
    typer.echo(report.model_dump_json(indent=2))


@app.command("phase1a2-news-probe")
def phase1a2_news_probe(
    run_kind: str = typer.Option(..., "--run-kind", help="intraday or post_close"),
    output_dir: Path = typer.Option(Path("data/phase1a2")),
    database_path: Path = typer.Option(Path("data/sector-pulse.db")),
    entity_config: Path = typer.Option(Path("config/sector_entities.yaml")),
    consent_file: Path = typer.Option(Path(".live-data-consent")),
) -> None:
    """执行带 consent 门禁的真实新闻检索与证据审计，不自动发布文章。"""
    if not consent_file.is_file():
        raise typer.BadParameter("create .live-data-consent after reviewing provider terms")
    if run_kind not in {"intraday", "post_close"}:
        raise typer.BadParameter("run_kind must be intraday or post_close")
    global_news = AkShareClsAdapter()
    keyword_news = AkShareEastmoneyNewsAdapter()
    disclosure_news = AkShareCninfoAdapter()
    dependencies: Phase1A2Dependencies = type(
        "Phase1A2RuntimeDependencies",
        (),
        {
            "market": AkShareMarketDataAdapter(),
            "constituents": AkShareSectorConstituentAdapter(),
            "global_news": global_news,
            "keyword_news": keyword_news,
            "disclosure_news": disclosure_news,
            "database": SQLiteDatabase(database_path),
            "entity_config": load_entity_config(entity_config),
        },
    )()
    report = asyncio.run(
        run_phase1a2_probe(
            dependencies,
            Phase1A2Request(requested_at=datetime.now(UTC), run_kind=run_kind),
        )
    )
    json_path, markdown_path = write_phase1a2_report(report, output_dir)
    typer.echo(f"json={json_path}")
    typer.echo(f"markdown={markdown_path}")


@app.command("multi-agent-run")
def multi_agent_run(
    goal: str = typer.Option(..., "--goal"),
    database_path: Path = typer.Option(Path("data/sector-pulse.db")),
    provider: Literal["fixture", "live"] = typer.Option("fixture", "--provider"),
) -> None:
    """显式启动一次父 Agent 多 Agent 运行并等待其完成。"""
    if not goal.strip():
        raise typer.BadParameter("goal must not be empty", param_hint="--goal")
    load_environment()
    packaged_config = load_llm_config(Path("config/llm.yaml"))
    settings = ApplicationSettings.from_environment(packaged_config).model_copy(
        update={"database_path": database_path, "database_url": None}
    )
    runtime = build_runtime_dependencies(
        settings,
        database_path,
        enable_multi_agent=True,
    )
    router_dependencies = build_web_router_dependencies(runtime, settings)
    commands = router_dependencies.commands
    if not isinstance(commands, MultiAgentRunCommands):
        raise typer.BadParameter("multi-agent runtime was not enabled")

    async def run() -> UUID:
        await initialize_database(runtime.database)
        run_id = commands.create(
            {"goal": goal}, provider, selection_policy="server_default"
        )
        await commands.wait(run_id)
        return run_id

    run_id = asyncio.run(run())
    typer.echo(str(run_id))
