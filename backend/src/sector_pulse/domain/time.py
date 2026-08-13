from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class AnalysisMode(StrEnum):
    LIVE = "LIVE"
    AS_OF = "AS_OF"


class CutoffAlreadyLockedError(RuntimeError):
    pass


class InvalidCutoffError(ValueError):
    pass


class AnalysisRun(BaseModel):
    """一次分析任务的时间边界；所有时间必须为带时区的 UTC。"""

    model_config = ConfigDict(frozen=True)
    run_id: UUID
    mode: AnalysisMode
    requested_at: datetime
    requested_cutoff_at: datetime | None = None
    run_cutoff_at: datetime | None = None
    cutoff_locked_at: datetime | None = None

    @field_validator("requested_at", "requested_cutoff_at", "run_cutoff_at", "cutoff_locked_at")
    @classmethod
    def require_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0)):
            raise ValueError("datetime must use UTC")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> "AnalysisRun":
        # AS_OF 在创建时即固定历史截点；LIVE 则必须同时写入截止时间和锁定时间。
        if self.mode is AnalysisMode.AS_OF and (
            self.requested_cutoff_at is None
            or self.run_cutoff_at != self.requested_cutoff_at
            or self.cutoff_locked_at is None
        ):
            raise ValueError("AS_OF runs must be locked")
        if self.mode is AnalysisMode.LIVE and self.requested_cutoff_at is not None:
            raise ValueError("LIVE runs cannot carry requested cutoff")
        if self.mode is AnalysisMode.LIVE and (self.run_cutoff_at is None) != (
            self.cutoff_locked_at is None
        ):
            raise ValueError("LIVE cutoff and lock time must be set together")
        return self

    @classmethod
    def create_live(cls, requested_at: datetime) -> "AnalysisRun":
        return cls(run_id=uuid4(), mode=AnalysisMode.LIVE, requested_at=requested_at)

    @classmethod
    def create_as_of(cls, requested_at: datetime, requested_cutoff_at: datetime) -> "AnalysisRun":
        if requested_cutoff_at > requested_at:
            raise InvalidCutoffError("cutoff cannot be later")
        return cls(
            run_id=uuid4(),
            mode=AnalysisMode.AS_OF,
            requested_at=requested_at,
            requested_cutoff_at=requested_cutoff_at,
            run_cutoff_at=requested_cutoff_at,
            cutoff_locked_at=requested_at,
        )

    def lock_live_cutoff(self, observed_at: datetime, locked_at: datetime) -> "AnalysisRun":
        # LIVE 任务只能在两类核心行情都采集完成后锁定一次，避免后续新闻混入不同时间面。
        if self.mode is not AnalysisMode.LIVE:
            raise InvalidCutoffError("only LIVE runs")
        if self.run_cutoff_at is not None:
            raise CutoffAlreadyLockedError("already locked")
        if observed_at > locked_at:
            raise InvalidCutoffError("observed_at cannot be later")
        return self.model_copy(update={"run_cutoff_at": observed_at, "cutoff_locked_at": locked_at})
