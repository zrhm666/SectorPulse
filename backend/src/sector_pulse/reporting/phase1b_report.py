import json
from pathlib import Path

from sector_pulse.application.phase1b_pipeline import Phase1BRunResult


def _require_ready(result: Phase1BRunResult) -> None:
    if result.draft is None or result.status != "READY_FOR_HUMAN_REVIEW":
        raise ValueError("draft is not ready for human review")


def render_phase1b_markdown(result: Phase1BRunResult) -> str:
    _require_ready(result)
    assert result.draft is not None
    lines = [
        f"# {result.draft.titles[0]}",
        "",
        f"状态：`{result.status}`｜版本：`{result.draft.version}`",
        "",
        result.draft.introduction,
        "",
    ]
    for index, section in enumerate(result.draft.sections, start=1):
        lines.extend(
            [
                f"## {section.heading}",
                "",
                section.body,
                "",
                "来源：" + "、".join(f"[来源{index}]" for _ in section.source_ids),
                "",
            ]
        )
    lines.extend(
        [
            result.draft.conclusion,
            "",
            f"风险提示：{result.draft.risk_notice}",
            "",
            "## 来源清单",
            "",
        ]
    )
    for index, source in enumerate(result.draft.sources, start=1):
        citation = f" - {source.citation_url}" if source.citation_url else ""
        lines.append(f"[来源{index}] {source.title}{citation}")
    return "\n".join(lines) + "\n"


def render_phase1b_text(result: Phase1BRunResult) -> str:
    return render_phase1b_markdown(result).replace("## ", "").replace("**", "")


def write_phase1b_artifacts(result: Phase1BRunResult, output_dir: Path) -> dict[str, Path]:
    target = output_dir / str(result.draft.run_id if result.draft else "unknown")
    target.mkdir(parents=True, exist_ok=False)
    result_path = target / "result.json"
    review_path = target / "review.json"
    result_path.write_text(
        json.dumps(result.__dict__, default=str, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    review_path.write_text(
        json.dumps(
            result.review.model_dump(mode="json") if result.review else {},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    paths = {"result": result_path, "review": review_path}
    if result.status == "READY_FOR_HUMAN_REVIEW":
        markdown_path = target / "draft.md"
        text_path = target / "draft.txt"
        markdown_path.write_text(render_phase1b_markdown(result), encoding="utf-8")
        text_path.write_text(render_phase1b_text(result), encoding="utf-8")
        paths.update(markdown=markdown_path, text=text_path)
    return paths
