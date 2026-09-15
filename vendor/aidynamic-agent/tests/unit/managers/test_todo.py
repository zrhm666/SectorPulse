"""Tests for agent/managers/todo.py - TodoManager, TodoItem."""

import json

from aidynamic_agent.managers.todo import TodoItem, TodoManager


class TestTodoItem:
    """Test TodoItem dataclass."""

    def test_create_todo_item(self):
        item = TodoItem(id="abc123", content="Test task", status="pending")
        assert item.id == "abc123"
        assert item.content == "Test task"
        assert item.status == "pending"


class TestTodoManagerCreate:
    """Test creating todos."""

    def test_create_returns_id(self):
        mgr = TodoManager()
        item_id = mgr.create("Buy groceries")
        assert isinstance(item_id, str)
        assert len(item_id) == 8  # uuid4 truncated to 8 chars

    def test_create_sets_pending_status(self):
        mgr = TodoManager()
        mgr.create("Buy groceries")
        todos = mgr.list_all()
        assert len(todos) == 1
        assert todos[0].status == "pending"

    def test_create_unique_ids(self):
        mgr = TodoManager()
        id1 = mgr.create("Task 1")
        id2 = mgr.create("Task 2")
        assert id1 != id2

    def test_create_preserves_content(self):
        mgr = TodoManager()
        mgr.create("Write documentation")
        todos = mgr.list_all()
        assert todos[0].content == "Write documentation"


class TestTodoManagerUpdate:
    """Test updating todo status."""

    def test_update_existing_todo(self):
        mgr = TodoManager()
        item_id = mgr.create("Task to update")
        result = mgr.update(item_id, "in_progress")
        assert result is True
        todos = mgr.list_all()
        assert todos[0].status == "in_progress"

    def test_update_nonexistent_todo_returns_false(self):
        mgr = TodoManager()
        result = mgr.update("nonexistent", "completed")
        assert result is False

    def test_update_to_completed(self):
        mgr = TodoManager()
        item_id = mgr.create("Finish report")
        mgr.update(item_id, "completed")
        todos = mgr.list_all()
        assert todos[0].status == "completed"

    def test_update_to_cancelled(self):
        mgr = TodoManager()
        item_id = mgr.create("Old task")
        mgr.update(item_id, "cancelled")
        todos = mgr.list_all()
        assert todos[0].status == "cancelled"


class TestTodoManagerList:
    """Test listing todos."""

    def test_list_all_returns_copies(self):
        mgr = TodoManager()
        mgr.create("Task 1")
        todos = mgr.list_all()
        # Modifying the returned list should not affect internal state
        todos.clear()
        assert len(mgr.list_all()) == 1

    def test_list_all_empty(self):
        mgr = TodoManager()
        assert mgr.list_all() == []

    def test_list_all_multiple_items(self):
        mgr = TodoManager()
        mgr.create("Task 1")
        mgr.create("Task 2")
        mgr.create("Task 3")
        assert len(mgr.list_all()) == 3


class TestTodoManagerGetByStatus:
    """Test filtering todos by status."""

    def test_get_by_status_pending(self):
        mgr = TodoManager()
        mgr.create("Task 1")
        mgr.create("Task 2")
        pending = mgr.get_by_status("pending")
        assert len(pending) == 2

    def test_get_by_status_filters_correctly(self):
        mgr = TodoManager()
        id1 = mgr.create("Task 1")
        mgr.create("Task 2")
        mgr.update(id1, "completed")
        completed = mgr.get_by_status("completed")
        pending = mgr.get_by_status("pending")
        assert len(completed) == 1
        assert len(pending) == 1

    def test_get_by_status_no_matches(self):
        mgr = TodoManager()
        mgr.create("Task 1")
        cancelled = mgr.get_by_status("cancelled")
        assert cancelled == []


class TestTodoManagerClear:
    """Test clearing all todos."""

    def test_clear_removes_all(self):
        mgr = TodoManager()
        mgr.create("Task 1")
        mgr.create("Task 2")
        mgr.clear()
        assert mgr.list_all() == []

    def test_clear_empty_has_no_effect(self):
        mgr = TodoManager()
        mgr.clear()
        assert mgr.list_all() == []


class TestTodoManagerPersistence:
    """Test persistence to file."""

    def test_persist_on_create(self, tmp_path):
        persist_file = tmp_path / "todos.json"
        mgr = TodoManager(persist_path=str(persist_file))
        mgr.create("Task 1")
        assert persist_file.exists()
        data = json.loads(persist_file.read_text())
        assert len(data) == 1
        assert data[0]["content"] == "Task 1"
        assert data[0]["status"] == "pending"

    def test_persist_on_update(self, tmp_path):
        persist_file = tmp_path / "todos.json"
        mgr = TodoManager(persist_path=str(persist_file))
        item_id = mgr.create("Task 1")
        mgr.update(item_id, "completed")
        data = json.loads(persist_file.read_text())
        assert data[0]["status"] == "completed"

    def test_persist_on_clear(self, tmp_path):
        persist_file = tmp_path / "todos.json"
        mgr = TodoManager(persist_path=str(persist_file))
        mgr.create("Task 1")
        mgr.clear()
        data = json.loads(persist_file.read_text())
        assert data == []

    def test_no_persist_when_no_path(self):
        mgr = TodoManager()  # No persist path
        mgr.create("Task 1")
        # Should not raise any error, just no file written
