"""Tests for agent/core/context.py - AgentContext, CompactConfig, ToolResultSummary."""

import pytest

from aidynamic_agent.core.context import AgentContext, CompactConfig, ToolResultSummary
from aidynamic_agent.core.message import Message, Role, TextBlock, ToolResultBlock

# --- CompactConfig Tests ---


class TestCompactConfig:
    """Test CompactConfig defaults and customization."""

    def test_default_trigger_token_threshold(self):
        config = CompactConfig()
        assert config.trigger_token_threshold == 80000

    def test_default_preserve_recent_count(self):
        config = CompactConfig()
        assert config.preserve_recent_count == 5

    def test_custom_trigger_token_threshold(self):
        config = CompactConfig(trigger_token_threshold=50000)
        assert config.trigger_token_threshold == 50000

    def test_custom_preserve_recent_count(self):
        config = CompactConfig(preserve_recent_count=10)
        assert config.preserve_recent_count == 10


# --- ToolResultSummary Tests ---


class TestToolResultSummary:
    """Test ToolResultSummary creation and to_compact_string."""

    def test_create_summary_success(self):
        summary = ToolResultSummary(
            tool_name="search",
            tool_call_id="call_123",
            success=True,
            brief="[Result: 500 chars]",
        )
        assert summary.tool_name == "search"
        assert summary.tool_call_id == "call_123"
        assert summary.success is True
        assert summary.brief == "[Result: 500 chars]"
        assert summary.history_key is None

    def test_create_summary_with_history_key(self):
        summary = ToolResultSummary(
            tool_name="read_file",
            tool_call_id="call_456",
            success=True,
            brief="[Result: 1200 chars]",
            history_key="hist_key_1",
        )
        assert summary.history_key == "hist_key_1"

    def test_create_summary_failure(self):
        summary = ToolResultSummary(
            tool_name="write_file",
            tool_call_id="call_789",
            success=False,
            brief="[Result: 50 chars]",
        )
        assert summary.success is False

    def test_to_compact_string_success(self):
        summary = ToolResultSummary(
            tool_name="search",
            tool_call_id="call_123",
            success=True,
            brief="[Result: 500 chars]",
        )
        result = summary.to_compact_string()
        assert "Tool: search" in result
        assert "Success: True" in result
        assert "Brief: [Result: 500 chars]" in result

    def test_to_compact_string_failure(self):
        summary = ToolResultSummary(
            tool_name="write_file",
            tool_call_id="call_789",
            success=False,
            brief="[Result: 50 chars]",
        )
        result = summary.to_compact_string()
        assert "Success: False" in result


# --- AgentContext Initialization Tests ---


class TestAgentContextInitialization:
    """Test AgentContext default state."""

    def test_default_messages_empty(self):
        ctx = AgentContext()
        assert ctx.messages == []

    def test_default_recent_files_empty(self):
        ctx = AgentContext()
        assert ctx.recent_files == []

    def test_default_total_tokens_zero(self):
        ctx = AgentContext()
        assert ctx.total_tokens == 0

    def test_default_has_compacted_false(self):
        ctx = AgentContext()
        assert ctx.has_compacted is False

    def test_default_last_summary_empty(self):
        ctx = AgentContext()
        assert ctx.last_summary == ""

    def test_default_compact_config(self):
        ctx = AgentContext()
        assert isinstance(ctx.compact_config, CompactConfig)

    def test_default_history_store_none(self):
        ctx = AgentContext()
        assert ctx.history_store is None

    def test_custom_compact_config(self):
        config = CompactConfig(trigger_token_threshold=10000, preserve_recent_count=3)
        ctx = AgentContext(compact_config=config)
        assert ctx.compact_config.trigger_token_threshold == 10000
        assert ctx.compact_config.preserve_recent_count == 3


# --- AgentContext.add_message Tests ---


