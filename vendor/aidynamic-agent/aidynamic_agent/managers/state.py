from __future__ import annotations

import json
from pathlib import Path

from aidynamic_agent.core.context import AgentContext


class StateManager:
    """JSON format save/load context, compatible with old JSONL format"""

    def __init__(self, state_path: str = "agent_state.json"):
        self.state_path = Path(state_path)

    async def save(self, context: AgentContext) -> None:
        """Save context to JSON"""
        data = {
            "messages": self._serialize_messages(context.messages),
            "total_tokens": context.total_tokens,
            "has_compacted": context.has_compacted,
            "last_summary": context.last_summary,
        }
        self.state_path.write_text(json.dumps(data, indent=2))

    async def load(self) -> AgentContext:
        """Load context from JSON"""
        if not self.state_path.exists():
            raise FileNotFoundError(f"State file not found: {self.state_path}")

        data = json.loads(self.state_path.read_text())
        # Reconstruct context
        from aidynamic_agent.core.message import Message, Role, TextBlock

        messages = []
        for msg_data in data.get("messages", []):
            msg = Message(
                role=Role(msg_data["role"]),
                content=[TextBlock(text=msg_data.get("text", ""))],
                provider=msg_data.get("provider"),
            )
            messages.append(msg)

        context = AgentContext(
            messages=messages,
            total_tokens=data.get("total_tokens", 0),
            has_compacted=data.get("has_compacted", False),
            last_summary=data.get("last_summary", ""),
        )
        return context

    def _serialize_messages(self, messages) -> list[dict]:
        result = []
        for msg in messages:
            text_parts = []
            for block in msg.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
            result.append(
                {
                    "role": msg.role.value,
                    "text": "\n".join(text_parts),
                    "provider": msg.provider,
                }
            )
        return result
