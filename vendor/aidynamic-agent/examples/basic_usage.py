"""
Agent Framework - Usage Examples

Demonstrates the main use cases:
1. Quick start with OpenAI provider
2. Custom tools
3. Multi-agent (parent + sub-agent)
4. Hooks (intercept tool calls)
5. State persistence
6. Streaming responses
"""

import asyncio
import os

# ---------------------------------------------------------------------------
# Example 1: Quick Start with OpenAI Provider
# ---------------------------------------------------------------------------


async def example_quick_start():
    """Minimal example: create a parent agent and run a task."""
    from aidynamic_agent.agents.factory import AgentFactory
    from aidynamic_agent.llm.providers.openai import OpenAIProvider
    from aidynamic_agent.tools.registry import ToolRegistry

    # Create provider (uses OPENAI_API_KEY env var)
    provider = OpenAIProvider(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini",
    )

    # Create agent via factory
    registry = ToolRegistry()
    factory = AgentFactory(
        provider=provider,
        tool_registry=registry,
    )
    agent = factory.create_parent_agent(
        system_prompt="You are a helpful assistant.",
    )

    # Run a task
    result = await agent.run("What is 2 + 2?")
    print(f"Response: {result.text}")
    print(f"Tokens used: {result.tokens_used}")
    print(f"Loops: {result.loops_used}")

    await provider.close()


# ---------------------------------------------------------------------------
# Example 2: Custom Tool
# ---------------------------------------------------------------------------


async def example_custom_tool():
    """Register a custom tool and use it in the agent loop."""
    from aidynamic_agent.agents.factory import AgentFactory
    from aidynamic_agent.llm.providers.openai import OpenAIProvider
    from aidynamic_agent.tools.base import Tool, ToolResult
    from aidynamic_agent.tools.registry import ToolRegistry

    class WeatherTool(Tool):
        """Get current weather for a city."""

        name = "get_weather"
        description = "Get the current weather for a given city."
        parameters = {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["city"],
        }

        async def execute(self, city: str, **kwargs) -> ToolResult:
            # In real usage, call a weather API here
            return ToolResult(content=f"The weather in {city} is sunny, 25°C")

    class CalculatorTool(Tool):
        """Simple calculator."""

        name = "calc"
        description = "Evaluate a math expression."
        parameters = {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression"},
            },
            "required": ["expression"],
        }

        async def execute(self, expression: str, **kwargs) -> ToolResult:
            try:
                result = eval(expression, {"__builtins__": {}}, {})
                return ToolResult(content=str(result))
            except Exception as e:
                return ToolResult(content=f"Error: {e}", success=False)

    provider = OpenAIProvider(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini",
    )

    # Register tools
    registry = ToolRegistry()
    registry.register(WeatherTool())
    registry.register(CalculatorTool())

    factory = AgentFactory(provider=provider, tool_registry=registry)
    agent = factory.create_parent_agent(
        system_prompt="You have access to weather and calculator tools.",
    )

    result = await agent.run("What's the weather in Beijing? Also calculate 15 * 23.")
    print(f"Response: {result.text}")

    await provider.close()


# ---------------------------------------------------------------------------
# Example 3: Multi-Agent (Parent + Sub-Agent)
# ---------------------------------------------------------------------------


async def example_multi_agent():
    """Parent agent delegates work to a sub-agent."""
    from aidynamic_agent.agents.factory import AgentFactory
    from aidynamic_agent.llm.providers.openai import OpenAIProvider
    from aidynamic_agent.tools.registry import ToolRegistry

    provider = OpenAIProvider(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini",
    )

    registry = ToolRegistry()
    factory = AgentFactory(provider=provider, tool_registry=registry)

    # Parent agent that can create sub-agents (not executed in this demo)
    factory.create_parent_agent(
        system_prompt=(
            "You are a project manager. Delegate detailed tasks to sub-agents " "when appropriate."
        ),
    )

    # Sub-agent with tighter limits and filtered tools
    sub = factory.create_sub_agent(
        system_prompt=(
            "You are a code reviewer. Analyze the given code and provide "
            "specific, actionable feedback."
        ),
    )

    # In practice, the parent agent calls create_subagent tool which
    # internally creates a sub-agent via the factory. Here we just
    # demonstrate the sub-agent API directly:
    result = await sub.run("Review: def foo(x): return x + 1")
    print(f"Sub-agent response: {result.text}")

    await provider.close()


# ---------------------------------------------------------------------------
# Example 4: Hooks (Intercept Tool Calls)
# ---------------------------------------------------------------------------


