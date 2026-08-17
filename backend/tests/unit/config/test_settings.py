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
