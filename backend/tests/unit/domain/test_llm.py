from decimal import Decimal

import pytest
from sector_pulse.domain.llm import LLMResult, MoneyCny, TokenUsage


def test_success_result_requires_data() -> None:
    with pytest.raises(ValueError, match="requires data"):
        LLMResult(
            status="SUCCESS",
            data=None,
            usage=TokenUsage(),
            estimated_cost_cny=MoneyCny(amount=Decimal("0")),
        )
