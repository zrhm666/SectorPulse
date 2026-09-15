from datetime import UTC, datetime

from sector_pulse.domain.market.quality import QualityThresholds, evaluate_universe
from sector_pulse.domain.provider import DataStatus, ProviderError, ProviderResult


def test_missing_market_retains_safe_error_code_not_provider_message() -> None:
    result = ProviderResult(
        provider_id="fallback", capability="sector_universe.industry",
        status=DataStatus.FAILED, collected_at=datetime.now(UTC),
        error=ProviderError(code="MARKET_PROVIDERS_FAILED", message="secret raw response"),
    )
    quality = evaluate_universe(result, QualityThresholds())
    assert quality.issues == ("FAILED", "MARKET_PROVIDERS_FAILED")
    assert "secret" not in quality.model_dump_json()


def test_unknown_provider_error_is_not_exposed_in_quality() -> None:
    result = ProviderResult(
        provider_id="fallback", capability="sector_universe.industry",
        status=DataStatus.FAILED, collected_at=datetime.now(UTC),
        error=ProviderError(code="https://user:secret@example.com", message="secret"),
    )
    assert evaluate_universe(result, QualityThresholds()).issues == ("FAILED",)