async def example_hooks():
    """Use hooks to intercept and approve/deny tool calls."""
    from aidynamic_agent.agents.factory import AgentFactory
    from aidynamic_agent.hooks.base import HookContext, HookEvent, HookExecutor
    from aidynamic_agent.llm.providers.openai import OpenAIProvider
    from aidynamic_agent.tools.registry import ToolRegistry

    class ApprovalHook(HookExecutor):
        """Require approval before executing dangerous tools."""

        DANGEROUS_TOOLS = {"bash", "file_write"}

        async def execute(self, event: HookEvent, context: dict) -> HookContext:
            if event == HookEvent.BEFORE_TOOL_EXEC:
                tool_name = context.get("tool_name", "")
                if tool_name in self.DANGEROUS_TOOLS:
                    # In a real app, prompt user for approval
                    print(f"[HOOK] Blocking '{tool_name}' - requires approval")
                    return HookContext(blocked=True)
            return HookContext(blocked=False)

    provider = OpenAIProvider(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini",
    )

    registry = ToolRegistry()
    hook = ApprovalHook()
    factory = AgentFactory(
        provider=provider,
        tool_registry=registry,
        hook_executor=hook,
    )
    agent = factory.create_parent_agent()

    result = await agent.run("List the files in the current directory.")
    print(f"Response: {result.text}")

    await provider.close()


# ---------------------------------------------------------------------------
# Example 5: State Persistence
# ---------------------------------------------------------------------------


async def example_state_persistence():
    """Save and resume agent conversation state."""
    from aidynamic_agent.agents.factory import AgentFactory
    from aidynamic_agent.llm.providers.openai import OpenAIProvider
    from aidynamic_agent.managers.state import StateManager
    from aidynamic_agent.tools.registry import ToolRegistry

    state_path = "agent_state.json"

    provider = OpenAIProvider(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini",
    )

    registry = ToolRegistry()
    state_manager = StateManager(state_path=state_path)
    factory = AgentFactory(provider=provider, tool_registry=registry)

    agent = factory.create_parent_agent(
        system_prompt="You remember our conversation history.",
    )

    # Try to resume from saved state
    try:
        context = await state_manager.load()
        agent.context = context
        print("[INFO] Resumed from saved state")
    except FileNotFoundError:
        print("[INFO] No saved state, starting fresh")

    result = await agent.run("Hello, what have we talked about before?")
    print(f"Response: {result.text}")

    # Save state after the conversation
    await state_manager.save(agent.context)
    print("[INFO] State saved")

    await provider.close()


# ---------------------------------------------------------------------------
# Example 6: Streaming Responses
# ---------------------------------------------------------------------------


async def example_streaming():
    """Stream tokens from the LLM as they are generated."""
    from aidynamic_agent.agents.factory import AgentFactory
    from aidynamic_agent.core.message import ContentType
    from aidynamic_agent.llm.providers.openai import OpenAIProvider
    from aidynamic_agent.tools.registry import ToolRegistry

    provider = OpenAIProvider(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini",
    )

    registry = ToolRegistry()
    factory = AgentFactory(provider=provider, tool_registry=registry)
    agent = factory.create_parent_agent()

    print("Streaming response:")
    async for chunk in provider.stream(
        messages=agent.context.messages,
        tools=agent.tool_registry.to_definition(),
    ):
        if chunk.type == ContentType.TEXT and chunk.delta:
            print(chunk.delta, end="", flush=True)
        elif chunk.finish_reason:
            print(f"\n\n[Finished: {chunk.finish_reason}]")

    await provider.close()


# ---------------------------------------------------------------------------
# Run all examples
# ---------------------------------------------------------------------------


async def main():
    examples = {
        "1": ("Quick Start", example_quick_start),
        "2": ("Custom Tool", example_custom_tool),
        "3": ("Multi-Agent", example_multi_agent),
        "4": ("Hooks", example_hooks),
        "5": ("State Persistence", example_state_persistence),
        "6": ("Streaming", example_streaming),
    }

    print("Agent Framework Examples")
    print("=" * 40)
    for key, (name, _) in examples.items():
        print(f"  {key}. {name}")
    print("  a. Run all")
    print()

    choice = input("Select example (1-6, a): ").strip().lower()

    if choice == "a":
        for name, func in examples.values():
            print(f"\n{'=' * 40}")
            print(f"Running: {name}")
            print(f"{'=' * 40}")
            try:
                await func()
            except Exception as e:
                print(f"[ERROR] {e}")
    elif choice in examples:
        name, func = examples[choice]
        print(f"\n{'=' * 40}")
        print(f"Running: {name}")
        print(f"{'=' * 40}")
        try:
            await func()
        except Exception as e:
            print(f"[ERROR] {e}")
    else:
        print("Invalid choice")


if __name__ == "__main__":
    asyncio.run(main())
