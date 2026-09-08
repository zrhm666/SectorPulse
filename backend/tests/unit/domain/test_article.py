from uuid import uuid4

import pytest
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus


def test_ready_draft_requires_three_to_six_sections() -> None:
    with pytest.raises(ValueError, match="3 to 6"):
        ArticleDraft(
            draft_id=uuid4(),
            run_id=uuid4(),
            version=1,
            status=DraftStatus.READY_FOR_HUMAN_REVIEW,
            titles=("今日板块观察",),
            introduction="导语",
            sections=(),
            conclusion="总结",
            risk_notice="仅供信息交流，不构成投资建议。",
            sources=(),
            character_count=1200,
        )