class TestAddMessage:
    """Test add_message behavior."""

    @pytest.mark.asyncio
    async def test_add_message_appends(self):
        ctx = AgentContext()
        msg = Message.from_text(Role.USER, "hello")
        await ctx.add_message(msg)
        assert len(ctx.messages) == 1
        assert ctx.messages[0] == msg

    @pytest.mark.asyncio
    async def test_add_message_multiple(self):
        ctx = AgentContext()
        msg1 = Message.from_text(Role.USER, "hello")
        msg2 = Message.from_text(Role.ASSISTANT, "hi there")
        await ctx.add_message(msg1)
        await ctx.add_message(msg2)
        assert len(ctx.messages) == 2

    @pytest.mark.asyncio
    async def test_add_message_updates_token_count(self):
        ctx = AgentContext()
        msg = Message(
            role=Role.ASSISTANT,
            content=[TextBlock(text="response")],
            raw_response={"usage": {"total_tokens": 100}},
        )
        await ctx.add_message(msg)
        assert ctx.total_tokens == 100

    @pytest.mark.asyncio
    async def test_add_message_accumulates_tokens(self):
        ctx = AgentContext()
        msg1 = Message(
            role=Role.USER,
            content=[TextBlock(text="hello")],
            raw_response={"usage": {"total_tokens": 50}},
        )
        msg2 = Message(
            role=Role.ASSISTANT,
            content=[TextBlock(text="hi")],
            raw_response={"usage": {"total_tokens": 75}},
        )
        await ctx.add_message(msg1)
        await ctx.add_message(msg2)
        assert ctx.total_tokens == 125

    @pytest.mark.asyncio
    async def test_add_message_no_raw_response(self):
        ctx = AgentContext()
        msg = Message.from_text(Role.USER, "hello")
        await ctx.add_message(msg)
        assert ctx.total_tokens == 0

    @pytest.mark.asyncio
    async def test_add_message_raw_response_no_usage(self):
        ctx = AgentContext()
        msg = Message(
            role=Role.ASSISTANT,
            content=[TextBlock(text="hi")],
            raw_response={"id": "msg_123"},
        )
        await ctx.add_message(msg)
        assert ctx.total_tokens == 0


# --- AgentContext.compact_if_needed Tests ---


class TestCompactIfNeeded:
    """Test compaction trigger logic."""

    @pytest.mark.asyncio
    async def test_no_compaction_below_threshold(self):
        ctx = AgentContext()
        msg = Message(
            role=Role.ASSISTANT,
            content=[TextBlock(text="response")],
            raw_response={"usage": {"total_tokens": 50000}},
        )
        await ctx.add_message(msg)
        result = await ctx.compact_if_needed()
        assert result is False
        assert ctx.has_compacted is False

    @pytest.mark.asyncio
    async def test_compaction_at_threshold(self):
        ctx = AgentContext(compact_config=CompactConfig(trigger_token_threshold=100))
        msg = Message(
            role=Role.ASSISTANT,
            content=[TextBlock(text="response")],
            raw_response={"usage": {"total_tokens": 100}},
        )
        await ctx.add_message(msg)
        result = await ctx.compact_if_needed()
        assert result is True
        assert ctx.has_compacted is True

    @pytest.mark.asyncio
    async def test_compaction_above_threshold(self):
        ctx = AgentContext(compact_config=CompactConfig(trigger_token_threshold=100))
        msg = Message(
            role=Role.ASSISTANT,
            content=[TextBlock(text="response")],
            raw_response={"usage": {"total_tokens": 200}},
        )
        await ctx.add_message(msg)
        result = await ctx.compact_if_needed()
        assert result is True
        assert ctx.has_compacted is True


# --- AgentContext._do_compact Tests ---


