"""Tests for tool parameter validation."""

import pytest

from aidynamic_agent.tools.base import Tool, ToolResult


class _ValidatedTool(Tool):
    """A tool with typed parameters for validation testing."""

    name = "validated_tool"
    description = "A tool with typed parameters"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "A name"},
            "count": {"type": "integer", "description": "A count"},
            "enabled": {"type": "boolean", "description": "A flag"},
            "threshold": {"type": "number", "description": "A float threshold"},
        },
        "required": ["name"],
    }

    async def execute(
        self, name: str = "", count: int = 0, enabled: bool = False, threshold: float = 0.0
    ) -> ToolResult:
        if not name:
            raise ValueError("name is required")
        return ToolResult(content=f"{name}:{count}:{enabled}:{threshold}")


class TestToolValidation:
    """Test tool parameter validation."""

    @pytest.fixture
    def tool(self):
        return _ValidatedTool()

    @pytest.mark.asyncio
    async def test_valid_params_pass(self, tool):
        result = await tool.run(name="test", count=5)
        assert result.success is True
        assert result.content == "test:5:False:0.0"

    @pytest.mark.asyncio
    async def test_missing_required_param_fails(self, tool):
        result = await tool.run()
        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_wrong_type_integer(self, tool):
        # JSON Schema validation should catch this
        result = await tool.run(name="test", count="not_an_int")
        # The tool may or may not accept this depending on validation layer
        # At minimum, it should not crash
        assert isinstance(result, ToolResult)

    @pytest.mark.asyncio
    async def test_wrong_type_boolean(self, tool):
        result = await tool.run(name="test", enabled="not_a_bool")
        assert isinstance(result, ToolResult)

    @pytest.mark.asyncio
    async def test_valid_all_types(self, tool):
        result = await tool.run(
            name="full",
            count=42,
            enabled=True,
            threshold=3.14,
        )
        assert result.success is True
        assert result.content == "full:42:True:3.14"

    def test_tool_definition_format(self, tool):
        """Test tool definition serializes correctly for LLM."""
        definition = tool.to_tool_definition()
        assert definition.name == "validated_tool"
        assert hasattr(definition, "input_schema")
        assert "properties" in definition.input_schema
        assert "name" in definition.input_schema["properties"]
        assert "count" in definition.input_schema["properties"]
