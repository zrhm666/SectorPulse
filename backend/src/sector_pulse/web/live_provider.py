import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from sector_pulse.infrastructure.llm.openai_compatible import ModelPrice, OpenAICompatibleProvider


def check_live_consent() -> bool:
    return Path(".live-llm-consent").is_file()


def get_live_config() -> tuple[str, str, str] | None:
    base_url = os.environ.get("SECTOR_PULSE_LLM_BASE_URL")
    api_key = os.environ.get("SECTOR_PULSE_LLM_API_KEY")
    model = os.environ.get("SECTOR_PULSE_LLM_MODEL")
    if not base_url or not api_key or not model:
        return None
    return (base_url, api_key, model)


def build_live_provider(
    base_url: str, api_key: str, pricing: dict[str, Any]
) -> OpenAICompatibleProvider:
    prices = {
        key: ModelPrice(
            input_cny_per_million=Decimal(item["input_cny_per_million"]),
            output_cny_per_million=Decimal(item["output_cny_per_million"]),
        )
        for key, item in pricing.items()
    }
    return OpenAICompatibleProvider(
        base_url=base_url,
        api_key=SecretStr(api_key),
        timeout_seconds=60.0,
        pricing=prices,
    )