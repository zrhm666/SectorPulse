from __future__ import annotations

from typing import Any


class ToolContext:
    """Dependency injection container for tools"""

    def __init__(self):
        self._store: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def has(self, key: str) -> bool:
        return key in self._store

    def remove(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    # Convenience accessors for common dependencies
    @property
    def agent_config(self) -> Any:
        return self.get("agent_config")

    @property
    def context(self) -> Any:
        return self.get("context")  # AgentContext

    @property
    def history_store(self) -> Any:
        return self.get("history_store")  # ToolHistoryStore

    @property
    def state_manager(self) -> Any:
        return self.get("state_manager")  # StateManager

    @property
    def skill_manager(self) -> Any:
        return self.get("skill_manager")  # SkillManager

    @property
    def todo_manager(self) -> Any:
        return self.get("todo_manager")  # TodoManager

    @property
    def agent_factory(self) -> Any:
        return self.get("agent_factory")  # AgentFactory

    @property
    def allowed_tools(self) -> list[str]:
        return self.get("allowed_tools", [])
