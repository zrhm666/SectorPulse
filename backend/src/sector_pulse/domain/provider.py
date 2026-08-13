from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator


class DataStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class AuthorizationStatus(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    VERIFIED_PRODUCTION = "VERIFIED_PRODUCTION"


class ProviderError(BaseModel):
    code: str
    message: str
    retriable: bool = False


T = TypeVar("T")


class ProviderResult(BaseModel, Generic[T]):
    """屏蔽供应商细节后的统一返回值，状态与数据是否存在必须一致。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    provider_id: str
    capability: str
    status: DataStatus
    data: T | None = None
    observed_at: datetime | None = None
    collected_at: datetime
    source_version: str | None = None
    raw_artifact_sha256: str | None = None
    error: ProviderError | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "ProviderResult[T]":
        # FAILED 与 SUCCESS 的约束让调用方可区分“确实为空”和“调用失败”。
        if self.status is DataStatus.SUCCESS and self.data is None:
            raise ValueError("successful result requires data")
        if self.status is DataStatus.FAILED and (self.data is not None or self.error is None):
            raise ValueError("failed result invariant")
        if (
            self.status is not DataStatus.FAILED
            and self.data is not None
            and self.error is not None
        ):
            raise ValueError("data/error mutually exclusive")
        return self


class ProviderManifest(BaseModel):
    provider_id: str
    version: str
    capabilities: frozenset[str]
    authorization_status: AuthorizationStatus
    supports_live: bool
    supports_as_of: bool
    source_attribution: str
    retention_note: str
