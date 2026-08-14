import json
from pathlib import Path

from sector_pulse.application.phase1a2_probe import Phase1A2Report


def render_phase1a2_markdown(report: Phase1A2Report) -> str:
    cutoff_text = report.run.run_cutoff_at.isoformat() if report.run.run_cutoff_at else "未锁定"
    lines = [
        f"# SectorPulse Phase 1A.2 报告（{report.run_kind}）",
        "",
        f"- run_id: `{report.run.run_id}`",
        f"- cutoff: `{cutoff_text}`",
        f"- elapsed_ms: `{report.elapsed_ms}`",
        f"- market precandidates/final: `{report.market_precandidate_count}` / "
        f"`{report.final_candidate_count}`",
        f"- documents/events/links: `{report.document_count}` / `{report.event_count}` / "
        f"`{report.link_count}`",
        f"- deduplication_rate: `{report.deduplication_rate:.2%}`",
        f"- mapping_rate: `{report.mapping_rate:.2%}`",
        f"- cutoff violations: `{report.cutoff_violation_count}`",
        f"- ready_for_phase1b: `{report.ready_for_phase1b}`",
        "",
        "## 来源指标",
        "",
    ]
    for source_id, metric in sorted(report.source_metrics.items()):
        lines.append(
            f"- `{source_id}`: {metric.status.value}, calls={metric.call_count}, "
            f"retries={metric.retry_count}, docs={metric.document_count}, "
            f"duration_ms={metric.duration_ms}"
        )
    lines.extend(
        [
            "",
            "## 质量",
            "",
            f"- news status: `{report.news_quality.status.value}`",
            f"- citation eligible/background/excluded: "
            f"`{report.news_quality.citation_eligible_count}` / "
            f"`{report.news_quality.background_only_count}` / "
            f"`{report.news_quality.excluded_after_cutoff_count}`",
            f"- downgrade reasons: `{', '.join(report.downgrade_reasons) or 'NONE'}`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_phase1a2_report(report: Phase1A2Report, output_dir: Path) -> tuple[Path, Path]:
    target = (
        output_dir
        / report.run.requested_at.date().isoformat()
        / report.run_kind
        / str(report.run.run_id)
    )
    target.mkdir(parents=True, exist_ok=False)
    json_path = target / "report.json"
    markdown_path = target / "report.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown_path.write_text(render_phase1a2_markdown(report), encoding="utf-8")
    return json_path, markdown_path
