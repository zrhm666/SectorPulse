from pathlib import Path

from sector_pulse.config.llm_config import load_llm_config
from sector_pulse.config.settings import ApplicationSettings, load_environment


def yaml_config(tmp_path: Path):
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


def test_dotenv_loads_without_overriding_existing_environment(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "SECTOR_PULSE_LLM_PROVIDER=from-dotenv\nSECTOR_PULSE_LLM_MODEL=dotenv-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SECTOR_PULSE_LLM_PROVIDER", "from-process")
    load_environment(dotenv)
    settings = ApplicationSettings.from_environment(yaml_config(tmp_path))
    assert settings.llm_provider == "from-process"


def test_settings_read_shared_model_and_never_dump_secret(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECTOR_PULSE_LLM_API_KEY", "secret-value")
    monkeypatch.setenv("SECTOR_PULSE_LLM_MODEL", "code-assistant")
    settings = ApplicationSettings.from_environment(yaml_config(tmp_path))
    assert settings.llm_model == "code-assistant"
    assert "secret-value" not in settings.model_dump_json()


def test_settings_apply_runtime_limits_from_environment(tmp_path, monkeypatch) -> None:
    config = yaml_config(tmp_path)
    monkeypatch.setenv("SECTOR_PULSE_LLM_BUDGET_CNY", "3.50")
    monkeypatch.setenv("SECTOR_PULSE_LLM_MAX_ATTRIBUTION_CONCURRENCY", "1")
    monkeypatch.setenv("SECTOR_PULSE_LLM_MAX_REVISION_ROUNDS", "0")

    settings = ApplicationSettings.from_environment(config)
    runtime = settings.apply_runtime_overrides(config)

    assert runtime.budget_cny_per_run == 3.50
    assert runtime.max_attribution_concurrency == 1
    assert runtime.max_revision_rounds == 0
