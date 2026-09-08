from types import SimpleNamespace

import pytest
from sector_pulse.application.writing.rewrite_service import RewriteService


@pytest.mark.asyncio
async def test_rewrite_cannot_add_unverified_source():
    async def llm(_prompt):
        return SimpleNamespace(source_ids=("source-1", "untrusted"), body="rewritten")

    service = RewriteService(llm, trusted_source_ids={"source-1"})
    result = await service.rewrite("section-1", "original", rejected_source_ids={"source-1"})

    assert result.source_ids == ()
