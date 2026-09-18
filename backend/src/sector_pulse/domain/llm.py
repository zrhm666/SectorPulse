from decimal import Decimal
from enum import StrEnum
from typing import Generic, Literal, TypeVar
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


class PromptExample(BaseModel):
    """一轮 few-shot 示范：模型看到的输入与应当产出的输出。"""

    model_config = ConfigDict(frozen=True)
    input: str = Field(min_length=1)
    output: str = Field(min_length=1)


class PromptTurn(BaseModel):
    """示范对话中的一条消息，按声明顺序进入 Agent 上下文。

    带 tool_name 的 assistant 轮必须紧跟一条 tool_call_id 相同的 tool 轮，
    否则服务端收到的工具调用没有结果，请求会被供应商拒绝。
    """

    model_config = ConfigDict(frozen=True)
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_arguments: dict[str, object] = Field(default_factory=dict)

    @property
    def calls_tool(self) -> bool:
        return bool(self.tool_name)


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
    max_output_tokens: int | None = Field(default=None, ge=1, le=16384)
    examples: tuple[PromptExample, ...] = ()


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
