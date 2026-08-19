from collections.abc import Awaitable, Callable
from typing import Any


class RewriteService:
    def __init__(
        self,
        llm: Callable[[str], Awaitable[Any]],
        *,
        trusted_source_ids: set[str],
    ) -> None:
        self._llm = llm
        self._trusted_source_ids = trusted_source_ids

    async def rewrite(
        self,
        section_id: str,
        body: str,
        *,
        rejected_source_ids: set[str],
    ) -> Any:
        candidate = await self._llm(
            f"Rewrite section {section_id}. Existing body:\n{body}\n"
            "Keep only validated evidence and do not invent sources."
        )
        allowed = self._trusted_source_ids - rejected_source_ids
        source_ids = tuple(source_id for source_id in candidate.source_ids if source_id in allowed)
        if hasattr(candidate, "model_copy"):
            return candidate.model_copy(update={"source_ids": source_ids})
        return type(candidate)(**{**vars(candidate), "source_ids": source_ids})
