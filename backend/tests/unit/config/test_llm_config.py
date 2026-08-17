from pathlib import Path

from sector_pulse.config.llm_config import load_llm_config


def test_load_llm_config_reads_budget_and_routes(tmp_path: Path) -> None:
    path = tmp_path / "llm.yaml"
    path.write_text(
        """version: '1'
budget_cny_per_run: '2.00'
max_attribution_concurrency: 4
max_revision_rounds: 2
routes:
  attribution: {provider: fixture, model: fixture-low}
""",
        encoding="utf-8",
    )
    config = load_llm_config(path)
    assert config.version == "1"
    assert config.routes["attribution"].provider == "fixture"
