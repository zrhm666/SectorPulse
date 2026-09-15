from __future__ import annotations

from aidynamic_agent.tools.context import ToolContext


class TestSetGet:
    """Test basic set/get operations."""

    def test_set_and_get(self):
        ctx = ToolContext()
        ctx.set("key", "value")
        assert ctx.get("key") == "value"

    def test_set_overwrites(self):
        ctx = ToolContext()
        ctx.set("key", "first")
        ctx.set("key", "second")
        assert ctx.get("key") == "second"

    def test_set_various_types(self):
        ctx = ToolContext()
        ctx.set("int_val", 42)
        ctx.set("list_val", [1, 2, 3])
        ctx.set("dict_val", {"a": 1})
        ctx.set("none_val", None)

        assert ctx.get("int_val") == 42
        assert ctx.get("list_val") == [1, 2, 3]
        assert ctx.get("dict_val") == {"a": 1}
        assert ctx.get("none_val") is None


class TestGetWithDefault:
    """Test get with default value."""

    def test_get_missing_key_returns_none(self):
        ctx = ToolContext()
        assert ctx.get("missing") is None

    def test_get_missing_key_returns_default(self):
        ctx = ToolContext()
        assert ctx.get("missing", "fallback") == "fallback"

    def test_get_existing_key_ignores_default(self):
        ctx = ToolContext()
        ctx.set("key", "value")
        assert ctx.get("key", "fallback") == "value"

    def test_get_existing_none_value_returns_none(self):
        ctx = ToolContext()
        ctx.set("key", None)
        assert ctx.get("key", "fallback") is None


class TestHasRemove:
    """Test has/remove operations."""

    def test_has_returns_true_for_set_key(self):
        ctx = ToolContext()
        ctx.set("key", "value")
        assert ctx.has("key") is True

    def test_has_returns_false_for_missing_key(self):
        ctx = ToolContext()
        assert ctx.has("key") is False

    def test_remove_existing_key(self):
        ctx = ToolContext()
        ctx.set("key", "value")
        ctx.remove("key")
        assert ctx.has("key") is False
        assert ctx.get("key") is None

    def test_remove_missing_key_no_error(self):
        ctx = ToolContext()
        ctx.remove("missing")  # Should not raise
        assert ctx.has("missing") is False

    def test_remove_then_has(self):
        ctx = ToolContext()
        ctx.set("key", "value")
        ctx.remove("key")
        assert ctx.has("key") is False


class TestClear:
    """Test clear operation."""

    def test_clear_empty_context(self):
        ctx = ToolContext()
        ctx.clear()
        assert ctx.get("anything") is None

    def test_clear_removes_all_keys(self):
        ctx = ToolContext()
        ctx.set("a", 1)
        ctx.set("b", 2)
        ctx.set("c", 3)
        ctx.clear()
        assert ctx.has("a") is False
        assert ctx.has("b") is False
        assert ctx.has("c") is False

    def test_clear_store_is_empty(self):
        ctx = ToolContext()
        ctx.set("key", "value")
        ctx.clear()
        assert ctx._store == {}


class TestConvenienceAccessorsNotConfigured:
    """Test convenience property accessors return defaults when not configured."""

    def test_agent_config_not_set(self):
        ctx = ToolContext()
        assert ctx.agent_config is None

    def test_context_not_set(self):
        ctx = ToolContext()
        assert ctx.context is None

    def test_history_store_not_set(self):
        ctx = ToolContext()
        assert ctx.history_store is None

    def test_state_manager_not_set(self):
        ctx = ToolContext()
        assert ctx.state_manager is None

    def test_skill_manager_not_set(self):
        ctx = ToolContext()
        assert ctx.skill_manager is None

    def test_todo_manager_not_set(self):
        ctx = ToolContext()
        assert ctx.todo_manager is None

    def test_allowed_tools_not_set(self):
        ctx = ToolContext()
        assert ctx.allowed_tools == []


class TestConvenienceAccessorsConfigured:
    """Test convenience property accessors return correct value when configured."""

    def test_agent_config_set(self):
        ctx = ToolContext()
        config = object()
        ctx.set("agent_config", config)
        assert ctx.agent_config is config

    def test_context_set(self):
        ctx = ToolContext()
        agent_ctx = object()
        ctx.set("context", agent_ctx)
        assert ctx.context is agent_ctx

    def test_history_store_set(self):
        ctx = ToolContext()
        hist = object()
        ctx.set("history_store", hist)
        assert ctx.history_store is hist

    def test_state_manager_set(self):
        ctx = ToolContext()
        mgr = object()
        ctx.set("state_manager", mgr)
        assert ctx.state_manager is mgr

    def test_skill_manager_set(self):
        ctx = ToolContext()
        mgr = object()
        ctx.set("skill_manager", mgr)
        assert ctx.skill_manager is mgr

    def test_todo_manager_set(self):
        ctx = ToolContext()
        mgr = object()
        ctx.set("todo_manager", mgr)
        assert ctx.todo_manager is mgr

    def test_allowed_tools_set(self):
        ctx = ToolContext()
        tools = ["read_file", "search_files"]
        ctx.set("allowed_tools", tools)
        assert ctx.allowed_tools == tools
        assert ctx.allowed_tools is tools
