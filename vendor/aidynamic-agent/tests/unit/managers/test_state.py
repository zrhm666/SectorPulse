"""Tests for agent/managers/state.py - StateManager."""

import json
import os

import pytest

from aidynamic_agent.core.context import AgentContext
from aidynamic_agent.core.message import Message, Role, TextBlock
from aidynamic_agent.managers.state import StateManager


@pytest.fixture
def tmp_state_path(tmp_path):
    return str(tmp_path / "agent_state.json")


class TestStateManagerSave:
    """Test saving context to JSON."""

    @pytest.mark.asyncio
    async def test_save_writes_json_file(self, tmp_state_path):
        manager = StateManager(state_path=tmp_state_path)
        ctx = AgentContext()
        await manager.save(ctx)
        assert os.path.exists(tmp_state_path)

    @pytest.mark.asyncio
    async def test_save_writes_valid_json(self, tmp_state_path):
        manager = StateManager(state_path=tmp_state_path)
        ctx = AgentContext()
        await manager.save(ctx)
        # Should not raise
        data = json.loads(open(tmp_state_path).read())
        assert "messages" in data
        assert "total_tokens" in data
        assert "has_compacted" in data
        assert "last_summary" in data

    @pytest.mark.asyncio
    async def test_save_with_messages(self, tmp_state_path):
        manager = StateManager(state_path=tmp_state_path)
        ctx = AgentContext()
        msg = Message.from_text(Role.USER, "hello world")
        ctx.messages.append(msg)
        ctx.total_tokens = 100
        await manager.save(ctx)

        data = json.loads(open(tmp_state_path).read())
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["text"] == "hello world"
        assert data["total_tokens"] == 100

    @pytest.mark.asyncio
    async def test_save_with_compaction_state(self, tmp_state_path):
        manager = StateManager(state_path=tmp_state_path)
        ctx = AgentContext(
            has_compacted=True,
            last_summary="Conversation summarized",
        )
        await manager.save(ctx)

        data = json.loads(open(tmp_state_path).read())
        assert data["has_compacted"] is True
        assert data["last_summary"] == "Conversation summarized"


class TestStateManagerLoad:
    """Test loading context from JSON."""

    @pytest.mark.asyncio
    async def test_load_file_not_found(self, tmp_state_path):
        manager = StateManager(state_path=tmp_state_path)
        with pytest.raises(FileNotFoundError, match="State file not found"):
            await manager.load()

    @pytest.mark.asyncio
    async def test_load_reconstructs_context(self, tmp_state_path):
        manager = StateManager(state_path=tmp_state_path)
        # First save
        ctx = AgentContext(
            messages=[Message.from_text(Role.USER, "test message")],
            total_tokens=50,
            has_compacted=True,
            last_summary="summary text",
        )
        await manager.save(ctx)

        # Then load
        loaded = await manager.load()
        assert len(loaded.messages) == 1
        assert loaded.messages[0].role == Role.USER
        assert loaded.messages[0].content[0].text == "test message"
        assert loaded.total_tokens == 50
        assert loaded.has_compacted is True
        assert loaded.last_summary == "summary text"

    @pytest.mark.asyncio
    async def test_load_multiple_messages(self, tmp_state_path):
        manager = StateManager(state_path=tmp_state_path)
        ctx = AgentContext()
        ctx.messages.append(Message.from_text(Role.USER, "hello"))
        ctx.messages.append(Message.from_text(Role.ASSISTANT, "hi there"))
        ctx.total_tokens = 200
        await manager.save(ctx)

        loaded = await manager.load()
        assert len(loaded.messages) == 2
        assert loaded.messages[0].role == Role.USER
        assert loaded.messages[1].role == Role.ASSISTANT

    @pytest.mark.asyncio
    async def test_load_with_provider(self, tmp_state_path):
        manager = StateManager(state_path=tmp_state_path)
        ctx = AgentContext()
        ctx.messages.append(
            Message(
                role=Role.ASSISTANT,
                content=[TextBlock(text="response")],
                provider="openai",
            )
        )
        await manager.save(ctx)

        loaded = await manager.load()
        assert loaded.messages[0].provider == "openai"

    @pytest.mark.asyncio
    async def test_load_empty_messages(self, tmp_state_path):
        manager = StateManager(state_path=tmp_state_path)
        data = {"messages": [], "total_tokens": 0, "has_compacted": False, "last_summary": ""}
        open(tmp_state_path, "w").write(json.dumps(data))

        loaded = await manager.load()
        assert loaded.messages == []
        assert loaded.total_tokens == 0


class TestStateManagerRoundTrip:
    """Test save-then-load round trips."""

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_state(self, tmp_state_path):
        manager = StateManager(state_path=tmp_state_path)
        original = AgentContext(
            messages=[Message.from_text(Role.USER, "query")],
            total_tokens=75,
            has_compacted=False,
            last_summary="",
        )
        await manager.save(original)
        loaded = await manager.load()

        assert len(loaded.messages) == len(original.messages)
        assert loaded.messages[0].role == original.messages[0].role
        assert loaded.total_tokens == original.total_tokens
        assert loaded.has_compacted == original.has_compacted
        assert loaded.last_summary == original.last_summary
