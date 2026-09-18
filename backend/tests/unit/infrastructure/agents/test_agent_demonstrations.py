"""few-shot 示范必须真正进入 Agent 上下文，而不只是写在提示词里。"""

import pytest


def turns():
    from sector_pulse.domain.llm import PromptTurn

    return (
        PromptTurn(role="user", text="现在该做什么？"),
        PromptTurn(
            role="assistant",
            text="先读服务端状态。",
            tool_call_id="demo-1",
            tool_name="inspect_tasks",
        ),
        PromptTurn(role="tool", tool_call_id="demo-1", text="[]"),
    )


def test_demonstration_turns_become_paired_framework_messages() -> None:
    from aidynamic_agent.core.message import Role, ToolResultBlock, ToolUseBlock
    from sector_pulse.infrastructure.agents.roles import demonstration_messages

    messages = demonstration_messages(turns())
    # 工具结果按框架自身的约定写成 user 轮，适配器会再转成 tool 轮。
    assert [message.role for message in messages] == [Role.USER, Role.ASSISTANT, Role.USER]
    assert [type(block).__name__ for block in messages[1].content] == [
        "TextBlock",
        "ToolUseBlock",
    ]
    assert isinstance(messages[1].content[1], ToolUseBlock)
    assert messages[1].content[1].tool_call_id == "demo-1"
    assert isinstance(messages[2].content[0], ToolResultBlock)
    assert messages[2].content[0].tool_call_id == "demo-1"


def test_demonstrations_without_tool_calls_keep_a_single_text_block() -> None:
    from aidynamic_agent.core.message import Role
    from sector_pulse.domain.llm import PromptTurn
    from sector_pulse.infrastructure.agents.roles import demonstration_messages

    messages = demonstration_messages((PromptTurn(role="assistant", text="先读状态。"),))
    assert messages[0].role is Role.ASSISTANT
    assert [type(block).__name__ for block in messages[0].content] == ["TextBlock"]


@pytest.mark.asyncio
async def test_example_messages_are_sent_after_the_system_message() -> None:
    from aidynamic_agent.agents.factory import AgentFactory
    from aidynamic_agent.core.agent import AgentConfig
    from aidynamic_agent.core.message import FinishReason, Role, TextBlock
    from aidynamic_agent.llm.base import LLMResponse
    from sector_pulse.infrastructure.agents.roles import demonstration_messages

    calls: list[list] = []

    class Endpoint:
        async def create(self, messages, tools=None, **kwargs):
            calls.append(list(messages))
            return LLMResponse(
                content=[TextBlock(text="done")],
                model="test",
                stop_reason=FinishReason.END_TURN,
                usage={"total_tokens": 5},
            )

    factory = AgentFactory(Endpoint(), config=AgentConfig(max_retries=1))
    agent = factory.create_parent_agent(
        system_prompt="系统提示", example_messages=demonstration_messages(turns())
    )
    await agent.run("真实任务")

    assert [message.role for message in calls[0]] == [
        Role.SYSTEM,
        Role.USER,
        Role.ASSISTANT,
        Role.USER,
        Role.USER,
    ]
    assert calls[0][4].content[0].text == "真实任务"


@pytest.mark.asyncio
async def test_agents_without_examples_keep_the_original_context() -> None:
    from aidynamic_agent.agents.factory import AgentFactory
    from aidynamic_agent.core.agent import AgentConfig
    from aidynamic_agent.core.message import FinishReason, Role, TextBlock
    from aidynamic_agent.llm.base import LLMResponse

    calls: list[list] = []

    class Endpoint:
        async def create(self, messages, tools=None, **kwargs):
            calls.append(list(messages))
            return LLMResponse(
                content=[TextBlock(text="done")],
                model="test",
                stop_reason=FinishReason.END_TURN,
                usage={"total_tokens": 5},
            )

    factory = AgentFactory(Endpoint(), config=AgentConfig(max_retries=1))
    await factory.create_parent_agent(system_prompt="系统提示").run("真实任务")

    assert [message.role for message in calls[0]] == [Role.SYSTEM, Role.USER]


def test_shipped_role_prompts_carry_pairable_demonstrations() -> None:
    """真实提示词一旦破坏调用与结果的成对关系，必须在加载阶段就失败。"""
    from pathlib import Path

    from aidynamic_agent.core.message import Role, ToolUseBlock
    from sector_pulse.infrastructure.agents.roles import demonstration_messages
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry

    registry = PromptRegistry(Path(__file__).resolve().parents[5] / "config" / "prompts")
    for prompt_id in (
        "orchestration_a0",
        "orchestration_a1",
        "orchestration_a2",
        "orchestration_a3",
        "orchestration_a4",
    ):
        prompt = registry.get(prompt_id)
        messages = demonstration_messages(prompt.demonstrations)
        assert messages, f"{prompt_id} has no demonstration"
        # 最后一条必须是工具结果：示范不能以纯文字收尾，否则会教出提前结束。
        assert messages[-1].role is Role.USER
        called = {
            block.tool_call_id
            for message in messages
            if message.role is Role.ASSISTANT
            for block in message.content
            if isinstance(block, ToolUseBlock)
        }
        assert called, f"{prompt_id} demonstrates no tool call"
