from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NewsDetail(BaseModel):
    model_config = ConfigDict(frozen=True)
    document_id: str
    availability: Literal["full_text", "summary_only", "unavailable"]
    content: str = Field(max_length=12000)
    fetched_at: datetime
    content_hash: str
    truncated: bool = False
    error_code: str | None = None
    # A page fetched now is not proof of what was visible at a historical cutoff.
    historical_snapshot_verified: bool = False
