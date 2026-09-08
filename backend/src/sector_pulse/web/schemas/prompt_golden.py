from datetime import datetime

from pydantic import BaseModel


class PromptGoldenRequest(BaseModel):
    prompt_id: str
    prompt_version: int
    input_hash: str
    expected_schema: str
    result: str
    notes: str = ""


class PromptGoldenResponse(PromptGoldenRequest):
    case_id: str
    created_at: datetime
