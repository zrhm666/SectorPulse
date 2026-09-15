import asyncio
from contextlib import suppress
from decimal import Decimal

from pydantic import BaseModel
from sector_pulse.application.writing.agent_budget import BudgetedLLM
from sector_pulse.domain.llm import LLMRequest, LLMResult, LLMStatus, MoneyCny, TokenUsage


class Answer(BaseModel):
    ok: bool


def request():
    return LLMRequest(
        agent_name="test",
        model="test",
        prompt_id="test",
        prompt_version="1",
        system_prompt="test",
        user_payload={},
        response_model=Answer,
    )


class Model:
    async def generate_structured(self, value):
        assert value.max_output_tokens == 4096
        await asyncio.sleep(0)
        return LLMResult(
            status=LLMStatus.SUCCESS,
            data=Answer(ok=True),
            usage=TokenUsage(prompt_tokens=8, completion_tokens=2, total_tokens=10),
            estimated_cost_cny=MoneyCny(amount=Decimal("0")),
        )


async def test_success_settles_reserved_tokens_to_reported_usage():
    budget = BudgetedLLM(Model(), Decimal("1"), {}, max_tokens=30000)
    assert (await budget.generate_structured(request())).status == LLMStatus.SUCCESS
    assert budget.tokens_left == 29990
    assert (await budget.generate_structured(request())).status == LLMStatus.SUCCESS


async def test_concurrent_requests_cannot_spend_same_token_reservation():
    budget = BudgetedLLM(Model(), Decimal("1"), {}, max_tokens=30000)
    results = await asyncio.gather(*(budget.generate_structured(request()) for _ in range(2)))
    assert sorted(r.status for r in results) == [LLMStatus.BLOCKED, LLMStatus.SUCCESS]


async def test_unknown_price_still_enforces_request_limit():
    budget = BudgetedLLM(Model(), Decimal("1"), {}, max_calls=1)
    await budget.generate_structured(request())
    assert (await budget.generate_structured(request())).error.code == "AGENT_BUDGET_EXHAUSTED"


async def test_cancellation_keeps_reservation_charged():
    class Cancelled:
        async def generate_structured(self, value):
            raise asyncio.CancelledError

    budget = BudgetedLLM(Cancelled(), Decimal("1"), {}, max_tokens=30000)
    with suppress(asyncio.CancelledError):
        await budget.generate_structured(request())
    assert budget.tokens_left < 15000
    assert budget.reserved_cost == 0
