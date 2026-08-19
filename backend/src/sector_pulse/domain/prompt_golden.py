from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class PromptGoldenCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: UUID = Field(default_factory=uuid4)
    prompt_id: str = Field(min_length=1)
    prompt_version: int = Field(ge=1)
    input_hash: str = Field(min_length=1)
    expected_schema: str = Field(min_length=1)
    result: str
    notes: str = ""
    created_at: datetime
