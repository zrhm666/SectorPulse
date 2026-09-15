from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class TodoItem:
    id: str
    content: str
    status: str  # pending, in_progress, completed, cancelled


class TodoManager:
    """Unique ID generation, batch event processing, status query, persistence"""

    def __init__(self, persist_path: str | None = None):
        self._todos: list[TodoItem] = []
        self._persist_path = Path(persist_path) if persist_path else None

    def create(self, content: str) -> str:
        """Create todo, return ID"""
        item_id = str(uuid.uuid4())[:8]
        item = TodoItem(id=item_id, content=content, status="pending")
        self._todos.append(item)
        self._persist()
        return item_id

    def update(self, todo_id: str, status: str) -> bool:
        """Update todo status, return True if found"""
        for todo in self._todos:
            if todo.id == todo_id:
                todo.status = status
                self._persist()
                return True
        return False

    def list_all(self) -> list[TodoItem]:
        return list(self._todos)

    def get_by_status(self, status: str) -> list[TodoItem]:
        return [t for t in self._todos if t.status == status]

    def clear(self):
        self._todos.clear()
        self._persist()

    def _persist(self):
        if self._persist_path:
            data = [asdict(t) for t in self._todos]
            self._persist_path.write_text(json.dumps(data, indent=2))
