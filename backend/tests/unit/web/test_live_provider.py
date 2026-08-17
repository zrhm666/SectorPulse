from unittest.mock import patch

from sector_pulse.web.live_provider import (
    build_live_provider,
    check_live_consent,
    get_live_config,
)


def test_check_live_consent_missing() -> None:
    with patch("sector_pulse.web.live_provider.Path.is_file", return_value=False):
        assert check_live_consent() is False


def test_check_live_consent_present() -> None:
    with patch("sector_pulse.web.live_provider.Path.is_file", return_value=True):
        assert check_live_consent() is True


def test_get_live_config_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("SECTOR_PULSE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("SECTOR_PULSE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("SECTOR_PULSE_LLM_MODEL", raising=False)
    assert get_live_config() is None


def test_build_live_provider_pricing() -> None:
    provider = build_live_provider(
        "https://example.test/v1",
        "sk-test",
        {"gpt-4o-mini": {"input_cny_per_million": "2.5", "output_cny_per_million": "10.0"}},
    )
    assert provider.provider_id == "openai-compatible"