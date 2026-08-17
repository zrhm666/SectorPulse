from pathlib import Path

from sector_pulse.infrastructure.providers.real_data_factory import RealDataProviderFactory


def factory(consent: Path) -> RealDataProviderFactory:
    return RealDataProviderFactory(consent_file=consent)


def test_missing_consent_is_unavailable(tmp_path: Path) -> None:
    result = factory(tmp_path / "missing").preflight()
    assert not result.available
    assert result.missing == ("live-data-consent",)


def test_preflight_never_returns_secret_values(tmp_path: Path) -> None:
    consent = tmp_path / "live-data-consent"
    consent.write_text("approved", encoding="utf-8")
    result = factory(consent).preflight()
    assert result.available
    assert "api_key" not in result.model_dump_json().lower()


def test_build_wires_eastmoney_then_ths_fallback(tmp_path: Path) -> None:
    consent = tmp_path / "live-data-consent"
    consent.touch()
    bundle = factory(consent).build()
    assert bundle.market.manifest.provider_id == "fallback:akshare-eastmoney|akshare-ths"
