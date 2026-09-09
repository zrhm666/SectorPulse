from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from sector_pulse.domain.evaluation.prompt_golden import PromptGoldenCase
from sector_pulse.domain.evaluation.shadow_acceptance import (
    ComplianceRecord,
    RecoveryDrill,
    ShadowRun,
)


@runtime_checkable
class PromptGoldenRepositoryPort(Protocol):
    def save(self, item: PromptGoldenCase) -> None: ...

    def list(self) -> tuple[PromptGoldenCase, ...]: ...



@runtime_checkable
class ShadowAcceptanceRepositoryPort(Protocol):
    def save_run(self, item: ShadowRun) -> None: ...

    def get(self, shadow_id: UUID) -> ShadowRun | None: ...

    def list_runs(self, limit: int = 20) -> tuple[ShadowRun, ...]: ...

    def update_run(self, shadow_id: UUID, item: ShadowRun) -> None: ...

    def save_recovery(self, item: RecoveryDrill) -> None: ...

    def save_compliance(self, item: ComplianceRecord) -> None: ...
