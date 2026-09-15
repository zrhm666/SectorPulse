from __future__ import annotations

from dataclasses import dataclass, field

from aidynamic_agent.core.message import Message, TextBlock, ToolResultBlock


@dataclass
class CompactConfig:
    """Compaction configuration"""

    trigger_token_threshold: int = 80000  # Token threshold to trigger compaction
    preserve_recent_count: int = 5  # Preserve last N tool results in full


@dataclass
class ToolResultSummary:
    tool_name: str
    tool_call_id: str
    success: bool
    brief: str
    history_key: str | None = None

    def to_compact_string(self) -> str:
        return f"[Tool: {self.tool_name}, Success: {self.success}, Brief: {self.brief}]"


@dataclass
class AgentContext:
    """Context manager - single writer model (feedback point 15)

    Agent loop executes sequentially: add_message -> check_compact -> continue
    No concurrent write risk, no locks needed.
    """

    messages: list[Message] = field(default_factory=list)
    recent_files: list[str] = field(default_factory=list)

    # Token counter (feedback point 14)
    total_tokens: int = 0

    # Compaction state
    has_compacted: bool = False
    last_summary: str = ""

    # Config
    compact_config: CompactConfig = field(default_factory=CompactConfig)
    history_store: object | None = None  # ToolHistoryStore | None

    async def add_message(self, message: Message):
        """Add message, update token count"""
        self.messages.append(message)
        # Update token count (from message.raw_response usage or LLMResponse.usage)
        if message.raw_response and "usage" in message.raw_response:
            self.total_tokens += message.raw_response["usage"].get("total_tokens", 0)

    async def compact_if_needed(self) -> bool:
        """Trigger compaction based on token count (feedback point 14)"""
        if self.total_tokens < self.compact_config.trigger_token_threshold:
            return False

        await self._do_compact()
        self.has_compacted = True
        return True

    async def _do_compact(self):
        """Execute compaction"""
        # 1. Collect all tool results and identify which to preserve vs compact
        all_tool_results: list[tuple[Message, int, ToolResultBlock]] = []

        for msg in self.messages:
            for idx, block in enumerate(msg.content):
                if isinstance(block, ToolResultBlock):
                    all_tool_results.append((msg, idx, block))

        total_tool_results = len(all_tool_results)
        preserve_count = self.compact_config.preserve_recent_count

        if total_tool_results <= preserve_count:
            return

        # 2. Determine which to compact (oldest ones) and which to preserve (recent ones)
        num_to_compact = total_tool_results - preserve_count
        to_compact = all_tool_results[:num_to_compact]

        # 3. Replace compacted tool results with summary text blocks
        for msg, idx, block in to_compact:
            summary = ToolResultSummary(
                tool_name=block.metadata.get("tool_name", "unknown"),
                tool_call_id=block.tool_call_id,
                success=not block.is_error,
                brief=f"[Result: {len(block.tool_result_content)} chars]",
                history_key=block.metadata.get("history_key"),
            )
            msg.content[idx] = TextBlock(text=summary.to_compact_string())
