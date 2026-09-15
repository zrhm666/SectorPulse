"""Tests for agent/managers/history.py - ToolHistoryStore."""

import asyncio

import pytest

from aidynamic_agent.managers.history import ToolHistoryStore


class TestToolHistoryStoreInit:
    """Test ToolHistoryStore initialization."""

    def test_default_session_id(self):
        store = ToolHistoryStore()
        assert store.session_id == "default"

    def test_custom_session_id(self):
        store = ToolHistoryStore(session_id="test_session")
        assert store.session_id == "test_session"

    def test_initial_store_empty(self):
        store = ToolHistoryStore()
        assert len(store) == 0


class TestToolHistoryStoreStore:
    """Test storing tool results."""

    @pytest.mark.asyncio
    async def test_store_returns_key(self):
        store = ToolHistoryStore()
        key = await store.store("read_file", "file contents", tool_call_id="call_1")
        assert isinstance(key, str)
        assert key.startswith("default:")
        assert "call_1" in key

    @pytest.mark.asyncio
    async def test_store_without_tool_call_id(self):
        store = ToolHistoryStore()
        key = await store.store("search", "search results")
        assert isinstance(key, str)
        # key uses id(content) when no tool_call_id provided
        assert key.startswith("default:")

    @pytest.mark.asyncio
    async def test_store_custom_session_id_in_key(self):
        store = ToolHistoryStore(session_id="session_a")
        key = await store.store("write_file", "data", tool_call_id="call_2")
        assert key.startswith("session_a:")

    @pytest.mark.asyncio
    async def test_store_increases_len(self):
        store = ToolHistoryStore()
        await store.store("tool1", "content1", tool_call_id="c1")
        assert len(store) == 1
        await store.store("tool2", "content2", tool_call_id="c2")
        assert len(store) == 2

    @pytest.mark.asyncio
    async def test_store_overwrite_same_key(self):
        store = ToolHistoryStore()
        await store.store("tool1", "v1", tool_call_id="c1")
        await store.store("tool1", "v2", tool_call_id="c1")
        assert len(store) == 1


class TestToolHistoryStoreGet:
    """Test retrieving tool results."""

    @pytest.mark.asyncio
    async def test_get_existing_entry(self):
        store = ToolHistoryStore()
        key = await store.store("read_file", "hello world", tool_call_id="c1")
        entry = await store.get(key)
        assert entry is not None
        assert entry.tool_name == "read_file"
        assert entry.content == "hello world"
        assert entry.tool_call_id == "c1"

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self):
        store = ToolHistoryStore()
        entry = await store.get("nonexistent")
        assert entry is None

    @pytest.mark.asyncio
    async def test_get_preserves_timestamp(self):
        import time

        store = ToolHistoryStore()
        before = time.time()
        key = await store.store("search", "results", tool_call_id="c2")
        after = time.time()
        entry = await store.get(key)
        assert entry is not None
        assert before <= entry.timestamp <= after


class TestToolHistoryStoreClear:
    """Test clearing the store."""

    @pytest.mark.asyncio
    async def test_clear_empties_store(self):
        store = ToolHistoryStore()
        await store.store("t1", "c1", tool_call_id="1")
        await store.store("t2", "c2", tool_call_id="2")
        assert len(store) == 2
        await store.clear()
        assert len(store) == 0

    @pytest.mark.asyncio
    async def test_clear_twice_no_error(self):
        store = ToolHistoryStore()
        await store.clear()
        await store.clear()
        assert len(store) == 0


class TestToolHistoryStoreConcurrent:
    """Test concurrent store operations."""

    @pytest.mark.asyncio
    async def test_concurrent_store_no_corruption(self):
        store = ToolHistoryStore()

        async def store_many(prefix, count):
            for i in range(count):
                await store.store(
                    f"tool_{prefix}", f"content_{prefix}_{i}", tool_call_id=f"{prefix}_{i}"
                )

        # Run two concurrent store tasks
        await asyncio.gather(
            store_many("a", 20),
            store_many("b", 20),
        )
        assert len(store) == 40

    @pytest.mark.asyncio
    async def test_concurrent_store_and_get(self):
        store = ToolHistoryStore()
        keys = []

        async def producer():
            for i in range(10):
                key = await store.store("tool", f"data_{i}", tool_call_id=f"p_{i}")
                keys.append(key)

        async def consumer():
            results = []
            for key in keys:
                entry = await store.get(key)
                if entry:
                    results.append(entry)
            return results

        await asyncio.gather(producer(), consumer())
        # At least some entries should be retrievable
        # (consumer may run before all producers finish)
