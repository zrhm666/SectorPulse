from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from sector_pulse.application.operations.operations_summary import OperationalRun


@runtime_checkable
class OperationsQueryPort(Protocol):
    def list_records(
        self, *, since: datetime | None = None, limit: int | None = None
    ) -> list[OperationalRun]: ...
