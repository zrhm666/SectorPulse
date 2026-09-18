from pathlib import Path

import pytest
from sector_pulse.config.llm_config import LLMRuntimeConfig, load_llm_config


@pytest.fixture
def yaml_config(tmp_path: Path) -> LLMRuntimeConfig:
    path = tmp_path / "llm.yaml"
    path.write_text(
        """version: '1'
budget_cny_per_run: '1.00'
max_attribution_concurrency: 2
max_revision_rounds: 1
routes: {}
""",
        encoding="utf-8",
    )
    return load_llm_config(path)
