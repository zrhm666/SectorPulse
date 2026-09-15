import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

pytest.importorskip("aidynamic_agent")


def budget_for(tmp_path, calls=1):
    from sector_pulse.application.orchestration.budget import SharedBudget
    from sector_pulse.domain.orchestration.models import BudgetLimits, RunSnapshot
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    db = SQLiteDatabase(tmp_path / "provider.db")
    db.initialize()
    repo = SQLiteOrchestrationRepository(db)
    state = RunSnapshot(
        run_id=uuid4(),
        limits=BudgetLimits(max_calls=calls),
        deadline=datetime.now(UTC) + timedelta(minutes=1),
    )
    repo.save(state, -1)
    return SharedBudget(repo, state.run_id), repo


@pytest.mark.asyncio
async def test_parent_and_child_share_real_provider_admission(tmp_path):
    from aidynamic_agent.agents.factory import AgentFactory
    from aidynamic_agent.core.agent import AgentConfig, TerminationReason
    from aidynamic_agent.core.message import FinishReason, TextBlock
    from aidynamic_agent.llm.base import LLMResponse
    from sector_pulse.infrastructure.agents.provider import BudgetedProvider

    class Endpoint:
        async def create(self, *args, **kwargs):
            return LLMResponse(
                content=[TextBlock(text="verified result")],
                model="test",
                stop_reason=FinishReason.END_TURN,
                usage={"total_tokens": 20},
            )

    budget, repo = budget_for(tmp_path)
    provider = BudgetedProvider(Endpoint(), budget, output_limit=100)
    factory = AgentFactory(provider, config=AgentConfig(max_retries=1))
    parent = await factory.create_parent_agent().run("inspect")
    child = await factory.create_sub_agent().run("inspect more")
    assert parent.text == "verified result"
    assert child.termination_reason == TerminationReason.ERROR
    assert "budget" in child.error
    state = repo.load(budget.run_id)
    assert state.ledger.calls == 1
    assert state.ledger.charged_tokens == 20


@pytest.mark.asyncio
async def test_missing_usage_keeps_charge_and_output_limit_is_enforced(tmp_path):
    from aidynamic_agent.core.message import FinishReason
    from aidynamic_agent.llm.base import LLMResponse
    from sector_pulse.infrastructure.agents.provider import BudgetedProvider

    class Endpoint:
        async def create(self, *args, **kwargs):
            assert kwargs["max_tokens"] == 100
            assert "max_completion_tokens" not in kwargs
            return LLMResponse(content=[], model="test", stop_reason=FinishReason.END_TURN)

    budget, repo = budget_for(tmp_path)
    await BudgetedProvider(Endpoint(), budget, output_limit=100).create(
        [], max_tokens=999999, max_completion_tokens=999999
    )
    state = repo.load(budget.run_id)
    assert state.ledger.charged_tokens >= 100
    assert state.ledger.reservations[0].settled
    assert state.ledger.reservations[0].actual_tokens is None


@pytest.mark.asyncio
async def test_cancelled_model_keeps_reservation(tmp_path):
    from sector_pulse.domain.orchestration.models import ModelCallStatus
    from sector_pulse.infrastructure.agents.provider import BudgetedProvider

    started = asyncio.Event()

    class Endpoint:
        async def create(self, *args, **kwargs):
            started.set()
            await asyncio.Event().wait()

    budget, repo = budget_for(tmp_path)
    task = asyncio.create_task(BudgetedProvider(Endpoint(), budget, output_limit=100).create([]))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    reservation = repo.load(budget.run_id).ledger.reservations[0]
    assert repo.load(budget.run_id).ledger.charged_tokens >= 100
    assert reservation.status is ModelCallStatus.UNKNOWN
    assert reservation.completed_at is not None


@pytest.mark.asyncio
async def test_multi_completion_or_extra_body_cannot_bypass_reservation(tmp_path):
    from sector_pulse.infrastructure.agents.provider import BudgetedProvider

    class Endpoint:
        async def create(self, *args, **kwargs):
            raise AssertionError("unsupported options must not reach endpoint")

    budget, repo = budget_for(tmp_path)
    provider = BudgetedProvider(Endpoint(), budget, output_limit=100)
    for options in ({"n": 2}, {"extra_body": {"max_tokens": 999999}}, {"stream": True}):
        with pytest.raises(ValueError, match="unsupported"):
            await provider.create([], **options)
    assert repo.load(budget.run_id).ledger.calls == 0


@pytest.mark.asyncio
async def test_money_limit_rejects_unpriced_provider_before_request(tmp_path):
    from sector_pulse.application.orchestration.budget import BudgetExceeded
    from sector_pulse.domain.orchestration.models import BudgetLimits
    from sector_pulse.infrastructure.agents.provider import BudgetedProvider

    class Endpoint:
        async def create(self, *args, **kwargs):
            raise AssertionError("unpriced request must not be sent")

    budget, repo = budget_for(tmp_path)
    state = repo.load(budget.run_id)
    repo.save(
        state.model_copy(
            update={
                "revision": 1,
                "limits": BudgetLimits(max_cny=Decimal("1")),
            }
        ),
        0,
    )
    with pytest.raises(BudgetExceeded, match="price"):
        await BudgetedProvider(Endpoint(), budget).create([])
    assert repo.load(budget.run_id).ledger.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "usage, expected",
    [
        ({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}, Decimal("0.18")),
        ({"total_tokens": 120}, None),
        ({}, None),
    ],
)
async def test_priced_provider_accounts_for_input_and_output(tmp_path, usage, expected):
    from aidynamic_agent.core.message import FinishReason
    from aidynamic_agent.llm.base import LLMResponse
    from sector_pulse.domain.orchestration.models import ModelPricing
    from sector_pulse.infrastructure.agents.provider import BudgetedProvider

    class Endpoint:
        async def create(self, *args, **kwargs):
            return LLMResponse(
                content=[], model="test", stop_reason=FinishReason.END_TURN, usage=usage
            )

    budget, repo = budget_for(tmp_path)
    provider = BudgetedProvider(
        Endpoint(),
        budget,
        output_limit=100,
        pricing=ModelPricing(
            input_cny_per_million=Decimal("1000"),
            output_cny_per_million=Decimal("4000"),
        ),
    )
    await provider.create([])
    ledger = repo.load(budget.run_id).ledger
    reservation = ledger.reservations[0]
    assert reservation.actual_cny == expected
    if expected is None:
        assert ledger.charged_cny == reservation.reserved_cny
        assert ledger.charged_cny > Decimal("0.40")
        assert ledger.has_unknown_cost
    else:
        assert ledger.charged_cny == Decimal("0.18")
        assert not ledger.has_unknown_cost
