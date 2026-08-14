from decimal import Decimal
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LLMStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class LLMHealth(BaseModel):
    model_config = ConfigDict(frozen=True)
    available: bool
    provider_id: str
    message: str = ""


class MoneyCny(BaseModel):
    model_config = ConfigDict(frozen=True)
    amount: Decimal = Field(ge=0)


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class LLMError(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    message: str
    retriable: bool = False


T = TypeVar("T")


class LLMRequest(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    agent_name: str
    model: str
    prompt_id: str
    prompt_version: str
    system_prompt: str
    user_payload: dict[str, object]
    response_model: type[BaseModel]
    fixture_key: str | None = None


class LLMResult(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    status: LLMStatus
    data: T | None = None
    usage: TokenUsage
    estimated_cost_cny: MoneyCny
    error: LLMError | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "LLMResult[T]":
        if self.status is LLMStatus.SUCCESS and (self.data is None or self.error is not None):
            raise ValueError("successful LLM result requires data")
        if self.status is not LLMStatus.SUCCESS and self.error is None:
            raise ValueError("failed LLM result requires error")
        return self


class AgentInvocation(BaseModel):
    model_config = ConfigDict(frozen=True)
    invocation_id: UUID
    run_id: UUID
    stage: str
    provider_id: str
    model: str
    prompt_id: str
    prompt_version: str
    input_hash: str
    output_hash: str | None = None
    status: LLMStatus
    usage: TokenUsage
    estimated_cost_cny: MoneyCny
    error_code: str | None = None
