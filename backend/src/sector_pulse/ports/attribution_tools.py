from typing import Protocol

from sector_pulse.domain.writing.agent_execution import (
    InspectMarket,
    ReadNewsDetail,
    SearchNews,
    ToolObservation,
)


class AttributionToolsPort(Protocol):
    async def execute(
        self, action: SearchNews | ReadNewsDetail | InspectMarket
    ) -> ToolObservation: ...
