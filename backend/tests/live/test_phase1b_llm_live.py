import os

import pytest

pytestmark = pytest.mark.live_llm


def test_live_llm_configuration_is_explicit() -> None:
    if not os.getenv("SECTOR_PULSE_LLM_API_KEY"):
        pytest.skip("SECTOR_PULSE_LLM_API_KEY is absent")
    if not os.getenv("SECTOR_PULSE_LLM_BASE_URL"):
        pytest.skip("SECTOR_PULSE_LLM_BASE_URL is absent")
    assert os.getenv("SECTOR_PULSE_LLM_MODEL")
