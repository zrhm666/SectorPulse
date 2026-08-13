from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sector_pulse.application.phase0_probe import Phase0ProbeReport


def write_utf8_atomic(path: Path, content: str) -> None:
    # 先写临时文件再替换，避免进程中断时留下截断 JSON/Markdown。
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def render_phase0_markdown(report: "Phase0ProbeReport") -> str:
    cutoff = report.run.run_cutoff_at.isoformat() if report.run.run_cutoff_at else "UNLOCKED"
    return "\n".join(
        [
            "# Phase 0 Market Data Validation",
            "",
            f"- run_cutoff_at: `{cutoff}`",
            f"- provider: `{report.provider_id}`",
            f"- authorization: `{report.provider_authorization.value}`",
            f"- INDUSTRY count/status: `{report.industry_quality.sector_count}` / "
            f"`{report.industry_quality.status.value}`",
            f"- CONCEPT count/status: `{report.concept_quality.sector_count}` / "
            f"`{report.concept_quality.status.value}`",
            f"- usable: `{str(report.usable).lower()}`",
            "",
            "This record proves technical availability only. "
            "RESEARCH_ONLY is not production authorization.",
            "",
        ]
    )