class TestDoCompact:
    """Test compaction logic: preserves recent tool results, summarizes older ones."""

    @pytest.mark.asyncio
    async def test_compaction_preserves_recent_tool_results(self):
        """Compaction should preserve the last N tool results."""
        config = CompactConfig(trigger_token_threshold=10, preserve_recent_count=2)
        ctx = AgentContext(compact_config=config)

        # Add 4 tool results
        for i in range(4):
            msg = Message(
                role=Role.ASSISTANT,
                content=[
                    ToolResultBlock(
                        tool_call_id=f"call_{i}",
                        tool_result_content=f"result {i}" * 100,
                        is_error=False,
                        history_key=f"hist_{i}",
                        metadata={"tool_name": "search", "history_key": f"hist_{i}"},
                    )
                ],
                raw_response={"usage": {"total_tokens": 50}},
            )
            await ctx.add_message(msg)

        await ctx.compact_if_needed()

        # Should preserve the last 2 tool results
        tool_results = []
        for msg in ctx.messages:
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    tool_results.append(block)

        assert len(tool_results) == 2
        # The preserved ones should be the most recent
        assert tool_results[0].tool_call_id == "call_2"
        assert tool_results[1].tool_call_id == "call_3"

    @pytest.mark.asyncio
    async def test_compaction_summarizes_older_results(self):
        """Compaction should replace older tool results with summaries."""
        config = CompactConfig(trigger_token_threshold=10, preserve_recent_count=1)
        ctx = AgentContext(compact_config=config)

        # Add 3 tool results (2 will be summarized, 1 preserved)
        for i in range(3):
            msg = Message(
                role=Role.ASSISTANT,
                content=[
                    ToolResultBlock(
                        tool_call_id=f"call_{i}",
                        tool_result_content=f"result {i}" * 50,
                        is_error=(i == 1),  # Second one is an error
                        history_key=f"hist_{i}",
                        metadata={"tool_name": "search", "history_key": f"hist_{i}"},
                    )
                ],
                raw_response={"usage": {"total_tokens": 50}},
            )
            await ctx.add_message(msg)

        await ctx.compact_if_needed()

        # Should have 1 ToolResultBlock (preserved) + 2 TextBlock summaries
        text_blocks = []
        tool_blocks = []
        for msg in ctx.messages:
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    tool_blocks.append(block)
                elif isinstance(block, TextBlock):
                    text_blocks.append(block)

        assert len(tool_blocks) == 1  # Preserved: call_2
        assert len(text_blocks) == 2  # Summarized: call_0, call_1
        assert tool_blocks[0].tool_call_id == "call_2"

    @pytest.mark.asyncio
    async def test_compaction_summary_contains_tool_name(self):
        """Summary text should contain the tool name."""
        config = CompactConfig(trigger_token_threshold=10, preserve_recent_count=1)
        ctx = AgentContext(compact_config=config)

        msg = Message(
            role=Role.ASSISTANT,
            content=[
                ToolResultBlock(
                    tool_call_id="call_old",
                    tool_result_content="old result data",
                    is_error=False,
                    metadata={"tool_name": "read_file"},
                )
            ],
            raw_response={"usage": {"total_tokens": 50}},
        )
        await ctx.add_message(msg)

        await ctx.compact_if_needed()

        # Check summary in text blocks
        for m in ctx.messages:
            for block in m.content:
                if isinstance(block, TextBlock):
                    assert "read_file" in block.text

    @pytest.mark.asyncio
    async def test_compaction_error_result_summary(self):
        """Error tool results should show Success: False in summary."""
        config = CompactConfig(trigger_token_threshold=10, preserve_recent_count=1)
        ctx = AgentContext(compact_config=config)

        msg = Message(
            role=Role.ASSISTANT,
            content=[
                ToolResultBlock(
                    tool_call_id="call_err",
                    tool_result_content="error data",
                    is_error=True,
                    metadata={"tool_name": "write_file"},
                )
            ],
            raw_response={"usage": {"total_tokens": 50}},
        )
        await ctx.add_message(msg)

        await ctx.compact_if_needed()

        # Check summary shows failure
        for m in ctx.messages:
            for block in m.content:
                if isinstance(block, TextBlock):
                    assert "Success: False" in block.text
