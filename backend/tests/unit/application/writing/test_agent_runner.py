import asyncio
from types import SimpleNamespace

from sector_pulse.application.writing.agent_runner import run_agent_loop
from sector_pulse.domain.llm import LLMResult, LLMStatus, MoneyCny, TokenUsage
from sector_pulse.domain.writing.agent_execution import AgentDecision, AgentLimits, ToolObservation

from backend.tests.integration.test_phase1b_pipeline import contexts, fixture_responses, gate


async def run(actions, *, limits=None, tools=None, allowed=True):
    requests, steps, invocations = [], [], []

    class Model:
        async def generate_structured(self, request):
            requests.append(request)
            decision = AgentDecision.model_validate({"next_action": actions[len(requests) - 1]})
            return LLMResult(
                status=LLMStatus.SUCCESS,
                data=decision,
                usage=TokenUsage(total_tokens=10),
                estimated_cost_cny=MoneyCny(amount="0.01"),
            )

    class Tools:
        async def execute(self, action):
            return ToolObservation(
                action=action.action, status="success", data={"document_id": "d1"}
            )

    async def admit(request):
        return allowed

    result = await run_agent_loop(
        contexts()[0],
        gate(contexts()[0]),
        Model(),
        tools or Tools(),
        model="test",
        limits=limits or AgentLimits(),
        admit=admit,
        record_invocation=invocations.append,
        record_step=lambda index, step: steps.append((index, step)),
    )
    return SimpleNamespace(result=result, requests=requests, steps=steps, invocations=invocations)


def finish():
    return {"action": "finish", "card": fixture_responses()["sector-analysis:industry-1"]}


async def test_model_decides_tools_and_sees_previous_results():
    output = await run(
        [
            {"action": "search_news", "query": "新闻"},
            {"action": "read_news_detail", "document_id": "d1"},
            {"action": "inspect_market"},
            finish(),
        ]
    )
    assert output.result.stop_reason == "finished"
    assert output.result.tool_calls == 3
    assert len(output.invocations) == 4
    assert output.requests[0].user_payload["observations"] == []
    assert output.requests[1].user_payload["observations"][0]["observation"]["data"] == {
        "document_id": "d1"
    }
    assert output.result.card.sector_id == contexts()[0].sector_id


async def test_model_can_finish_without_tool_calls():
    output = await run([finish()])
    assert output.result.stop_reason == "finished"
    assert output.result.tool_calls == 0


async def test_repeated_tool_request_stops_no_progress_loop():
    output = await run([{"action": "inspect_market"}, {"action": "inspect_market"}])
    assert output.result.stop_reason == "AGENT_NO_PROGRESS"
    assert output.result.tool_calls == 1


async def test_budget_rejected_before_model_call():
    output = await run([], allowed=False)
    assert output.result.stop_reason == "AGENT_BUDGET_EXHAUSTED"
    assert output.requests == []


async def test_time_limit_bounds_tool_execution():
    class Slow:
        async def execute(self, action):
            await asyncio.sleep(1)

    output = await run(
        [{"action": "inspect_market"}], tools=Slow(), limits=AgentLimits(timeout_seconds=0.01)
    )
    assert output.result.stop_reason == "AGENT_TIME_LIMIT"


async def test_tool_limit_stops_before_tool_execution():
    output = await run([{"action": "inspect_market"}], limits=AgentLimits(max_tool_calls=0))
    assert output.result.stop_reason == "AGENT_TOOL_LIMIT"
    assert output.result.tool_calls == 0
