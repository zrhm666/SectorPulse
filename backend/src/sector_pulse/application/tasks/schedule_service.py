from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from sector_pulse.storage.ports.tasks import ScheduleRepositoryPort


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    mode: str
    timezone: str
    local_time: str
    trading_days: str = "weekdays"
    enabled: bool = True
    input_template: dict[str, object] = {}


class ScheduleView(ScheduleCreate):
    schedule_id: UUID
    version: int = 1
    next_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ScheduleService:
    def __init__(self, repository: ScheduleRepositoryPort) -> None:
        self._repository = repository

    def create(self, request: ScheduleCreate) -> ScheduleView:
        if request.mode not in {"intraday", "post_close", "manual"}:
            raise ValueError("invalid schedule mode")
        self._parse_local_time(request.local_time)
        ZoneInfo(request.timezone)
        now = datetime.now(UTC)
        schedule_id = uuid4()
        schedule = ScheduleView(
            schedule_id=schedule_id, **request.model_dump(), created_at=now, updated_at=now
        )
        next_run_at = self.next_after(schedule, now)
        self._repository.insert_schedule(
            {
                "schedule_id": str(schedule_id), "name": request.name,
                "mode": request.mode, "timezone": request.timezone,
                "local_time": request.local_time, "trading_days": request.trading_days,
                "input_template": request.input_template, "enabled": request.enabled,
                "next_run_at": next_run_at.isoformat() if next_run_at else None,
                "created_at": now.isoformat(), "updated_at": now.isoformat(),
            }
        )
        return schedule.model_copy(update={"next_run_at": next_run_at})

    def list(self) -> list[ScheduleView]:
        return [
            ScheduleView.model_validate(self._view_values(row))
            for row in self._repository.list_schedules()
        ]

    def from_stored(self, row: dict[str, object]) -> ScheduleView:
        return ScheduleView.model_validate(self._view_values(row))

    def next_after(self, schedule: ScheduleView, after: datetime) -> datetime | None:
        if not schedule.enabled or schedule.mode == "manual":
            return None
        local_zone = ZoneInfo(schedule.timezone)
        local_now = after.astimezone(local_zone)
        local_day = local_now.date()
        scheduled_time = self._parse_local_time(schedule.local_time)
        for offset in range(8):
            candidate_day = local_day + timedelta(days=offset)
            if self._is_trading_day(candidate_day, schedule.trading_days):
                candidate = datetime.combine(candidate_day, scheduled_time, local_zone)
                candidate_utc = candidate.astimezone(UTC)
                if candidate_utc > after:
                    return candidate_utc
        return None

    def next_due(self, schedule: ScheduleView, now: datetime) -> datetime | None:
        """Compatibility alias for callers not yet migrated to persisted cursors."""
        return self.next_after(schedule, now)

    @staticmethod
    def _parse_local_time(value: str) -> time:
        try:
            hour, minute = (int(item) for item in value.split(":", 1))
            return time(hour=hour, minute=minute)
        except (ValueError, TypeError) as exc:
            raise ValueError("local_time must be HH:MM") from exc

    @staticmethod
    def _is_trading_day(day: date, trading_days: str) -> bool:
        return trading_days != "weekdays" or day.weekday() < 5

    @staticmethod
    def _view_values(row: dict[str, object]) -> dict[str, object]:
        schedule_id = row["schedule_id"]
        next_run_at = row["next_run_at"]
        created_at = row["created_at"]
        updated_at = row["updated_at"]
        if not isinstance(schedule_id, str):
            raise TypeError("stored schedule_id must be a string")
        if next_run_at is not None and not isinstance(next_run_at, str):
            raise TypeError("stored next_run_at must be a string or null")
        if not isinstance(created_at, str) or not isinstance(updated_at, str):
            raise TypeError("stored schedule timestamps must be strings")
        return {
            **row,
            "schedule_id": UUID(schedule_id),
            "next_run_at": (
                datetime.fromisoformat(next_run_at) if next_run_at else None
            ),
            "created_at": datetime.fromisoformat(created_at),
            "updated_at": datetime.fromisoformat(updated_at),
        }
