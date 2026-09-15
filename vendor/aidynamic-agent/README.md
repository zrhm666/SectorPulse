# aidynamic-agent

A modular, extensible AI Agent framework with OOP design, multi-provider support,
and a plugin architecture for tools, hooks, and multi-agent workflows.

## Features

- **Unified Message Model**: Subclassed content blocks (`TextBlock`, `ToolUseBlock`,
  `ThinkingBlock`, etc.) with type-safe access and `FinishReason` enums.
- **LLM Provider Abstraction**: Swap between OpenAI, Anthropic, or any custom provider
  via the `LLMProvider` interface. Adapters handle protocol differences.
- **Plugin Tools**: Register custom tools by subclassing `Tool` with JSON Schema
  parameters. Tools support tags (e.g., `parent_only`) for access control.
- **Multi-Agent**: Parent agent can spawn sub-agents with filtered tool access and
  tighter limits (max_loops=10, timeout=120s).
- **Hook System**: Intercept tool calls, LLM responses, and agent lifecycle events
  for approval workflows, logging, or blocking.
- **State Persistence**: Save/restore conversation context as JSON.
- **Streaming**: Token-by-token streaming with `StreamChunk` dataclass.
- **Retry Logic**: Exponential backoff for transient LLM errors.

## Installation

### Using uv (recommended)

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
cd new_agent
uv sync

# Install with dev dependencies (pytest, etc.)
uv sync --all-extras
```

### Manual pip install

```bash
pip install -e ".[dev]"
```

## Quick Start

### Minimal Example

```python
import asyncio
from aidynamic_agent.llm.providers.openai import OpenAIProvider
from aidynamic_agent.agents.factory import AgentFactory
from aidynamic_agent.tools.registry import ToolRegistry

async def main():
    provider = OpenAIProvider(
        api_key="your-key",  # or set OPENAI_API_KEY env var
        model="gpt-4o-mini",
    )

    factory = AgentFactory(
        provider=provider,
        tool_registry=ToolRegistry(),
    )
    agent = factory.create_parent_agent(
        system_prompt="You are a helpful assistant.",
    )

    result = await agent.run("What is the capital of France?")
    print(result.text)
    print(f"Tokens: {result.tokens_used}, Loops: {result.loops_used}")

    await provider.close()

asyncio.run(main())
```

### Custom Tool

```python
from aidynamic_agent.tools.base import Tool, ToolResult

class WeatherTool(Tool):
    name = "get_weather"
    description = "Get weather for a city."
    parameters = {
        "type": "object",
        "properties": {
            "city": {"type": "string"},
        },
        "required": ["city"],
    }

    async def execute(self, city: str, **kwargs) -> ToolResult:
        # Call weather API here
        return ToolResult(content=f"Sunny, 25°C in {city}")

# Register it
registry = ToolRegistry()
registry.register(WeatherTool())

factory = AgentFactory(provider=provider, tool_registry=registry)
agent = factory.create_parent_agent()
result = await agent.run("What's the weather in Tokyo?")
```

### State Persistence

```python
from aidynamic_agent.managers.state import StateManager

state = StateManager(state_path="session.json")

# Save
await state.save(agent.context)

# Resume
context = await state.load()
agent.context = context
```

### Sub-Agent Creation

```python
# Sub-agents have filtered tools (no parent_only) and tighter limits
sub = factory.create_sub_agent(
    system_prompt="You are a code reviewer.",
)
result = await sub.run("Review this function: def foo(x): return x + 1")
```

## Project Structure

```
aidynamic_agent/
├── core/          # Message model, Agent base class, Context
├── llm/           # Provider abstraction, adapters, exceptions
│   └── providers/ # OpenAI, Anthropic implementations
├── tools/         # Tool base class, registry, context
│   └── builtins/  # Built-in tools (bash, file_ops, todo, etc.)
├── agents/        # Parent agent, Sub-agent, Factory
├── hooks/         # Hook system (before/after tool, LLM, etc.)
├── managers/      # State, skill, todo, history persistence
└── legacy/        # Backward compatibility adapter

tests/
├── unit/          # Isolated component tests
├── integration/   # Multi-component workflow tests
├── mocks/         # MockLLMProvider, mock tools
└── conftest.py    # Pytest fixtures

examples/
├── basic_usage.py           # Interactive examples (6 scenarios)
└── streaming_react_agent.py # Streaming ReAct agent with .env config
```

## Configuration

### Using .env File

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Supported environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `openai` | Provider name: `openai` or `anthropic` |
| `API_KEY` | *(required)* | Your API key |
| `BASE_URL` | *(empty)* | Custom endpoint (vLLM, Azure, etc.) |
| `MODEL` | `gpt-4o-mini` | Model name |
| `MAX_LOOPS` | `30` | Max agent loops per run |
| `MAX_TOKENS` | `8000` | Max tokens per LLM call |
| `TOTAL_TIMEOUT` | `300` | Total timeout in seconds |
| `TEMPERATURE` | `0.7` | Sampling temperature |
| `SYSTEM_PROMPT` | *(see .env)* | System prompt for the agent |

## Running Examples

```bash
# 1. Set up your .env first
cp .env.example .env
# Edit .env with your API key

# 2. Streaming ReAct Agent (reads .env, streams output)
uv run python examples/streaming_react_agent.py "What's 25 * 13?"

# 3. Interactive basic examples menu
uv run python examples/basic_usage.py
```

## Publishing

### Build and Publish to PyPI

Use the provided `publish.py` script to build and publish the package:

```bash
# Build and publish to private PyPI server
python publish.py

# Build only (without publishing)
python publish.py --build-only

# Publish only (without rebuilding)
python publish.py --publish-only

# With credentials
python publish.py -u your_username -p your_password

# Custom server URL
python publish.py --url http://your-server/
```

The script will:
1. Clean the `dist/` directory
2. Build wheel and source distribution using `uv build`
3. Upload to the PyPI server using `twine`

Default server: `http://192.168.1.15:8080/`

### Install from Private PyPI

```bash
pip install aidynamic-agent \
  --index-url http://192.168.1.15:8080/simple/ \
  --trusted-host 192.168.1.15
```

### Manual Build

```bash
# Build with uv
uv build

# Or with hatch
pip install hatch
hatch build

# Upload manually with twine
twine upload --repository-url http://192.168.1.15:8080/ dist/*
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Subclassed content blocks | Type safety, static analysis catches wrong field access |
| `FinishReason` enum over strings | No magic strings, IDE autocomplete |
| `content: list[...]` always | Simplifies adapter logic, no str/list branching |
| Provider is pure call, no retry | Single responsibility, retry belongs in Agent layer |
| Tools use JSON Schema params | Compatible with OpenAI/Anthropic tool calling APIs |
| Sequential tool execution | Simpler error handling, predictable ordering |
| AgentFactory owns config | Factory config propagates to created agents |

## License

MIT
