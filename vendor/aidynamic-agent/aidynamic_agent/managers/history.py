from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class ToolHistoryEntry:
    tool_name: str
    content: str
    timestamp: float
    tool_call_id: str | None = None


class ToolHistoryStore:
    """Per-session tool result storage, supports query by tool_call_id"""

    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self._store: dict[str, ToolHistoryEntry] = {}
        self._lock = asyncio.Lock()

    async def store(self, tool_name: str, content: str, tool_call_id: str | None = None) -> str:
        """Store full result, return key"""
        key = f"{self.session_id}:{tool_call_id or id(content)}"
        async with self._lock:
            self._store[key] = ToolHistoryEntry(
                tool_name=tool_name,
                content=content,
                timestamp=time.time(),
                tool_call_id=tool_call_id,
            )
        return key

    async def get(self, key: str) -> ToolHistoryEntry | None:
        async with self._lock:
            return self._store.get(key)

    async def clear(self):
        async with self._lock:
            self._store.clear()

    def __len__(self):
        return len(self._store)
