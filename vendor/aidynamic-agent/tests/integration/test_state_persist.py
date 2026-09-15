"""Integration tests for state persistence."""

import pytest

from aidynamic_agent.core.context import AgentContext
from aidynamic_agent.core.message import Message, Role
from aidynamic_agent.managers.state import StateManager


class TestStatePersist:
    """Test state save/load cycle."""

    @pytest.mark.asyncio
    async def test_save_and_load(self, tmp_path):
        """State should survive a save/load cycle."""
        state_file = str(tmp_path / "state.json")
        manager = StateManager(state_path=state_file)

        ctx = AgentContext()
        await ctx.add_message(Message.from_text(Role.USER, "Hello"))
        await ctx.add_message(Message.from_text(Role.ASSISTANT, "Hi there!"))
        ctx.total_tokens = 100

        await manager.save(ctx)

        # Load into a new context
        manager2 = StateManager(state_path=state_file)
        loaded_ctx = await manager2.load()

        assert len(loaded_ctx.messages) == 2
        assert loaded_ctx.total_tokens == 100
        assert loaded_ctx.messages[0].role == Role.USER

    @pytest.mark.asyncio
    async def test_load_nonexistent_raises(self, tmp_path):
        """Loading from a non-existent file should raise FileNotFoundError."""
        state_file = str(tmp_path / "nonexistent.json")
        manager = StateManager(state_path=state_file)
        with pytest.raises(FileNotFoundError):
            await manager.load()

    @pytest.mark.asyncio
    async def test_save_and_load_empty_context(self, tmp_path):
        """Save and load an empty context."""
        state_file = str(tmp_path / "empty.json")
        manager = StateManager(state_path=state_file)

        ctx = AgentContext()
        await manager.save(ctx)

        manager2 = StateManager(state_path=state_file)
        loaded_ctx = await manager2.load()

        assert len(loaded_ctx.messages) == 0
